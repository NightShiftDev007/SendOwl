"""Queue, verify, and project durable MatrAIx chatbot evaluations."""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import NamedTuple
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.matraix_chat.contracts import (
    ChatCohortRef,
    ChatPersonaRef,
    ChatTranscriptMessage,
    ChatTrialError,
    ChatTrialFeedback,
    ChatTrialResult,
    MatraixChatEvaluationCreateRequest,
    MatraixChatEvaluationDetail,
    MatraixChatEvaluationsResponse,
    MatraixChatEvaluationSummary,
    MatraixChatReadiness,
    MatraixChatTask,
    MatraixChatTasksResponse,
    MatraixChatTrial,
)
from app.matraix_chat.errors import (
    MatraixChatEvaluationNotFoundError,
    MatraixChatSelectionError,
    MatraixChatTrialNotFoundError,
    MatraixChatUnavailableError,
)
from app.matraix_chat.hashing import (
    calculate_evaluation_sha256,
    calculate_feedback_sha256,
    calculate_result_sha256,
    calculate_transcript_sha256,
    calculate_trial_sha256,
)
from app.matraix_chat.models import (
    MatraixChatEvaluationRecord,
    MatraixChatFeedbackRecord,
    MatraixChatMessageRecord,
    MatraixChatTrialRecord,
)
from app.matraix_chat.tasks import (
    CHAT_SUITE_ID,
    CHAT_SUITE_SHA256,
    CHAT_SUITE_VERSION,
    PROMPT_SCHEMA_VERSION,
    RUNNER_VERSION,
    build_chat_task,
    build_chat_tasks,
)
from app.populations.contracts import CohortDetail, CohortMember
from app.populations.repository import get_cohort
from app.simulations.constants import (
    CAMEL_ENGINE_VERSION,
    OASIS_ENGINE_VERSION,
    WORKER_HEARTBEAT_MAX_AGE_SECONDS,
)
from app.simulations.models import SimulationWorkerHeartbeatRecord

READINESS_LIMITATIONS = (
    "Readiness requires a recent worker heartbeat after the provider tool-call probe, "
    "the REST /ready identity probe, and the MCP tool/identity probe.",
    "The integrated Acme REST and MCP services are deterministic MatrAIx source samples, not "
    "production customer-support system.",
    "No reward is inferred: the stored rating and qualitative fields are synthetic "
    "Persona self-report tied to the immutable transcript.",
)


def list_chat_tasks() -> MatraixChatTasksResponse:
    tasks = build_chat_tasks()
    return MatraixChatTasksResponse(items=tasks, total=len(tasks))


def _cohort_ref(cohort: CohortDetail) -> ChatCohortRef:
    return ChatCohortRef(
        id=cohort.id,
        title=cohort.title,
        cohort_sha256=cohort.cohort_sha256,
        dataset_sha256=cohort.dataset.dataset_sha256,
        persona_count=cohort.persona_count,
    )


def _persona_ref(member: CohortMember) -> ChatPersonaRef:
    return ChatPersonaRef(
        id=member.persona.id,
        position=member.position,
        persona_id=member.persona.persona_id,
        display_name=member.persona.display_name,
        profile_sha256=member.persona.profile_sha256,
    )


async def _lock_evaluation_content(session: AsyncSession, digest: str) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:digest, 0))"),
        {"digest": digest},
    )


