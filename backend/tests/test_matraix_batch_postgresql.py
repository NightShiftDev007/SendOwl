"""Real PostgreSQL behavior for immutable MatrAIx batch registries."""

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine
from test_matraix_trial_archive_postgresql import (
    _insert_failed_chat_trial,
    _insert_population,
    _insert_scenario,
    _insert_survey_trial,
)

from app.api.matraix_batch import (
    create_matraix_batch_router,
    require_batch_registry_session,
)
from app.database import DatabaseConnector, normalize_async_database_url
from app.matraix_batch.contracts import MatraixBatchRegistryCreateRequest
from app.matraix_batch.models import MatraixBatchRegistryRecord
from app.matraix_batch.repository import create_batch_registry
from app.matraix_chat.models import MatraixChatEvaluationRecord, MatraixChatTrialRecord
from app.matraix_chat.tasks import CHAT_SUITE_ID, CHAT_SUITE_SHA256, CHAT_SUITE_VERSION
from app.matraix_linux.contracts import LinuxCohortRef, LinuxPersonaRef
from app.matraix_linux.hashing import (
    calculate_evaluation_sha256 as calculate_linux_evaluation_sha256,
)
from app.matraix_linux.hashing import calculate_trial_sha256 as calculate_linux_trial_sha256
from app.matraix_linux.tasks import PROMPT_SCHEMA_VERSION as LINUX_PROMPT_SCHEMA_VERSION
from app.matraix_linux.tasks import build_linux_task
from app.matraix_surveys.models import MatraixSurveyExperimentRecord, MatraixSurveyTrialRecord
from app.matraix_web.contracts import WebCohortRef, WebPersonaRef
from app.matraix_web.hashing import (
    calculate_evaluation_sha256 as calculate_web_evaluation_sha256,
)
from app.matraix_web.hashing import calculate_trial_sha256 as calculate_web_trial_sha256
from app.matraix_web.tasks import PROMPT_SCHEMA_VERSION as WEB_PROMPT_SCHEMA_VERSION
from app.matraix_web.tasks import build_web_task
from app.populations.contracts import CohortDetail

TEST_POSTGRES_DATABASE_URL = os.environ.get("TEST_POSTGRES_DATABASE_URL")
ARTIFACT_TABLES = (
    "matraix_survey_answers",
    "matraix_chat_messages",
    "matraix_chat_feedback",
    "matraix_web_pages",
    "matraix_web_quotes",
)


