"""Immutable Chat/Web SUT definitions bound to one research scope."""

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.research_evaluations.bundles import verified_research_evaluation_scope
from app.research_evaluations.contracts import (
    ResearchEvaluationTarget,
    ResearchEvaluationTargetCreateRequest,
    ResearchEvaluationTargetPayload,
)
from app.research_evaluations.errors import ResearchEvaluationScopeError
from app.research_evaluations.hashing import calculate_evaluation_target_sha256
from app.research_evaluations.models import ResearchEvaluationTargetRecord


def _target_payload(
    request: ResearchEvaluationTargetCreateRequest,
    *,
    project_sha256: str,
    run_spec_sha256: str,
    cohort_sha256: str,
    dataset_sha256: str,
) -> ResearchEvaluationTargetPayload:
    verifier_schema = {
        "chat": "research-chat-outcome-verifier/v1",
        "web": "research-web-evidence-verifier/v1",
        "app": "research-app-artifact-verifier/v1",
    }[request.kind]
    return ResearchEvaluationTargetPayload(
        schema_version="sandowl-research-evaluation-target/v1",
        kind=request.kind,
        project_sha256=project_sha256,
        run_spec_sha256=run_spec_sha256,
        cohort_sha256=cohort_sha256,
        dataset_sha256=dataset_sha256,
        title=request.title,
        target_url=request.target_url,
        task_package=request.task_package,
        transport=request.transport,
        task_goal=request.task_goal,
        success_criteria=request.success_criteria,
        verifier_schema_version=verifier_schema,
        execution_policy="definition_only",
        limitations=(
            "该记录只封存被测对象定义，不会访问目标地址、发送 Persona 数据或启动评测。",
            "只有后续隔离执行器、网络策略和 verifier 全部核验通过后才能开放启动。",
        ),
    )


def _payload_from_record(record: ResearchEvaluationTargetRecord) -> ResearchEvaluationTargetPayload:
    payload = ResearchEvaluationTargetPayload.model_validate_json(
        json.dumps(record.payload_json, ensure_ascii=False, allow_nan=False),
        strict=True,
    )
    if (
        payload.schema_version != record.schema_version
        or payload.kind != record.kind
        or calculate_evaluation_target_sha256(payload) != record.target_sha256
    ):
        raise RuntimeError(f"research evaluation target {record.id} metadata mismatch")
    return payload


def research_evaluation_target_detail(
    record: ResearchEvaluationTargetRecord,
) -> ResearchEvaluationTarget:
    return ResearchEvaluationTarget(
        id=record.id,
        research_project_id=record.research_project_id,
        research_simulation_run_id=record.research_simulation_run_id,
        cohort_id=record.cohort_id,
        payload=_payload_from_record(record),
        target_sha256=record.target_sha256,
        created_at=record.created_at,
        sealed_at=record.sealed_at,
    )


async def ensure_research_evaluation_target(
    session: AsyncSession,
    request: ResearchEvaluationTargetCreateRequest,
    *,
    commit: bool,
) -> ResearchEvaluationTarget:
    project, run, cohort = await verified_research_evaluation_scope(
        session,
        request.research_project_id,
        request.research_simulation_run_id,
    )
    payload = _target_payload(
        request,
        project_sha256=project.project_sha256,
        run_spec_sha256=run.run_spec_sha256,
        cohort_sha256=cohort.cohort_sha256,
        dataset_sha256=cohort.dataset.dataset_sha256,
    )
    target_sha256 = calculate_evaluation_target_sha256(payload)
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:digest, 0))"),
        {"digest": target_sha256},
    )
    existing = (
        await session.execute(
            select(ResearchEvaluationTargetRecord).where(
                ResearchEvaluationTargetRecord.research_simulation_run_id == run.id,
                ResearchEvaluationTargetRecord.kind == request.kind,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.target_sha256 != target_sha256:
            raise ResearchEvaluationScopeError(
                f"a different {request.kind} target is already sealed for this Run"
            )
        return research_evaluation_target_detail(existing)
    now = datetime.now(UTC)
    record = ResearchEvaluationTargetRecord(
        id=uuid4(),
        research_project_id=project.id,
        research_simulation_run_id=run.id,
        cohort_id=cohort.id,
        kind=request.kind,
        schema_version=payload.schema_version,
        payload_json=payload.model_dump(mode="json"),
        target_sha256=target_sha256,
        created_at=now,
        sealed_at=now,
    )
    session.add(record)
    await session.flush((record,))
    if commit:
        await session.commit()
    return research_evaluation_target_detail(record)


async def list_research_evaluation_targets(
    session: AsyncSession,
    project_id: UUID,
    run_id: UUID,
) -> tuple[ResearchEvaluationTarget, ...]:
    records = tuple(
        (
            await session.execute(
                select(ResearchEvaluationTargetRecord)
                .where(
                    ResearchEvaluationTargetRecord.research_project_id == project_id,
                    ResearchEvaluationTargetRecord.research_simulation_run_id == run_id,
                )
                .order_by(ResearchEvaluationTargetRecord.kind)
            )
        )
        .scalars()
        .all()
    )
    return tuple(research_evaluation_target_detail(record) for record in records)