async def _live_chat_config(session: AsyncSession) -> tuple[str, str]:
    await session.execute(text("LOCK TABLE simulation_worker_heartbeats IN SHARE MODE"))
    cutoff = datetime.now(UTC) - timedelta(seconds=WORKER_HEARTBEAT_MAX_AGE_SECONDS)
    heartbeats = tuple(
        (
            await session.execute(
                select(SimulationWorkerHeartbeatRecord)
                .where(
                    SimulationWorkerHeartbeatRecord.last_seen_at >= cutoff,
                    SimulationWorkerHeartbeatRecord.engine == "camel-oasis",
                    SimulationWorkerHeartbeatRecord.engine_version == OASIS_ENGINE_VERSION,
                    SimulationWorkerHeartbeatRecord.camel_version == CAMEL_ENGINE_VERSION,
                    SimulationWorkerHeartbeatRecord.mode == "reddit_manual_smoke",
                    SimulationWorkerHeartbeatRecord.platform_runtime_ready.is_(True),
                    SimulationWorkerHeartbeatRecord.semantic_runtime_ready.is_(True),
                    SimulationWorkerHeartbeatRecord.chat_runtime_ready.is_(True),
                    SimulationWorkerHeartbeatRecord.chat_sut_task_id == CHAT_SUITE_ID,
                    SimulationWorkerHeartbeatRecord.chat_sut_task_version == CHAT_SUITE_VERSION,
                    SimulationWorkerHeartbeatRecord.chat_sut_spec_sha256 == CHAT_SUITE_SHA256,
                )
                .with_for_update(read=True)
            )
        )
        .scalars()
        .all()
    )
    configs = {
        (
            heartbeat.chat_model_name,
            heartbeat.chat_config_sha256,
            heartbeat.chat_prompt_schema_version,
        )
        for heartbeat in heartbeats
    }
    if not configs:
        raise MatraixChatUnavailableError(
            "MatrAIx Chat execution is unavailable because no correctly pinned worker "
            "reported a complete chat configuration in the last 30 seconds"
        )
    if len(configs) != 1:
        readable = ", ".join(
            sorted(
                f"model={name!r}, config_sha256={digest!r}, prompt={prompt!r}"
                for name, digest, prompt in configs
            )
        )
        raise MatraixChatUnavailableError(
            "live Chat workers disagree on execution configuration; resolve the conflict "
            f"before enqueueing evaluations: {readable}"
        )
    model_name, config_sha256, prompt_schema = next(iter(configs))
    if model_name is None or config_sha256 is None or prompt_schema != PROMPT_SCHEMA_VERSION:
        raise RuntimeError("chat-ready worker persisted an incomplete configuration")
    return model_name, config_sha256


class ChatTrialSummaryRow(NamedTuple):
    evaluation_id: UUID
    persona_position: int
    persona_id: UUID
    persona_external_id: str
    persona_display_name: str
    persona_profile_sha256: str
    trial_sha256: str
    status: str


def _evaluation_status(statuses: tuple[str, ...]) -> str:
    if all(status == "queued" for status in statuses):
        return "queued"
    if any(status in ("queued", "running") for status in statuses):
        return "running"
    if all(status == "succeeded" for status in statuses):
        return "succeeded"
    return "failed"


def verify_chat_evaluation_record(
    record: MatraixChatEvaluationRecord,
    task: MatraixChatTask,
) -> ChatCohortRef:
    if record.input_sealed_at is None:
        raise RuntimeError(f"MatrAIx Chat evaluation {record.id} is not sealed")
    if (
        record.task_id != task.task_id
        or record.task_version != task.version
        or record.task_schema_version != task.schema_version
        or record.task_spec_sha256 != task.task_spec_sha256
        or record.sut_spec_sha256 != task.sut_spec_sha256
        or record.prompt_schema_version != PROMPT_SCHEMA_VERSION
    ):
        raise RuntimeError(f"MatrAIx Chat evaluation {record.id} task integrity mismatch")
    cohort = ChatCohortRef(
        id=record.cohort_id,
        title=record.cohort_title,
        cohort_sha256=record.cohort_sha256,
        dataset_sha256=record.dataset_sha256,
        persona_count=record.persona_count,
    )
    expected = calculate_evaluation_sha256(
        record.task_spec_sha256,
        record.sut_spec_sha256,
        cohort,
        record.model_name,
        record.chat_config_sha256,
        record.retry_of_evaluation_sha256,
        record.attempt_number,
    )
    if expected != record.evaluation_sha256:
        raise RuntimeError(f"MatrAIx Chat evaluation {record.id} integrity mismatch")
    return cohort


def _message(record: MatraixChatMessageRecord) -> ChatTranscriptMessage:
    return ChatTranscriptMessage(
        position=record.position,
        role=record.role,
        content=record.content,
        recorded_at=record.recorded_at,
    )


