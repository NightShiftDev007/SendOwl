"""Verified, bounded reads across durable MatrAIx source trials."""

from datetime import datetime
from typing import NamedTuple, TypedDict, cast
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.matraix_chat.contracts import ChatPersonaRef
from app.matraix_chat.errors import MatraixChatTrialNotFoundError
from app.matraix_chat.hashing import calculate_trial_sha256
from app.matraix_chat.models import (
    MatraixChatEvaluationRecord,
    MatraixChatTrialRecord,
)
from app.matraix_chat.repository import get_chat_trial, verify_chat_evaluation_record
from app.matraix_chat.tasks import RUNNER_VERSION as CHAT_RUNNER_VERSION
from app.matraix_chat.tasks import build_chat_task
from app.matraix_linux.contracts import LinuxCohortRef, LinuxPersonaRef
from app.matraix_linux.errors import MatraixLinuxTrialNotFoundError
from app.matraix_linux.hashing import calculate_trial_sha256 as calculate_linux_trial_sha256
from app.matraix_linux.models import MatraixLinuxTrialRecord
from app.matraix_linux.repository import get_linux_trial
from app.matraix_linux.tasks import RUNNER_VERSION as LINUX_RUNNER_VERSION
from app.matraix_linux.tasks import build_linux_task
from app.matraix_surveys.contracts import SurveyPersonaRef
from app.matraix_surveys.errors import MatraixSurveyTrialNotFoundError
from app.matraix_surveys.hashing import calculate_survey_trial_sha256
from app.matraix_surveys.instrument import RUNNER_VERSION as SURVEY_RUNNER_VERSION
from app.matraix_surveys.models import (
    MatraixSurveyExperimentRecord,
    MatraixSurveyTrialRecord,
)
from app.matraix_surveys.repository import get_matraix_survey_trial, verify_survey_experiment_record
from app.matraix_trial_archive.contracts import (
    ChatTrialArchiveItem,
    ChatTrialArchiveProvenance,
    LinuxTrialArchiveItem,
    LinuxTrialArchiveProvenance,
    MatraixTrialArchiveError,
    MatraixTrialArchiveItem,
    MatraixTrialArchivePersona,
    MatraixTrialArchiveResponse,
    MatraixTrialArchiveStatistics,
    MatraixTrialIntegrityCheck,
    MatraixTrialIntegrityVerification,
    MatraixTrialKind,
    MatraixTrialStatus,
    SurveyTrialArchiveItem,
    SurveyTrialArchiveProvenance,
    WebTrialArchiveItem,
    WebTrialArchiveProvenance,
)
from app.matraix_trial_archive.errors import (
    MatraixTrialArchiveIntegrityError,
    MatraixTrialArchivePageOutOfRangeError,
)
from app.matraix_web.contracts import WebCohortRef, WebPersonaRef
from app.matraix_web.errors import MatraixWebTrialNotFoundError
from app.matraix_web.hashing import (
    calculate_evaluation_sha256 as calculate_web_evaluation_sha256,
)
from app.matraix_web.hashing import calculate_trial_sha256 as calculate_web_trial_sha256
from app.matraix_web.models import MatraixWebEvaluationRecord, MatraixWebTrialRecord
from app.matraix_web.repository import get_web_trial
from app.matraix_web.tasks import RUNNER_VERSION as WEB_RUNNER_VERSION
from app.matraix_web.tasks import build_web_task
from app.populations.models import CohortRecord
from app.research_surveys.hashing import trial_sha256 as research_survey_trial_sha256
from app.research_surveys.models import ResearchSurveyRecord, ResearchSurveyTrialRecord

INTEGRITY_LIMITATIONS = (
    "Verification proves stored parent, Trial, state, and output content-address integrity.",
    "A verified Trial is not a benchmark reward, real-human result, forecast, or causal claim.",
)

