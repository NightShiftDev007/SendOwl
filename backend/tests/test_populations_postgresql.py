"""Real PostgreSQL integration coverage for population repository behavior."""

import asyncio
import json
import os
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine

from app.database import normalize_async_database_url
from app.populations.contracts import (
    CohortCreateRequest,
    StoredPersonaProfile,
    StoredPersonaProvenance,
)
from app.populations.hashing import (
    calculate_persona_profile_sha256,
    canonical_persona_profile_json,
)
from app.populations.repository import (
    create_cohort,
    get_cohort,
    list_cohorts,
    list_datasets,
    list_personas,
)

TEST_POSTGRES_DATABASE_URL = os.environ.get("TEST_POSTGRES_DATABASE_URL")


def _profile(persona_id: str, display_name: str, region: str) -> StoredPersonaProfile:
    return StoredPersonaProfile(
        display_name=display_name,
        dimensions={"region": region, "risk_tolerance": "Balanced"},
        persona_id=persona_id,
        provenance=StoredPersonaProvenance(
            hf_repo=None,
            origin_persona_id=None,
            origin_source_row_index=None,
            parent_pool="integration-test",
        ),
        source="synthetic",
        version="1.0",
    )


def _dataset_sha256(
    slug: str,
    display_name: str,
    manifest_sha256: str,
    personas: tuple[StoredPersonaProfile, ...],
) -> str:
    payload = {
        "display_name": display_name,
        "manifest_sha256": manifest_sha256,
        "parent_pool": "integration-test",
        "persona_count": len(personas),
        "personas": [
            {
                "persona_id": persona.persona_id,
                "profile_sha256": calculate_persona_profile_sha256(persona),
            }
            for persona in personas
        ],
        "schema": "matraix-persona-dataset/v1",
        "schema_version": "1.0",
        "slug": slug,
        "source_repository": None,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


async def _insert_dataset(connection: AsyncConnection) -> tuple[UUID, tuple[UUID, UUID]]:
    dataset_id = uuid4()
    persona_ids = (uuid4(), uuid4())
    created_at = datetime.now(UTC)
    profiles = (
        _profile("reader-001", "Policy Reader", "East Asia"),
        _profile("reader-002", "Market Reader", "Western Europe"),
    )
    manifest_sha256 = "a" * 64
    await connection.execute(
        text(
            """
            INSERT INTO persona_datasets (
                id, slug, display_name, schema_version, parent_pool,
                source_repository, persona_count, manifest_sha256,
                dataset_sha256, created_at, sealed_at
            ) VALUES (
                :id, :slug, :display_name, '1.0', 'integration-test',
                NULL, 2, :manifest_sha256, :dataset_sha256, :created_at, NULL
            )
            """
        ),
        {
            "id": dataset_id,
            "slug": "repository-integration",
            "display_name": "Repository integration",
            "manifest_sha256": manifest_sha256,
            "dataset_sha256": _dataset_sha256(
                "repository-integration",
                "Repository integration",
                manifest_sha256,
                profiles,
            ),
            "created_at": created_at,
        },
    )
    for position, (persona_id, profile) in enumerate(zip(persona_ids, profiles, strict=True)):
        await connection.execute(
            text(
                """
                INSERT INTO personas (
                    id, dataset_id, position, persona_id, display_name,
                    source, profile_json, profile_sha256
                ) VALUES (
                    :id, :dataset_id, :position, :persona_id, :display_name,
                    :source, CAST(:profile_json AS jsonb), :profile_sha256
                )
                """
            ),
            {
                "id": persona_id,
                "dataset_id": dataset_id,
                "position": position,
                "persona_id": profile.persona_id,
                "display_name": profile.display_name,
                "source": profile.source,
                "profile_json": canonical_persona_profile_json(profile),
                "profile_sha256": calculate_persona_profile_sha256(profile),
            },
        )
    await connection.execute(
        text("UPDATE persona_datasets SET sealed_at = created_at WHERE id = :dataset_id"),
        {"dataset_id": dataset_id},
    )
    return dataset_id, persona_ids


async def _exercise_population_repository(database_url: str) -> None:
    engine = create_async_engine(normalize_async_database_url(database_url), pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                current_revision = await connection.scalar(
                    text("SELECT version_num FROM alembic_version")
                )
                assert current_revision == "20260816_core_0038"
                dataset_id, persona_ids = await _insert_dataset(connection)
                async with AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                ) as session:
                    datasets = await list_datasets(session)
                    assert any(dataset.id == dataset_id for dataset in datasets.items)

                    personas = await list_personas(session, dataset_id, "Policy", 1, 20)
                    assert personas.total == 1
                    assert personas.items[0].persona_id == "reader-001"
                    assert tuple(attribute.name for attribute in personas.items[0].attributes) == (
                        "region",
                        "risk_tolerance",
                    )

                    request = CohortCreateRequest(
                        title="Ordered readers",
                        dataset_id=dataset_id,
                        persona_ids=persona_ids,
                    )
                    first = await create_cohort(session, request)
                    repeated = await create_cohort(session, request)
                    assert repeated.id == first.id
                    assert tuple(member.persona.id for member in repeated.members) == persona_ids
                    assert (await get_cohort(session, first.id)).cohort_sha256 == (
                        first.cohort_sha256
                    )
                    assert any(
                        cohort.id == first.id for cohort in (await list_cohorts(session)).items
                    )
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    TEST_POSTGRES_DATABASE_URL is None,
    reason="TEST_POSTGRES_DATABASE_URL is required for population repository integration tests",
)
def test_population_repository_uses_sealed_postgresql_resources() -> None:
    assert TEST_POSTGRES_DATABASE_URL is not None
    asyncio.run(_exercise_population_repository(TEST_POSTGRES_DATABASE_URL))