def _feedback(record: MatraixChatFeedbackRecord) -> ChatTrialFeedback:
    return ChatTrialFeedback(
        schema_version=record.schema_version,
        need_constraint_satisfaction=record.need_constraint_satisfaction,
        personal_preference_satisfaction=record.personal_preference_satisfaction,
        overall_experience_rating=record.overall_experience_rating,
        reason=record.reason,
        asked_useful_clarification_questions=record.asked_useful_clarification_questions,
        clarifying_notes=record.clarifying_notes,
    )


def _trial(
    record: MatraixChatTrialRecord,
    evaluation: MatraixChatEvaluationRecord,
    messages: tuple[MatraixChatMessageRecord, ...],
    feedback_record: MatraixChatFeedbackRecord | None,
) -> MatraixChatTrial:
    persona = ChatPersonaRef(
        id=record.persona_id,
        position=record.persona_position,
        persona_id=record.persona_external_id,
        display_name=record.persona_display_name,
        profile_sha256=record.persona_profile_sha256,
    )
    expected_trial = calculate_trial_sha256(evaluation.evaluation_sha256, persona)
    if expected_trial != record.trial_sha256:
        raise RuntimeError(f"MatrAIx Chat trial {record.id} integrity mismatch")
    transcript = tuple(_message(item) for item in messages)
    feedback = None if feedback_record is None else _feedback(feedback_record)
    result: ChatTrialResult | None = None
    error: ChatTrialError | None = None
    if record.status == "succeeded":
        if feedback is None:
            raise RuntimeError(f"successful MatrAIx Chat trial {record.id} has no feedback")
        expected_transcript = calculate_transcript_sha256(record.trial_sha256, transcript)
        expected_feedback = calculate_feedback_sha256(record.trial_sha256, feedback)
        required = (
            record.runner_version,
            record.model_name,
            record.chat_config_sha256,
            record.prompt_schema_version,
            record.transcript_sha256,
            record.feedback_sha256,
            record.result_sha256,
            record.outcome_status,
            record.next_step_owner,
            record.conversation_path,
            record.resolution_progression,
            record.message_count,
            record.customer_turn_count,
            record.support_turn_count,
            record.clarification_question_count,
        )
        if any(value is None for value in required):
            raise RuntimeError(f"successful MatrAIx Chat trial {record.id} is incomplete")
        if expected_transcript != record.transcript_sha256:
            raise RuntimeError(f"MatrAIx Chat trial {record.id} transcript integrity mismatch")
        if expected_feedback != record.feedback_sha256:
            raise RuntimeError(f"MatrAIx Chat trial {record.id} feedback integrity mismatch")
        expected_result = calculate_result_sha256(
            record.trial_sha256,
            expected_transcript,
            expected_feedback,
            record.outcome_status,
            record.next_step_owner,
            record.conversation_path,
            record.resolution_progression,
            record.message_count,
            record.customer_turn_count,
            record.support_turn_count,
            record.clarification_question_count,
        )
        if expected_result != record.result_sha256:
            raise RuntimeError(f"MatrAIx Chat trial {record.id} result integrity mismatch")
        if (
            record.model_name != evaluation.model_name
            or record.chat_config_sha256 != evaluation.chat_config_sha256
            or record.prompt_schema_version != evaluation.prompt_schema_version
        ):
            raise RuntimeError(f"MatrAIx Chat trial {record.id} runtime integrity mismatch")
        result = ChatTrialResult(
            runner_version=record.runner_version,
            model_name=record.model_name,
            chat_config_sha256=record.chat_config_sha256,
            prompt_schema_version=record.prompt_schema_version,
            transcript_sha256=record.transcript_sha256,
            feedback_sha256=record.feedback_sha256,
            result_sha256=record.result_sha256,
            outcome_status=record.outcome_status,
            next_step_owner=record.next_step_owner,
            conversation_path=record.conversation_path,
            resolution_progression=record.resolution_progression,
            message_count=record.message_count,
            customer_turn_count=record.customer_turn_count,
            support_turn_count=record.support_turn_count,
            clarification_question_count=record.clarification_question_count,
        )
    elif record.status == "failed":
        if feedback is not None:
            raise RuntimeError(f"failed MatrAIx Chat trial {record.id} retained feedback")
        if record.error_code is None or record.error_message is None:
            raise RuntimeError(f"failed MatrAIx Chat trial {record.id} has no error")
        error = ChatTrialError(code=record.error_code, message=record.error_message)
    elif feedback is not None:
        raise RuntimeError(f"nonterminal MatrAIx Chat trial {record.id} retained feedback")
    return MatraixChatTrial(
        id=record.id,
        status=record.status,
        persona=persona,
        trial_sha256=record.trial_sha256,
        created_at=record.created_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
        transcript=transcript,
        feedback=feedback,
        result=result,
        error=error,
    )


