"""Real PostgreSQL coverage for MatrAIx Web lifecycle and database guards."""

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

from app.api.matraix_web import create_matraix_web_router, require_web_session
from app.database import normalize_async_database_url
from app.matraix_web.contracts import WebPageObservation, WebQuoteObservation
from app.matraix_web.hashing import calculate_result_sha256, calculate_trace_sha256
from app.matraix_web.tasks import EXECUTOR_SPEC_SHA256
from tests.test_matraix_chat_postgresql import _insert_population

TEST_POSTGRES_DATABASE_URL = os.environ.get("TEST_POSTGRES_DATABASE_URL")
WEB_CONFIG_SHA256 = "d" * 64


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


async def _insert_ready_worker(connection: AsyncConnection) -> None:
    await connection.execute(
        text(
            """
            INSERT INTO simulation_worker_heartbeats (
                worker_id,engine,engine_version,camel_version,mode,
                platform_runtime_ready,semantic_runtime_ready,
                semantic_model_name,semantic_config_sha256,
                semantic_prompt_schema_version,web_runtime_ready,
                web_model_name,web_config_sha256,web_prompt_schema_version,
                web_executor_schema_version,web_executor_spec_sha256,
                started_at,last_seen_at
            ) VALUES (
                :worker_id,'camel-oasis','0.2.5','0.2.78','reddit_manual_smoke',
                true,true,'qwen-plus',:semantic_sha,'matraix-semantic-profile/v1',
                true,'qwen-plus',:web_sha,'matraix-web-quotes-choice/v1',
                'matraix-web-browser-executor/v1',:executor_sha,
                clock_timestamp(),clock_timestamp()
            )
            """
        ),
        {
            "worker_id": f"web-test-{uuid4()}",
            "semantic_sha": "c" * 64,
            "web_sha": WEB_CONFIG_SHA256,
            "executor_sha": EXECUTOR_SPEC_SHA256,
        },
    )


def _observations(trial_id: UUID, started_at: object) -> tuple[WebPageObservation, ...]:
    pages: list[WebPageObservation] = []
    for page_position in range(3):
        quote_position = page_position
        quote = WebQuoteObservation(
            position=quote_position,
            quote_id=str(page_position + 4) * 64,
            text=f"Observed quote number {page_position + 1}.",
            author=f"Author {page_position + 1}",
            tags=(f"tag-{page_position + 1}",),
        )
        pages.append(
            WebPageObservation(
                position=page_position,
                url=(
                    "https://quotes.toscrape.com/"
                    if page_position == 0
                    else f"https://quotes.toscrape.com/page/{page_position + 1}/"
                ),
                title="Quotes to Scrape",
                screenshot_sha256=str(page_position + 1) * 64,
                screenshot_path=(
                    f"/api/v2/matraix/web-trials/{trial_id}/screenshots/{page_position}"
                ),
                observed_at=started_at,
                quotes=(quote,),
            )
        )
    return tuple(pages)


