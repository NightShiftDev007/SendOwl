"""Real PostgreSQL coverage for immutable Policy evidence."""

import asyncio
import os
from collections.abc import AsyncIterator
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine

from app.api.policy_evidence import (
    create_policy_evidence_router,
    require_policy_evidence_session,
)
from app.database import normalize_async_database_url

TEST_POSTGRES_DATABASE_URL = os.environ.get("TEST_POSTGRES_DATABASE_URL")


async def _expect_rejection(
    connection: AsyncConnection,
    statement: str,
    parameters: dict[str, object],
) -> None:
    savepoint = await connection.begin_nested()
    try:
        with pytest.raises(DBAPIError):
            await connection.execute(text(statement), parameters)
    finally:
        await savepoint.rollback()


def _capture_payload(content: str, effective_until: str | None) -> dict[str, object]:
    return {
        "source": {
            "authority_name": "Example Policy Authority",
            "jurisdiction_code": "EX",
            "homepage_url": "https://policy.example.gov/",
        },
        "canonical_identifier": "EX-2026-17",
        "title": "Example Evidence Policy",
        "original_url": "https://policy.example.gov/documents/ex-2026-17",
        "language": "en",
        "publication_date": "2026-08-01",
        "effective_from": "2026-09-01",
        "effective_until": effective_until,
        "captured_text": content,
        "verification": "human_confirmed",
    }


async def _exercise_policy_evidence(database_url: str) -> None:
    engine = create_async_engine(normalize_async_database_url(database_url), pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
                assert revision == "20260816_core_0038"
                application = FastAPI()
                application.include_router(create_policy_evidence_router())

                async def session_override() -> AsyncIterator[AsyncSession]:
                    async with AsyncSession(
                        bind=connection,
                        expire_on_commit=False,
                        join_transaction_mode="create_savepoint",
                    ) as session:
                        yield session

                application.dependency_overrides[require_policy_evidence_session] = session_override
                async with AsyncClient(
                    transport=ASGITransport(app=application),
                    base_url="http://policy-integration-test",
                ) as client:
                    initial_content = "Section 1. Initial authoritative policy evidence."
                    create_response = await client.post(
                        "/api/v2/policy-documents",
                        json=_capture_payload(initial_content, None),
                    )
                    assert create_response.status_code == 201, create_response.text
                    created = create_response.json()
                    document_id = UUID(created["id"])
                    first_version_id = UUID(created["latest_version"]["id"])
                    assert created["version_count"] == 1
                    assert created["latest_version"]["effective_from"] == "2026-09-01"

                    repeated = await client.post(
                        "/api/v2/policy-documents",
                        json=_capture_payload(initial_content, None),
                    )
                    assert repeated.status_code == 201
                    assert repeated.json()["id"] == str(document_id)
                    assert repeated.json()["version_count"] == 1

                    append_payload = _capture_payload(
                        "Section 1. Amended policy evidence with a bounded validity period.",
                        "2028-01-01",
                    )
                    append_payload.pop("source")
                    append_payload.pop("canonical_identifier")
                    append_response = await client.post(
                        f"/api/v2/policy-documents/{document_id}/versions",
                        json=append_payload,
                    )
                    assert append_response.status_code == 201
                    appended = append_response.json()
                    assert appended["version_count"] == 2
                    assert [item["version"] for item in appended["versions"]] == [1, 2]

                    directory_response = await client.get(
                        "/api/v2/policy-documents?page=1&page_size=20"
                    )
                    assert directory_response.status_code == 200
                    assert directory_response.json()["total"] == 1
                    assert directory_response.json()["items"][0]["version_count"] == 2

                    content_response = await client.get(
                        f"/api/v2/policy-documents/{document_id}/versions/"
                        f"{first_version_id}/content"
                    )
                    assert content_response.status_code == 200
                    assert content_response.json()["captured_text"] == initial_content

                    invalid_page = await client.get("/api/v2/policy-documents?page=2&page_size=20")
                    assert invalid_page.status_code == 422
                    await _expect_rejection(
                        connection,
                        "UPDATE policy_document_versions SET title='Tampered' WHERE id=:id",
                        {"id": first_version_id},
                    )
                    await _expect_rejection(
                        connection,
                        "DELETE FROM policy_documents WHERE id=:id",
                        {"id": document_id},
                    )
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    TEST_POSTGRES_DATABASE_URL is None,
    reason="TEST_POSTGRES_DATABASE_URL is required for Policy evidence PostgreSQL tests",
)
def test_policy_evidence_executes_against_postgresql() -> None:
    assert TEST_POSTGRES_DATABASE_URL is not None
    asyncio.run(_exercise_policy_evidence(TEST_POSTGRES_DATABASE_URL))
