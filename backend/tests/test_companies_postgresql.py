"""Real PostgreSQL company API behavior, enabled by an explicit test DSN."""

import asyncio
import os
from collections.abc import AsyncIterator
from uuid import uuid4

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.api.companies import require_company_session
from app.config import load_runtime_settings
from app.database import ApplicationBase, normalize_async_database_url
from app.main import create_app

TEST_DATABASE_URL_VARIABLE = "COMPANY_TEST_DATABASE_URL"


async def _exercise_company_api(database_url: str) -> None:
    settings = load_runtime_settings({"DATABASE_URL": database_url})
    if settings.database_url is None:
        raise RuntimeError("validated COMPANY_TEST_DATABASE_URL unexpectedly resolved to None")
    engine = create_async_engine(normalize_async_database_url(settings.database_url))
    unique_suffix = uuid4().hex
    canonical_name = f"Integration Company {unique_suffix}"
    alias = f"Integration Alias {unique_suffix}"
    unknown_company_id = uuid4()

    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await connection.run_sync(ApplicationBase.metadata.create_all)
            session = AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )

            async def override_company_session() -> AsyncIterator[AsyncSession]:
                yield session

            application = create_app(load_runtime_settings({}))
            application.dependency_overrides[require_company_session] = override_company_session
            transport = httpx2.ASGITransport(app=application)
            async with httpx2.AsyncClient(
                transport=transport,
                base_url="http://test.local",
            ) as client:
                create_response = await client.post(
                    "/api/v2/companies",
                    json={"canonical_name": canonical_name, "aliases": [alias]},
                )
                assert create_response.status_code == 201
                company = create_response.json()
                assert company["canonical_name"] == canonical_name
                assert company["aliases"] == [alias]

                conflict_response = await client.post(
                    "/api/v2/companies",
                    json={"canonical_name": alias.upper(), "aliases": []},
                )
                assert conflict_response.status_code == 409
                assert "already owned by company" in conflict_response.json()["detail"]

                list_response = await client.get("/api/v2/companies")
                assert list_response.status_code == 200
                assert any(item["id"] == company["id"] for item in list_response.json()["items"])

                missing_response = await client.get(
                    f"/api/v2/companies/{unknown_company_id}/coverage"
                )
                assert missing_response.status_code == 404

                coverage_response = await client.get(f"/api/v2/companies/{company['id']}/coverage")
                assert coverage_response.status_code == 200
                coverage = coverage_response.json()
                assert coverage["company"]["id"] == company["id"]
                assert coverage["total_matching_articles"] == 0
                assert coverage["items"] == []
            await session.close()
        finally:
            await transaction.rollback()
    await engine.dispose()


def test_company_api_create_conflict_not_found_and_empty_coverage_with_postgresql() -> None:
    database_url = os.environ.get(TEST_DATABASE_URL_VARIABLE)
    if database_url is None:
        pytest.skip(f"{TEST_DATABASE_URL_VARIABLE} is required for PostgreSQL integration")
    asyncio.run(_exercise_company_api(database_url))
