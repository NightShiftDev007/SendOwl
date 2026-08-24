"""Compile and project immutable Project-bound evaluation task bundles."""

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.populations.contracts import CohortDetail
from app.populations.repository import get_cohort
from app.research_evaluations.contracts import (
    ResearchEvaluationExecutionProjection,
    ResearchEvaluationTaskBundle,
    ResearchEvaluationTaskBundleCreateRequest,
    ResearchEvaluationTaskBundlePayload,
)
from app.research_evaluations.errors import ResearchEvaluationScopeError
from app.research_evaluations.hashing import (
    calculate_survey_artifact_sha256,
    calculate_task_bundle_sha256,
)
from app.research_evaluations.models import ResearchEvaluationTaskBundleRecord
from app.research_projects.models import ResearchProjectRecord, ResearchSimulationRunRecord
from app.research_surveys.hashing import instrument_sha256
from app.research_surveys.models import ResearchSurveyRecord


async def verified_research_evaluation_scope(
    session: AsyncSession,
    project_id: UUID,
    run_id: UUID,
) -> tuple[ResearchProjectRecord, ResearchSimulationRunRecord, CohortDetail]:
    project = await session.get(ResearchProjectRecord, project_id)
    run = await session.get(ResearchSimulationRunRecord, run_id)
    if project is None or run is None or run.research_project_id != project_id:
        raise ResearchEvaluationScopeError(
            "evaluation task bundle requires one Run belonging to the selected Project"
        )
    if run.status != "succeeded":
        raise ResearchEvaluationScopeError(
            "evaluation task bundle requires a succeeded Simulation Run"
        )
    cohort = await get_cohort(session, run.cohort_id)
    if (
        run.project_sha256 != project.project_sha256
        or run.cohort_sha256 != cohort.cohort_sha256
        or run.persona_count != cohort.persona_count
        or cohort.persona_count > 8
    ):
        raise RuntimeError("evaluation task bundle failed immutable scope verification")
    return project, run, cohort


def _payload(
    project_sha256: str,
    run_spec_sha256: str,
    cohort: CohortDetail,
) -> ResearchEvaluationTaskBundlePayload:
    return ResearchEvaluationTaskBundlePayload(
        schema_version="sandowl-research-evaluation-task-bundle/v1",
        kind="survey",
        project_sha256=project_sha256,
        run_spec_sha256=run_spec_sha256,
        cohort_sha256=cohort.cohort_sha256,
        dataset_sha256=cohort.dataset.dataset_sha256,
        instrument_schema_version="single-context-observation/v1",
        instrument_sha256=instrument_sha256(),
        persona_profile_sha256s=tuple(member.persona.profile_sha256 for member in cohort.members),
        verifier_schema_version="research-survey-structural-verifier/v1",
        trajectory_schema_version="ordered-persona-observations/v1",
        artifact_schema_version="sandowl-research-survey-artifact/v1",
        reward_policy="not_applicable",
        limitations=(
            "任务包只定义合成 Persona 的单一上下文问卷，不验证现实用户或商业效果。",
            "该研究任务不产生跨任务标量 reward，避免把观察结果误写成排名。",
        ),
    )