async def _exercise_web_api(database_url: str) -> None:
    engine = create_async_engine(normalize_async_database_url(database_url), pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
                assert revision == "20260816_core_0035"
                cohort_id = await _insert_population(connection)
                await _insert_ready_worker(connection)

                application = FastAPI()
                application.include_router(create_matraix_web_router())

                async def session_override() -> AsyncIterator[AsyncSession]:
                    async with AsyncSession(
                        bind=connection,
                        expire_on_commit=False,
                        join_transaction_mode="create_savepoint",
                    ) as session:
                        yield session

                application.dependency_overrides[require_web_session] = session_override
                async with AsyncClient(
                    transport=ASGITransport(app=application),
                    base_url="http://web-integration-test",
                ) as client:
                    readiness = await client.get("/api/v2/matraix/web-readiness")
                    assert readiness.status_code == 200
                    assert readiness.json()["web_runtime_ready"] is True

                    created_response = await client.post(
                        "/api/v2/matraix/web-evaluations",
                        json={
                            "cohort_id": str(cohort_id),
                            "task_id": "matraix/quotes-playwright-choice",
                            "task_version": "1.0.0",
                        },
                    )
                    assert created_response.status_code == 202, created_response.text
                    created = created_response.json()
                    evaluation_id = UUID(created["id"])
                    trial_id = UUID(created["trials"][0]["id"])
                    assert created["status"] == "queued"
                    assert created["attempt_number"] == 1
                    progress_response = await client.get(
                        f"/api/v2/matraix/web-evaluations/{evaluation_id}/progress"
                    )
                    assert progress_response.status_code == 200
                    assert progress_response.json()["queued_trial_count"] == 1
                    assert progress_response.json()["event_count"] == 0

                    await connection.execute(
                        text(
                            "UPDATE matraix_web_trials SET status='running',"
                            "started_at=clock_timestamp(),claimed_by_worker_id='web-test' "
                            "WHERE id=:trial_id"
                        ),
                        {"trial_id": trial_id},
                    )
                    await connection.execute(
                        text(
                            "UPDATE matraix_web_trials SET status='failed',"
                            "completed_at=clock_timestamp(),error_code='browser_timeout',"
                            "error_message='The fixed browser attempt timed out.' "
                            "WHERE id=:trial_id"
                        ),
                        {"trial_id": trial_id},
                    )
                    retry_response = await client.post(
                        f"/api/v2/matraix/web-evaluations/{evaluation_id}/retry",
                        json={},
                    )
                    assert retry_response.status_code == 202, retry_response.text
                    retried = retry_response.json()
                    assert retried["attempt_number"] == 2
                    assert retried["retry_of_evaluation_id"] == str(evaluation_id)
                    assert retried["retry_of_evaluation_sha256"] == created["evaluation_sha256"]
                    repeated_retry = await client.post(
                        f"/api/v2/matraix/web-evaluations/{evaluation_id}/retry",
                        json={},
                    )
                    assert repeated_retry.status_code == 202
                    assert repeated_retry.json()["id"] == retried["id"]
                    parent_response = await client.get(
                        f"/api/v2/matraix/web-evaluations/{evaluation_id}"
                    )
                    assert parent_response.json()["status"] == "failed"
                    evaluation_id = UUID(retried["id"])
                    trial_id = UUID(retried["trials"][0]["id"])

                    await connection.execute(
                        text(
                            """
                            UPDATE matraix_web_trials
                            SET status='running',started_at=clock_timestamp(),
                                claimed_by_worker_id='web-test'
                            WHERE id=:trial_id
                            """
                        ),
                        {"trial_id": trial_id},
                    )
                    started_at = await connection.scalar(
                        text("SELECT started_at FROM matraix_web_trials WHERE id=:trial_id"),
                        {"trial_id": trial_id},
                    )
                    assert started_at is not None
                    pages = _observations(trial_id, started_at)
                    for page in pages:
                        await connection.execute(
                            text(
                                """
                                INSERT INTO matraix_web_pages (
                                    trial_id,position,url,title,screenshot_sha256,observed_at
                                ) VALUES (
                                    :trial_id,:position,:url,:title,:screenshot_sha,:observed_at
                                )
                                """
                            ),
                            {
                                "trial_id": trial_id,
                                "position": page.position,
                                "url": page.url,
                                "title": page.title,
                                "screenshot_sha": page.screenshot_sha256,
                                "observed_at": page.observed_at,
                            },
                        )
                        quote = page.quotes[0]
                        await connection.execute(
                            text(
                                """
                                INSERT INTO matraix_web_quotes (
                                    trial_id,position,page_position,quote_id,text,author,tags
                                ) VALUES (
                                    :trial_id,:position,:page_position,:quote_id,:text,:author,
                                    ARRAY[:tag]
                                )
                                """
                            ),
                            {
                                "trial_id": trial_id,
                                "position": quote.position,
                                "page_position": page.position,
                                "quote_id": quote.quote_id,
                                "text": quote.text,
                                "author": quote.author,
                                "tag": quote.tags[0],
                            },
                        )

                    trial_sha = await connection.scalar(
                        text("SELECT trial_sha256 FROM matraix_web_trials WHERE id=:trial_id"),
                        {"trial_id": trial_id},
                    )
                    assert isinstance(trial_sha, str)
                    selected = pages[1].quotes[0]
                    trace_sha = calculate_trace_sha256(trial_sha, pages)
                    reason = (
                        "This observed quote best matches the frozen Persona after comparing "
                        "all three pages."
                    )
                    result_sha = calculate_result_sha256(
                        trial_sha,
                        trace_sha,
                        selected.quote_id,
                        selected.text,
                        "fit",
                        reason,
                        selected.author,
                        "yes",
                        "yes",
                        8,
                    )
                    update_statement = """
                        UPDATE matraix_web_trials SET
                            status='succeeded',completed_at=clock_timestamp(),
                            runner_version='1.0.0',model_name='qwen-plus',
                            web_config_sha256=:web_sha,
                            prompt_schema_version='matraix-web-quotes-choice/v1',
                            trace_sha256=:trace_sha,result_sha256=:result_sha,
                            decision_subject_id=:subject_id,
                            decision_subject_label=:subject_label,basis_primary='fit',
                            reason=:reason,task_author=:author,
                            need_constraint_satisfaction='yes',
                            personal_preference_satisfaction='yes',
                            overall_experience_rating=8
                        WHERE id=:trial_id
                    """
                    await _expect_rejection(
                        connection,
                        update_statement,
                        {
                            "trial_id": trial_id,
                            "web_sha": WEB_CONFIG_SHA256,
                            "trace_sha": trace_sha,
                            "result_sha": result_sha,
                            "subject_id": "f" * 64,
                            "subject_label": selected.text,
                            "reason": reason,
                            "author": selected.author,
                        },
                    )
                    await connection.execute(
                        text(update_statement),
                        {
                            "trial_id": trial_id,
                            "web_sha": WEB_CONFIG_SHA256,
                            "trace_sha": trace_sha,
                            "result_sha": result_sha,
                            "subject_id": selected.quote_id,
                            "subject_label": selected.text,
                            "reason": reason,
                            "author": selected.author,
                        },
                    )
                    await _expect_rejection(
                        connection,
                        "UPDATE matraix_web_quotes SET text='tampered' "
                        "WHERE trial_id=:trial_id AND position=0",
                        {"trial_id": trial_id},
                    )

                    detail_response = await client.get(
                        f"/api/v2/matraix/web-evaluations/{evaluation_id}"
                    )
                    assert detail_response.status_code == 200
                    detail = detail_response.json()
                    assert detail["status"] == "succeeded"
                    assert detail["succeeded_trial_count"] == 1
                    assert detail["trials"][0]["selected_quote_id"] == selected.quote_id

                    trial_response = await client.get(f"/api/v2/matraix/web-trials/{trial_id}")
                    assert trial_response.status_code == 200
                    trial = trial_response.json()
                    assert len(trial["pages"]) == 3
                    assert trial["result"]["result_sha256"] == result_sha
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    TEST_POSTGRES_DATABASE_URL is None,
    reason="TEST_POSTGRES_DATABASE_URL is required for MatrAIx Web PostgreSQL tests",
)
def test_matraix_web_api_and_guards_execute_against_postgresql() -> None:
    assert TEST_POSTGRES_DATABASE_URL is not None
    asyncio.run(_exercise_web_api(TEST_POSTGRES_DATABASE_URL))