async def _insert_web_evaluation(
    connection: AsyncConnection,
    cohort: CohortDetail,
    created_at: datetime,
) -> UUID:
    task = build_web_task()
    member = cohort.members[0]
    cohort_ref = WebCohortRef(
        id=cohort.id,
        title=cohort.title,
        cohort_sha256=cohort.cohort_sha256,
        dataset_sha256=cohort.dataset.dataset_sha256,
        persona_count=cohort.persona_count,
    )
    persona = WebPersonaRef(
        id=member.persona.id,
        position=member.position,
        persona_id=member.persona.persona_id,
        display_name=member.persona.display_name,
        profile_sha256=member.persona.profile_sha256,
    )
    evaluation_id = UUID("26000000-0000-4000-8000-000000000001")
    trial_id = UUID("27000000-0000-4000-8000-000000000001")
    web_config_sha256 = "f" * 64
    evaluation_sha256 = calculate_web_evaluation_sha256(
        task.task_spec_sha256,
        task.executor_spec_sha256,
        cohort_ref,
        "qwen-plus",
        web_config_sha256,
        None,
        1,
    )
    trial_sha256 = calculate_web_trial_sha256(evaluation_sha256, persona)
    await connection.execute(
        text(
            """
            INSERT INTO matraix_web_evaluations (
                id, cohort_id, cohort_sha256, cohort_title, dataset_sha256,
                persona_count, task_id, task_version, task_schema_version,
                task_spec_sha256, executor_schema_version, executor_spec_sha256,
                model_name, web_config_sha256, prompt_schema_version,
                evaluation_sha256, created_at, input_sealed_at
            ) VALUES (
                :id, :cohort_id, :cohort_sha256, :cohort_title, :dataset_sha256,
                :persona_count, :task_id, :task_version, :task_schema_version,
                :task_spec_sha256, :executor_schema_version, :executor_spec_sha256,
                'qwen-plus', :web_config_sha256, :prompt_schema_version,
                :evaluation_sha256, :created_at, NULL
            )
            """
        ),
        {
            "id": evaluation_id,
            "cohort_id": cohort.id,
            "cohort_sha256": cohort.cohort_sha256,
            "cohort_title": cohort.title,
            "dataset_sha256": cohort.dataset.dataset_sha256,
            "persona_count": cohort.persona_count,
            "task_id": task.task_id,
            "task_version": task.version,
            "task_schema_version": task.schema_version,
            "task_spec_sha256": task.task_spec_sha256,
            "executor_schema_version": task.executor_schema_version,
            "executor_spec_sha256": task.executor_spec_sha256,
            "web_config_sha256": web_config_sha256,
            "prompt_schema_version": WEB_PROMPT_SCHEMA_VERSION,
            "evaluation_sha256": evaluation_sha256,
            "created_at": created_at,
        },
    )
    await connection.execute(
        text(
            """
            INSERT INTO matraix_web_trials (
                id, evaluation_id, persona_position, persona_id,
                persona_external_id, persona_display_name, persona_profile_sha256,
                trial_sha256, status, created_at
            ) VALUES (
                :id, :evaluation_id, :persona_position, :persona_id,
                :persona_external_id, :persona_display_name, :persona_profile_sha256,
                :trial_sha256, 'queued', :created_at
            )
            """
        ),
        {
            "id": trial_id,
            "evaluation_id": evaluation_id,
            "persona_position": persona.position,
            "persona_id": persona.id,
            "persona_external_id": persona.persona_id,
            "persona_display_name": persona.display_name,
            "persona_profile_sha256": persona.profile_sha256,
            "trial_sha256": trial_sha256,
            "created_at": created_at,
        },
    )
    await connection.execute(
        text("UPDATE matraix_web_evaluations SET input_sealed_at=:created_at WHERE id=:id"),
        {"created_at": created_at, "id": evaluation_id},
    )
    return evaluation_id


async def _insert_linux_evaluation(
    connection: AsyncConnection,
    cohort: CohortDetail,
    created_at: datetime,
) -> UUID:
    task = build_linux_task()
    member = cohort.members[0]
    cohort_ref = LinuxCohortRef(
        id=cohort.id,
        title=cohort.title,
        cohort_sha256=cohort.cohort_sha256,
        dataset_sha256=cohort.dataset.dataset_sha256,
    )
    persona = LinuxPersonaRef(
        id=member.persona.id,
        position=member.position,
        persona_id=member.persona.persona_id,
        display_name=member.persona.display_name,
        profile_sha256=member.persona.profile_sha256,
    )
    trial_id = UUID("28000000-0000-4000-8000-000000000001")
    evaluation_id = UUID("29000000-0000-4000-8000-000000000001")
    linux_config_sha256 = "7" * 64
    trial_sha256 = calculate_linux_trial_sha256(
        task.task_spec_sha256,
        task.runner_spec_sha256,
        cohort_ref,
        persona,
        "qwen-plus",
        linux_config_sha256,
        LINUX_PROMPT_SCHEMA_VERSION,
        None,
        1,
    )
    evaluation_sha256 = calculate_linux_evaluation_sha256(trial_id, trial_sha256)
    await connection.execute(
        text(
            """
            INSERT INTO matraix_linux_trials (
                id, cohort_id, cohort_title, cohort_sha256, dataset_sha256,
                persona_id, persona_position, persona_external_id,
                persona_display_name, persona_profile_sha256,
                task_id, task_version, task_schema_version, task_spec_sha256,
                runner_schema_version, runner_spec_sha256, model_name,
                linux_config_sha256, prompt_schema_version, trial_sha256,
                status, created_at
            ) VALUES (
                :id, :cohort_id, :cohort_title, :cohort_sha256, :dataset_sha256,
                :persona_id, :persona_position, :persona_external_id,
                :persona_display_name, :persona_profile_sha256,
                :task_id, :task_version, :task_schema_version, :task_spec_sha256,
                :runner_schema_version, :runner_spec_sha256, 'qwen-plus',
                :linux_config_sha256, :prompt_schema_version, :trial_sha256,
                'queued', :created_at
            )
            """
        ),
        {
            "id": trial_id,
            "cohort_id": cohort.id,
            "cohort_title": cohort.title,
            "cohort_sha256": cohort.cohort_sha256,
            "dataset_sha256": cohort.dataset.dataset_sha256,
            "persona_id": persona.id,
            "persona_position": persona.position,
            "persona_external_id": persona.persona_id,
            "persona_display_name": persona.display_name,
            "persona_profile_sha256": persona.profile_sha256,
            "task_id": task.task_id,
            "task_version": task.version,
            "task_schema_version": task.schema_version,
            "task_spec_sha256": task.task_spec_sha256,
            "runner_schema_version": task.runner_schema_version,
            "runner_spec_sha256": task.runner_spec_sha256,
            "linux_config_sha256": linux_config_sha256,
            "prompt_schema_version": LINUX_PROMPT_SCHEMA_VERSION,
            "trial_sha256": trial_sha256,
            "created_at": created_at,
        },
    )
    await connection.execute(
        text(
            """
            INSERT INTO matraix_linux_evaluations (
                id, trial_id, trial_sha256, evaluation_sha256,
                created_at, input_sealed_at
            ) VALUES (
                :id, :trial_id, :trial_sha256, :evaluation_sha256,
                :created_at, NULL
            )
            """
        ),
        {
            "id": evaluation_id,
            "trial_id": trial_id,
            "trial_sha256": trial_sha256,
            "evaluation_sha256": evaluation_sha256,
            "created_at": created_at,
        },
    )
    await connection.execute(
        text("UPDATE matraix_linux_evaluations SET input_sealed_at=:at WHERE id=:id"),
        {"at": created_at, "id": evaluation_id},
    )
    return evaluation_id


