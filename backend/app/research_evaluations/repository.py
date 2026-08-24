"""Verified Project / Run / Cohort projection for MatrAIx evaluation."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.populations.models import (
    CohortMemberRecord,
    CohortRecord,
    PersonaDatasetRecord,
    PersonaRecord,
)
from app.research_evaluations.bundles import list_research_evaluation_task_bundles
from app.research_evaluations.contracts import (
    ResearchEvaluationCapability,
    ResearchEvaluationCohortRef,
    ResearchEvaluationProjectRef,
    ResearchEvaluationRunRef,
    ResearchEvaluationRuntimeBoundary,
    ResearchEvaluationWorkspace,
    ResearchPersonaQualityReport,
)
from app.research_evaluations.errors import ResearchEvaluationScopeError
from app.research_evaluations.jobs import list_research_evaluation_jobs
from app.research_evaluations.targets import list_research_evaluation_targets
from app.research_projects.models import ResearchProjectRecord, ResearchSimulationRunRecord
from app.research_surveys.models import ResearchSurveyRecord
from app.world_graphs.models import SemanticWorldGraphCohortOriginRecord


async def get_research_evaluation_workspace(
    session: AsyncSession,
    project_id: UUID,
    run_id: UUID,
) -> ResearchEvaluationWorkspace:
    row = (
        await session.execute(
            select(
                ResearchProjectRecord,
                ResearchSimulationRunRecord,
                CohortRecord,
                PersonaDatasetRecord,
            )
            .join(
                ResearchSimulationRunRecord,
                ResearchSimulationRunRecord.research_project_id == ResearchProjectRecord.id,
            )
            .join(CohortRecord, CohortRecord.id == ResearchSimulationRunRecord.cohort_id)
            .join(PersonaDatasetRecord, PersonaDatasetRecord.id == CohortRecord.dataset_id)
            .where(
                ResearchProjectRecord.id == project_id,
                ResearchSimulationRunRecord.id == run_id,
                ResearchSimulationRunRecord.status == "succeeded",
                CohortRecord.sealed_at.is_not(None),
                PersonaDatasetRecord.sealed_at.is_not(None),
            )
        )
    ).one_or_none()
    if row is None:
        raise ResearchEvaluationScopeError(
            "evaluation workspace requires one succeeded Run belonging to the selected Project"
        )
    project, run, cohort, dataset = row
    if (
        run.project_sha256 != project.project_sha256
        or run.cohort_sha256 != cohort.cohort_sha256
        or run.persona_count != cohort.persona_count
        or cohort.persona_count > 8
    ):
        raise RuntimeError("research evaluation scope failed immutable identity verification")
    survey_count = int(
        (
            await session.execute(
                select(func.count(ResearchSurveyRecord.id)).where(
                    ResearchSurveyRecord.research_project_id == project_id,
                    ResearchSurveyRecord.research_simulation_run_id == run_id,
                    ResearchSurveyRecord.cohort_id == cohort.id,
                )
            )
        ).scalar_one()
    )
    persona_profiles = tuple(
        (
            await session.execute(
                select(PersonaRecord.profile_json)
                .join(
                    CohortMemberRecord,
                    (CohortMemberRecord.dataset_id == PersonaRecord.dataset_id)
                    & (CohortMemberRecord.persona_id == PersonaRecord.id),
                )
                .where(CohortMemberRecord.cohort_id == cohort.id)
                .order_by(CohortMemberRecord.position)
            )
        ).scalars()
    )
    if len(persona_profiles) != cohort.persona_count:
        raise RuntimeError("research evaluation cohort member projection is incomplete")
    dimension_counts = tuple(
        len(profile.get("dimensions", {})) if isinstance(profile.get("dimensions", {}), dict) else 0
        for profile in persona_profiles
    )
    graph_origin = (
        (
            await session.execute(
                select(SemanticWorldGraphCohortOriginRecord)
                .where(SemanticWorldGraphCohortOriginRecord.cohort_id == cohort.id)
                .order_by(
                    SemanticWorldGraphCohortOriginRecord.created_at.desc(),
                    SemanticWorldGraphCohortOriginRecord.id.asc(),
                )
                .limit(1)
            )
        )
        .scalars()
        .one_or_none()
    )
    populated_profile_count = sum(count > 0 for count in dimension_counts)
    quality_state = "verified" if populated_profile_count == cohort.persona_count else "limited"
    task_bundles = await list_research_evaluation_task_bundles(session, project_id, run_id)
    targets = await list_research_evaluation_targets(session, project_id, run_id)
    jobs = await list_research_evaluation_jobs(session, project_id, run_id)
    target_kinds = {target.payload.kind for target in targets}
    survey_bundle_ready = any(bundle.payload.kind == "survey" for bundle in task_bundles)
    capabilities = (
        ResearchEvaluationCapability(
            kind="survey",
            title="单一研究上下文问卷",
            integration_state="native_bound",
            can_launch_for_scope=True,
            existing_run_count=survey_count,
            explanation="直接继承当前 Project、成功 Run 与该 Run 的冻结 Cohort。",
        ),
        ResearchEvaluationCapability(
            kind="chat",
            title="对话系统评测",
            integration_state=(
                "target_defined" if "chat" in target_kinds else "source_sample_only"
            ),
            can_launch_for_scope="chat" in target_kinds,
            existing_run_count=0,
            explanation=(
                "当前研究已封存 Chat 被测对象；可提交到独立 Harbor runner。"
                if "chat" in target_kinds
                else "当前 Chat 仍使用固定 Acme Support 样例，尚未定义本研究被测对象。"
            ),
        ),
        ResearchEvaluationCapability(
            kind="web",
            title="网页任务评测",
            integration_state=("target_defined" if "web" in target_kinds else "source_sample_only"),
            can_launch_for_scope="web" in target_kinds,
            existing_run_count=0,
            explanation=(
                "当前研究已封存 Web 被测对象；可提交到独立 Harbor runner。"
                if "web" in target_kinds
                else "当前 Web 仍使用固定 Quotes 样例，尚未定义本研究被测对象。"
            ),
        ),
        ResearchEvaluationCapability(
            kind="app",
            title="通用 App 任务评测",
            integration_state=("target_defined" if "app" in target_kinds else "not_implemented"),
            can_launch_for_scope="app" in target_kinds,
            existing_run_count=0,
            explanation=(
                "当前研究已绑定 App Harbor task package；可提交到独立 Harbor runner。"
                if "app" in target_kinds
                else "通用 App 需要先绑定一个受许可的 Harbor task package。"
            ),
        ),
        ResearchEvaluationCapability(
            kind="linux",
            title="Linux 产物评测",
            integration_state="source_sample_only",
            can_launch_for_scope=False,
            existing_run_count=0,
            explanation="当前 Linux 仍是固定 Note-to-CSV 样例，未绑定当前 Project / Run。",
        ),
    )
    boundaries = (
        ResearchEvaluationRuntimeBoundary(
            name="task_bundle",
            state="available" if survey_bundle_ready else "partial",
            explanation=(
                "当前 Project / Run / Cohort 已封存为内容寻址的 Survey task bundle。"
                if survey_bundle_ready
                else "Survey 可准备原生 task bundle；当前研究尚未显式封存。"
            ),
        ),
        ResearchEvaluationRuntimeBoundary(
            name="job_runtime",
            state="available",
            explanation="Project-bound Job 由 PostgreSQL 队列调度到固定 MatrAIx Harbor runner。",
        ),
        ResearchEvaluationRuntimeBoundary(
            name="verifier",
            state="available",
            explanation=(
                "Survey task bundle 固定逐 Persona 三题结构、结果哈希和完整性 verifier。"
                if survey_bundle_ready
                else "Survey verifier 契约会随 task bundle 一起封存。"
            ),
        ),
        ResearchEvaluationRuntimeBoundary(
            name="trajectory",
            state="available",
            explanation=(
                "Survey 以成员顺序保存逐 Persona 的有序观察轨迹。"
                if survey_bundle_ready
                else "当前研究尚未封存有序观察轨迹契约。"
            ),
        ),
        ResearchEvaluationRuntimeBoundary(
            name="artifact",
            state="available",
            explanation=(
                "Survey 终态结果投影为由有序 answers_sha256 组成的 typed artifact。"
                if survey_bundle_ready
                else "Survey typed artifact schema 会随 task bundle 一起封存。"
            ),
        ),
        ResearchEvaluationRuntimeBoundary(
            name="reward",
            state="available",
            explanation="该研究问卷明确使用 not_applicable reward policy，不生成误导性评分。",
        ),
    )
    return ResearchEvaluationWorkspace(
        schema_version="sandowl-research-evaluation-workspace/v1",
        project=ResearchEvaluationProjectRef(
            id=project.id,
            title=project.title,
            project_sha256=project.project_sha256,
        ),
        run=ResearchEvaluationRunRef(
            id=run.id,
            run_spec_sha256=run.run_spec_sha256,
            status="succeeded",
        ),
        cohort=ResearchEvaluationCohortRef(
            id=cohort.id,
            title=cohort.title,
            cohort_sha256=cohort.cohort_sha256,
            dataset_sha256=dataset.dataset_sha256,
            persona_count=cohort.persona_count,
        ),
        persona_quality=ResearchPersonaQualityReport(
            selection_method="graph_match" if graph_origin is not None else "frozen_cohort",
            graph_origin_sha256=(graph_origin.origin_sha256 if graph_origin is not None else None),
            profile_count=cohort.persona_count,
            populated_profile_count=populated_profile_count,
            minimum_dimension_count=min(dimension_counts),
            maximum_dimension_count=max(dimension_counts),
            quality_state=quality_state,
            explanation=(
                "该 Cohort 保留了语义图匹配来源、成员顺序与非空 profile 内容地址；"
                "维度数量按实际档案报告。"
                if graph_origin is not None
                else "该 Cohort 已冻结成员顺序与非空 profile 内容地址，但没有语义图检索来源；"
                "维度数量按实际档案报告。"
            ),
        ),
        task_bundles=task_bundles,
        targets=targets,
        jobs=jobs,
        capabilities=capabilities,
        runtime_boundaries=boundaries,
        limitations=(
            "评测结果只描述合成人物在受控任务中的行为，不验证现实用户或商业效果。",
            "未标记为“原生绑定”的固定样例不得用于支持当前研究报告的结论。",
        ),
    )