ARCHIVE_SOURCE_SQL = """
SELECT 'chat'::text AS kind, trial.id, trial.created_at, trial.status
FROM matraix_chat_trials AS trial
JOIN matraix_chat_evaluations AS parent ON parent.id = trial.evaluation_id
WHERE parent.input_sealed_at IS NOT NULL
  AND (CAST(:kind AS text) IS NULL OR CAST(:kind AS text) = 'chat')
  AND (CAST(:status AS text) IS NULL OR trial.status = CAST(:status AS text))
UNION ALL
SELECT 'survey'::text AS kind, trial.id, trial.created_at, trial.status
FROM matraix_survey_trials AS trial
JOIN matraix_survey_experiments AS parent ON parent.id = trial.experiment_id
WHERE parent.input_sealed_at IS NOT NULL
  AND (CAST(:kind AS text) IS NULL OR CAST(:kind AS text) = 'survey')
  AND (CAST(:status AS text) IS NULL OR trial.status = CAST(:status AS text))
UNION ALL
SELECT 'survey'::text AS kind, trial.id, trial.created_at, trial.status
FROM research_survey_trials AS trial
JOIN research_surveys AS parent ON parent.id = trial.survey_id
WHERE parent.sealed_at IS NOT NULL
  AND (CAST(:kind AS text) IS NULL OR CAST(:kind AS text) = 'survey')
  AND (CAST(:status AS text) IS NULL OR trial.status = CAST(:status AS text))
UNION ALL
SELECT 'web'::text AS kind, trial.id, trial.created_at, trial.status
FROM matraix_web_trials AS trial
JOIN matraix_web_evaluations AS parent ON parent.id = trial.evaluation_id
WHERE parent.input_sealed_at IS NOT NULL
  AND (CAST(:kind AS text) IS NULL OR CAST(:kind AS text) = 'web')
  AND (CAST(:status AS text) IS NULL OR trial.status = CAST(:status AS text))
UNION ALL
SELECT 'linux'::text AS kind, trial.id, trial.created_at, trial.status
FROM matraix_linux_trials AS trial
JOIN cohorts AS parent ON parent.id = trial.cohort_id
WHERE parent.sealed_at IS NOT NULL
  AND parent.cohort_sha256 = trial.cohort_sha256
  AND (CAST(:kind AS text) IS NULL OR CAST(:kind AS text) = 'linux')
  AND (CAST(:status AS text) IS NULL OR trial.status = CAST(:status AS text))
"""
ARCHIVE_COUNT_SQL = f"SELECT count(*) FROM ({ARCHIVE_SOURCE_SQL}) AS archive"
ARCHIVE_STATISTICS_SQL = f"""
SELECT kind, status, count(*) AS item_count
FROM ({ARCHIVE_SOURCE_SQL}) AS archive
GROUP BY kind, status
"""
ARCHIVE_PAGE_SQL = f"""
SELECT kind, id, created_at
FROM ({ARCHIVE_SOURCE_SQL}) AS archive
ORDER BY created_at DESC, kind ASC, id ASC
OFFSET :offset ROWS FETCH FIRST :page_size ROWS ONLY
"""


class ArchiveQueryParameters(TypedDict):
    kind: MatraixTrialKind | None
    status: MatraixTrialStatus | None


class ArchivePageParameters(ArchiveQueryParameters):
    offset: int
    page_size: int


class ArchiveIdentity(NamedTuple):
    kind: MatraixTrialKind
    id: UUID
    created_at: datetime


def _check(
    name: str,
    digest: str | None,
    applicable: bool,
) -> MatraixTrialIntegrityCheck:
    return MatraixTrialIntegrityCheck(
        name=name,
        status="passed" if applicable else "not_applicable",
        content_sha256=digest if applicable else None,
    )


