"""Real PostgreSQL behavior for the bounded unified MatrAIx trial archive."""

import asyncio
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine

from app.api.matraix_trial_archive import (
    create_matraix_trial_archive_router,
    require_trial_archive_session,
)
from app.database import DatabaseConnector, normalize_async_database_url
from app.matraix_chat.contracts import ChatCohortRef, ChatPersonaRef
from app.matraix_chat.hashing import calculate_evaluation_sha256, calculate_trial_sha256
from app.matraix_chat.tasks import PROMPT_SCHEMA_VERSION as CHAT_PROMPT_SCHEMA_VERSION
from app.matraix_chat.tasks import build_chat_task
from app.matraix_surveys.contracts import (
    SurveyCohortRef,
    SurveyPersonaRef,
    SurveyScenarioRef,
    SurveyVariantRef,
)
from app.matraix_surveys.hashing import (
    calculate_survey_experiment_sha256,
    calculate_survey_trial_sha256,
)
from app.matraix_surveys.instrument import (
    INSTRUMENT_SCHEMA_VERSION,
    build_survey_instrument,
)
from app.matraix_surveys.instrument import (
    PROMPT_SCHEMA_VERSION as SURVEY_PROMPT_SCHEMA_VERSION,
)
from app.matraix_surveys.repository import (
    get_matraix_survey_experiment_progress,
    list_matraix_survey_experiments,
)
from app.populations.contracts import (
    CohortCreateRequest,
    CohortDetail,
    StoredPersonaProfile,
    StoredPersonaProvenance,
)
from app.populations.hashing import (
    calculate_persona_profile_sha256,
    canonical_persona_profile_json,
)
from app.populations.repository import create_cohort
from app.scenarios.contracts import Intervention, ScenarioSnapshotRef, ScenarioVariant
from app.scenarios.hashing import calculate_scenario_sha256
from app.world_models.contracts import SnapshotEvidence
from app.world_models.hashing import calculate_snapshot_sha256

TEST_POSTGRES_DATABASE_URL = os.environ.get("TEST_POSTGRES_DATABASE_URL")
ARTIFACT_TABLES = (
    "matraix_survey_answers",
    "matraix_chat_messages",
    "matraix_chat_feedback",
)


def _profile() -> StoredPersonaProfile:
    return StoredPersonaProfile(
        display_name="Archive Persona",
        dimensions={"intent": "Inspect durable trials", "region": "East Asia"},
        persona_id="archive-persona",
        provenance=StoredPersonaProvenance(
            hf_repo=None,
            origin_persona_id=None,
            origin_source_row_index=None,
            parent_pool="archive-integration-test",
        ),
        source="synthetic",
        version="1.0",
    )


