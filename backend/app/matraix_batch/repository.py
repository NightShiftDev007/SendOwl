"""Content-addressed writes and verified bounded reads for batch registries."""

from collections import defaultdict
from datetime import UTC, datetime
from typing import NamedTuple, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.matraix_batch.contracts import (
    ChatBatchRegistryCandidate,
    ChatBatchRegistryItem,
    LinuxBatchRegistryCandidate,
    LinuxBatchRegistryItem,
    MatraixBatchKind,
    MatraixBatchRegistriesResponse,
    MatraixBatchRegistryCandidate,
    MatraixBatchRegistryCandidatesResponse,
    MatraixBatchRegistryCreateRequest,
    MatraixBatchRegistryDetail,
    MatraixBatchRegistryItem,
    MatraixBatchRegistrySummary,
    MatraixNativeBatchLaunchRequest,
    MatraixNativeBatchLaunchResult,
    MatraixNativeChatLaunchItem,
    MatraixNativeSurveyLaunchItem,
    MatraixObservedTrialStatus,
    SurveyBatchRegistryCandidate,
    SurveyBatchRegistryItem,
    WebBatchRegistryCandidate,
    WebBatchRegistryItem,
)
from app.matraix_batch.errors import (
    MatraixBatchRegistryIntegrityError,
    MatraixBatchRegistryNotFoundError,
    MatraixBatchRegistryPageOutOfRangeError,
)
from app.matraix_batch.hashing import calculate_batch_registry_sha256
from app.matraix_batch.models import (
    MatraixBatchRegistryItemRecord,
    MatraixBatchRegistryRecord,
)
from app.matraix_chat.contracts import (
    ChatPersonaRef,
    MatraixChatEvaluationCreateRequest,
)
from app.matraix_chat.hashing import calculate_trial_sha256
from app.matraix_chat.models import MatraixChatEvaluationRecord, MatraixChatTrialRecord
from app.matraix_chat.repository import (
    ensure_chat_evaluation_record,
    verify_chat_evaluation_record,
)
from app.matraix_chat.tasks import build_chat_task
from app.matraix_linux.models import MatraixLinuxEvaluationRecord, MatraixLinuxTrialRecord
from app.matraix_linux.repository import (
    verify_linux_evaluation_record,
    verify_linux_trial_record,
)
from app.matraix_linux.tasks import build_linux_task
from app.matraix_surveys.contracts import SurveyPersonaRef
from app.matraix_surveys.hashing import calculate_survey_trial_sha256
from app.matraix_surveys.models import MatraixSurveyExperimentRecord, MatraixSurveyTrialRecord
from app.matraix_surveys.repository import verify_survey_experiment_record
from app.matraix_web.contracts import WebPersonaRef
from app.matraix_web.hashing import calculate_trial_sha256 as calculate_web_trial_sha256
from app.matraix_web.models import MatraixWebEvaluationRecord, MatraixWebTrialRecord
from app.matraix_web.repository import verify_web_evaluation_record
from app.matraix_web.tasks import build_web_task
from app.research_surveys.contracts import ResearchSurveyCreateRequest
from app.research_surveys.hashing import trial_sha256 as research_survey_trial_sha256
from app.research_surveys.models import ResearchSurveyRecord, ResearchSurveyTrialRecord
from app.research_surveys.repository import ensure_research_survey_record

SUPPORTED_STATUSES = frozenset({"queued", "running", "succeeded", "failed"})


class SourceProjection(NamedTuple):
    kind: MatraixBatchKind
    parent_id: UUID
    parent_sha256: str
    title: str
    version: str
    observed_status: MatraixObservedTrialStatus
    created_at: datetime
    trial_count: int
    succeeded_trial_count: int
    failed_trial_count: int
    model_name: str
    parent_config_sha256: str
    prompt_schema_version: str
    source_detail_path: str


def _observed_status(
    statuses: tuple[MatraixObservedTrialStatus, ...],
) -> MatraixObservedTrialStatus:
    if not statuses:
        raise MatraixBatchRegistryIntegrityError("a batch registry source has no trials")
    if all(status == "queued" for status in statuses):
        return "queued"
    if any(status in ("queued", "running") for status in statuses):
        return "running"
    if all(status == "succeeded" for status in statuses):
        return "succeeded"
    return "failed"


def _validated_status(value: str, trial_id: UUID) -> MatraixObservedTrialStatus:
    if value not in SUPPORTED_STATUSES:
        raise MatraixBatchRegistryIntegrityError(
            f"MatrAIx trial {trial_id} has unsupported status {value!r}"
        )
    return cast(MatraixObservedTrialStatus, value)


