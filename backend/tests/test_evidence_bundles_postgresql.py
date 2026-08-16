"""Real PostgreSQL coverage for the sealed Evidence Bundle HTTP projection."""

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine

from app.api.evidence_bundles import (
    create_evidence_bundles_router,
    require_evidence_bundle_session,
)
from app.database import normalize_async_database_url
from app.evidence.hashing import calculate_evidence_bundle_sha256
from app.evidence.revisions import (
    calculate_evidence_revision_sha256,
    combine_article_text,
)
from app.policy_evidence.contracts import PolicyDocumentCaptureRequest, PolicySourceInput
from app.policy_evidence.repository import capture_policy_document
from app.world_models.contracts import (
    WorldModelCreateRequest,
    WorldSnapshotEvidenceSelection,
    WorldSnapshotPolicyEvidenceSelection,
)
from app.world_models.repository import create_world_model

TEST_POSTGRES_DATABASE_URL = os.environ.get("TEST_POSTGRES_DATABASE_URL")


async def _insert_media_article(
    connection: AsyncConnection,
) -> tuple[UUID, str, str, str]:
    source_id = uuid4()
    article_id = uuid4()
    captured_at = datetime.now(UTC)
    published_at = captured_at.replace(microsecond=0)
    source_name = "Evidence Bundle Integration Media"
    title = "Verified evidence bundle article"
    content = "This exact article text is frozen into the sealed world snapshot."
    summary = "A verified source used by the Evidence Bundle integration test."
    url = f"https://example.com/evidence-bundles/{article_id}"
    await connection.execute(
        text(
            """
            INSERT INTO media_sources (
                id,name,name_zh,country_code,homepage_url,media_type,language,status,
                last_success_at,created_at,updated_at
            ) VALUES (
                :id,:name,NULL,'CN','https://example.com','online','en','active',
                :now,:now,:now
            )
            """
        ),
        {"id": source_id, "name": source_name, "now": captured_at},
    )
    await connection.execute(
        text(
            """
            INSERT INTO media_articles (
                id,source_id,url,url_hash,title,content,summary,language,published_at,
                crawled_at,country_code,is_duplicate,created_at
            ) VALUES (
                :id,:source_id,:url,:url_hash,:title,:content,:summary,'en',:published_at,
                :crawled_at,'CN',false,:created_at
            )
            """
        ),
        {
            "id": article_id,
            "source_id": source_id,
            "url": url,
            "url_hash": sha256(url.encode("utf-8")).hexdigest(),
            "title": title,
            "content": content,
            "summary": summary,
            "published_at": published_at,
            "crawled_at": captured_at,
            "created_at": captured_at,
        },
    )
    revision_sha256 = calculate_evidence_revision_sha256(
        title,
        content,
        summary,
        url,
        published_at,
        captured_at,
        "CN",
        source_id,
        source_name,
    )
    return article_id, revision_sha256, title, content


async def _exercise_evidence_bundle_api(database_url: str) -> None:
    engine = create_async_engine(normalize_async_database_url(database_url), pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                article_id, revision_sha256, title, content = await _insert_media_article(
                    connection
                )
                async with AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                ) as session:
                    policy = await capture_policy_document(
                        session,
                        PolicyDocumentCaptureRequest(
                            source=PolicySourceInput(
                                authority_name="Evidence Policy Authority",
                                jurisdiction_code="CN",
                                homepage_url="https://policy.example.com/",
                            ),
                            canonical_identifier="CN-EVIDENCE-2026-1",
                            title="Evidence Bundle Policy",
                            original_url="https://policy.example.com/documents/1",
                            language="en",
                            publication_date=date(2026, 8, 1),
                            effective_from=date(2026, 9, 1),
                            effective_until=None,
                            captured_text=(
                                "Article 1. This Policy text is frozen into the snapshot."
                            ),
                            verification="human_confirmed",
                        ),
                    )
                    world_model = await create_world_model(
                        session,
                        WorldModelCreateRequest(
                            title="Evidence Bundle integration world",
                            evidence=(
                                WorldSnapshotEvidenceSelection(
                                    article_id=article_id,
                                    evidence_revision_sha256=revision_sha256,
                                ),
                            ),
                            policy_evidence=(
                                WorldSnapshotPolicyEvidenceSelection(
                                    policy_version_id=policy.latest_version.id,
                                    version_sha256=policy.latest_version.version_sha256,
                                ),
                            ),
                            verification="human_confirmed",
                        ),
                    )
                snapshot = world_model.latest_snapshot
                expected_bundle_sha256 = calculate_evidence_bundle_sha256(
                    snapshot.id,
                    snapshot.snapshot_sha256,
                )
                application = FastAPI()
                application.include_router(create_evidence_bundles_router())

                async def session_override() -> AsyncIterator[AsyncSession]:
                    async with AsyncSession(
                        bind=connection,
                        expire_on_commit=False,
                        join_transaction_mode="create_savepoint",
                    ) as session:
                        yield session

                application.dependency_overrides[require_evidence_bundle_session] = session_override
                async with AsyncClient(
                    transport=ASGITransport(app=application),
                    base_url="http://evidence-bundle-test",
                ) as client:
                    list_response = await client.get("/api/v2/evidence-bundles")
                    assert list_response.status_code == 200
                    listed = next(
                        item
                        for item in list_response.json()["items"]
                        if item["id"] == str(snapshot.id)
                    )
                    assert listed["bundle_sha256"] == expected_bundle_sha256
                    assert listed["world_snapshot_id"] == str(snapshot.id)
                    assert listed["item_count"] == 1
                    assert listed["policy_item_count"] == 1

                    detail_response = await client.get(f"/api/v2/evidence-bundles/{snapshot.id}")
                    assert detail_response.status_code == 200
                    detail = detail_response.json()
                    assert detail["bundle_sha256"] == expected_bundle_sha256
                    assert detail["snapshot_sha256"] == snapshot.snapshot_sha256
                    assert detail["items"][0]["position"] == 0
                    assert detail["items"][0]["article_id"] == str(article_id)
                    assert detail["policy_items"][0]["policy_version_id"] == str(
                        policy.latest_version.id
                    )
                    assert detail["policy_items"][0]["title"] == "Evidence Bundle Policy"

                    content_response = await client.get(
                        f"/api/v2/evidence-bundles/{snapshot.id}/items/{article_id}/content"
                    )
                    assert content_response.status_code == 200
                    frozen_content = content_response.json()
                    assert frozen_content["bundle_sha256"] == expected_bundle_sha256
                    assert frozen_content["captured_text"] == combine_article_text(title, content)

                    policy_content_response = await client.get(
                        f"/api/v2/evidence-bundles/{snapshot.id}/policy-items/"
                        f"{policy.latest_version.id}/content"
                    )
                    assert policy_content_response.status_code == 200
                    assert policy_content_response.json()["captured_text"].startswith("Article 1.")

                    missing_response = await client.get(
                        f"/api/v2/evidence-bundles/{snapshot.id}/items/{uuid4()}/content"
                    )
                    assert missing_response.status_code == 404
                    invalid_response = await client.get("/api/v2/evidence-bundles/not-a-uuid")
                    assert invalid_response.status_code == 422
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    TEST_POSTGRES_DATABASE_URL is None,
    reason="TEST_POSTGRES_DATABASE_URL is required for Evidence Bundle API integration tests",
)
def test_evidence_bundle_api_projects_sealed_world_snapshot() -> None:
    assert TEST_POSTGRES_DATABASE_URL is not None
    asyncio.run(_exercise_evidence_bundle_api(TEST_POSTGRES_DATABASE_URL))