async def _assert_read_only_snapshot(database_url: str) -> None:
    connector = DatabaseConnector.create(database_url)
    statements: list[str] = []

    def capture(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(" ".join(statement.lower().split()))

    event.listen(connector.engine.sync_engine, "before_cursor_execute", capture)
    application = FastAPI()
    application.state.database = connector
    application.include_router(create_matraix_batch_router())
    try:
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://batch-snapshot-test"
        ) as client:
            response = await client.get("/api/v2/matraix/batch-registry-candidates")
            assert response.status_code == 200
        isolation_index = statements.index(
            "set transaction isolation level repeatable read read only"
        )
        select_index = next(
            index
            for index, statement in enumerate(statements)
            if "select count(*) from (" in statement
            and "matraix_chat_evaluations" in statement
            and "matraix_survey_experiments" in statement
            and "matraix_web_evaluations" in statement
            and "matraix_linux_evaluations" in statement
        )
        assert isolation_index < select_index
    finally:
        event.remove(connector.engine.sync_engine, "before_cursor_execute", capture)
        await connector.close()


async def _exercise_registry(database_url: str) -> None:
    await _assert_read_only_snapshot(database_url)
    engine = create_async_engine(normalize_async_database_url(database_url), pool_pre_ping=True)
    statements: list[str] = []

    def capture(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(statement.lower())

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
                assert revision == "20260816_core_0035"
                cohort = await _insert_population(connection)
                scenario, baseline, alternative = await _insert_scenario(connection)
                created_at = datetime.now(UTC) + timedelta(seconds=1)
                _survey_experiment_id, survey_trial_id, _survey_sha = await _insert_survey_trial(
                    connection,
                    cohort,
                    scenario,
                    baseline,
                    alternative,
                    created_at,
                )
                chat_trial_id, _chat_sha = await _insert_failed_chat_trial(
                    connection,
                    cohort,
                    created_at,
                )
                web_parent_id = await _insert_web_evaluation(connection, cohort, created_at)
                linux_parent_id = await _insert_linux_evaluation(connection, cohort, created_at)
                survey_parent_id = await connection.scalar(
                    select(MatraixSurveyTrialRecord.experiment_id).where(
                        MatraixSurveyTrialRecord.id == survey_trial_id
                    )
                )
                chat_parent_id = await connection.scalar(
                    select(MatraixChatTrialRecord.evaluation_id).where(
                        MatraixChatTrialRecord.id == chat_trial_id
                    )
                )
                assert isinstance(survey_parent_id, UUID)
                assert isinstance(chat_parent_id, UUID)
                request = MatraixBatchRegistryCreateRequest.model_validate(
                    {
                        "title": "Cross-task release evidence",
                        "items": [
                            {"kind": "survey", "parent_id": str(survey_parent_id)},
                            {"kind": "chat", "parent_id": str(chat_parent_id)},
                            {"kind": "web", "parent_id": str(web_parent_id)},
                            {"kind": "linux", "parent_id": str(linux_parent_id)},
                        ],
                    }
                )
                async with AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                ) as session:
                    first = await create_batch_registry(session, request)
                    second = await create_batch_registry(session, request)
                assert first.id == second.id
                assert first.registry_sha256 == second.registry_sha256
                assert first.registry_state == "sealed"
                assert first.execution_kind == "registry_only"
                assert first.observed_trial_status == "running"
                assert first.trial_count == 4
                assert first.failed_trial_count == 1

                application = FastAPI()
                application.include_router(create_matraix_batch_router())

                async def session_override() -> AsyncIterator[AsyncSession]:
                    async with AsyncSession(
                        bind=connection,
                        expire_on_commit=False,
                        join_transaction_mode="create_savepoint",
                    ) as session:
                        yield session

                application.dependency_overrides[require_batch_registry_session] = session_override
                statements.clear()
                async with AsyncClient(
                    transport=ASGITransport(app=application),
                    base_url="http://batch-integration-test",
                ) as client:
                    candidates = await client.get(
                        "/api/v2/matraix/batch-registry-candidates?page=1&page_size=20"
                    )
                    assert candidates.status_code == 200
                    candidate_payload = candidates.json()
                    assert candidate_payload["total"] == 4
                    assert {item["kind"] for item in candidate_payload["items"]} == {
                        "survey",
                        "chat",
                        "web",
                        "linux",
                    }
                    web_candidates = await client.get(
                        "/api/v2/matraix/batch-registry-candidates?kind=web"
                    )
                    assert web_candidates.status_code == 200
                    assert [item["parent_id"] for item in web_candidates.json()["items"]] == [
                        str(web_parent_id)
                    ]
                    linux_candidates = await client.get(
                        "/api/v2/matraix/batch-registry-candidates?kind=linux"
                    )
                    assert linux_candidates.status_code == 200
                    assert [item["parent_id"] for item in linux_candidates.json()["items"]] == [
                        str(linux_parent_id)
                    ]
                    listing = await client.get("/api/v2/matraix/batch-registries")
                    assert listing.status_code == 200
                    listing_payload = listing.json()
                    assert listing_payload["total"] == 1
                    assert listing_payload["items"][0]["id"] == str(first.id)
                    assert (
                        listing_payload["items"][0]["observed_at"] == listing_payload["observed_at"]
                    )
                    detail = await client.get(f"/api/v2/matraix/batch-registries/{first.id}")
                    assert detail.status_code == 200
                    assert detail.json()["registry_sha256"] == first.registry_sha256

                    await connection.execute(
                        text(
                            """
                            INSERT INTO simulation_worker_heartbeats (
                                worker_id, engine, engine_version, camel_version, mode,
                                platform_runtime_ready, semantic_runtime_ready,
                                semantic_model_name, semantic_config_sha256,
                                semantic_prompt_schema_version, survey_runtime_ready,
                                survey_model_name, survey_config_sha256,
                                survey_prompt_schema_version, chat_runtime_ready,
                                chat_model_name, chat_config_sha256,
                                chat_prompt_schema_version, chat_sut_task_id,
                                chat_sut_task_version, chat_sut_spec_sha256,
                                started_at, last_seen_at
                            ) VALUES (
                                :worker_id, 'camel-oasis', '0.2.5', '0.2.78',
                                'reddit_manual_smoke', true, true, 'qwen-plus', :semantic_sha,
                                'matraix-semantic-profile/v1', true, 'qwen-plus', :survey_sha,
                                'matraix-survey-scenario-preference/v1', true,
                                'qwen-plus', :chat_sha, 'matraix-chat-acme-support/v1',
                                :suite_id, :suite_version, :suite_sha,
                                clock_timestamp(), clock_timestamp()
                            )
                            """
                        ),
                        {
                            "worker_id": f"native-batch-test-{first.id}",
                            "semantic_sha": "8" * 64,
                            "survey_sha": "9" * 64,
                            "chat_sha": "a" * 64,
                            "suite_id": CHAT_SUITE_ID,
                            "suite_version": CHAT_SUITE_VERSION,
                            "suite_sha": CHAT_SUITE_SHA256,
                        },
                    )
                    launched = await client.post(
                        "/api/v2/matraix/batch-launches",
                        json={
                            "title": "Native atomic release",
                            "items": [
                                {
                                    "kind": "survey",
                                    "scenario_id": str(scenario.id),
                                    "cohort_id": str(cohort.id),
                                    "alternative_id": str(alternative.id),
                                },
                                {
                                    "kind": "chat",
                                    "cohort_id": str(cohort.id),
                                    "task_id": "matraix/acme-support-order-4521",
                                    "task_version": "1.0.0",
                                },
                            ],
                        },
                    )
                    assert launched.status_code == 202, launched.text
                    launched_payload = launched.json()
                    assert launched_payload["launch_mode"] == "native_parent_enqueue"
                    assert [item["kind"] for item in launched_payload["registry"]["items"]] == [
                        "survey",
                        "chat",
                    ]

                    evaluation_count = int(
                        await connection.scalar(select(func.count(MatraixChatEvaluationRecord.id)))
                        or 0
                    )
                    experiment_count = int(
                        await connection.scalar(
                            select(func.count(MatraixSurveyExperimentRecord.id))
                        )
                        or 0
                    )
                    registry_count = int(
                        await connection.scalar(select(func.count(MatraixBatchRegistryRecord.id)))
                        or 0
                    )
                    rejected = await client.post(
                        "/api/v2/matraix/batch-launches",
                        json={
                            "title": "Must roll back",
                            "items": [
                                {
                                    "kind": "chat",
                                    "cohort_id": str(cohort.id),
                                    "task_id": "matraix/acme-support-mcp-order-4521",
                                    "task_version": "1.0.0",
                                },
                                {
                                    "kind": "survey",
                                    "scenario_id": "ffffffff-ffff-4fff-8fff-ffffffffffff",
                                    "cohort_id": str(cohort.id),
                                    "alternative_id": str(alternative.id),
                                },
                            ],
                        },
                    )
                    assert rejected.status_code == 404
                    assert (
                        await connection.scalar(select(func.count(MatraixChatEvaluationRecord.id)))
                        == evaluation_count
                    )
                    assert (
                        await connection.scalar(
                            select(func.count(MatraixSurveyExperimentRecord.id))
                        )
                        == experiment_count
                    )
                    assert (
                        await connection.scalar(select(func.count(MatraixBatchRegistryRecord.id)))
                        == registry_count
                    )

                selected_sql = "\n".join(statements)
                for table_name in ARTIFACT_TABLES:
                    assert table_name not in selected_sql

                with pytest.raises(DBAPIError, match="immutable"):
                    async with connection.begin_nested():
                        await connection.execute(
                            text(
                                "UPDATE matraix_batch_registries SET title='Changed' WHERE id=:id"
                            ),
                            {"id": first.id},
                        )
                stored_count = await connection.scalar(
                    select(text("count(*)"))
                    .select_from(MatraixBatchRegistryRecord)
                    .where(MatraixBatchRegistryRecord.id == first.id)
                )
                assert stored_count == 1
            finally:
                await transaction.rollback()
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
        await engine.dispose()


@pytest.mark.skipif(
    TEST_POSTGRES_DATABASE_URL is None,
    reason="TEST_POSTGRES_DATABASE_URL is required for PostgreSQL integration",
)
def test_matraix_batch_registry_executes_against_postgresql() -> None:
    assert TEST_POSTGRES_DATABASE_URL is not None
    asyncio.run(_exercise_registry(TEST_POSTGRES_DATABASE_URL))