async def verify_trial_integrity(
    session: AsyncSession,
    kind: MatraixTrialKind,
    trial_id: UUID,
) -> MatraixTrialIntegrityVerification:
    """Recompute one Trial's existing immutable addresses and state invariants."""
    if kind == "survey":
        legacy_record = await session.scalar(
            select(MatraixSurveyTrialRecord).where(MatraixSurveyTrialRecord.id == trial_id)
        )
        native_record = await session.scalar(
            select(ResearchSurveyTrialRecord).where(ResearchSurveyTrialRecord.id == trial_id)
        )
        if legacy_record is not None and native_record is not None:
            raise MatraixTrialArchiveIntegrityError(
                f"Survey trial id {trial_id} is ambiguous across native and historical stores"
            )
        if legacy_record is None and native_record is None:
            raise MatraixSurveyTrialNotFoundError(f"MatrAIx Survey trial {trial_id} was not found")
        if native_record is not None:
            native_parent = await session.scalar(
                select(ResearchSurveyRecord).where(
                    ResearchSurveyRecord.id == native_record.survey_id,
                    ResearchSurveyRecord.sealed_at.is_not(None),
                )
            )
            if native_parent is None:
                raise MatraixTrialArchiveIntegrityError(
                    f"SandOwl Survey trial {trial_id} references a missing sealed parent"
                )
            expected_sha = research_survey_trial_sha256(
                native_parent.survey_sha256,
                native_record.persona_position,
                native_record.persona_id,
                native_record.persona_profile_sha256,
            )
            if native_record.trial_sha256 != expected_sha:
                raise MatraixTrialArchiveIntegrityError(
                    f"SandOwl Survey trial {trial_id} does not match trial_sha256"
                )
            trial = native_record
            checks = (
                _check("sealed_parent", native_parent.survey_sha256, True),
                _check("trial_address", trial.trial_sha256, True),
                _check("state_shape", None, True),
                _check("survey_answers", trial.answers_sha256, trial.answers_sha256 is not None),
            )
        else:
            assert legacy_record is not None
            parent = await session.scalar(
                select(MatraixSurveyExperimentRecord).where(
                    MatraixSurveyExperimentRecord.id == legacy_record.experiment_id,
                    MatraixSurveyExperimentRecord.input_sealed_at.is_not(None),
                )
            )
            if parent is None:
                raise MatraixTrialArchiveIntegrityError(
                    f"MatrAIx Survey trial {trial_id} references a missing sealed parent"
                )
            trial = await get_matraix_survey_trial(session, trial_id)
            checks = (
                _check("sealed_parent", parent.experiment_sha256, True),
                _check("trial_address", trial.trial_sha256, True),
                _check("state_shape", None, True),
                _check(
                    "survey_answers",
                    trial.result.answers_sha256 if trial.result is not None else None,
                    trial.result is not None,
                ),
            )
    elif kind == "chat":
        record = await session.scalar(
            select(MatraixChatTrialRecord).where(MatraixChatTrialRecord.id == trial_id)
        )
        if record is None:
            raise MatraixChatTrialNotFoundError(f"MatrAIx Chat trial {trial_id} was not found")
        parent = await session.scalar(
            select(MatraixChatEvaluationRecord).where(
                MatraixChatEvaluationRecord.id == record.evaluation_id,
                MatraixChatEvaluationRecord.input_sealed_at.is_not(None),
            )
        )
        if parent is None:
            raise MatraixTrialArchiveIntegrityError(
                f"MatrAIx Chat trial {trial_id} references a missing sealed parent"
            )
        trial = await get_chat_trial(session, trial_id)
        checks = (
            _check("sealed_parent", parent.evaluation_sha256, True),
            _check("trial_address", trial.trial_sha256, True),
            _check("state_shape", None, True),
            _check(
                "chat_transcript",
                trial.result.transcript_sha256 if trial.result is not None else None,
                trial.result is not None,
            ),
            _check(
                "chat_feedback",
                trial.result.feedback_sha256 if trial.result is not None else None,
                trial.result is not None,
            ),
            _check(
                "chat_result",
                trial.result.result_sha256 if trial.result is not None else None,
                trial.result is not None,
            ),
        )
    elif kind == "web":
        record = await session.scalar(
            select(MatraixWebTrialRecord).where(MatraixWebTrialRecord.id == trial_id)
        )
        if record is None:
            raise MatraixWebTrialNotFoundError(f"MatrAIx Web trial {trial_id} was not found")
        parent = await session.scalar(
            select(MatraixWebEvaluationRecord).where(
                MatraixWebEvaluationRecord.id == record.evaluation_id,
                MatraixWebEvaluationRecord.input_sealed_at.is_not(None),
            )
        )
        if parent is None:
            raise MatraixTrialArchiveIntegrityError(
                f"MatrAIx Web trial {trial_id} references a missing sealed parent"
            )
        trial = await get_web_trial(session, trial_id)
        checks = (
            _check("sealed_parent", parent.evaluation_sha256, True),
            _check("trial_address", trial.trial_sha256, True),
            _check("state_shape", None, True),
            _check(
                "web_trace",
                trial.result.trace_sha256 if trial.result is not None else None,
                trial.result is not None,
            ),
            _check(
                "web_result",
                trial.result.result_sha256 if trial.result is not None else None,
                trial.result is not None,
            ),
        )
    else:
        record = await session.scalar(
            select(MatraixLinuxTrialRecord).where(MatraixLinuxTrialRecord.id == trial_id)
        )
        if record is None:
            raise MatraixLinuxTrialNotFoundError(f"MatrAIx Linux trial {trial_id} was not found")
        parent = await session.scalar(
            select(CohortRecord).where(
                CohortRecord.id == record.cohort_id,
                CohortRecord.sealed_at.is_not(None),
                CohortRecord.cohort_sha256 == record.cohort_sha256,
            )
        )
        if parent is None:
            raise MatraixTrialArchiveIntegrityError(
                f"MatrAIx Linux trial {trial_id} references a missing sealed Cohort"
            )
        trial = await get_linux_trial(session, trial_id)
        checks = (
            _check("sealed_parent", parent.cohort_sha256, True),
            _check("trial_address", trial.trial_sha256, True),
            _check("state_shape", None, True),
            _check(
                "linux_artifact",
                trial.result.artifact_sha256 if trial.result is not None else None,
                trial.result is not None,
            ),
            _check(
                "linux_result",
                trial.result.result_sha256 if trial.result is not None else None,
                trial.result is not None,
            ),
        )
    verified_at = await session.scalar(select(func.current_timestamp()))
    if verified_at is None:
        raise MatraixTrialArchiveIntegrityError(
            "PostgreSQL did not return an integrity verification timestamp"
        )
    return MatraixTrialIntegrityVerification(
        kind=kind,
        trial_id=trial_id,
        status=trial.status,
        verification="verified",
        verified_at=verified_at,
        checks=checks,
        limitations=INTEGRITY_LIMITATIONS,
    )


