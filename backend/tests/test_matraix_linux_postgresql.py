"""Real PostgreSQL coverage for immutable MatrAIx Linux retry attempts."""

import asyncio
import os
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine

from app.api.matraix_linux import create_matraix_linux_router, require_linux_session
from app.database import normalize_async_database_url
from app.matraix_linux.tasks import RUNNER_SCHEMA_VERSION, RUNNER_SPEC_SHA256
from tests.test_matraix_chat_postgresql import _insert_population

TEST_POSTGRES_DATABASE_URL = os.environ.get("TEST_POSTGRES_DATABASE_URL")


async def _insert_ready_worker(connection: AsyncConnection) -> None:
    await connection.execute(
        text(
            """
            INSERT INTO simulation_worker_heartbeats (
                worker_id,worker_domain,engine,engine_version,camel_version,mode,
                platform_runtime_ready,semantic_runtime_ready,
                semantic_model_name,semantic_config_sha256,
                semantic_prompt_schema_version,linux_runtime_ready,
                linux_model_name,linux_config_sha256,linux_prompt_schema_version,
                linux_runner_schema_version,linux_runner_spec_sha256,
                started_at,last_seen_at
            ) VALUES (
                :worker_id,'evaluation','camel-oasis','0.2.5','0.2.78','reddit_manual_smoke',
                false,false,NULL,NULL,NULL,
                true,'qwen-plus',:linux_sha,'matraix-linux-note-to-csv/v1',
                :runner_schema,:runner_sha,clock_timestamp(),clock_timestamp()
            )
            """
        ),
        {
            "worker_id": f"linux-retry-test-{uuid4()}",
            "semantic_sha": "8" * 64,
            "linux_sha": "9" * 64,
            "runner_schema": RUNNER_SCHEMA_VERSION,
            "runner_sha": RUNNER_SPEC_SHA256,
        },
    )


