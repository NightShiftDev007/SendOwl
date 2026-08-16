"""Strict public contracts for durable MatrAIx chatbot evaluations."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
    model_validator,
)

from app.shared.contracts import ContractModel, Identifier, NonEmptyText, Sha256Digest

type ChatStatus = Literal["queued", "running", "succeeded", "failed"]
type ChatTaskId = Literal["matraix/acme-support-order-4521", "matraix/acme-support-mcp-order-4521"]
type ChatTaskVersion = Literal["1.0.0"]
type ChatTaskSchemaVersion = Literal["matraix-chat-task/acme-support-v1"]
type ChatFeedbackSchemaVersion = Literal["matraix-chat-feedback/acme-support-v1"]
type ChatPromptSchemaVersion = Literal["matraix-chat-acme-support/v1"]
type ChatRunnerVersion = Literal["1.0.0"]
type Satisfaction = Literal["yes", "partially", "no"]
type ChatModelName = Annotated[
    str,
    StringConstraints(min_length=1, max_length=200, pattern=r"^[^\r\n]+$", strip_whitespace=True),
]
type ChatText = Annotated[
    str,
    StringConstraints(min_length=1, max_length=8000, strip_whitespace=True),
]
type FeedbackText = Annotated[
    str,
    StringConstraints(min_length=1, max_length=2000, strip_whitespace=True),
]
type TaskText = Annotated[
    str,
    StringConstraints(min_length=1, max_length=4000, strip_whitespace=True),
]
type LimitationText = Annotated[
    str,
    StringConstraints(min_length=1, max_length=2000, strip_whitespace=True),
]


def _request_uuid(value: object, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a UUID string; received {type(value).__name__}")
    try:
        return UUID(value)
    except ValueError as error:
        raise ValueError(f"{field_name} must be a valid UUID string; received {value!r}") from error


class MatraixChatTaskSource(ContractModel):
    kind: Literal["source_sample"]
    project: Literal["MatrAIx"]
    canonical_path: Literal[
        "application/tasks/example-chat-api_support_chatbot",
        "application/tasks/example-chat-mcp_support_chatbot",
    ]
    production_sut: Literal[False]


class MatraixChatTask(ContractModel):
    task_id: ChatTaskId
    version: ChatTaskVersion
    schema_version: ChatTaskSchemaVersion
    title: Literal["Acme support: late order #4521"]
    domain: Literal["commerce-retail"]
    source: MatraixChatTaskSource
    application_id: Literal["acme_support_api", "acme_support_mcp"]
    application_context: Literal["customer_support"]
    transport: Literal["sidecar_http", "mcp_streamable_http"]
    capabilities: tuple[Literal["text_chat", "mcp_tool"], ...]
    instruction: TaskText
    context: TaskText
    minimum_customer_turns: Literal[2]
    minimum_total_messages: Literal[4]
    feedback_schema_version: ChatFeedbackSchemaVersion
    task_spec_sha256: Sha256Digest
    sut_spec_sha256: Sha256Digest
    limitations: Annotated[tuple[LimitationText, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_capabilities(self) -> Self:
        is_mcp = self.task_id == "matraix/acme-support-mcp-order-4521"
        expected_path = (
            "application/tasks/example-chat-mcp_support_chatbot"
            if is_mcp
            else "application/tasks/example-chat-api_support_chatbot"
        )
        expected_application = "acme_support_mcp" if is_mcp else "acme_support_api"
        expected_transport = "mcp_streamable_http" if is_mcp else "sidecar_http"
        expected_capabilities = ("text_chat", "mcp_tool") if is_mcp else ("text_chat",)
        if (
            self.source.canonical_path != expected_path
            or self.application_id != expected_application
            or self.transport != expected_transport
            or self.capabilities != expected_capabilities
        ):
            raise ValueError("Acme source-sample task fields do not match its fixed transport")
        return self


class MatraixChatTasksResponse(ContractModel):
    items: tuple[MatraixChatTask, ...]
    total: Annotated[int, Field(ge=0)]


class MatraixChatEvaluationCreateRequest(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    cohort_id: UUID
    task_id: ChatTaskId
    task_version: ChatTaskVersion

    @field_validator("cohort_id", mode="before")
    @classmethod
    def parse_resource_id(cls, value: object, info: ValidationInfo) -> UUID:
        return _request_uuid(value, info.field_name)


class ChatCohortRef(ContractModel):
    id: UUID
    title: Annotated[
        str,
        StringConstraints(min_length=1, max_length=200, pattern=r"^[^\r\n]+$"),
    ]
    cohort_sha256: Sha256Digest
    dataset_sha256: Sha256Digest
    persona_count: Annotated[int, Field(ge=1, le=8)]


class ChatPersonaRef(ContractModel):
    id: UUID
    position: Annotated[int, Field(ge=0, le=7)]
    persona_id: Identifier
    display_name: Annotated[
        str,
        StringConstraints(min_length=1, max_length=200, pattern=r"^[^\r\n]+$"),
    ]
    profile_sha256: Sha256Digest


class ChatTranscriptMessage(ContractModel):
    position: Annotated[int, Field(ge=0, le=39)]
    role: Literal["customer", "support"]
    content: ChatText
    recorded_at: AwareDatetime


class ChatTranscriptDeltaItem(ContractModel):
    event_sequence: Annotated[
        str,
        StringConstraints(pattern=r"^[1-9][0-9]{0,18}$"),
    ]
    trial_id: UUID
    message: ChatTranscriptMessage


class MatraixChatTranscriptDelta(ContractModel):
    evaluation_id: UUID
    after_event_sequence: Annotated[
        str,
        StringConstraints(pattern=r"^(0|[1-9][0-9]{0,18})$"),
    ]
    next_event_sequence: Annotated[
        str,
        StringConstraints(pattern=r"^(0|[1-9][0-9]{0,18})$"),
    ]
    items: Annotated[tuple[ChatTranscriptDeltaItem, ...], Field(max_length=320)]
    observed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_cursor(self) -> Self:
        after = int(self.after_event_sequence)
        sequences = tuple(int(item.event_sequence) for item in self.items)
        if sequences != tuple(sorted(sequences)) or len(set(sequences)) != len(sequences):
            raise ValueError("chat delta event sequences must be strictly increasing")
        if sequences and sequences[0] <= after:
            raise ValueError("chat delta items must follow after_event_sequence")
        expected_next = sequences[-1] if sequences else after
        if int(self.next_event_sequence) != expected_next:
            raise ValueError("next_event_sequence must equal the last observed event")
        return self


class ChatTrialFeedback(ContractModel):
    schema_version: ChatFeedbackSchemaVersion
    need_constraint_satisfaction: Satisfaction
    personal_preference_satisfaction: Satisfaction
    overall_experience_rating: Annotated[int, Field(ge=1, le=10)]
    reason: FeedbackText
    asked_useful_clarification_questions: bool
    clarifying_notes: FeedbackText


class ChatTrialResult(ContractModel):
    runner_version: ChatRunnerVersion
    model_name: ChatModelName
    chat_config_sha256: Sha256Digest
    prompt_schema_version: ChatPromptSchemaVersion
    transcript_sha256: Sha256Digest
    feedback_sha256: Sha256Digest
    result_sha256: Sha256Digest
    outcome_status: Literal["resolved", "partially_resolved", "unresolved"]
    next_step_owner: Literal["user", "support", "none"]
    conversation_path: Literal["clarify_then_resolve", "clarify_then_partial", "stalled"]
    resolution_progression: Literal["single_response", "looped", "advanced"]
    message_count: Annotated[int, Field(ge=4, le=40)]
    customer_turn_count: Annotated[int, Field(ge=2, le=20)]
    support_turn_count: Annotated[int, Field(ge=2, le=20)]
    clarification_question_count: Annotated[int, Field(ge=0, le=20)]

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        if self.message_count != self.customer_turn_count + self.support_turn_count:
            raise ValueError("message_count must equal customer plus support turns")
        if self.customer_turn_count != self.support_turn_count:
            raise ValueError("successful chat must contain complete customer/support exchanges")
        return self


class ChatTrialError(ContractModel):
    code: Identifier
    message: Annotated[str, StringConstraints(min_length=1, max_length=4000)]


class MatraixChatTrial(ContractModel):
    id: UUID
    status: ChatStatus
    persona: ChatPersonaRef
    trial_sha256: Sha256Digest
    created_at: AwareDatetime
    started_at: AwareDatetime | None
    completed_at: AwareDatetime | None
    transcript: Annotated[tuple[ChatTranscriptMessage, ...], Field(max_length=40)]
    feedback: ChatTrialFeedback | None
    result: ChatTrialResult | None
    error: ChatTrialError | None

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        positions = tuple(message.position for message in self.transcript)
        if positions != tuple(range(len(self.transcript))):
            raise ValueError("chat transcript positions must be contiguous and start at zero")
        if any(
            message.role != ("customer" if index % 2 == 0 else "support")
            for index, message in enumerate(self.transcript)
        ):
            raise ValueError("chat transcript must alternate customer then support")
        if self.status == "queued":
            valid = self.started_at is None and self.completed_at is None and not self.transcript
            valid = valid and self.feedback is None and self.result is None and self.error is None
        elif self.status == "running":
            valid = self.started_at is not None and self.completed_at is None
            valid = valid and self.feedback is None and self.result is None and self.error is None
        elif self.status == "succeeded":
            valid = self.started_at is not None and self.completed_at is not None
            valid = valid and len(self.transcript) >= 4 and len(self.transcript) % 2 == 0
            valid = valid and self.feedback is not None and self.result is not None
            valid = valid and self.error is None
            if self.result is not None:
                valid = valid and self.result.message_count == len(self.transcript)
        else:
            valid = self.started_at is not None and self.completed_at is not None
            valid = valid and self.feedback is None and self.result is None
            valid = valid and self.error is not None
        if not valid:
            raise ValueError(f"chat trial fields do not match status {self.status}")
        return self


class MatraixChatEvaluationSummary(ContractModel):
    id: UUID
    status: ChatStatus
    created_at: AwareDatetime
    task: MatraixChatTask
    cohort: ChatCohortRef
    trial_count: Annotated[int, Field(ge=1, le=8)]
    succeeded_trial_count: Annotated[int, Field(ge=0, le=8)]
    failed_trial_count: Annotated[int, Field(ge=0, le=8)]
    model_name: ChatModelName
    chat_config_sha256: Sha256Digest
    prompt_schema_version: ChatPromptSchemaVersion
    evaluation_sha256: Sha256Digest
    retry_of_evaluation_id: UUID | None
    retry_of_evaluation_sha256: Sha256Digest | None
    attempt_number: Annotated[int, Field(ge=1, le=5)]

    @model_validator(mode="after")
    def validate_attempt_lineage(self) -> Self:
        is_root = self.attempt_number == 1
        has_parent = (
            self.retry_of_evaluation_id is not None and self.retry_of_evaluation_sha256 is not None
        )
        if is_root == has_parent:
            raise ValueError("root attempts have no retry parent; later attempts require one")
        return self


class MatraixChatEvaluationDetail(MatraixChatEvaluationSummary):
    trials: Annotated[tuple[MatraixChatTrial, ...], Field(min_length=1, max_length=8)]

    @model_validator(mode="after")
    def validate_trials(self) -> Self:
        if len(self.trials) != self.trial_count:
            raise ValueError("trial_count must equal trials length")
        if tuple(item.persona.position for item in self.trials) != tuple(range(len(self.trials))):
            raise ValueError("chat trials must follow contiguous cohort positions")
        succeeded = sum(item.status == "succeeded" for item in self.trials)
        failed = sum(item.status == "failed" for item in self.trials)
        if succeeded != self.succeeded_trial_count or failed != self.failed_trial_count:
            raise ValueError("summary terminal counts must match trial statuses")
        return self


class MatraixChatEvaluationsResponse(ContractModel):
    items: Annotated[tuple[MatraixChatEvaluationSummary, ...], Field(max_length=50)]
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=50)]
    total: Annotated[int, Field(ge=0)]


class MatraixChatReadiness(ContractModel):
    engine: Literal["matraix-chat"]
    runner_version: ChatRunnerVersion
    worker_online: bool
    live_worker_count: Annotated[int, Field(ge=0)]
    chat_runtime_ready: bool
    configuration_conflict: bool
    model_name: ChatModelName | None
    chat_config_sha256: Sha256Digest | None
    prompt_schema_version: ChatPromptSchemaVersion | None
    tasks: Annotated[tuple[MatraixChatTask, ...], Field(min_length=2, max_length=2)]
    limitations: Annotated[tuple[NonEmptyText, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_readiness(self) -> Self:
        if self.worker_online != (self.live_worker_count > 0):
            raise ValueError("worker_online must equal live_worker_count > 0")
        fields = (self.model_name, self.chat_config_sha256, self.prompt_schema_version)
        has_config = all(value is not None for value in fields)
        if any(value is not None for value in fields) != has_config:
            raise ValueError("chat config fields must be all present or all absent")
        expected = self.worker_online and not self.configuration_conflict and has_config
        if self.chat_runtime_ready != expected:
            raise ValueError("chat_runtime_ready requires one non-conflicting live config")
        if not self.chat_runtime_ready and has_config:
            raise ValueError("unready chat projection must not expose a selected config")
        return self