async def _load_archive_statistics(
    session: AsyncSession,
    filters: ArchiveQueryParameters,
) -> MatraixTrialArchiveStatistics:
    kind_counts: dict[MatraixTrialKind, int] = {
        "survey": 0,
        "chat": 0,
        "web": 0,
        "linux": 0,
    }
    status_counts: dict[MatraixTrialStatus, int] = {
        "queued": 0,
        "running": 0,
        "succeeded": 0,
        "failed": 0,
    }
    rows = (await session.execute(text(ARCHIVE_STATISTICS_SQL), filters)).tuples()
    for raw_kind, raw_status, raw_count in rows:
        if raw_kind not in kind_counts or raw_status not in status_counts:
            raise MatraixTrialArchiveIntegrityError(
                "MatrAIx archive statistics contain an unsupported kind or status"
            )
        kind = cast(MatraixTrialKind, raw_kind)
        trial_status = cast(MatraixTrialStatus, raw_status)
        count = int(raw_count)
        if count < 0:
            raise MatraixTrialArchiveIntegrityError(
                "MatrAIx archive statistics contain a negative count"
            )
        kind_counts[kind] += count
        status_counts[trial_status] += count
    total = sum(kind_counts.values())
    return MatraixTrialArchiveStatistics(
        total=total,
        by_kind={
            "survey": kind_counts["survey"],
            "chat": kind_counts["chat"],
            "web": kind_counts["web"],
            "linux": kind_counts["linux"],
        },
        by_status={
            "queued": status_counts["queued"],
            "running": status_counts["running"],
            "succeeded": status_counts["succeeded"],
            "failed": status_counts["failed"],
        },
    )


def _archive_error(
    trial_id: UUID,
    error_code: str | None,
    error_message: str | None,
) -> MatraixTrialArchiveError | None:
    if error_code is None and error_message is None:
        return None
    if error_code is None or error_message is None:
        raise MatraixTrialArchiveIntegrityError(
            f"MatrAIx trial {trial_id} has incomplete failure fields"
        )
    return MatraixTrialArchiveError(code=error_code, message=error_message)


def _archive_persona(
    persona_id: UUID,
    persona_position: int,
    persona_external_id: str,
    persona_display_name: str,
    persona_profile_sha256: str,
) -> MatraixTrialArchivePersona:
    return MatraixTrialArchivePersona(
        id=persona_id,
        position=persona_position,
        persona_id=persona_external_id,
        display_name=persona_display_name,
        profile_sha256=persona_profile_sha256,
    )