def _verify_survey_trials(
    parent: MatraixSurveyExperimentRecord,
    trials: tuple[MatraixSurveyTrialRecord, ...],
) -> tuple[MatraixObservedTrialStatus, ...]:
    if len(trials) != parent.persona_count:
        raise MatraixBatchRegistryIntegrityError(
            f"MatrAIx Survey experiment {parent.id} trial count is inconsistent"
        )
    if tuple(trial.persona_position for trial in trials) != tuple(range(parent.persona_count)):
        raise MatraixBatchRegistryIntegrityError(
            f"MatrAIx Survey experiment {parent.id} trial positions are not contiguous"
        )
    statuses: list[MatraixObservedTrialStatus] = []
    for trial in trials:
        persona = SurveyPersonaRef(
            id=trial.persona_id,
            position=trial.persona_position,
            persona_id=trial.persona_external_id,
            display_name=trial.persona_display_name,
            profile_sha256=trial.persona_profile_sha256,
        )
        expected_sha = calculate_survey_trial_sha256(parent.experiment_sha256, persona)
        if (
            trial.experiment_id != parent.id
            or trial.created_at != parent.created_at
            or trial.trial_sha256 != expected_sha
        ):
            raise MatraixBatchRegistryIntegrityError(
                f"MatrAIx Survey trial {trial.id} does not match its sealed parent"
            )
        statuses.append(_validated_status(trial.status, trial.id))
    return tuple(statuses)


def _verify_research_survey_trials(
    parent: ResearchSurveyRecord,
    trials: tuple[ResearchSurveyTrialRecord, ...],
) -> tuple[MatraixObservedTrialStatus, ...]:
    if len(trials) != parent.persona_count:
        raise MatraixBatchRegistryIntegrityError(
            f"SandOwl Research Survey {parent.id} trial count is inconsistent"
        )
    if tuple(trial.persona_position for trial in trials) != tuple(range(parent.persona_count)):
        raise MatraixBatchRegistryIntegrityError(
            f"SandOwl Research Survey {parent.id} trial positions are not contiguous"
        )
    statuses: list[MatraixObservedTrialStatus] = []
    for trial in trials:
        expected_sha = research_survey_trial_sha256(
            parent.survey_sha256,
            trial.persona_position,
            trial.persona_id,
            trial.persona_profile_sha256,
        )
        if trial.survey_id != parent.id or trial.trial_sha256 != expected_sha:
            raise MatraixBatchRegistryIntegrityError(
                f"SandOwl Research Survey trial {trial.id} does not match its sealed parent"
            )
        statuses.append(_validated_status(trial.status, trial.id))
    return tuple(statuses)


def _verify_chat_trials(
    parent: MatraixChatEvaluationRecord,
    trials: tuple[MatraixChatTrialRecord, ...],
) -> tuple[MatraixObservedTrialStatus, ...]:
    if len(trials) != parent.persona_count:
        raise MatraixBatchRegistryIntegrityError(
            f"MatrAIx Chat evaluation {parent.id} trial count is inconsistent"
        )
    if tuple(trial.persona_position for trial in trials) != tuple(range(parent.persona_count)):
        raise MatraixBatchRegistryIntegrityError(
            f"MatrAIx Chat evaluation {parent.id} trial positions are not contiguous"
        )
    statuses: list[MatraixObservedTrialStatus] = []
    for trial in trials:
        persona = ChatPersonaRef(
            id=trial.persona_id,
            position=trial.persona_position,
            persona_id=trial.persona_external_id,
            display_name=trial.persona_display_name,
            profile_sha256=trial.persona_profile_sha256,
        )
        expected_sha = calculate_trial_sha256(parent.evaluation_sha256, persona)
        if (
            trial.evaluation_id != parent.id
            or trial.created_at != parent.created_at
            or trial.trial_sha256 != expected_sha
        ):
            raise MatraixBatchRegistryIntegrityError(
                f"MatrAIx Chat trial {trial.id} does not match its sealed parent"
            )
        statuses.append(_validated_status(trial.status, trial.id))
    return tuple(statuses)


