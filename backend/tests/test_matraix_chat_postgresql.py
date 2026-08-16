"""Real PostgreSQL coverage for MatrAIx Chat lifecycle, API, and query bounds."""

import asyncio
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine

from app.api.matraix_chat import create_matraix_chat_router, require_chat_session
from app.database import normalize_async_database_url
from app.matraix_chat.contracts import (
    ChatTranscriptMessage,
    ChatTrialFeedback,
)
from app.matraix_chat.hashing import (
    calculate_feedback_sha256,
    calculate_result_sha256,
    calculate_transcript_sha256,
)
from app.matraix_chat.tasks import CHAT_SUITE_ID, CHAT_SUITE_SHA256, CHAT_SUITE_VERSION
from app.populations.contracts import (
    CohortCreateRequest,
    StoredPersonaProfile,
    StoredPersonaProvenance,
)
from app.populations.hashing import (
    calculate_persona_profile_sha256,
    canonical_persona_profile_json,
)
from app.populations.repository import create_cohort

TEST_POSTGRES_DATABASE_URL = os.environ.get("TEST_POSTGRES_DATABASE_URL")


def _profile() -> StoredPersonaProfile:
    return StoredPersonaProfile(
        display_name="Chat integration Persona",
        dimensions={"intent": "Get task done", "region": "East Asia"},
        persona_id="chat-integration-persona",
        provenance=StoredPersonaProvenance(
            hf_repo=None,
            origin_persona_id=None,
            origin_source_row_index=None,
            parent_pool="chat-integration-test",
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
        "parent_pool": "chat-integration-test",
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


async def _insert_population(connection: AsyncConnection) -> UUID:
    dataset_id = uuid4()
    persona_id = uuid4()
    profile = _profile()
    created_at = datetime.now(UTC)
    slug = f"chat-integration-{dataset_id}"
    display_name = "Chat integration dataset"
    manifest_sha256 = "a" * 64
    await connection.execute(
        text(
            """
            INSERT INTO persona_datasets (
                id, slug, display_name, schema_version, parent_pool,
                source_repository, persona_count, manifest_sha256,
                dataset_sha256, created_at, sealed_at
            ) VALUES (
                :id, :slug, :display_name, '1.0', 'chat-integration-test',
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
        cohort = await create_cohort(
            session,
            CohortCreateRequest(
                title="Chat integration Cohort",
                dataset_id=dataset_id,
                persona_ids=(persona_id,),
            ),
        )
    return cohort.id


async def _insert_ready_worker(connection: AsyncConnection) -> None:
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
                'matraix-semantic-profile/v1', false, NULL, NULL, NULL,
                true, 'qwen-plus', :chat_sha, 'matraix-chat-acme-support/v1',
                :suite_id, :suite_version, :suite_sha,
                clock_timestamp(), clock_timestamp()
            )
            """
        ),
        {
            "worker_id": f"chat-test-{uuid4()}",
            "semantic_sha": "b" * 64,
            "chat_sha": "c" * 64,
            "suite_id": CHAT_SUITE_ID,
            "suite_version": CHAT_SUITE_VERSION,
            "suite_sha": CHAT_SUITE_SHA256,
        },
    )


async def _expect_guard_rejection(
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


async def _exercise_chat_api(database_url: str) -> None:
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
                assert revision == "20260816_core_0034"
                cohort_id = await _insert_population(connection)
                await _insert_ready_worker(connection)
                application = FastAPI()
                application.include_router(create_matraix_chat_router())

                async def session_override() -> AsyncIterator[AsyncSession]:
                    async with AsyncSession(
                        bind=connection,
                        expire_on_commit=False,
                        join_transaction_mode="create_savepoint",
                    ) as session:
                        yield session

                application.dependency_overrides[require_chat_session] = session_override
                async with AsyncClient(
                    transport=ASGITransport(app=application),
                    base_url="http://chat-integration-test",
                ) as client:
                    readiness = await client.get("/api/v2/matraix/chat-readiness")
                    assert readiness.status_code == 200
                    assert readiness.json()["chat_runtime_ready"] is True
                    create_response = await client.post(
                        "/api/v2/matraix/chat-evaluations",
                        json={
                            "cohort_id": str(cohort_id),
                            "task_id": "matraix/acme-support-order-4521",
                            "task_version": "1.0.0",
                        },
                    )
                    assert create_response.status_code == 202
                    created = create_response.json()
                    evaluation_id = UUID(created["id"])
                    trial_id = UUID(created["trials"][0]["id"])
                    assert created["status"] == "queued"
                    assert created["task"]["source"]["production_sut"] is False

                    await connection.execute(
                        text(
                            """
                            UPDATE matraix_chat_trials
                            SET status='running', started_at=clock_timestamp(),
                                claimed_by_worker_id='chat-test'
                            WHERE id=:trial_id
                            """
                        ),
                        {"trial_id": trial_id},
                    )
                    await _expect_guard_rejection(
                        connection,
                        """
                        INSERT INTO matraix_chat_messages
                            (trial_id,position,role,content,recorded_at)
                        VALUES (:trial_id,0,'customer',:content,clock_timestamp())
                        """,
                        {"trial_id": trial_id, "content": "\t\n"},
                    )
                    await _expect_guard_rejection(
                        connection,
                        """
                        INSERT INTO matraix_chat_messages
                            (trial_id,position,role,content,recorded_at)
                        VALUES (:trial_id,1,'support','Out of order',clock_timestamp())
                        """,
                        {"trial_id": trial_id},
                    )
                    message_values = (
                        (0, "customer", "My order #4521 is late."),
                        (1, "support", "Is the shipping address correct?"),
                        (2, "customer", "Yes. What does tracking show?"),
                        (3, "support", "It left the regional hub yesterday."),
                    )
                    for position, role, content in message_values:
                        await connection.execute(
                            text(
                                """
                                INSERT INTO matraix_chat_messages
                                    (trial_id,position,role,content,recorded_at)
                                VALUES (
                                    :trial_id,:position,:role,:content,clock_timestamp()
                                )
                                """
                            ),
                            {
                                "trial_id": trial_id,
                                "position": position,
                                "role": role,
                                "content": content,
                            },
                        )
                    await connection.execute(
                        text(
                            """
                            INSERT INTO matraix_chat_feedback (
                                trial_id,schema_version,need_constraint_satisfaction,
                                personal_preference_satisfaction,overall_experience_rating,
                                reason,asked_useful_clarification_questions,
                                clarifying_notes,recorded_at
                            ) VALUES (
                                :trial_id,'matraix-chat-feedback/acme-support-v1',
                                'partially','yes',7,:reason,true,:notes,clock_timestamp()
                            )
                            """
                        ),
                        {
                            "trial_id": trial_id,
                            "reason": "The path is concrete, but delivery is pending.",
                            "notes": "The address question confirmed the order details.",
                        },
                    )
                    trial_sha = await connection.scalar(
                        text("SELECT trial_sha256 FROM matraix_chat_trials WHERE id=:trial_id"),
                        {"trial_id": trial_id},
                    )
                    assert isinstance(trial_sha, str)
                    recorded_at = datetime.now(UTC)
                    messages = tuple(
                        ChatTranscriptMessage(
                            position=position,
                            role=role,
                            content=content,
                            recorded_at=recorded_at,
                        )
                        for position, role, content in message_values
                    )
                    feedback = ChatTrialFeedback(
                        schema_version="matraix-chat-feedback/acme-support-v1",
                        need_constraint_satisfaction="partially",
                        personal_preference_satisfaction="yes",
                        overall_experience_rating=7,
                        reason="The path is concrete, but delivery is pending.",
                        asked_useful_clarification_questions=True,
                        clarifying_notes="The address question confirmed the order details.",
                    )
                    transcript_sha = calculate_transcript_sha256(trial_sha, messages)
                    feedback_sha = calculate_feedback_sha256(trial_sha, feedback)
                    result_sha = calculate_result_sha256(
                        trial_sha,
                        transcript_sha,
                        feedback_sha,
                        "partially_resolved",
                        "user",
                        "clarify_then_partial",
                        "advanced",
                        4,
                        2,
                        2,
                        1,
                    )
                    await connection.execute(
                        text(
                            """
                            UPDATE matraix_chat_trials SET
                                status='succeeded',completed_at=clock_timestamp(),
                                runner_version='1.0.0',
                                model_name='qwen-plus',chat_config_sha256=:chat_sha,
                                prompt_schema_version='matraix-chat-acme-support/v1',
                                transcript_sha256=:transcript_sha,feedback_sha256=:feedback_sha,
                                result_sha256=:result_sha,outcome_status='partially_resolved',
                                next_step_owner='user',conversation_path='clarify_then_partial',
                                resolution_progression='advanced',message_count=4,
                                customer_turn_count=2,support_turn_count=2,
                                clarification_question_count=1
                            WHERE id=:trial_id
                            """
                        ),
                        {
                            "trial_id": trial_id,
                            "chat_sha": "c" * 64,
                            "transcript_sha": transcript_sha,
                            "feedback_sha": feedback_sha,
                            "result_sha": result_sha,
                        },
                    )
                    await _expect_guard_rejection(
                        connection,
                        "UPDATE matraix_chat_messages SET content='tampered' "
                        "WHERE trial_id=:trial_id AND position=0",
                        {"trial_id": trial_id},
                    )

                    await connection.execute(
                        text(
                            """
                            UPDATE simulation_worker_heartbeats
                            SET chat_config_sha256=:chat_sha,
                                last_seen_at=clock_timestamp()
                            WHERE worker_id LIKE 'chat-test-%'
                            """
                        ),
                        {"chat_sha": "d" * 64},
                    )
                    failed_create_response = await client.post(
                        "/api/v2/matraix/chat-evaluations",
                        json={
                            "cohort_id": str(cohort_id),
                            "task_id": "matraix/acme-support-order-4521",
                            "task_version": "1.0.0",
                        },
                    )
                    assert failed_create_response.status_code == 202
                    failed_evaluation = failed_create_response.json()
                    failed_trial_id = UUID(failed_evaluation["trials"][0]["id"])
                    await connection.execute(
                        text(
                            """
                            UPDATE matraix_chat_trials
                            SET status='running', started_at=clock_timestamp(),
                                claimed_by_worker_id='chat-test'
                            WHERE id=:trial_id
                            """
                        ),
                        {"trial_id": failed_trial_id},
                    )
                    await connection.execute(
                        text(
                            """
                            INSERT INTO matraix_chat_messages
                                (trial_id,position,role,content,recorded_at)
                            VALUES (
                                :trial_id,0,'customer','My order is late.',clock_timestamp()
                            )
                            """
                        ),
                        {"trial_id": failed_trial_id},
                    )
                    await _expect_guard_rejection(
                        connection,
                        """
                        INSERT INTO matraix_chat_feedback (
                            trial_id,schema_version,need_constraint_satisfaction,
                            personal_preference_satisfaction,overall_experience_rating,
                            reason,asked_useful_clarification_questions,
                            clarifying_notes,recorded_at
                        ) VALUES (
                            :trial_id,'matraix-chat-feedback/acme-support-v1',
                            'no','no',1,'Premature.',false,'No complete exchange.',
                            clock_timestamp()
                        )
                        """,
                        {"trial_id": failed_trial_id},
                    )
                    await connection.execute(
                        text(
                            """
                            UPDATE matraix_chat_trials
                            SET status='failed',completed_at=clock_timestamp(),
                                error_code='sut_timeout',
                                error_message='The source-sample SUT timed out.'
                            WHERE id=:trial_id
                            """
                        ),
                        {"trial_id": failed_trial_id},
                    )
                    failed_trial_response = await client.get(
                        f"/api/v2/matraix/chat-trials/{failed_trial_id}"
                    )
                    assert failed_trial_response.status_code == 200
                    failed_trial = failed_trial_response.json()
                    assert failed_trial["status"] == "failed"
                    assert len(failed_trial["transcript"]) == 1
                    assert failed_trial["feedback"] is None
                    assert failed_trial["result"] is None
                    assert failed_trial["error"]["code"] == "sut_timeout"

                    statements.clear()
                    list_response = await client.get("/api/v2/matraix/chat-evaluations")
                    assert list_response.status_code == 200
                    listed = next(
                        item
                        for item in list_response.json()["items"]
                        if item["id"] == str(evaluation_id)
                    )
                    assert listed["status"] == "succeeded"
                    assert listed["succeeded_trial_count"] == 1
                    list_sql = "\n".join(statements)
                    assert "matraix_chat_messages" not in list_sql
                    assert "matraix_chat_feedback" not in list_sql

                    detail_response = await client.get(
                        f"/api/v2/matraix/chat-evaluations/{evaluation_id}"
                    )
                    assert detail_response.status_code == 200
                    detail = detail_response.json()
                    assert detail["trials"][0]["result"]["result_sha256"] == result_sha
                    assert len(detail["trials"][0]["transcript"]) == 4
                    trial_response = await client.get(f"/api/v2/matraix/chat-trials/{trial_id}")
                    assert trial_response.status_code == 200
                    assert trial_response.json()["feedback"]["overall_experience_rating"] == 7
            finally:
                await transaction.rollback()
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture_statement)
        await engine.dispose()


@pytest.mark.skipif(
    TEST_POSTGRES_DATABASE_URL is None,
    reason="TEST_POSTGRES_DATABASE_URL is required for MatrAIx Chat PostgreSQL tests",
)
def test_matraix_chat_api_and_guards_execute_against_postgresql() -> None:
    assert TEST_POSTGRES_DATABASE_URL is not None
    asyncio.run(_exercise_chat_api(TEST_POSTGRES_DATABASE_URL))