def _chat_archive_item(
    trial: MatraixChatTrialRecord,
    parent: MatraixChatEvaluationRecord,
) -> ChatTrialArchiveItem:
    task = build_chat_task(parent.task_id)
    verify_chat_evaluation_record(parent, task)
    if trial.evaluation_id != parent.id or trial.created_at != parent.created_at:
        raise MatraixTrialArchiveIntegrityError(
            f"MatrAIx Chat trial {trial.id} does not match its sealed parent"
        )
    persona = ChatPersonaRef(
        id=trial.persona_id,
        position=trial.persona_position,
        persona_id=trial.persona_external_id,
        display_name=trial.persona_display_name,
        profile_sha256=trial.persona_profile_sha256,
    )
    expected_trial_sha256 = calculate_trial_sha256(parent.evaluation_sha256, persona)
    if expected_trial_sha256 != trial.trial_sha256:
        raise MatraixTrialArchiveIntegrityError(
            f"MatrAIx Chat trial {trial.id} does not match trial_sha256"
        )
    if trial.status == "succeeded" and (
        trial.runner_version != CHAT_RUNNER_VERSION
        or trial.model_name != parent.model_name
        or trial.chat_config_sha256 != parent.chat_config_sha256
        or trial.prompt_schema_version != parent.prompt_schema_version
    ):
        raise MatraixTrialArchiveIntegrityError(
            f"MatrAIx Chat trial {trial.id} provenance does not match its sealed parent"
        )
    return ChatTrialArchiveItem(
        kind="chat",
        id=trial.id,
        status=trial.status,
        parent_id=parent.id,
        parent_sha256=parent.evaluation_sha256,
        trial_sha256=trial.trial_sha256,
        task={"title": task.title, "version": task.version},
        persona=_archive_persona(
            trial.persona_id,
            trial.persona_position,
            trial.persona_external_id,
            trial.persona_display_name,
            trial.persona_profile_sha256,
        ),
        created_at=trial.created_at,
        started_at=trial.started_at,
        completed_at=trial.completed_at,
        error=_archive_error(trial.id, trial.error_code, trial.error_message),
        provenance=ChatTrialArchiveProvenance(
            runner_version=trial.runner_version,
            model_name=parent.model_name,
            parent_config_sha256=parent.chat_config_sha256,
            prompt_schema_version=parent.prompt_schema_version,
            transcript_sha256=trial.transcript_sha256,
            feedback_sha256=trial.feedback_sha256,
            result_sha256=trial.result_sha256,
        ),
        source_detail_path=f"/api/v2/matraix/chat-trials/{trial.id}",
    )


def _survey_archive_item(
    trial: MatraixSurveyTrialRecord,
    parent: MatraixSurveyExperimentRecord,
) -> SurveyTrialArchiveItem:
    verify_survey_experiment_record(parent)
    if trial.experiment_id != parent.id or trial.created_at != parent.created_at:
        raise MatraixTrialArchiveIntegrityError(
            f"MatrAIx Survey trial {trial.id} does not match its sealed parent"
        )
    persona = SurveyPersonaRef(
        id=trial.persona_id,
        position=trial.persona_position,
        persona_id=trial.persona_external_id,
        display_name=trial.persona_display_name,
        profile_sha256=trial.persona_profile_sha256,
    )
    expected_trial_sha256 = calculate_survey_trial_sha256(parent.experiment_sha256, persona)
    if expected_trial_sha256 != trial.trial_sha256:
        raise MatraixTrialArchiveIntegrityError(
            f"MatrAIx Survey trial {trial.id} does not match trial_sha256"
        )
    if trial.status == "succeeded" and (
        trial.runner_version != SURVEY_RUNNER_VERSION
        or trial.model_name != parent.model_name
        or trial.survey_config_sha256 != parent.survey_config_sha256
        or trial.prompt_schema_version != parent.prompt_schema_version
    ):
        raise MatraixTrialArchiveIntegrityError(
            f"MatrAIx Survey trial {trial.id} provenance does not match its sealed parent"
        )
    return SurveyTrialArchiveItem(
        kind="survey",
        id=trial.id,
        status=trial.status,
        parent_id=parent.id,
        parent_sha256=parent.experiment_sha256,
        trial_sha256=trial.trial_sha256,
        task={"title": parent.scenario_title, "version": "scenario-preference/v1"},
        persona=_archive_persona(
            trial.persona_id,
            trial.persona_position,
            trial.persona_external_id,
            trial.persona_display_name,
            trial.persona_profile_sha256,
        ),
        created_at=trial.created_at,
        started_at=trial.started_at,
        completed_at=trial.completed_at,
        error=_archive_error(trial.id, trial.error_code, trial.error_message),
        provenance=SurveyTrialArchiveProvenance(
            runner_version=trial.runner_version,
            model_name=parent.model_name,
            parent_config_sha256=parent.survey_config_sha256,
            prompt_schema_version=parent.prompt_schema_version,
            answers_sha256=trial.answers_sha256,
        ),
        source_detail_path=f"/api/v2/matraix/survey-trials/{trial.id}",
    )