async def _exercise_linux_retry(database_url: str) -> None:
    engine = create_async_engine(normalize_async_database_url(database_url), pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
                assert revision == "20260820_core_0061"
                cohort_id = await _insert_population(connection)
                persona_id = await connection.scalar(
                    text(
                        "SELECT persona_id FROM cohort_members "
                        "WHERE cohort_id=:cohort_id ORDER BY position LIMIT 1"
                    ),
                    {"cohort_id": cohort_id},
                )
                assert isinstance(persona_id, UUID)
                await _insert_ready_worker(connection)

                application = FastAPI()
                application.include_router(create_matraix_linux_router())

                async def session_override() -> AsyncIterator[AsyncSession]:
                    async with AsyncSession(
                        bind=connection,
                        expire_on_commit=False,
                        join_transaction_mode="create_savepoint",
                    ) as session:
                        yield session

                application.dependency_overrides[require_linux_session] = session_override
                async with AsyncClient(
                    transport=ASGITransport(app=application),
                    base_url="http://linux-retry-test",
                ) as client:
                    created_response = await client.post(
                        "/api/v2/matraix/linux-evaluations",
                        json={
                            "cohort_id": str(cohort_id),
                            "persona_id": str(persona_id),
                            "task_id": "matraix/linux-note-to-csv",
                            "task_version": "1.0.0",
                        },
                    )
                    assert created_response.status_code == 202, created_response.text
                    created = created_response.json()
                    evaluation_id = UUID(created["id"])
                    trial_id = UUID(created["trial"]["id"])
                    assert created["trial"]["attempt_number"] == 1
                    progress_response = await client.get(
                        f"/api/v2/matraix/linux-evaluations/{evaluation_id}/progress"
                    )
                    assert progress_response.status_code == 200
                    progress = progress_response.json()
                    assert progress["status"] == "queued"
                    assert progress["attempt_number"] == 1
                    assert progress["event_count"] == 0

                    await connection.execute(
                        text(
                            "UPDATE matraix_linux_trials SET status='running',"
                            "claimed_by_worker_id='linux-test',started_at=clock_timestamp() "
                            "WHERE id=:trial_id"
                        ),
                        {"trial_id": trial_id},
                    )
                    await connection.execute(
                        text(
                            "UPDATE matraix_linux_trials SET status='failed',"
                            "completed_at=clock_timestamp(),error_code='runner_timeout',"
                            "error_message='The fixed runner attempt timed out.' "
                            "WHERE id=:trial_id"
                        ),
                        {"trial_id": trial_id},
                    )

                    retry_response = await client.post(
                        f"/api/v2/matraix/linux-evaluations/{evaluation_id}/retry",
                        json={},
                    )
                    assert retry_response.status_code == 202, retry_response.text
                    retried = retry_response.json()
                    assert retried["trial"]["attempt_number"] == 2
                    assert retried["trial"]["retry_of_trial_id"] == str(trial_id)
                    assert (
                        retried["trial"]["retry_of_trial_sha256"]
                        == created["trial"]["trial_sha256"]
                    )
                    assert retried["trial"]["status"] == "queued"

                    repeated = await client.post(
                        f"/api/v2/matraix/linux-evaluations/{evaluation_id}/retry",
                        json={},
                    )
                    assert repeated.status_code == 202
                    assert repeated.json()["id"] == retried["id"]
                    directory = await client.get(
                        "/api/v2/matraix/linux-evaluations?page=1&page_size=20"
                    )
                    assert directory.status_code == 200
                    directory_payload = directory.json()
                    assert directory_payload["page"] == 1
                    assert directory_payload["page_size"] == 20
                    assert directory_payload["total"] == 2
                    assert {item["id"] for item in directory_payload["items"]} == {
                        str(evaluation_id),
                        retried["id"],
                    }
                    invalid_page = await client.get(
                        "/api/v2/matraix/linux-evaluations?page=2&page_size=20"
                    )
                    assert invalid_page.status_code == 422
                    parent = await client.get(f"/api/v2/matraix/linux-evaluations/{evaluation_id}")
                    assert parent.status_code == 200
                    assert parent.json()["trial"]["status"] == "failed"

                    savepoint = await connection.begin_nested()
                    try:
                        with pytest.raises(DBAPIError, match="Linux retry"):
                            await connection.execute(
                                text(
                                    """
                                    INSERT INTO matraix_linux_trials (
                                        id,cohort_id,cohort_title,cohort_sha256,dataset_sha256,
                                        persona_id,persona_position,persona_external_id,
                                        persona_display_name,persona_profile_sha256,task_id,
                                        task_version,task_schema_version,task_spec_sha256,
                                        runner_schema_version,runner_spec_sha256,model_name,
                                        linux_config_sha256,prompt_schema_version,trial_sha256,
                                        status,created_at,retry_of_trial_id,
                                        retry_of_trial_sha256,attempt_number
                                    )
                                    SELECT :new_id,cohort_id,cohort_title,cohort_sha256,
                                        dataset_sha256,persona_id,persona_position,
                                        persona_external_id,persona_display_name,
                                        persona_profile_sha256,task_id,task_version,
                                        task_schema_version,task_spec_sha256,
                                        runner_schema_version,runner_spec_sha256,model_name,
                                        linux_config_sha256,prompt_schema_version,:bad_sha,
                                        'queued',clock_timestamp(),id,trial_sha256,attempt_number+2
                                    FROM matraix_linux_trials WHERE id=:trial_id
                                    """
                                ),
                                {
                                    "new_id": uuid4(),
                                    "bad_sha": "f" * 64,
                                    "trial_id": trial_id,
                                },
                            )
                    finally:
                        await savepoint.rollback()
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    TEST_POSTGRES_DATABASE_URL is None,
    reason="TEST_POSTGRES_DATABASE_URL is required for MatrAIx Linux PostgreSQL tests",
)
def test_matraix_linux_retry_executes_against_postgresql() -> None:
    assert TEST_POSTGRES_DATABASE_URL is not None
    asyncio.run(_exercise_linux_retry(TEST_POSTGRES_DATABASE_URL))