def _verify_web_trials(
    parent: MatraixWebEvaluationRecord,
    trials: tuple[MatraixWebTrialRecord, ...],
) -> tuple[MatraixObservedTrialStatus, ...]:
    if len(trials) != parent.persona_count:
        raise MatraixBatchRegistryIntegrityError(
            f"MatrAIx Web evaluation {parent.id} trial count is inconsistent"
        )
    if tuple(trial.persona_position for trial in trials) != tuple(range(parent.persona_count)):
        raise MatraixBatchRegistryIntegrityError(
            f"MatrAIx Web evaluation {parent.id} trial positions are not contiguous"
        )
    statuses: list[MatraixObservedTrialStatus] = []
    for trial in trials:
        persona = WebPersonaRef(
            id=trial.persona_id,
            position=trial.persona_position,
            persona_id=trial.persona_external_id,
            display_name=trial.persona_display_name,
            profile_sha256=trial.persona_profile_sha256,
        )
        expected_sha = calculate_web_trial_sha256(parent.evaluation_sha256, persona)
        if (
            trial.evaluation_id != parent.id
            or trial.created_at != parent.created_at
            or trial.trial_sha256 != expected_sha
        ):
            raise MatraixBatchRegistryIntegrityError(
                f"MatrAIx Web trial {trial.id} does not match its sealed parent"
            )
        statuses.append(_validated_status(trial.status, trial.id))
    return tuple(statuses)


def _verify_linux_trial(
    parent: MatraixLinuxEvaluationRecord,
    trial: MatraixLinuxTrialRecord,
) -> MatraixObservedTrialStatus:
    try:
        verify_linux_evaluation_record(parent, trial)
        verify_linux_trial_record(trial)
    except RuntimeError as error:
        raise MatraixBatchRegistryIntegrityError(str(error)) from error
    return _validated_status(trial.status, trial.id)