def _research_survey_archive_item(
    trial: ResearchSurveyTrialRecord,
    parent: ResearchSurveyRecord,
) -> SurveyTrialArchiveItem:
    expected_trial_sha256 = research_survey_trial_sha256(
        parent.survey_sha256,
        trial.persona_position,
        trial.persona_id,
        trial.persona_profile_sha256,
    )
    if trial.survey_id != parent.id or expected_trial_sha256 != trial.trial_sha256:
        raise MatraixTrialArchiveIntegrityError(
            f"SandOwl Research Survey trial {trial.id} does not match its sealed parent"
        )
    if trial.status == "succeeded" and (
        trial.runner_version != "1.0.0"
        or trial.model_name != parent.model_name
        or trial.survey_config_sha256 != parent.survey_config_sha256
        or trial.prompt_schema_version != parent.prompt_schema_version
        or trial.answers_sha256 is None
    ):
        raise MatraixTrialArchiveIntegrityError(
            f"SandOwl Research Survey trial {trial.id} provenance does not match its parent"
        )
    return SurveyTrialArchiveItem(
        kind="survey",
        id=trial.id,
        status=trial.status,
        parent_id=parent.id,
        parent_sha256=parent.survey_sha256,
        trial_sha256=trial.trial_sha256,
        task={"title": parent.project_title, "version": "single-context-observation/v1"},
        persona=_archive_persona(
            trial.persona_id,
            trial.persona_position,
            trial.persona_external_id,
            trial.persona_display_name,
            trial.persona_profile_sha256,
        ),
        created_at=trial.created_at,
        started_at=trial.started_at,
        completed_at=trial.completed_at,
        error=_archive_error(trial.id, trial.error_code, trial.error_message),
        provenance=SurveyTrialArchiveProvenance(
            runner_version=trial.runner_version,
            model_name=parent.model_name,
            parent_config_sha256=parent.survey_config_sha256,
            prompt_schema_version=parent.prompt_schema_version,
            answers_sha256=trial.answers_sha256,
        ),
        source_detail_path=f"/api/v2/research-surveys/{parent.id}",
    )


def _web_archive_item(
    trial: MatraixWebTrialRecord,
    parent: MatraixWebEvaluationRecord,
) -> WebTrialArchiveItem:
    task = build_web_task()
    cohort = WebCohortRef(
        id=parent.cohort_id,
        title=parent.cohort_title,
        cohort_sha256=parent.cohort_sha256,
        dataset_sha256=parent.dataset_sha256,
        persona_count=parent.persona_count,
    )
    expected_parent_sha256 = calculate_web_evaluation_sha256(
        parent.task_spec_sha256,
        parent.executor_spec_sha256,
        cohort,
        parent.model_name,
        parent.web_config_sha256,
    )
    if (
        parent.input_sealed_at is None
        or parent.task_id != task.task_id
        or parent.task_version != task.version
        or parent.task_schema_version != task.schema_version
        or parent.task_spec_sha256 != task.task_spec_sha256
        or parent.executor_schema_version != task.executor_schema_version
        or parent.executor_spec_sha256 != task.executor_spec_sha256
        or parent.evaluation_sha256 != expected_parent_sha256
    ):
        raise MatraixTrialArchiveIntegrityError(
            f"MatrAIx Web evaluation {parent.id} failed archive integrity verification"
        )
    if trial.evaluation_id != parent.id or trial.created_at != parent.created_at:
        raise MatraixTrialArchiveIntegrityError(
            f"MatrAIx Web trial {trial.id} does not match its sealed parent"
        )
    persona = WebPersonaRef(
        id=trial.persona_id,
        position=trial.persona_position,
        persona_id=trial.persona_external_id,
        display_name=trial.persona_display_name,
        profile_sha256=trial.persona_profile_sha256,
    )
    if calculate_web_trial_sha256(parent.evaluation_sha256, persona) != trial.trial_sha256:
        raise MatraixTrialArchiveIntegrityError(
            f"MatrAIx Web trial {trial.id} does not match trial_sha256"
        )
    if trial.status == "succeeded" and (
        trial.runner_version != WEB_RUNNER_VERSION
        or trial.model_name != parent.model_name
        or trial.web_config_sha256 != parent.web_config_sha256
        or trial.prompt_schema_version != parent.prompt_schema_version
    ):
        raise MatraixTrialArchiveIntegrityError(
            f"MatrAIx Web trial {trial.id} provenance does not match its sealed parent"
        )
    return WebTrialArchiveItem(
        kind="web",
        id=trial.id,
        status=trial.status,
        parent_id=parent.id,
        parent_sha256=parent.evaluation_sha256,
        trial_sha256=trial.trial_sha256,
        task={"title": task.title, "version": task.version},
        persona=_archive_persona(
            trial.persona_id,
            trial.persona_position,
            trial.persona_external_id,
            trial.persona_display_name,
            trial.persona_profile_sha256,
        ),
        created_at=trial.created_at,
        started_at=trial.started_at,
        completed_at=trial.completed_at,
        error=_archive_error(trial.id, trial.error_code, trial.error_message),
        provenance=WebTrialArchiveProvenance(
            runner_version=trial.runner_version,
            model_name=parent.model_name,
            parent_config_sha256=parent.web_config_sha256,
            prompt_schema_version=parent.prompt_schema_version,
            trace_sha256=trial.trace_sha256,
            result_sha256=trial.result_sha256,
        ),
        source_detail_path=f"/api/v2/matraix/web-trials/{trial.id}",
    )


