"""MatrAIx Web public contracts, hashes, and no-database API boundary."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import load_runtime_settings
from app.main import create_app
from app.matraix_web.contracts import (
    MatraixWebEvaluationCreateRequest,
    MatraixWebTrial,
    WebCohortRef,
    WebPageObservation,
    WebPersonaRef,
    WebQuoteObservation,
    WebTrialResult,
)
from app.matraix_web.hashing import (
    calculate_evaluation_sha256,
    calculate_result_sha256,
    calculate_trace_sha256,
    calculate_trial_sha256,
)
from app.matraix_web.tasks import EXECUTOR_SPEC_SHA256, build_web_task


def _frozen_input() -> tuple[WebCohortRef, WebPersonaRef]:
    return (
        WebCohortRef(
            id=UUID("21000000-0000-4000-8000-000000000001"),
            title="Web cohort",
            cohort_sha256="a" * 64,
            dataset_sha256="b" * 64,
            persona_count=1,
        ),
        WebPersonaRef(
            id=UUID("22000000-0000-4000-8000-000000000001"),
            position=0,
            persona_id="web-persona",
            display_name="Web Persona",
            profile_sha256="c" * 64,
        ),
    )


def test_web_task_and_output_are_content_addressed() -> None:
    task = build_web_task()
    cohort, persona = _frozen_input()
    evaluation_sha = calculate_evaluation_sha256(
        task.task_spec_sha256,
        task.executor_spec_sha256,
        cohort,
        "qwen-plus",
        "d" * 64,
    )
    trial_sha = calculate_trial_sha256(evaluation_sha, persona)
    observed_at = datetime(2026, 8, 15, tzinfo=UTC)
    quote = WebQuoteObservation(
        position=0,
        quote_id="e" * 64,
        text="The world as we have created it is a process of our thinking.",
        author="Albert Einstein",
        tags=("change", "thinking"),
    )
    pages = tuple(
        WebPageObservation(
            position=position,
            url=(
                "https://quotes.toscrape.com/"
                if position == 0
                else f"https://quotes.toscrape.com/page/{position + 1}/"
            ),
            title="Quotes to Scrape",
            screenshot_sha256=str(position + 1) * 64,
            screenshot_path=(
                "/api/v2/matraix/web-trials/"
                f"23000000-0000-4000-8000-000000000001/screenshots/{position}"
            ),
            observed_at=observed_at,
            quotes=(
                quote.model_copy(update={"position": position, "quote_id": f"{position + 4}" * 64}),
            ),
        )
        for position in range(3)
    )
    selected = pages[0].quotes[0]
    trace_sha = calculate_trace_sha256(trial_sha, pages)
    result_sha = calculate_result_sha256(
        trial_sha,
        trace_sha,
        selected.quote_id,
        selected.text,
        "taste",
        "This quote fits the Persona's reflective preference and was compared with others.",
        selected.author,
        "yes",
        "yes",
        8,
    )
    result = WebTrialResult(
        runner_version="1.0.0",
        model_name="qwen-plus",
        web_config_sha256="d" * 64,
        prompt_schema_version="matraix-web-quotes-choice/v1",
        trace_sha256=trace_sha,
        result_sha256=result_sha,
        decision_subject_id=selected.quote_id,
        decision_subject_label=selected.text,
        decision_outcome="selected",
        basis_primary="taste",
        exploration_style="compared_multiple",
        reason="This quote fits the Persona's reflective preference and was compared with others.",
        task_author=selected.author,
        need_constraint_satisfaction="yes",
        personal_preference_satisfaction="yes",
        overall_experience_rating=8,
    )
    trial = MatraixWebTrial(
        id=UUID("23000000-0000-4000-8000-000000000001"),
        status="succeeded",
        persona=persona,
        trial_sha256=trial_sha,
        created_at=observed_at,
        started_at=observed_at,
        completed_at=observed_at,
        pages=pages,
        result=result,
        error=None,
    )

    assert task.executor_spec_sha256 == EXECUTOR_SPEC_SHA256
    assert task.task_spec_sha256 == (
        "f5be8a4a377764ac77f80e3178720e914b4b069875dc5b8f3bbd6ff3508525ad"
    )
    assert trial.result is not None
    assert trial.result.result_sha256 == result_sha


def test_web_task_is_public_and_runtime_routes_require_database() -> None:
    client = TestClient(create_app(load_runtime_settings({})))
    task_response = client.get("/api/v2/matraix/web-tasks")
    assert task_response.status_code == 200
    assert task_response.json()["items"][0]["transport"] == "playwright_chromium"

    responses = (
        client.get("/api/v2/matraix/web-evaluations"),
        client.get(f"/api/v2/matraix/web-evaluations/{uuid4()}"),
        client.get(f"/api/v2/matraix/web-trials/{uuid4()}"),
        client.get(f"/api/v2/matraix/web-trials/{uuid4()}/screenshots/0"),
        client.get("/api/v2/matraix/web-readiness"),
        client.post(
            "/api/v2/matraix/web-evaluations",
            json={
                "cohort_id": str(uuid4()),
                "task_id": "matraix/quotes-playwright-choice",
                "task_version": "1.0.0",
            },
        ),
    )
    for response in responses:
        assert response.status_code == 503
        assert response.json() == {
            "detail": "MatrAIx Web data is unavailable because DATABASE_URL is not configured"
        }


def test_web_create_request_rejects_unversioned_or_extra_input() -> None:
    with pytest.raises(ValueError):
        MatraixWebEvaluationCreateRequest.model_validate(
            {
                "cohort_id": uuid4(),
                "task_id": "example-web-playwright_quote-choice",
                "task_version": "1.0",
                "target_url": "https://example.com",
            }
        )