async def _load_sources(
    session: AsyncSession,
    references: tuple[tuple[MatraixBatchKind, UUID], ...],
) -> dict[tuple[MatraixBatchKind, UUID], SourceProjection]:
    survey_ids = tuple(parent_id for kind, parent_id in references if kind == "survey")
    chat_ids = tuple(parent_id for kind, parent_id in references if kind == "chat")
    web_ids = tuple(parent_id for kind, parent_id in references if kind == "web")
    linux_ids = tuple(parent_id for kind, parent_id in references if kind == "linux")
    survey_parents: tuple[MatraixSurveyExperimentRecord, ...] = ()
    survey_trials: tuple[MatraixSurveyTrialRecord, ...] = ()
    research_survey_parents: tuple[ResearchSurveyRecord, ...] = ()
    research_survey_trials: tuple[ResearchSurveyTrialRecord, ...] = ()
    chat_parents: tuple[MatraixChatEvaluationRecord, ...] = ()
    chat_trials: tuple[MatraixChatTrialRecord, ...] = ()
    web_parents: tuple[MatraixWebEvaluationRecord, ...] = ()
    web_trials: tuple[MatraixWebTrialRecord, ...] = ()
    linux_rows: tuple[tuple[MatraixLinuxEvaluationRecord, MatraixLinuxTrialRecord], ...] = ()
    if survey_ids:
        survey_parents = tuple(
            (
                await session.execute(
                    select(MatraixSurveyExperimentRecord).where(
                        MatraixSurveyExperimentRecord.id.in_(survey_ids),
                        MatraixSurveyExperimentRecord.input_sealed_at.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        survey_trials = tuple(
            (
                await session.execute(
                    select(MatraixSurveyTrialRecord)
                    .where(MatraixSurveyTrialRecord.experiment_id.in_(survey_ids))
                    .order_by(
                        MatraixSurveyTrialRecord.experiment_id,
                        MatraixSurveyTrialRecord.persona_position,
                    )
                )
            )
            .scalars()
            .all()
        )
        research_survey_parents = tuple(
            (
                await session.execute(
                    select(ResearchSurveyRecord).where(
                        ResearchSurveyRecord.id.in_(survey_ids),
                        ResearchSurveyRecord.sealed_at.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        research_survey_trials = tuple(
            (
                await session.execute(
                    select(ResearchSurveyTrialRecord)
                    .where(ResearchSurveyTrialRecord.survey_id.in_(survey_ids))
                    .order_by(
                        ResearchSurveyTrialRecord.survey_id,
                        ResearchSurveyTrialRecord.persona_position,
                    )
                )
            )
            .scalars()
            .all()
        )
    if chat_ids:
        chat_parents = tuple(
            (
                await session.execute(
                    select(MatraixChatEvaluationRecord).where(
                        MatraixChatEvaluationRecord.id.in_(chat_ids),
                        MatraixChatEvaluationRecord.input_sealed_at.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        chat_trials = tuple(
            (
                await session.execute(
                    select(MatraixChatTrialRecord)
                    .where(MatraixChatTrialRecord.evaluation_id.in_(chat_ids))
                    .order_by(
                        MatraixChatTrialRecord.evaluation_id,
                        MatraixChatTrialRecord.persona_position,
                    )
                )
            )
            .scalars()
            .all()
        )
    if web_ids:
        web_parents = tuple(
            (
                await session.execute(
                    select(MatraixWebEvaluationRecord).where(
                        MatraixWebEvaluationRecord.id.in_(web_ids),
                        MatraixWebEvaluationRecord.input_sealed_at.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        web_trials = tuple(
            (
                await session.execute(
                    select(MatraixWebTrialRecord)
                    .where(MatraixWebTrialRecord.evaluation_id.in_(web_ids))
                    .order_by(
                        MatraixWebTrialRecord.evaluation_id,
                        MatraixWebTrialRecord.persona_position,
                    )
                )
            )
            .scalars()
            .all()
        )
    if linux_ids:
        linux_rows = tuple(
            (
                await session.execute(
                    select(MatraixLinuxEvaluationRecord, MatraixLinuxTrialRecord)
                    .join(
                        MatraixLinuxTrialRecord,
                        MatraixLinuxTrialRecord.id == MatraixLinuxEvaluationRecord.trial_id,
                    )
                    .where(
                        MatraixLinuxEvaluationRecord.id.in_(linux_ids),
                        MatraixLinuxEvaluationRecord.input_sealed_at.is_not(None),
                    )
                )
            ).tuples()
        )
    survey_trials_by_parent: dict[UUID, list[MatraixSurveyTrialRecord]] = defaultdict(list)
    for trial in survey_trials:
        survey_trials_by_parent[trial.experiment_id].append(trial)
    research_survey_trials_by_parent: dict[UUID, list[ResearchSurveyTrialRecord]] = defaultdict(
        list
    )
    for trial in research_survey_trials:
        research_survey_trials_by_parent[trial.survey_id].append(trial)
    chat_trials_by_parent: dict[UUID, list[MatraixChatTrialRecord]] = defaultdict(list)
    for trial in chat_trials:
        chat_trials_by_parent[trial.evaluation_id].append(trial)
    web_trials_by_parent: dict[UUID, list[MatraixWebTrialRecord]] = defaultdict(list)
    for trial in web_trials:
        web_trials_by_parent[trial.evaluation_id].append(trial)
    sources: dict[tuple[MatraixBatchKind, UUID], SourceProjection] = {}
    for parent in survey_parents:
        try:
            verify_survey_experiment_record(parent)
        except RuntimeError as error:
            raise MatraixBatchRegistryIntegrityError(str(error)) from error
        statuses = _verify_survey_trials(parent, tuple(survey_trials_by_parent[parent.id]))
        sources[("survey", parent.id)] = SourceProjection(
            kind="survey",
            parent_id=parent.id,
            parent_sha256=parent.experiment_sha256,
            title=parent.scenario_title,
            version="scenario-preference/v1",
            observed_status=_observed_status(statuses),
            created_at=parent.created_at,
            trial_count=len(statuses),
            succeeded_trial_count=sum(status == "succeeded" for status in statuses),
            failed_trial_count=sum(status == "failed" for status in statuses),
            model_name=parent.model_name,
            parent_config_sha256=parent.survey_config_sha256,
            prompt_schema_version=parent.prompt_schema_version,
            source_detail_path=f"/api/v2/matraix/survey-experiments/{parent.id}",
        )
    for parent in research_survey_parents:
        key: tuple[MatraixBatchKind, UUID] = ("survey", parent.id)
        if key in sources:
            raise MatraixBatchRegistryIntegrityError(
                f"Survey parent id {parent.id} is ambiguous across native and historical stores"
            )
        statuses = _verify_research_survey_trials(
            parent, tuple(research_survey_trials_by_parent[parent.id])
        )
        sources[key] = SourceProjection(
            kind="survey",
            parent_id=parent.id,
            parent_sha256=parent.survey_sha256,
            title=parent.project_title,
            version="single-context-observation/v1",
            observed_status=_observed_status(statuses),
            created_at=parent.created_at,
            trial_count=len(statuses),
            succeeded_trial_count=sum(status == "succeeded" for status in statuses),
            failed_trial_count=sum(status == "failed" for status in statuses),
            model_name=parent.model_name,
            parent_config_sha256=parent.survey_config_sha256,
            prompt_schema_version=parent.prompt_schema_version,
            source_detail_path=f"/api/v2/research-surveys/{parent.id}",
        )
    for parent in chat_parents:
        task = build_chat_task(parent.task_id)
        try:
            verify_chat_evaluation_record(parent, task)
        except RuntimeError as error:
            raise MatraixBatchRegistryIntegrityError(str(error)) from error
        statuses = _verify_chat_trials(parent, tuple(chat_trials_by_parent[parent.id]))
        sources[("chat", parent.id)] = SourceProjection(
            kind="chat",
            parent_id=parent.id,
            parent_sha256=parent.evaluation_sha256,
            title=task.title,
            version=task.version,
            observed_status=_observed_status(statuses),
            created_at=parent.created_at,
            trial_count=len(statuses),
            succeeded_trial_count=sum(status == "succeeded" for status in statuses),
            failed_trial_count=sum(status == "failed" for status in statuses),
            model_name=parent.model_name,
            parent_config_sha256=parent.chat_config_sha256,
            prompt_schema_version=parent.prompt_schema_version,
            source_detail_path=f"/api/v2/matraix/chat-evaluations/{parent.id}",
        )
    for parent in web_parents:
        task = build_web_task()
        try:
            verify_web_evaluation_record(parent)
        except RuntimeError as error:
            raise MatraixBatchRegistryIntegrityError(str(error)) from error
        statuses = _verify_web_trials(parent, tuple(web_trials_by_parent[parent.id]))
        sources[("web", parent.id)] = SourceProjection(
            kind="web",
            parent_id=parent.id,
            parent_sha256=parent.evaluation_sha256,
            title=task.title,
            version=task.version,
            observed_status=_observed_status(statuses),
            created_at=parent.created_at,
            trial_count=len(statuses),
            succeeded_trial_count=sum(status == "succeeded" for status in statuses),
            failed_trial_count=sum(status == "failed" for status in statuses),
            model_name=parent.model_name,
            parent_config_sha256=parent.web_config_sha256,
            prompt_schema_version=parent.prompt_schema_version,
            source_detail_path=f"/api/v2/matraix/web-evaluations/{parent.id}",
        )
    for parent, trial in linux_rows:
        status = _verify_linux_trial(parent, trial)
        task = build_linux_task()
        sources[("linux", parent.id)] = SourceProjection(
            kind="linux",
            parent_id=parent.id,
            parent_sha256=parent.evaluation_sha256,
            title=task.title,
            version=task.version,
            observed_status=status,
            created_at=parent.created_at,
            trial_count=1,
            succeeded_trial_count=int(status == "succeeded"),
            failed_trial_count=int(status == "failed"),
            model_name=trial.model_name,
            parent_config_sha256=trial.linux_config_sha256,
            prompt_schema_version=trial.prompt_schema_version,
            source_detail_path=f"/api/v2/matraix/linux-evaluations/{parent.id}",
        )
    missing = tuple(reference for reference in references if reference not in sources)
    if missing:
        kind, parent_id = missing[0]
        raise MatraixBatchRegistryNotFoundError(
            f"sealed MatrAIx {kind} parent {parent_id} was not found"
        )
    return sources


def _public_item(position: int, source: SourceProjection) -> MatraixBatchRegistryItem:
    common = {
        "position": position,
        "parent_id": source.parent_id,
        "parent_sha256": source.parent_sha256,
        "title": source.title,
        "version": source.version,
        "observed_status": source.observed_status,
        "created_at": source.created_at,
        "trial_count": source.trial_count,
        "succeeded_trial_count": source.succeeded_trial_count,
        "failed_trial_count": source.failed_trial_count,
        "model_name": source.model_name,
        "parent_config_sha256": source.parent_config_sha256,
        "prompt_schema_version": source.prompt_schema_version,
        "source_detail_path": source.source_detail_path,
    }
    if source.kind == "survey":
        return SurveyBatchRegistryItem(kind="survey", **common)
    if source.kind == "chat":
        return ChatBatchRegistryItem(kind="chat", **common)
    if source.kind == "web":
        return WebBatchRegistryItem(kind="web", **common)
    return LinuxBatchRegistryItem(kind="linux", **common)


def _public_candidate(source: SourceProjection) -> MatraixBatchRegistryCandidate:
    common = {
        "parent_id": source.parent_id,
        "parent_sha256": source.parent_sha256,
        "title": source.title,
        "version": source.version,
        "observed_status": source.observed_status,
        "created_at": source.created_at,
        "trial_count": source.trial_count,
        "succeeded_trial_count": source.succeeded_trial_count,
        "failed_trial_count": source.failed_trial_count,
        "model_name": source.model_name,
        "parent_config_sha256": source.parent_config_sha256,
        "prompt_schema_version": source.prompt_schema_version,
        "source_detail_path": source.source_detail_path,
    }
    if source.kind == "survey":
        return SurveyBatchRegistryCandidate(kind="survey", **common)
    if source.kind == "chat":
        return ChatBatchRegistryCandidate(kind="chat", **common)
    if source.kind == "web":
        return WebBatchRegistryCandidate(kind="web", **common)
    return LinuxBatchRegistryCandidate(kind="linux", **common)


def _detail(
    record: MatraixBatchRegistryRecord,
    stored_items: tuple[MatraixBatchRegistryItemRecord, ...],
    sources: dict[tuple[MatraixBatchKind, UUID], SourceProjection],
    observed_at: datetime,
) -> MatraixBatchRegistryDetail:
    if record.sealed_at is None:
        raise MatraixBatchRegistryIntegrityError(
            f"MatrAIx batch registry {record.id} is not sealed"
        )
    if tuple(item.position for item in stored_items) != tuple(range(len(stored_items))):
        raise MatraixBatchRegistryIntegrityError(
            f"MatrAIx batch registry {record.id} item positions are not contiguous"
        )
    references: list[tuple[int, MatraixBatchKind, UUID, str]] = []
    public_items: list[MatraixBatchRegistryItem] = []
    for stored in stored_items:
        if stored.kind not in ("survey", "chat", "web", "linux"):
            raise MatraixBatchRegistryIntegrityError(
                f"MatrAIx batch registry {record.id} contains unsupported kind {stored.kind!r}"
            )
        kind = cast(MatraixBatchKind, stored.kind)
        source = sources[(kind, stored.parent_id)]
        if source.parent_sha256 != stored.parent_sha256:
            raise MatraixBatchRegistryIntegrityError(
                f"MatrAIx batch registry {record.id} source hash does not match its sealed parent"
            )
        references.append((stored.position, kind, stored.parent_id, stored.parent_sha256))
        public_items.append(_public_item(stored.position, source))
    expected_sha = calculate_batch_registry_sha256(record.title, tuple(references))
    if expected_sha != record.registry_sha256:
        raise MatraixBatchRegistryIntegrityError(
            f"MatrAIx batch registry {record.id} does not match registry_sha256"
        )
    statuses = tuple(item.observed_status for item in public_items)
    return MatraixBatchRegistryDetail(
        id=record.id,
        title=record.title,
        registry_state="sealed",
        execution_kind="registry_only",
        observed_trial_status=_observed_status(statuses),
        observed_at=observed_at,
        created_at=record.created_at,
        sealed_at=record.sealed_at,
        registry_sha256=record.registry_sha256,
        item_count=len(public_items),
        trial_count=sum(item.trial_count for item in public_items),
        succeeded_trial_count=sum(item.succeeded_trial_count for item in public_items),
        failed_trial_count=sum(item.failed_trial_count for item in public_items),
        items=tuple(public_items),
    )


async def _load_registry_details(
    session: AsyncSession,
    records: tuple[MatraixBatchRegistryRecord, ...],
    observed_at: datetime,
) -> dict[UUID, MatraixBatchRegistryDetail]:
    if not records:
        return {}
    registry_ids = tuple(record.id for record in records)
    stored_items = tuple(
        (
            await session.execute(
                select(MatraixBatchRegistryItemRecord)
                .where(MatraixBatchRegistryItemRecord.registry_id.in_(registry_ids))
                .order_by(
                    MatraixBatchRegistryItemRecord.registry_id,
                    MatraixBatchRegistryItemRecord.position,
                )
            )
        )
        .scalars()
        .all()
    )
    by_registry: dict[UUID, list[MatraixBatchRegistryItemRecord]] = defaultdict(list)
    references: list[tuple[MatraixBatchKind, UUID]] = []
    for item in stored_items:
        if item.kind not in ("survey", "chat", "web", "linux"):
            raise MatraixBatchRegistryIntegrityError(
                f"MatrAIx batch registry item contains unsupported kind {item.kind!r}"
            )
        kind = cast(MatraixBatchKind, item.kind)
        by_registry[item.registry_id].append(item)
        references.append((kind, item.parent_id))
    try:
        sources = await _load_sources(session, tuple(dict.fromkeys(references)))
    except MatraixBatchRegistryNotFoundError as error:
        raise MatraixBatchRegistryIntegrityError(str(error)) from error
    return {
        record.id: _detail(record, tuple(by_registry[record.id]), sources, observed_at)
        for record in records
    }


async def ensure_batch_registry(
    session: AsyncSession,
    request: MatraixBatchRegistryCreateRequest,
) -> MatraixBatchRegistryDetail:
    references = tuple((item.kind, item.parent_id) for item in request.items)
    sources = await _load_sources(session, references)
    hash_items = tuple(
        (position, kind, parent_id, sources[(kind, parent_id)].parent_sha256)
        for position, (kind, parent_id) in enumerate(references)
    )
    digest = calculate_batch_registry_sha256(request.title, hash_items)
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:digest, 0))"),
        {"digest": digest},
    )
    existing = await session.scalar(
        select(MatraixBatchRegistryRecord).where(
            MatraixBatchRegistryRecord.registry_sha256 == digest,
            MatraixBatchRegistryRecord.sealed_at.is_not(None),
        )
    )
    if existing is not None:
        observed_at = await _database_now(session)
        return (await _load_registry_details(session, (existing,), observed_at))[existing.id]
    created_at = datetime.now(UTC)
    record = MatraixBatchRegistryRecord(
        id=uuid4(),
        title=request.title,
        registry_sha256=digest,
        created_at=created_at,
        sealed_at=None,
    )
    items = tuple(
        MatraixBatchRegistryItemRecord(
            registry_id=record.id,
            position=position,
            kind=kind,
            parent_id=parent_id,
            parent_sha256=parent_sha256,
        )
        for position, kind, parent_id, parent_sha256 in hash_items
    )
    session.add(record)
    await session.flush((record,))
    session.add_all(items)
    await session.flush(items)
    record.sealed_at = created_at
    await session.flush((record,))
    observed_at = await _database_now(session)
    detail = _detail(record, items, sources, observed_at)
    return detail


async def create_batch_registry(
    session: AsyncSession,
    request: MatraixBatchRegistryCreateRequest,
) -> MatraixBatchRegistryDetail:
    detail = await ensure_batch_registry(session, request)
    await session.commit()
    return detail


def _native_launch_sort_key(
    indexed_item: tuple[int, MatraixNativeSurveyLaunchItem | MatraixNativeChatLaunchItem],
) -> tuple[str, ...]:
    _, item = indexed_item
    if item.kind == "survey":
        return (
            item.kind,
            str(item.research_project_id),
            str(item.research_simulation_run_id),
        )
    return (item.kind, str(item.cohort_id), item.task_id, item.task_version)


async def create_native_batch_launch(
    session: AsyncSession,
    request: MatraixNativeBatchLaunchRequest,
) -> MatraixNativeBatchLaunchResult:
    """Atomically enqueue native parents and seal their ordered registry."""
    references: dict[int, tuple[MatraixBatchKind, UUID]] = {}
    try:
        indexed_items = tuple(enumerate(request.items))
        for position, item in sorted(indexed_items, key=_native_launch_sort_key):
            if item.kind == "survey":
                parent = await ensure_research_survey_record(
                    session,
                    ResearchSurveyCreateRequest(
                        research_project_id=item.research_project_id,
                        research_simulation_run_id=item.research_simulation_run_id,
                    ),
                )
            else:
                parent = await ensure_chat_evaluation_record(
                    session,
                    MatraixChatEvaluationCreateRequest(
                        cohort_id=item.cohort_id,
                        task_id=item.task_id,
                        task_version=item.task_version,
                    ),
                )
            references[position] = (item.kind, parent.id)
        registry = await ensure_batch_registry(
            session,
            MatraixBatchRegistryCreateRequest(
                title=request.title,
                items=tuple(
                    {"kind": references[position][0], "parent_id": references[position][1]}
                    for position in range(len(request.items))
                ),
            ),
        )
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    return MatraixNativeBatchLaunchResult(
        launch_mode="native_parent_enqueue",
        registry=registry,
    )


async def list_batch_registries(
    session: AsyncSession,
    page: int,
    page_size: int,
) -> MatraixBatchRegistriesResponse:
    observed_at = await _database_now(session)
    total = int(
        await session.scalar(
            select(func.count())
            .select_from(MatraixBatchRegistryRecord)
            .where(MatraixBatchRegistryRecord.sealed_at.is_not(None))
        )
        or 0
    )
    if (total == 0 and page > 1) or (total > 0 and (page - 1) * page_size >= total):
        raise MatraixBatchRegistryPageOutOfRangeError(
            f"MatrAIx batch registry page {page} is out of range for {total} items"
        )
    records = tuple(
        (
            await session.execute(
                select(MatraixBatchRegistryRecord)
                .where(MatraixBatchRegistryRecord.sealed_at.is_not(None))
                .order_by(
                    MatraixBatchRegistryRecord.created_at.desc(),
                    MatraixBatchRegistryRecord.id.asc(),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    details = await _load_registry_details(session, records, observed_at)
    summaries = tuple(
        MatraixBatchRegistrySummary.model_validate(
            details[record.id].model_dump(mode="python", exclude={"items"})
        )
        for record in records
    )
    return MatraixBatchRegistriesResponse(
        items=summaries,
        page=page,
        page_size=page_size,
        total=total,
        observed_at=observed_at,
    )


async def get_batch_registry(
    session: AsyncSession,
    registry_id: UUID,
) -> MatraixBatchRegistryDetail:
    record = await session.scalar(
        select(MatraixBatchRegistryRecord).where(
            MatraixBatchRegistryRecord.id == registry_id,
            MatraixBatchRegistryRecord.sealed_at.is_not(None),
        )
    )
    if record is None:
        raise MatraixBatchRegistryNotFoundError(
            f"MatrAIx batch registry {registry_id} was not found"
        )
    observed_at = await _database_now(session)
    return (await _load_registry_details(session, (record,), observed_at))[record.id]


async def _database_now(session: AsyncSession) -> datetime:
    observed_at = await session.scalar(select(func.current_timestamp()))
    if observed_at is None:
        raise MatraixBatchRegistryIntegrityError("PostgreSQL did not return CURRENT_TIMESTAMP")
    return observed_at


async def list_batch_registry_candidates(
    session: AsyncSession,
    page: int,
    page_size: int,
    kind: MatraixBatchKind | None,
) -> MatraixBatchRegistryCandidatesResponse:
    observed_at = await _database_now(session)
    source_sql = """
    SELECT 'chat'::text AS kind, id, created_at
    FROM matraix_chat_evaluations
    WHERE input_sealed_at IS NOT NULL
      AND (CAST(:kind AS text) IS NULL OR CAST(:kind AS text)='chat')
    UNION ALL
    SELECT 'survey'::text AS kind, id, created_at
    FROM matraix_survey_experiments
    WHERE input_sealed_at IS NOT NULL
      AND (CAST(:kind AS text) IS NULL OR CAST(:kind AS text)='survey')
    UNION ALL
    SELECT 'survey'::text AS kind, id, created_at
    FROM research_surveys
    WHERE sealed_at IS NOT NULL
      AND (CAST(:kind AS text) IS NULL OR CAST(:kind AS text)='survey')
    UNION ALL
    SELECT 'web'::text AS kind, id, created_at
    FROM matraix_web_evaluations
    WHERE input_sealed_at IS NOT NULL
      AND (CAST(:kind AS text) IS NULL OR CAST(:kind AS text)='web')
    UNION ALL
    SELECT 'linux'::text AS kind, id, created_at
    FROM matraix_linux_evaluations
    WHERE input_sealed_at IS NOT NULL
      AND (CAST(:kind AS text) IS NULL OR CAST(:kind AS text)='linux')
    """
    parameters = {"kind": kind, "offset": (page - 1) * page_size, "limit": page_size}
    total = int(
        await session.scalar(text(f"SELECT count(*) FROM ({source_sql}) AS candidates"), parameters)
        or 0
    )
    if (total == 0 and page > 1) or (total > 0 and (page - 1) * page_size >= total):
        raise MatraixBatchRegistryPageOutOfRangeError(
            f"MatrAIx batch registry candidate page {page} is out of range for {total} items"
        )
    rows = tuple(
        (
            await session.execute(
                text(
                    f"SELECT kind, id FROM ({source_sql}) AS candidates "
                    "ORDER BY created_at DESC, kind ASC, id ASC "
                    "OFFSET :offset ROWS FETCH FIRST :limit ROWS ONLY"
                ),
                parameters,
            )
        ).tuples()
    )
    references: list[tuple[MatraixBatchKind, UUID]] = []
    for raw_kind, raw_id in rows:
        if raw_kind not in ("survey", "chat", "web", "linux") or not isinstance(raw_id, UUID):
            raise MatraixBatchRegistryIntegrityError("candidate identity has an invalid shape")
        references.append((cast(MatraixBatchKind, raw_kind), raw_id))
    sources = await _load_sources(session, tuple(references))
    return MatraixBatchRegistryCandidatesResponse(
        items=tuple(_public_candidate(sources[reference]) for reference in references),
        page=page,
        page_size=page_size,
        total=total,
        observed_at=observed_at,
    )


__all__ = [
    "create_batch_registry",
    "create_native_batch_launch",
    "ensure_batch_registry",
    "get_batch_registry",
    "list_batch_registries",
    "list_batch_registry_candidates",
]