def _linux_archive_item(
    trial: MatraixLinuxTrialRecord,
    cohort_record: CohortRecord,
) -> LinuxTrialArchiveItem:
    task = build_linux_task()
    cohort = LinuxCohortRef(
        id=trial.cohort_id,
        title=trial.cohort_title,
        cohort_sha256=trial.cohort_sha256,
        dataset_sha256=trial.dataset_sha256,
    )
    persona = LinuxPersonaRef(
        id=trial.persona_id,
        position=trial.persona_position,
        persona_id=trial.persona_external_id,
        display_name=trial.persona_display_name,
        profile_sha256=trial.persona_profile_sha256,
    )
    expected_trial_sha256 = calculate_linux_trial_sha256(
        trial.task_spec_sha256,
        trial.runner_spec_sha256,
        cohort,
        persona,
        trial.model_name,
        trial.linux_config_sha256,
        trial.prompt_schema_version,
    )
    if (
        cohort_record.sealed_at is None
        or cohort_record.id != trial.cohort_id
        or cohort_record.title != trial.cohort_title
        or cohort_record.cohort_sha256 != trial.cohort_sha256
        or trial.task_id != task.task_id
        or trial.task_version != task.version
        or trial.task_schema_version != task.schema_version
        or trial.task_spec_sha256 != task.task_spec_sha256
        or trial.runner_schema_version != task.runner_schema_version
        or trial.runner_spec_sha256 != task.runner_spec_sha256
        or trial.trial_sha256 != expected_trial_sha256
    ):
        raise MatraixTrialArchiveIntegrityError(
            f"MatrAIx Linux trial {trial.id} failed archive integrity verification"
        )
    if trial.status == "succeeded" and trial.result_runner_version != LINUX_RUNNER_VERSION:
        raise MatraixTrialArchiveIntegrityError(
            f"MatrAIx Linux trial {trial.id} runner provenance is invalid"
        )
    return LinuxTrialArchiveItem(
        kind="linux",
        id=trial.id,
        status=trial.status,
        parent_id=cohort_record.id,
        parent_sha256=cohort_record.cohort_sha256,
        trial_sha256=trial.trial_sha256,
        task={"title": task.title, "version": task.version},
        persona=_archive_persona(
            trial.persona_id,
            trial.persona_position,
            trial.persona_external_id,
            trial.persona_display_name,
            trial.persona_profile_sha256,
        ),
        created_at=trial.created_at,
        started_at=trial.started_at,
        completed_at=trial.completed_at,
        error=_archive_error(trial.id, trial.error_code, trial.error_message),
        provenance=LinuxTrialArchiveProvenance(
            runner_version=trial.result_runner_version,
            model_name=trial.model_name,
            parent_config_sha256=trial.linux_config_sha256,
            prompt_schema_version=trial.prompt_schema_version,
            artifact_sha256=trial.result_artifact_sha256,
            result_sha256=trial.result_sha256,
        ),
        source_detail_path=f"/api/v2/matraix/linux-trials/{trial.id}",
    )