def _dataset_sha256(
    slug: str,
    display_name: str,
    manifest_sha256: str,
    profile: StoredPersonaProfile,
) -> str:
    payload = {
        "display_name": display_name,
        "manifest_sha256": manifest_sha256,
        "parent_pool": "archive-integration-test",
        "persona_count": 1,
        "personas": [
            {
                "persona_id": profile.persona_id,
                "profile_sha256": calculate_persona_profile_sha256(profile),
            }
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


async def _insert_population(connection: AsyncConnection) -> CohortDetail:
    dataset_id = uuid4()
    persona_id = uuid4()
    profile = _profile()
    created_at = datetime.now(UTC)
    slug = f"archive-integration-{dataset_id}"
    display_name = "Archive integration dataset"
    manifest_sha256 = "1" * 64
    await connection.execute(
        text(
            """
            INSERT INTO persona_datasets (
                id, slug, display_name, schema_version, parent_pool,
                source_repository, persona_count, manifest_sha256,
                dataset_sha256, created_at, sealed_at
            ) VALUES (
                :id, :slug, :display_name, '1.0', 'archive-integration-test',
                NULL, 1, :manifest_sha256, :dataset_sha256, :created_at, NULL
            )
            """
        ),
        {
            "id": dataset_id,
            "slug": slug,
            "display_name": display_name,
            "manifest_sha256": manifest_sha256,
            "dataset_sha256": _dataset_sha256(
                slug,
                display_name,
                manifest_sha256,
                profile,
            ),
            "created_at": created_at,
        },
    )
    await connection.execute(
        text(
            """
            INSERT INTO personas (
                id, dataset_id, position, persona_id, display_name,
                source, profile_json, profile_sha256
            ) VALUES (
                :id, :dataset_id, 0, :persona_id, :display_name,
                :source, CAST(:profile_json AS jsonb), :profile_sha256
            )
            """
        ),
        {
            "id": persona_id,
            "dataset_id": dataset_id,
            "persona_id": profile.persona_id,
            "display_name": profile.display_name,
            "source": profile.source,
            "profile_json": canonical_persona_profile_json(profile),
            "profile_sha256": calculate_persona_profile_sha256(profile),
        },
    )
    await connection.execute(
        text("UPDATE persona_datasets SET sealed_at=created_at WHERE id=:dataset_id"),
        {"dataset_id": dataset_id},
    )
    async with AsyncSession(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    ) as session:
        return await create_cohort(
            session,
            CohortCreateRequest(
                title="Archive integration Cohort",
                dataset_id=dataset_id,
                persona_ids=(persona_id,),
            ),
        )


async def _insert_scenario(
    connection: AsyncConnection,
) -> tuple[SurveyScenarioRef, SurveyVariantRef, SurveyVariantRef]:
    created_at = datetime.now(UTC)
    world_model_id = uuid4()
    world_snapshot_id = uuid4()
    captured_text = "Archive integration evidence"
    captured_text_sha256 = sha256(captured_text.encode("utf-8")).hexdigest()
    evidence = SnapshotEvidence(
        article_id=uuid4(),
        source_name="Archive source",
        original_url="https://example.com/archive-evidence",
        title="Archive evidence",
        published_at=created_at - timedelta(minutes=5),
        captured_at=created_at,
        country_code="CN",
        excerpt="Archive integration evidence",
        captured_text_sha256=captured_text_sha256,
    )
    snapshot_sha256 = calculate_snapshot_sha256(
        world_model_id,
        1,
        "human_confirmed",
        (evidence,),
    )
    await connection.execute(
        text(
            "INSERT INTO world_models (id,title,created_at) "
            "VALUES (:id,'Archive integration model',:created_at)"
        ),
        {"id": world_model_id, "created_at": created_at},
    )
    await connection.execute(
        text(
            """
            INSERT INTO world_snapshots (
                id,world_model_id,version,verification,snapshot_sha256,created_at,sealed_at
            ) VALUES (:id,:model_id,1,'human_confirmed',:digest,:created_at,NULL)
            """
        ),
        {
            "id": world_snapshot_id,
            "model_id": world_model_id,
            "digest": snapshot_sha256,
            "created_at": created_at,
        },
    )
    await connection.execute(
        text(
            """
            INSERT INTO world_snapshot_evidence (
                snapshot_id,position,article_id,source_name,original_url,title,captured_text,
                published_at,captured_at,country_code,excerpt,captured_text_sha256
            ) VALUES (
                :snapshot,0,:article,:source,:url,:title,:captured_text,
                :published_at,:captured_at,:country,:excerpt,:text_sha
            )
            """
        ),
        {
            "snapshot": world_snapshot_id,
            "article": evidence.article_id,
            "source": evidence.source_name,
            "url": str(evidence.original_url),
            "title": evidence.title,
            "captured_text": captured_text,
            "published_at": evidence.published_at,
            "captured_at": evidence.captured_at,
            "country": evidence.country_code,
            "excerpt": evidence.excerpt,
            "text_sha": evidence.captured_text_sha256,
        },
    )
    await connection.execute(
        text("UPDATE world_snapshots SET sealed_at=created_at WHERE id=:id"),
        {"id": world_snapshot_id},
    )
    snapshot = ScenarioSnapshotRef(
        world_model_id=world_model_id,
        world_snapshot_id=world_snapshot_id,
        version=1,
        snapshot_sha256=snapshot_sha256,
        evidence_count=1,
    )
    baseline = ScenarioVariant(
        id=uuid4(),
        position=0,
        name="No action",
        hypothesis="Keep the current path.",
        interventions=(),
    )
    alternative = ScenarioVariant(
        id=uuid4(),
        position=1,
        name="Clarify",
        hypothesis="Publish verified facts.",
        interventions=(
            Intervention(
                id=uuid4(),
                position=0,
                kind="initial_post",
                actor="scenario_actor",
                channel="reddit",
                content="Here are the verified facts.",
                offset_minutes=0,
            ),
        ),
    )
    scenario_id = uuid4()
    scenario_title = "Archive scenario"
    decision_question = "Should the actor publish verified facts?"
    scenario_sha256 = calculate_scenario_sha256(
        scenario_title,
        decision_question,
        snapshot,
        baseline,
        (alternative,),
    )
    await connection.execute(
        text(
            """
            INSERT INTO scenarios (
                id,title,decision_question,world_model_id,world_snapshot_id,
                snapshot_version,snapshot_sha256,snapshot_evidence_count,
                scenario_sha256,created_at,sealed_at
            ) VALUES (
                :id,:title,:question,:model_id,:snapshot_id,1,:snapshot_sha,1,
                :scenario_sha,:created_at,NULL
            )
            """
        ),
        {
            "id": scenario_id,
            "title": scenario_title,
            "question": decision_question,
            "model_id": world_model_id,
            "snapshot_id": world_snapshot_id,
            "snapshot_sha": snapshot_sha256,
            "scenario_sha": scenario_sha256,
            "created_at": created_at,
        },
    )
    for variant, role in ((baseline, "baseline"), (alternative, "alternative")):
        await connection.execute(
            text(
                """
                INSERT INTO scenario_variants (
                    id,scenario_id,position,role,name,hypothesis
                ) VALUES (:id,:scenario_id,:position,:role,:name,:hypothesis)
                """
            ),
            {
                "id": variant.id,
                "scenario_id": scenario_id,
                "position": variant.position,
                "role": role,
                "name": variant.name,
                "hypothesis": variant.hypothesis,
            },
        )
    intervention = alternative.interventions[0]
    await connection.execute(
        text(
            """
            INSERT INTO scenario_interventions (
                id,scenario_id,variant_id,position,kind,actor,channel,content,offset_minutes
            ) VALUES (
                :id,:scenario_id,:variant_id,0,'initial_post','scenario_actor','reddit',
                :content,0
            )
            """
        ),
        {
            "id": intervention.id,
            "scenario_id": scenario_id,
            "variant_id": alternative.id,
            "content": intervention.content,
        },
    )
    await connection.execute(
        text("UPDATE scenarios SET sealed_at=created_at WHERE id=:id"),
        {"id": scenario_id},
    )
    return (
        SurveyScenarioRef(
            id=scenario_id,
            title=scenario_title,
            decision_question=decision_question,
            scenario_sha256=scenario_sha256,
        ),
        SurveyVariantRef(
            id=baseline.id,
            role="baseline",
            position=baseline.position,
            name=baseline.name,
            hypothesis=baseline.hypothesis,
        ),
        SurveyVariantRef(
            id=alternative.id,
            role="alternative",
            position=alternative.position,
            name=alternative.name,
            hypothesis=alternative.hypothesis,
        ),
    )


def _survey_cohort(cohort: CohortDetail) -> SurveyCohortRef:
    return SurveyCohortRef(
        id=cohort.id,
        title=cohort.title,
        cohort_sha256=cohort.cohort_sha256,
        dataset_sha256=cohort.dataset.dataset_sha256,
        persona_count=cohort.persona_count,
    )


def _survey_persona(cohort: CohortDetail) -> SurveyPersonaRef:
    member = cohort.members[0]
    return SurveyPersonaRef(
        id=member.persona.id,
        position=member.position,
        persona_id=member.persona.persona_id,
        display_name=member.persona.display_name,
        profile_sha256=member.persona.profile_sha256,
    )


async def _insert_survey_trial(
    connection: AsyncConnection,
    cohort: CohortDetail,
    scenario: SurveyScenarioRef,
    baseline: SurveyVariantRef,
    alternative: SurveyVariantRef,
    created_at: datetime,
) -> tuple[UUID, UUID, str]:
    cohort_ref = _survey_cohort(cohort)
    persona = _survey_persona(cohort)
    instrument = build_survey_instrument(baseline, alternative)
    experiment_sha256 = calculate_survey_experiment_sha256(
        scenario,
        cohort_ref,
        baseline,
        alternative,
        instrument.instrument_sha256,
        "qwen-plus",
        "2" * 64,
        None,
        1,
    )
    experiment_id = uuid4()
    trial_id = uuid4()
    trial_sha256 = calculate_survey_trial_sha256(experiment_sha256, persona)
    await connection.execute(
        text(
            """
            INSERT INTO matraix_survey_experiments (
                id,scenario_id,scenario_sha256,scenario_title,decision_question,
                cohort_id,cohort_sha256,cohort_title,dataset_sha256,persona_count,
                baseline_id,baseline_position,baseline_name,baseline_hypothesis,
                alternative_id,alternative_position,alternative_name,alternative_hypothesis,
                instrument_schema_version,instrument_sha256,model_name,
                survey_config_sha256,prompt_schema_version,experiment_sha256,
                created_at,input_sealed_at
            ) VALUES (
                :id,:scenario_id,:scenario_sha,:scenario_title,:question,
                :cohort_id,:cohort_sha,:cohort_title,:dataset_sha,1,
                :baseline_id,0,:baseline_name,:baseline_hypothesis,
                :alternative_id,1,:alternative_name,:alternative_hypothesis,
                :instrument_schema,:instrument_sha,'qwen-plus',
                :config_sha,:prompt_schema,:experiment_sha,:created_at,NULL
            )
            """
        ),
        {
            "id": experiment_id,
            "scenario_id": scenario.id,
            "scenario_sha": scenario.scenario_sha256,
            "scenario_title": scenario.title,
            "question": scenario.decision_question,
            "cohort_id": cohort_ref.id,
            "cohort_sha": cohort_ref.cohort_sha256,
            "cohort_title": cohort_ref.title,
            "dataset_sha": cohort_ref.dataset_sha256,
            "baseline_id": baseline.id,
            "baseline_name": baseline.name,
            "baseline_hypothesis": baseline.hypothesis,
            "alternative_id": alternative.id,
            "alternative_name": alternative.name,
            "alternative_hypothesis": alternative.hypothesis,
            "instrument_schema": INSTRUMENT_SCHEMA_VERSION,
            "instrument_sha": instrument.instrument_sha256,
            "config_sha": "2" * 64,
            "prompt_schema": SURVEY_PROMPT_SCHEMA_VERSION,
            "experiment_sha": experiment_sha256,
            "created_at": created_at,
        },
    )
    await connection.execute(
        text(
            """
            INSERT INTO matraix_survey_trials (
                id,experiment_id,persona_position,persona_id,persona_external_id,
                persona_display_name,persona_profile_sha256,trial_sha256,status,created_at
            ) VALUES (
                :id,:parent_id,0,:persona_id,:external_id,:display_name,
                :profile_sha,:trial_sha,'queued',:created_at
            )
            """
        ),
        {
            "id": trial_id,
            "parent_id": experiment_id,
            "persona_id": persona.id,
            "external_id": persona.persona_id,
            "display_name": persona.display_name,
            "profile_sha": persona.profile_sha256,
            "trial_sha": trial_sha256,
            "created_at": created_at,
        },
    )
    await connection.execute(
        text("UPDATE matraix_survey_experiments SET input_sealed_at=:created_at WHERE id=:id"),
        {"id": experiment_id, "created_at": created_at},
    )
    return experiment_id, trial_id, trial_sha256


async def _insert_failed_chat_trial(
    connection: AsyncConnection,
    cohort: CohortDetail,
    created_at: datetime,
) -> tuple[UUID, str]:
    task = build_chat_task("matraix/acme-support-order-4521")
    member = cohort.members[0]
    cohort_ref = ChatCohortRef(
        id=cohort.id,
        title=cohort.title,
        cohort_sha256=cohort.cohort_sha256,
        dataset_sha256=cohort.dataset.dataset_sha256,
        persona_count=cohort.persona_count,
    )
    persona = ChatPersonaRef(
        id=member.persona.id,
        position=member.position,
        persona_id=member.persona.persona_id,
        display_name=member.persona.display_name,
        profile_sha256=member.persona.profile_sha256,
    )
    evaluation_sha256 = calculate_evaluation_sha256(
        task.task_spec_sha256,
        task.sut_spec_sha256,
        cohort_ref,
        "qwen-plus",
        "3" * 64,
        None,
        1,
    )
    evaluation_id = uuid4()
    trial_id = uuid4()
    trial_sha256 = calculate_trial_sha256(evaluation_sha256, persona)
    await connection.execute(
        text(
            """
            INSERT INTO matraix_chat_evaluations (
                id,cohort_id,cohort_sha256,cohort_title,dataset_sha256,persona_count,
                task_id,task_version,task_schema_version,task_spec_sha256,sut_spec_sha256,
                model_name,chat_config_sha256,prompt_schema_version,evaluation_sha256,
                created_at,input_sealed_at
            ) VALUES (
                :id,:cohort_id,:cohort_sha,:cohort_title,:dataset_sha,1,
                :task_id,:task_version,:task_schema,:task_sha,:sut_sha,
                'qwen-plus',:config_sha,:prompt_schema,:evaluation_sha,:created_at,NULL
            )
            """
        ),
        {
            "id": evaluation_id,
            "cohort_id": cohort_ref.id,
            "cohort_sha": cohort_ref.cohort_sha256,
            "cohort_title": cohort_ref.title,
            "dataset_sha": cohort_ref.dataset_sha256,
            "task_id": task.task_id,
            "task_version": task.version,
            "task_schema": task.schema_version,
            "task_sha": task.task_spec_sha256,
            "sut_sha": task.sut_spec_sha256,
            "config_sha": "3" * 64,
            "prompt_schema": CHAT_PROMPT_SCHEMA_VERSION,
            "evaluation_sha": evaluation_sha256,
            "created_at": created_at,
        },
    )
    await connection.execute(
        text(
            """
            INSERT INTO matraix_chat_trials (
                id,evaluation_id,persona_position,persona_id,persona_external_id,
                persona_display_name,persona_profile_sha256,trial_sha256,status,created_at
            ) VALUES (
                :id,:parent_id,0,:persona_id,:external_id,:display_name,
                :profile_sha,:trial_sha,'queued',:created_at
            )
            """
        ),
        {
            "id": trial_id,
            "parent_id": evaluation_id,
            "persona_id": persona.id,
            "external_id": persona.persona_id,
            "display_name": persona.display_name,
            "profile_sha": persona.profile_sha256,
            "trial_sha": trial_sha256,
            "created_at": created_at,
        },
    )
    await connection.execute(
        text("UPDATE matraix_chat_evaluations SET input_sealed_at=:created_at WHERE id=:id"),
        {"id": evaluation_id, "created_at": created_at},
    )
    await connection.execute(
        text(
            """
            UPDATE matraix_chat_trials
            SET status='running',started_at=:started_at,claimed_by_worker_id='archive-test'
            WHERE id=:id
            """
        ),
        {"id": trial_id, "started_at": created_at + timedelta(seconds=1)},
    )
    await connection.execute(
        text(
            """
            UPDATE matraix_chat_trials
            SET status='failed',completed_at=:completed_at,error_code='sut_timeout',
                error_message='The source-sample SUT timed out.'
            WHERE id=:id
            """
        ),
        {"id": trial_id, "completed_at": created_at + timedelta(seconds=2)},
    )
    return trial_id, trial_sha256


async def _assert_read_only_snapshot_starts_before_archive_select(database_url: str) -> None:
    connector = DatabaseConnector.create(database_url)
    statements: list[str] = []

    def capture_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(" ".join(statement.lower().split()))

    event.listen(connector.engine.sync_engine, "before_cursor_execute", capture_statement)
    application = FastAPI()
    application.state.database = connector
    application.include_router(create_matraix_trial_archive_router())
    try:
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://archive-snapshot-test",
        ) as client:
            response = await client.get("/api/v2/matraix/trials?page=1&page_size=1")
            assert response.status_code == 200
        isolation_index = next(
            index
            for index, statement in enumerate(statements)
            if statement == "set transaction isolation level repeatable read read only"
        )
        archive_select_index = next(
            index
            for index, statement in enumerate(statements)
            if "select count(*) from (" in statement
            and "matraix_chat_trials" in statement
            and "matraix_survey_trials" in statement
        )
        assert isolation_index < archive_select_index
        archive_sql = "\n".join(statements[isolation_index:])
        for table_name in ARTIFACT_TABLES:
            assert table_name not in archive_sql
    finally:
        event.remove(connector.engine.sync_engine, "before_cursor_execute", capture_statement)
        await connector.close()


async def _exercise_archive_api(database_url: str) -> None:
    await _assert_read_only_snapshot_starts_before_archive_select(database_url)
    engine = create_async_engine(normalize_async_database_url(database_url), pool_pre_ping=True)
    statements: list[str] = []

    def capture_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(statement.lower())

    event.listen(engine.sync_engine, "before_cursor_execute", capture_statement)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
                assert revision == "20260816_core_0035"
                cohort = await _insert_population(connection)
                scenario, baseline, alternative = await _insert_scenario(connection)
                trial_created_at = datetime.now(UTC)
                survey_experiment_id, survey_id, survey_sha = await _insert_survey_trial(
                    connection,
                    cohort,
                    scenario,
                    baseline,
                    alternative,
                    trial_created_at,
                )
                chat_id, chat_sha = await _insert_failed_chat_trial(
                    connection,
                    cohort,
                    trial_created_at,
                )
                application = FastAPI()
                application.include_router(create_matraix_trial_archive_router())

                async def session_override() -> AsyncIterator[AsyncSession]:
                    async with AsyncSession(
                        bind=connection,
                        expire_on_commit=False,
                        join_transaction_mode="create_savepoint",
                    ) as session:
                        yield session

                application.dependency_overrides[require_trial_archive_session] = session_override
                statements.clear()
                async with AsyncClient(
                    transport=ASGITransport(app=application),
                    base_url="http://archive-integration-test",
                ) as client:
                    first_response = await client.get("/api/v2/matraix/trials?page=1&page_size=1")
                    assert first_response.status_code == 200
                    first = first_response.json()
                    assert first["total"] == 2
                    assert first["items"][0]["kind"] == "chat"
                    assert first["items"][0]["id"] == str(chat_id)
                    assert first["items"][0]["trial_sha256"] == chat_sha
                    assert first["items"][0]["error"]["code"] == "sut_timeout"
                    assert first["items"][0]["provenance"]["model_name"] == "qwen-plus"
                    assert first["items"][0]["provenance"]["runner_version"] is None

                    second_response = await client.get("/api/v2/matraix/trials?page=2&page_size=1")
                    assert second_response.status_code == 200
                    second = second_response.json()
                    assert second["total"] == 2
                    assert second["items"][0]["kind"] == "survey"
                    assert second["items"][0]["id"] == str(survey_id)
                    assert second["items"][0]["trial_sha256"] == survey_sha
                    assert second["items"][0]["task"] == {
                        "title": "Archive scenario",
                        "version": "scenario-preference/v1",
                    }

                    survey_response = await client.get(
                        "/api/v2/matraix/trials?kind=survey&status=queued"
                    )
                    assert survey_response.status_code == 200
                    assert survey_response.json()["total"] == 1
                    assert survey_response.json()["items"][0]["id"] == str(survey_id)

                    failed_response = await client.get("/api/v2/matraix/trials?status=failed")
                    assert failed_response.status_code == 200
                    assert failed_response.json()["total"] == 1
                    assert failed_response.json()["items"][0]["id"] == str(chat_id)

                    empty_response = await client.get(
                        "/api/v2/matraix/trials?kind=survey&status=failed"
                    )
                    assert empty_response.status_code == 200
                    assert empty_response.json()["items"] == []
                    assert empty_response.json()["total"] == 0

                    out_of_range = await client.get("/api/v2/matraix/trials?page=3&page_size=1")
                    assert out_of_range.status_code == 422

                archive_sql = "\n".join(statements)
                assert "union all" in archive_sql
                assert "fetch first" in archive_sql
                for table_name in ARTIFACT_TABLES:
                    assert table_name not in archive_sql

                statements.clear()
                async with AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                ) as session:
                    survey_experiments = await list_matraix_survey_experiments(session)
                assert survey_experiments.total == 1
                assert survey_experiments.items[0].status == "queued"
                survey_list_sql = "\n".join(statements)
                assert "matraix_survey_trials" in survey_list_sql
                assert "matraix_survey_answers" not in survey_list_sql

                async with AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                ) as session:
                    survey_progress = await get_matraix_survey_experiment_progress(
                        session,
                        survey_experiment_id,
                    )
                assert survey_progress.status == "queued"
                assert survey_progress.queued_trial_count == 1
                assert survey_progress.event_count == 0
            finally:
                await transaction.rollback()
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture_statement)
        await engine.dispose()


@pytest.mark.skipif(
    TEST_POSTGRES_DATABASE_URL is None,
    reason="TEST_POSTGRES_DATABASE_URL is required for MatrAIx Trial Archive PostgreSQL tests",
)
def test_matraix_trial_archive_executes_against_postgresql() -> None:
    assert TEST_POSTGRES_DATABASE_URL is not None
    asyncio.run(_exercise_archive_api(TEST_POSTGRES_DATABASE_URL))