async def _load_trials(
    session: AsyncSession,
    evaluations: tuple[MatraixChatEvaluationRecord, ...],
) -> dict[UUID, tuple[MatraixChatTrial, ...]]:
    if not evaluations:
        return {}
    evaluation_by_id = {item.id: item for item in evaluations}
    trial_records = tuple(
        (
            await session.execute(
                select(MatraixChatTrialRecord)
                .where(MatraixChatTrialRecord.evaluation_id.in_(tuple(evaluation_by_id)))
                .order_by(
                    MatraixChatTrialRecord.evaluation_id,
                    MatraixChatTrialRecord.persona_position,
                )
            )
        )
        .scalars()
        .all()
    )
    trial_ids = tuple(item.id for item in trial_records)
    message_records = (
        ()
        if not trial_ids
        else tuple(
            (
                await session.execute(
                    select(MatraixChatMessageRecord)
                    .where(MatraixChatMessageRecord.trial_id.in_(trial_ids))
                    .order_by(
                        MatraixChatMessageRecord.trial_id,
                        MatraixChatMessageRecord.position,
                    )
                )
            )
            .scalars()
            .all()
        )
    )
    feedback_records = (
        ()
        if not trial_ids
        else tuple(
            (
                await session.execute(
                    select(MatraixChatFeedbackRecord).where(
                        MatraixChatFeedbackRecord.trial_id.in_(trial_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
    )
    messages_by_trial: dict[UUID, list[MatraixChatMessageRecord]] = defaultdict(list)
    for message_record in message_records:
        messages_by_trial[message_record.trial_id].append(message_record)
    feedback_by_trial = {item.trial_id: item for item in feedback_records}
    trials_by_evaluation: dict[UUID, list[MatraixChatTrial]] = defaultdict(list)
    for trial_record in trial_records:
        evaluation = evaluation_by_id[trial_record.evaluation_id]
        trials_by_evaluation[trial_record.evaluation_id].append(
            _trial(
                trial_record,
                evaluation,
                tuple(messages_by_trial[trial_record.id]),
                feedback_by_trial.get(trial_record.id),
            )
        )
    return {evaluation.id: tuple(trials_by_evaluation[evaluation.id]) for evaluation in evaluations}


def _summary(
    record: MatraixChatEvaluationRecord,
    trials: tuple[MatraixChatTrial, ...],
    task: MatraixChatTask,
) -> MatraixChatEvaluationSummary:
    cohort = verify_chat_evaluation_record(record, task)
    if len(trials) != record.persona_count:
        raise RuntimeError(f"MatrAIx Chat evaluation {record.id} has incomplete trials")
    return MatraixChatEvaluationSummary(
        id=record.id,
        status=_evaluation_status(tuple(item.status for item in trials)),
        created_at=record.created_at,
        task=task,
        cohort=cohort,
        trial_count=len(trials),
        succeeded_trial_count=sum(item.status == "succeeded" for item in trials),
        failed_trial_count=sum(item.status == "failed" for item in trials),
        model_name=record.model_name,
        chat_config_sha256=record.chat_config_sha256,
        prompt_schema_version=record.prompt_schema_version,
        evaluation_sha256=record.evaluation_sha256,
        retry_of_evaluation_id=record.retry_of_evaluation_id,
        retry_of_evaluation_sha256=record.retry_of_evaluation_sha256,
        attempt_number=record.attempt_number,
    )


async def _load_trial_summaries(
    session: AsyncSession,
    evaluations: tuple[MatraixChatEvaluationRecord, ...],
) -> dict[UUID, tuple[ChatTrialSummaryRow, ...]]:
    """Load bounded trial identity/status rows without transcript or feedback tables."""
    if not evaluations:
        return {}
    evaluation_ids = tuple(item.id for item in evaluations)
    rows = tuple(
        ChatTrialSummaryRow(*row)
        for row in (
            await session.execute(
                select(
                    MatraixChatTrialRecord.evaluation_id,
                    MatraixChatTrialRecord.persona_position,
                    MatraixChatTrialRecord.persona_id,
                    MatraixChatTrialRecord.persona_external_id,
                    MatraixChatTrialRecord.persona_display_name,
                    MatraixChatTrialRecord.persona_profile_sha256,
                    MatraixChatTrialRecord.trial_sha256,
                    MatraixChatTrialRecord.status,
                )
                .where(MatraixChatTrialRecord.evaluation_id.in_(evaluation_ids))
                .order_by(
                    MatraixChatTrialRecord.evaluation_id,
                    MatraixChatTrialRecord.persona_position,
                )
            )
        ).tuples()
    )
    grouped: dict[UUID, list[ChatTrialSummaryRow]] = defaultdict(list)
    for row in rows:
        grouped[row.evaluation_id].append(row)
    return {evaluation.id: tuple(grouped[evaluation.id]) for evaluation in evaluations}


def _summary_without_artifacts(
    record: MatraixChatEvaluationRecord,
    rows: tuple[ChatTrialSummaryRow, ...],
    task: MatraixChatTask,
) -> MatraixChatEvaluationSummary:
    cohort = verify_chat_evaluation_record(record, task)
    if len(rows) != record.persona_count:
        raise RuntimeError(f"MatrAIx Chat evaluation {record.id} has incomplete trials")
    if tuple(row.persona_position for row in rows) != tuple(range(record.persona_count)):
        raise RuntimeError(f"MatrAIx Chat evaluation {record.id} trial positions are incomplete")
    if len({row.persona_id for row in rows}) != len(rows):
        raise RuntimeError(f"MatrAIx Chat evaluation {record.id} contains duplicate Personas")
    for row in rows:
        persona = ChatPersonaRef(
            id=row.persona_id,
            position=row.persona_position,
            persona_id=row.persona_external_id,
            display_name=row.persona_display_name,
            profile_sha256=row.persona_profile_sha256,
        )
        if calculate_trial_sha256(record.evaluation_sha256, persona) != row.trial_sha256:
            raise RuntimeError(f"MatrAIx Chat trial {row.trial_sha256} integrity mismatch")
    statuses = tuple(row.status for row in rows)
    return MatraixChatEvaluationSummary(
        id=record.id,
        status=_evaluation_status(statuses),
        created_at=record.created_at,
        task=task,
        cohort=cohort,
        trial_count=len(rows),
        succeeded_trial_count=sum(status == "succeeded" for status in statuses),
        failed_trial_count=sum(status == "failed" for status in statuses),
        model_name=record.model_name,
        chat_config_sha256=record.chat_config_sha256,
        prompt_schema_version=record.prompt_schema_version,
        evaluation_sha256=record.evaluation_sha256,
        retry_of_evaluation_id=record.retry_of_evaluation_id,
        retry_of_evaluation_sha256=record.retry_of_evaluation_sha256,
        attempt_number=record.attempt_number,
    )


async def _detail(
    session: AsyncSession,
    record: MatraixChatEvaluationRecord,
) -> MatraixChatEvaluationDetail:
    task = build_chat_task(record.task_id)
    trials = (await _load_trials(session, (record,)))[record.id]
    summary = _summary(record, trials, task)
    return MatraixChatEvaluationDetail(
        **summary.model_dump(mode="python"),
        trials=trials,
    )


async def _create_evaluation_attempt(
    session: AsyncSession,
    task: MatraixChatTask,
    cohort: ChatCohortRef,
    personas: tuple[ChatPersonaRef, ...],
    model_name: str,
    config_sha256: str,
    retry_of_evaluation_id: UUID | None,
    retry_of_evaluation_sha256: str | None,
    attempt_number: int,
) -> MatraixChatEvaluationRecord:
    evaluation_digest = calculate_evaluation_sha256(
        task.task_spec_sha256,
        task.sut_spec_sha256,
        cohort,
        model_name,
        config_sha256,
        retry_of_evaluation_sha256,
        attempt_number,
    )
    await _lock_evaluation_content(session, evaluation_digest)
    existing = await session.scalar(
        select(MatraixChatEvaluationRecord).where(
            MatraixChatEvaluationRecord.evaluation_sha256 == evaluation_digest
        )
    )
    if existing is not None:
        return existing
    created_at = datetime.now(UTC)
    evaluation = MatraixChatEvaluationRecord(
        id=uuid4(),
        cohort_id=cohort.id,
        cohort_sha256=cohort.cohort_sha256,
        cohort_title=cohort.title,
        dataset_sha256=cohort.dataset_sha256,
        persona_count=cohort.persona_count,
        task_id=task.task_id,
        task_version=task.version,
        task_schema_version=task.schema_version,
        task_spec_sha256=task.task_spec_sha256,
        sut_spec_sha256=task.sut_spec_sha256,
        model_name=model_name,
        chat_config_sha256=config_sha256,
        prompt_schema_version=PROMPT_SCHEMA_VERSION,
        evaluation_sha256=evaluation_digest,
        retry_of_evaluation_id=retry_of_evaluation_id,
        retry_of_evaluation_sha256=retry_of_evaluation_sha256,
        attempt_number=attempt_number,
        created_at=created_at,
        input_sealed_at=None,
    )
    trials = tuple(
        MatraixChatTrialRecord(
            id=uuid4(),
            evaluation_id=evaluation.id,
            persona_position=persona.position,
            persona_id=persona.id,
            persona_external_id=persona.persona_id,
            persona_display_name=persona.display_name,
            persona_profile_sha256=persona.profile_sha256,
            trial_sha256=calculate_trial_sha256(evaluation_digest, persona),
            status="queued",
            created_at=created_at,
            claimed_by_worker_id=None,
            started_at=None,
            completed_at=None,
            runner_version=None,
            model_name=None,
            chat_config_sha256=None,
            prompt_schema_version=None,
            transcript_sha256=None,
            feedback_sha256=None,
            result_sha256=None,
            outcome_status=None,
            next_step_owner=None,
            conversation_path=None,
            resolution_progression=None,
            message_count=None,
            customer_turn_count=None,
            support_turn_count=None,
            clarification_question_count=None,
            error_code=None,
            error_message=None,
        )
        for persona in personas
    )
    session.add(evaluation)
    await session.flush((evaluation,))
    session.add_all(trials)
    await session.flush(trials)
    evaluation.input_sealed_at = created_at
    await session.flush((evaluation,))
    return evaluation


async def ensure_chat_evaluation_record(
    session: AsyncSession,
    request: MatraixChatEvaluationCreateRequest,
) -> MatraixChatEvaluationRecord:
    """Validate and stage one content-addressed Chat evaluation without committing."""
    try:
        task = build_chat_task(request.task_id)
    except ValueError as error:
        raise MatraixChatSelectionError(str(error)) from error
    if request.task_version != task.version:
        raise MatraixChatSelectionError(
            f"unsupported MatrAIx Chat task {request.task_id}@{request.task_version}"
        )
    cohort_detail = await get_cohort(session, request.cohort_id)
    if cohort_detail.persona_count > 8:
        raise MatraixChatSelectionError(
            f"cohort contains {cohort_detail.persona_count} personas; Chat supports at most 8"
        )
    model_name, config_sha256 = await _live_chat_config(session)
    return await _create_evaluation_attempt(
        session,
        task,
        _cohort_ref(cohort_detail),
        tuple(_persona_ref(member) for member in cohort_detail.members),
        model_name,
        config_sha256,
        None,
        None,
        1,
    )


async def create_chat_evaluation(
    session: AsyncSession,
    request: MatraixChatEvaluationCreateRequest,
) -> MatraixChatEvaluationDetail:
    record = await ensure_chat_evaluation_record(session, request)
    detail = await _detail(session, record)
    await session.commit()
    return detail


async def retry_chat_evaluation(
    session: AsyncSession,
    evaluation_id: UUID,
) -> MatraixChatEvaluationDetail:
    parent = await session.get(MatraixChatEvaluationRecord, evaluation_id)
    if parent is None or parent.input_sealed_at is None:
        raise MatraixChatEvaluationNotFoundError(
            f"MatrAIx Chat evaluation {evaluation_id} was not found"
        )
    existing = await session.scalar(
        select(MatraixChatEvaluationRecord).where(
            MatraixChatEvaluationRecord.retry_of_evaluation_id == parent.id
        )
    )
    if existing is not None:
        return await _detail(session, existing)
    rows = (await _load_trial_summaries(session, (parent,)))[parent.id]
    statuses = tuple(row.status for row in rows)
    if any(status in ("queued", "running") for status in statuses) or not any(
        status == "failed" for status in statuses
    ):
        raise MatraixChatSelectionError(
            "only a terminal Chat evaluation containing at least one failed trial can be retried"
        )
    if parent.attempt_number >= 5:
        raise MatraixChatSelectionError("Chat evaluation retry limit of 5 attempts was reached")
    task = build_chat_task(parent.task_id)
    cohort_detail = await get_cohort(session, parent.cohort_id)
    cohort = _cohort_ref(cohort_detail)
    frozen_cohort = verify_chat_evaluation_record(parent, task)
    if cohort != frozen_cohort:
        raise RuntimeError(f"MatrAIx Chat evaluation {parent.id} Cohort integrity mismatch")
    model_name, config_sha256 = await _live_chat_config(session)
    record = await _create_evaluation_attempt(
        session,
        task,
        cohort,
        tuple(_persona_ref(member) for member in cohort_detail.members),
        model_name,
        config_sha256,
        parent.id,
        parent.evaluation_sha256,
        parent.attempt_number + 1,
    )
    detail = await _detail(session, record)
    await session.commit()
    return detail


async def list_chat_evaluations(session: AsyncSession) -> MatraixChatEvaluationsResponse:
    records = tuple(
        (
            await session.execute(
                select(MatraixChatEvaluationRecord)
                .where(MatraixChatEvaluationRecord.input_sealed_at.is_not(None))
                .order_by(
                    MatraixChatEvaluationRecord.created_at.desc(),
                    MatraixChatEvaluationRecord.id.asc(),
                )
            )
        )
        .scalars()
        .all()
    )
    trials = await _load_trial_summaries(session, records)
    items = tuple(
        _summary_without_artifacts(record, trials[record.id], build_chat_task(record.task_id))
        for record in records
    )
    return MatraixChatEvaluationsResponse(items=items, total=len(items))


async def get_chat_evaluation(
    session: AsyncSession,
    evaluation_id: UUID,
) -> MatraixChatEvaluationDetail:
    record = await session.scalar(
        select(MatraixChatEvaluationRecord).where(
            MatraixChatEvaluationRecord.id == evaluation_id,
            MatraixChatEvaluationRecord.input_sealed_at.is_not(None),
        )
    )
    if record is None:
        raise MatraixChatEvaluationNotFoundError(
            f"MatrAIx Chat evaluation {evaluation_id} was not found"
        )
    return await _detail(session, record)


async def get_chat_trial(session: AsyncSession, trial_id: UUID) -> MatraixChatTrial:
    trial_record = await session.scalar(
        select(MatraixChatTrialRecord).where(MatraixChatTrialRecord.id == trial_id)
    )
    if trial_record is None:
        raise MatraixChatTrialNotFoundError(f"MatrAIx Chat trial {trial_id} was not found")
    evaluation = await session.scalar(
        select(MatraixChatEvaluationRecord).where(
            MatraixChatEvaluationRecord.id == trial_record.evaluation_id,
            MatraixChatEvaluationRecord.input_sealed_at.is_not(None),
        )
    )
    if evaluation is None:
        raise RuntimeError(f"Chat trial {trial_id} references a missing sealed evaluation")
    verify_chat_evaluation_record(evaluation, build_chat_task(evaluation.task_id))
    messages = tuple(
        (
            await session.execute(
                select(MatraixChatMessageRecord)
                .where(MatraixChatMessageRecord.trial_id == trial_id)
                .order_by(MatraixChatMessageRecord.position)
            )
        )
        .scalars()
        .all()
    )
    feedback = await session.get(MatraixChatFeedbackRecord, trial_id)
    return _trial(trial_record, evaluation, messages, feedback)


async def get_chat_readiness(session: AsyncSession) -> MatraixChatReadiness:
    cutoff = datetime.now(UTC) - timedelta(seconds=WORKER_HEARTBEAT_MAX_AGE_SECONDS)
    heartbeats = tuple(
        (
            await session.execute(
                select(SimulationWorkerHeartbeatRecord).where(
                    SimulationWorkerHeartbeatRecord.last_seen_at >= cutoff,
                    SimulationWorkerHeartbeatRecord.engine == "camel-oasis",
                    SimulationWorkerHeartbeatRecord.engine_version == OASIS_ENGINE_VERSION,
                    SimulationWorkerHeartbeatRecord.camel_version == CAMEL_ENGINE_VERSION,
                    SimulationWorkerHeartbeatRecord.mode == "reddit_manual_smoke",
                )
            )
        )
        .scalars()
        .all()
    )
    configs = {
        (
            heartbeat.chat_model_name,
            heartbeat.chat_config_sha256,
            heartbeat.chat_prompt_schema_version,
            heartbeat.chat_sut_task_id,
            heartbeat.chat_sut_task_version,
            heartbeat.chat_sut_spec_sha256,
        )
        for heartbeat in heartbeats
        if heartbeat.platform_runtime_ready
        and heartbeat.semantic_runtime_ready
        and heartbeat.chat_runtime_ready
    }
    conflict = len(configs) > 1
    complete = next(iter(configs)) if len(configs) == 1 else None
    ready = bool(heartbeats) and complete is not None and not conflict
    if ready and complete is not None:
        model_name, config_sha256, prompt, task_id, version, sut_spec = complete
        if (
            model_name is None
            or config_sha256 is None
            or prompt != PROMPT_SCHEMA_VERSION
            or task_id != CHAT_SUITE_ID
            or version != CHAT_SUITE_VERSION
            or sut_spec != CHAT_SUITE_SHA256
        ):
            raise RuntimeError("chat-ready worker persisted an incomplete task configuration")
    else:
        model_name = None
        config_sha256 = None
        prompt = None
    limitations = READINESS_LIMITATIONS
    if conflict:
        limitations += (
            "Live Chat workers disagree on model, runtime configuration, or SUT identity; "
            "enqueueing is blocked.",
        )
    elif not ready:
        limitations += (
            "No live worker currently exposes a complete probed Chat execution configuration.",
        )
    return MatraixChatReadiness(
        engine="matraix-chat",
        runner_version=RUNNER_VERSION,
        worker_online=bool(heartbeats),
        live_worker_count=len(heartbeats),
        chat_runtime_ready=ready,
        configuration_conflict=conflict,
        model_name=model_name,
        chat_config_sha256=config_sha256,
        prompt_schema_version=prompt,
        tasks=build_chat_tasks(),
        limitations=limitations,
    )


__all__ = [
    "create_chat_evaluation",
    "ensure_chat_evaluation_record",
    "get_chat_evaluation",
    "get_chat_readiness",
    "get_chat_trial",
    "list_chat_evaluations",
    "list_chat_tasks",
    "verify_chat_evaluation_record",
]