async def _load_archive_items(
    session: AsyncSession,
    identities: tuple[ArchiveIdentity, ...],
) -> dict[tuple[MatraixTrialKind, UUID], MatraixTrialArchiveItem]:
    chat_ids = tuple(item.id for item in identities if item.kind == "chat")
    survey_ids = tuple(item.id for item in identities if item.kind == "survey")
    web_ids = tuple(item.id for item in identities if item.kind == "web")
    linux_ids = tuple(item.id for item in identities if item.kind == "linux")
    items: dict[tuple[MatraixTrialKind, UUID], MatraixTrialArchiveItem] = {}
    if chat_ids:
        chat_rows = tuple(
            (
                await session.execute(
                    select(MatraixChatTrialRecord, MatraixChatEvaluationRecord)
                    .join(
                        MatraixChatEvaluationRecord,
                        MatraixChatEvaluationRecord.id == MatraixChatTrialRecord.evaluation_id,
                    )
                    .where(
                        MatraixChatTrialRecord.id.in_(chat_ids),
                        MatraixChatEvaluationRecord.input_sealed_at.is_not(None),
                    )
                )
            ).tuples()
        )
        for trial, parent in chat_rows:
            items[("chat", trial.id)] = _chat_archive_item(trial, parent)
    if survey_ids:
        survey_rows = tuple(
            (
                await session.execute(
                    select(MatraixSurveyTrialRecord, MatraixSurveyExperimentRecord)
                    .join(
                        MatraixSurveyExperimentRecord,
                        MatraixSurveyExperimentRecord.id == MatraixSurveyTrialRecord.experiment_id,
                    )
                    .where(
                        MatraixSurveyTrialRecord.id.in_(survey_ids),
                        MatraixSurveyExperimentRecord.input_sealed_at.is_not(None),
                    )
                )
            ).tuples()
        )
        for trial, parent in survey_rows:
            items[("survey", trial.id)] = _survey_archive_item(trial, parent)
        research_survey_rows = tuple(
            (
                await session.execute(
                    select(ResearchSurveyTrialRecord, ResearchSurveyRecord)
                    .join(
                        ResearchSurveyRecord,
                        ResearchSurveyRecord.id == ResearchSurveyTrialRecord.survey_id,
                    )
                    .where(
                        ResearchSurveyTrialRecord.id.in_(survey_ids),
                        ResearchSurveyRecord.sealed_at.is_not(None),
                    )
                )
            ).tuples()
        )
        for trial, parent in research_survey_rows:
            key: tuple[MatraixTrialKind, UUID] = ("survey", trial.id)
            if key in items:
                raise MatraixTrialArchiveIntegrityError(
                    f"Survey trial id {trial.id} is ambiguous across native and historical stores"
                )
            items[key] = _research_survey_archive_item(trial, parent)
    if web_ids:
        web_rows = tuple(
            (
                await session.execute(
                    select(MatraixWebTrialRecord, MatraixWebEvaluationRecord)
                    .join(
                        MatraixWebEvaluationRecord,
                        MatraixWebEvaluationRecord.id == MatraixWebTrialRecord.evaluation_id,
                    )
                    .where(
                        MatraixWebTrialRecord.id.in_(web_ids),
                        MatraixWebEvaluationRecord.input_sealed_at.is_not(None),
                    )
                )
            ).tuples()
        )
        for trial, parent in web_rows:
            items[("web", trial.id)] = _web_archive_item(trial, parent)
    if linux_ids:
        linux_rows = tuple(
            (
                await session.execute(
                    select(MatraixLinuxTrialRecord, CohortRecord)
                    .join(CohortRecord, CohortRecord.id == MatraixLinuxTrialRecord.cohort_id)
                    .where(
                        MatraixLinuxTrialRecord.id.in_(linux_ids),
                        CohortRecord.sealed_at.is_not(None),
                        CohortRecord.cohort_sha256 == MatraixLinuxTrialRecord.cohort_sha256,
                    )
                )
            ).tuples()
        )
        for trial, cohort in linux_rows:
            items[("linux", trial.id)] = _linux_archive_item(trial, cohort)
    expected_keys = {(identity.kind, identity.id) for identity in identities}
    if set(items) != expected_keys:
        missing = sorted(f"{kind}:{trial_id}" for kind, trial_id in expected_keys - set(items))
        raise MatraixTrialArchiveIntegrityError(
            f"MatrAIx archive page references missing sealed source trials: {', '.join(missing)}"
        )
    return items


async def list_matraix_trial_archive(
    session: AsyncSession,
    page: int,
    page_size: int,
    kind: MatraixTrialKind | None,
    status: MatraixTrialStatus | None,
) -> MatraixTrialArchiveResponse:
    """Return one strictly bounded merged page without loading source artifacts."""
    filters = ArchiveQueryParameters(kind=kind, status=status)
    total = await session.scalar(text(ARCHIVE_COUNT_SQL), filters)
    if total is None:
        raise RuntimeError("MatrAIx archive count query returned no result")
    statistics = await _load_archive_statistics(session, filters)
    if statistics.total != total:
        raise MatraixTrialArchiveIntegrityError(
            "MatrAIx archive count and statistics were read from inconsistent snapshots"
        )
    offset = (page - 1) * page_size
    if offset > 0 and offset >= total:
        raise MatraixTrialArchivePageOutOfRangeError(
            f"MatrAIx Trial Archive page {page} is outside {total} filtered trials"
        )
    parameters = ArchivePageParameters(
        kind=kind,
        status=status,
        offset=offset,
        page_size=page_size,
    )
    identities = tuple(
        ArchiveIdentity(*row)
        for row in (await session.execute(text(ARCHIVE_PAGE_SQL), parameters)).tuples()
    )
    loaded = await _load_archive_items(session, identities)
    items = tuple(loaded[(identity.kind, identity.id)] for identity in identities)
    return MatraixTrialArchiveResponse(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        statistics=statistics,
    )


__all__ = ["list_matraix_trial_archive", "verify_trial_integrity"]