async def ensure_research_evaluation_task_bundle(
    session: AsyncSession,
    request: ResearchEvaluationTaskBundleCreateRequest,
    *,
    commit: bool,
) -> ResearchEvaluationTaskBundle:
    project, run, cohort = await verified_research_evaluation_scope(
        session,
        request.research_project_id,
        request.research_simulation_run_id,
    )
    payload = _payload(project.project_sha256, run.run_spec_sha256, cohort)
    bundle_sha256 = calculate_task_bundle_sha256(payload)
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:digest, 0))"),
        {"digest": bundle_sha256},
    )
    existing = (
        await session.execute(
            select(ResearchEvaluationTaskBundleRecord).where(
                ResearchEvaluationTaskBundleRecord.research_simulation_run_id == run.id,
                ResearchEvaluationTaskBundleRecord.kind == request.kind,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return await research_evaluation_task_bundle_detail(session, existing)
    now = datetime.now(UTC)
    record = ResearchEvaluationTaskBundleRecord(
        id=uuid4(),
        research_project_id=project.id,
        research_simulation_run_id=run.id,
        cohort_id=cohort.id,
        kind=request.kind,
        schema_version=payload.schema_version,
        payload_json=payload.model_dump(mode="json"),
        bundle_sha256=bundle_sha256,
        created_at=now,
        sealed_at=now,
    )
    session.add(record)
    await session.flush((record,))
    if commit:
        await session.commit()
    return await research_evaluation_task_bundle_detail(session, record)


def _payload_from_record(
    record: ResearchEvaluationTaskBundleRecord,
) -> ResearchEvaluationTaskBundlePayload:
    payload = ResearchEvaluationTaskBundlePayload.model_validate_json(
        json.dumps(record.payload_json, ensure_ascii=False, allow_nan=False),
        strict=True,
    )
    if (
        payload.schema_version != record.schema_version
        or payload.kind != record.kind
        or calculate_task_bundle_sha256(payload) != record.bundle_sha256
    ):
        raise RuntimeError(f"research evaluation task bundle {record.id} metadata mismatch")
    return payload


async def _execution_projection(
    session: AsyncSession,
    record: ResearchEvaluationTaskBundleRecord,
) -> ResearchEvaluationExecutionProjection | None:
    survey = (
        await session.execute(
            select(ResearchSurveyRecord).where(
                ResearchSurveyRecord.research_simulation_run_id == record.research_simulation_run_id
            )
        )
    ).scalar_one_or_none()
    if survey is None:
        return None
    from app.research_surveys.repository import get_research_survey

    detail = await get_research_survey(session, survey.id)
    succeeded = tuple(trial for trial in detail.trials if trial.status == "succeeded")
    observation_count = len(succeeded) * 3
    if detail.status == "succeeded":
        verifier_state = "passed"
        trajectory_state = "complete"
        artifact_state = "sealed"
    elif detail.status == "failed":
        verifier_state = "failed"
        trajectory_state = "partial" if observation_count > 0 else "empty"
        artifact_state = "partial" if observation_count > 0 else "unavailable"
    else:
        verifier_state = "pending"
        trajectory_state = "partial" if observation_count > 0 else "empty"
        artifact_state = "unavailable"
    artifact_sha256 = None
    if artifact_state in ("partial", "sealed"):
        answer_digests = tuple(
            (trial.persona.position, trial.result.answers_sha256)
            for trial in succeeded
            if trial.result is not None
        )
        artifact_sha256 = calculate_survey_artifact_sha256(
            record.bundle_sha256,
            answer_digests,
        )
    return ResearchEvaluationExecutionProjection(
        evaluation_id=detail.id,
        status=detail.status,
        evaluation_sha256=detail.survey_sha256,
        verifier_state=verifier_state,
        trajectory_state=trajectory_state,
        recorded_observation_count=observation_count,
        artifact_state=artifact_state,
        artifact_sha256=artifact_sha256,
        reward_mode="not_applicable",
        reward_value=None,
    )


async def research_evaluation_task_bundle_detail(
    session: AsyncSession,
    record: ResearchEvaluationTaskBundleRecord,
) -> ResearchEvaluationTaskBundle:
    payload = _payload_from_record(record)
    return ResearchEvaluationTaskBundle(
        id=record.id,
        research_project_id=record.research_project_id,
        research_simulation_run_id=record.research_simulation_run_id,
        cohort_id=record.cohort_id,
        payload=payload,
        bundle_sha256=record.bundle_sha256,
        execution=await _execution_projection(session, record),
        created_at=record.created_at,
        sealed_at=record.sealed_at,
    )


async def list_research_evaluation_task_bundles(
    session: AsyncSession,
    project_id: UUID,
    run_id: UUID,
) -> tuple[ResearchEvaluationTaskBundle, ...]:
    records = tuple(
        (
            await session.execute(
                select(ResearchEvaluationTaskBundleRecord)
                .where(
                    ResearchEvaluationTaskBundleRecord.research_project_id == project_id,
                    ResearchEvaluationTaskBundleRecord.research_simulation_run_id == run_id,
                )
                .order_by(ResearchEvaluationTaskBundleRecord.created_at)
            )
        )
        .scalars()
        .all()
    )
    return tuple(
        [await research_evaluation_task_bundle_detail(session, record) for record in records]
    )
