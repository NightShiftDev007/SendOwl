"""Strict public contracts for the unified MatrAIx trial archive."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from app.shared.contracts import ContractModel, Identifier, Sha256Digest

type MatraixTrialKind = Literal["survey", "chat", "web", "linux"]
type MatraixTrialStatus = Literal["queued", "running", "succeeded", "failed"]
type MatraixIntegrityCheckStatus = Literal["passed", "not_applicable"]
type FrozenTaskTitle = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=300,
        pattern=r"^[^\r\n]+$",
        strip_whitespace=True,
    ),
]
type FrozenPersonaName = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=200,
        pattern=r"^[^\r\n]+$",
        strip_whitespace=True,
    ),
]
type FrozenModelName = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=200,
        pattern=r"^[^\r\n]+$",
        strip_whitespace=True,
    ),
]
type ArchiveErrorMessage = Annotated[
    str,
    StringConstraints(min_length=1, max_length=4000, strip_whitespace=True),
]
type SourceDetailPath = Annotated[
    str,
    StringConstraints(min_length=1, max_length=128, pattern=r"^/api/v2/[A-Za-z0-9/_-]+$"),
]


class MatraixTrialArchivePersona(ContractModel):
    """Frozen Persona identity shared by all source trial types."""

    id: UUID
    position: Annotated[int, Field(ge=0, le=99)]
    persona_id: Identifier
    display_name: FrozenPersonaName
    profile_sha256: Sha256Digest


class MatraixTrialArchiveError(ContractModel):
    """Explicit terminal failure copied from the durable source trial."""

    code: Identifier
    message: ArchiveErrorMessage


class SurveyTrialArchiveTask(ContractModel):
    title: FrozenTaskTitle
    version: Literal["scenario-preference/v1", "single-context-observation/v1"]


class ChatTrialArchiveTask(ContractModel):
    title: Literal["Acme support: late order #4521"]
    version: Literal["1.0.0"]


class WebTrialArchiveTask(ContractModel):
    title: Literal["Quote to save"]
    version: Literal["1.0.0"]


class LinuxTrialArchiveTask(ContractModel):
    title: Literal["Note to CSV cleanup"]
    version: Literal["1.0.0"]


class SurveyTrialArchiveProvenance(ContractModel):
    runner_version: Literal["1.0.0"] | None
    model_name: FrozenModelName
    parent_config_sha256: Sha256Digest
    prompt_schema_version: Literal[
        "matraix-survey-scenario-preference/v1", "sandowl-research-survey/v1"
    ]
    answers_sha256: Sha256Digest | None


class ChatTrialArchiveProvenance(ContractModel):
    runner_version: Literal["1.0.0"] | None
    model_name: FrozenModelName
    parent_config_sha256: Sha256Digest
    prompt_schema_version: Literal["matraix-chat-acme-support/v1"]
    transcript_sha256: Sha256Digest | None
    feedback_sha256: Sha256Digest | None
    result_sha256: Sha256Digest | None


class WebTrialArchiveProvenance(ContractModel):
    runner_version: Literal["1.0.0"] | None
    model_name: FrozenModelName
    parent_config_sha256: Sha256Digest
    prompt_schema_version: Literal["matraix-web-quotes-choice/v1"]
    trace_sha256: Sha256Digest | None
    result_sha256: Sha256Digest | None


class LinuxTrialArchiveProvenance(ContractModel):
    runner_version: Literal["1.0.0"] | None
    model_name: FrozenModelName
    parent_config_sha256: Sha256Digest
    prompt_schema_version: Literal["matraix-linux-note-to-csv/v1"]
    artifact_sha256: Sha256Digest | None
    result_sha256: Sha256Digest | None


def _validate_trial_state(
    status: MatraixTrialStatus,
    created_at: AwareDatetime,
    started_at: AwareDatetime | None,
    completed_at: AwareDatetime | None,
    error: MatraixTrialArchiveError | None,
    runner_version: str | None,
    output_hashes: tuple[str | None, ...],
) -> None:
    if started_at is not None and started_at < created_at:
        raise ValueError("started_at must not precede created_at")
    if completed_at is not None and (started_at is None or completed_at < started_at):
        raise ValueError("completed_at requires and must not precede started_at")
    no_output = runner_version is None and all(value is None for value in output_hashes)
    complete_output = runner_version == "1.0.0" and all(
        value is not None for value in output_hashes
    )
    if status == "queued":
        valid = started_at is None and completed_at is None and error is None and no_output
    elif status == "running":
        valid = started_at is not None and completed_at is None and error is None and no_output
    elif status == "succeeded":
        valid = started_at is not None and completed_at is not None
        valid = valid and error is None and complete_output
    else:
        valid = started_at is not None and completed_at is not None
        valid = valid and error is not None and no_output
    if not valid:
        raise ValueError(f"archive trial fields do not match status {status}")


class SurveyTrialArchiveItem(ContractModel):
    kind: Literal["survey"]
    id: UUID
    status: MatraixTrialStatus
    parent_id: UUID
    parent_sha256: Sha256Digest
    trial_sha256: Sha256Digest
    task: SurveyTrialArchiveTask
    persona: MatraixTrialArchivePersona
    created_at: AwareDatetime
    started_at: AwareDatetime | None
    completed_at: AwareDatetime | None
    error: MatraixTrialArchiveError | None
    provenance: SurveyTrialArchiveProvenance
    source_detail_path: SourceDetailPath

    @model_validator(mode="after")
    def validate_archive_item(self) -> Self:
        _validate_trial_state(
            self.status,
            self.created_at,
            self.started_at,
            self.completed_at,
            self.error,
            self.provenance.runner_version,
            (self.provenance.answers_sha256,),
        )
        expected_path = (
            f"/api/v2/research-surveys/{self.parent_id}"
            if self.task.version == "single-context-observation/v1"
            else f"/api/v2/matraix/survey-trials/{self.id}"
        )
        if self.source_detail_path != expected_path:
            raise ValueError("survey source_detail_path must address the source trial")
        return self


class ChatTrialArchiveItem(ContractModel):
    kind: Literal["chat"]
    id: UUID
    status: MatraixTrialStatus
    parent_id: UUID
    parent_sha256: Sha256Digest
    trial_sha256: Sha256Digest
    task: ChatTrialArchiveTask
    persona: MatraixTrialArchivePersona
    created_at: AwareDatetime
    started_at: AwareDatetime | None
    completed_at: AwareDatetime | None
    error: MatraixTrialArchiveError | None
    provenance: ChatTrialArchiveProvenance
    source_detail_path: SourceDetailPath

    @model_validator(mode="after")
    def validate_archive_item(self) -> Self:
        _validate_trial_state(
            self.status,
            self.created_at,
            self.started_at,
            self.completed_at,
            self.error,
            self.provenance.runner_version,
            (
                self.provenance.transcript_sha256,
                self.provenance.feedback_sha256,
                self.provenance.result_sha256,
            ),
        )
        expected_path = f"/api/v2/matraix/chat-trials/{self.id}"
        if self.source_detail_path != expected_path:
            raise ValueError("chat source_detail_path must address the source trial")
        return self


class WebTrialArchiveItem(ContractModel):
    kind: Literal["web"]
    id: UUID
    status: MatraixTrialStatus
    parent_id: UUID
    parent_sha256: Sha256Digest
    trial_sha256: Sha256Digest
    task: WebTrialArchiveTask
    persona: MatraixTrialArchivePersona
    created_at: AwareDatetime
    started_at: AwareDatetime | None
    completed_at: AwareDatetime | None
    error: MatraixTrialArchiveError | None
    provenance: WebTrialArchiveProvenance
    source_detail_path: SourceDetailPath

    @model_validator(mode="after")
    def validate_archive_item(self) -> Self:
        _validate_trial_state(
            self.status,
            self.created_at,
            self.started_at,
            self.completed_at,
            self.error,
            self.provenance.runner_version,
            (self.provenance.trace_sha256, self.provenance.result_sha256),
        )
        expected_path = f"/api/v2/matraix/web-trials/{self.id}"
        if self.source_detail_path != expected_path:
            raise ValueError("web source_detail_path must address the source trial")
        return self


class LinuxTrialArchiveItem(ContractModel):
    kind: Literal["linux"]
    id: UUID
    status: MatraixTrialStatus
    parent_id: UUID
    parent_sha256: Sha256Digest
    trial_sha256: Sha256Digest
    task: LinuxTrialArchiveTask
    persona: MatraixTrialArchivePersona
    created_at: AwareDatetime
    started_at: AwareDatetime | None
    completed_at: AwareDatetime | None
    error: MatraixTrialArchiveError | None
    provenance: LinuxTrialArchiveProvenance
    source_detail_path: SourceDetailPath

    @model_validator(mode="after")
    def validate_archive_item(self) -> Self:
        _validate_trial_state(
            self.status,
            self.created_at,
            self.started_at,
            self.completed_at,
            self.error,
            self.provenance.runner_version,
            (self.provenance.artifact_sha256, self.provenance.result_sha256),
        )
        expected_path = f"/api/v2/matraix/linux-trials/{self.id}"
        if self.source_detail_path != expected_path:
            raise ValueError("linux source_detail_path must address the source trial")
        return self


type MatraixTrialArchiveItem = Annotated[
    SurveyTrialArchiveItem | ChatTrialArchiveItem | WebTrialArchiveItem | LinuxTrialArchiveItem,
    Field(discriminator="kind"),
]


def _validate_archive_order(items: tuple[MatraixTrialArchiveItem, ...]) -> None:
    for previous, current in zip(items, items[1:], strict=False):
        previous_key = (previous.created_at, previous.kind, previous.id)
        current_key = (current.created_at, current.kind, current.id)
        if previous.created_at < current.created_at:
            raise ValueError("archive items must be ordered by created_at descending")
        if previous.created_at == current.created_at and previous_key[1:] > current_key[1:]:
            raise ValueError("archive item tie-break ordering is invalid")


class MatraixTrialArchiveResponse(ContractModel):
    items: tuple[MatraixTrialArchiveItem, ...]
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=100)]
    total: Annotated[int, Field(ge=0)]
    statistics: "MatraixTrialArchiveStatistics"

    @model_validator(mode="after")
    def validate_page(self) -> Self:
        if len(self.items) > self.page_size:
            raise ValueError("archive items must not exceed page_size")
        if self.total < len(self.items):
            raise ValueError("archive total must not be smaller than the returned page")
        minimum_total = (self.page - 1) * self.page_size + len(self.items)
        if self.total < minimum_total:
            raise ValueError("archive total is inconsistent with the requested page")
        if self.statistics.total != self.total:
            raise ValueError("archive statistics total must equal the filtered total")
        _validate_archive_order(self.items)
        return self


class MatraixTrialArchiveKindCounts(ContractModel):
    survey: Annotated[int, Field(ge=0)]
    chat: Annotated[int, Field(ge=0)]
    web: Annotated[int, Field(ge=0)]
    linux: Annotated[int, Field(ge=0)]


class MatraixTrialArchiveStatusCounts(ContractModel):
    queued: Annotated[int, Field(ge=0)]
    running: Annotated[int, Field(ge=0)]
    succeeded: Annotated[int, Field(ge=0)]
    failed: Annotated[int, Field(ge=0)]


class MatraixTrialArchiveStatistics(ContractModel):
    total: Annotated[int, Field(ge=0)]
    by_kind: MatraixTrialArchiveKindCounts
    by_status: MatraixTrialArchiveStatusCounts

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        if (
            self.by_kind.survey + self.by_kind.chat + self.by_kind.web + self.by_kind.linux
            != self.total
        ):
            raise ValueError("archive kind counts must equal total")
        status_total = (
            self.by_status.queued
            + self.by_status.running
            + self.by_status.succeeded
            + self.by_status.failed
        )
        if status_total != self.total:
            raise ValueError("archive status counts must equal total")
        return self


class MatraixTrialIntegrityCheck(ContractModel):
    """One deterministic integrity assertion over a durable Trial record."""

    name: Identifier
    status: MatraixIntegrityCheckStatus
    content_sha256: Sha256Digest | None

    @model_validator(mode="after")
    def validate_digest(self) -> Self:
        if self.status == "not_applicable" and self.content_sha256 is not None:
            raise ValueError("not-applicable integrity checks cannot expose a content digest")
        return self


class MatraixTrialIntegrityVerification(ContractModel):
    """Server-side recomputation proof, never a benchmark reward or task score."""

    kind: MatraixTrialKind
    trial_id: UUID
    status: MatraixTrialStatus
    verification: Literal["verified"]
    verified_at: AwareDatetime
    checks: Annotated[tuple[MatraixTrialIntegrityCheck, ...], Field(min_length=4, max_length=6)]
    limitations: Annotated[tuple[FrozenTaskTitle, ...], Field(min_length=2, max_length=3)]

    @model_validator(mode="after")
    def validate_checks(self) -> Self:
        names = tuple(check.name for check in self.checks)
        expected_by_kind = {
            "survey": ("sealed_parent", "trial_address", "state_shape", "survey_answers"),
            "chat": (
                "sealed_parent",
                "trial_address",
                "state_shape",
                "chat_transcript",
                "chat_feedback",
                "chat_result",
            ),
            "web": (
                "sealed_parent",
                "trial_address",
                "state_shape",
                "web_trace",
                "web_result",
            ),
            "linux": (
                "sealed_parent",
                "trial_address",
                "state_shape",
                "linux_artifact",
                "linux_result",
            ),
        }
        expected = expected_by_kind[self.kind]
        if names != expected:
            raise ValueError("integrity checks must use the fixed kind-specific order")
        return self


__all__ = [
    "ChatTrialArchiveItem",
    "ChatTrialArchiveProvenance",
    "MatraixTrialArchiveError",
    "MatraixTrialArchiveItem",
    "MatraixTrialArchiveKindCounts",
    "MatraixTrialArchivePersona",
    "MatraixTrialArchiveResponse",
    "MatraixTrialArchiveStatistics",
    "MatraixTrialArchiveStatusCounts",
    "MatraixTrialIntegrityCheck",
    "MatraixTrialIntegrityVerification",
    "MatraixTrialKind",
    "MatraixTrialStatus",
    "LinuxTrialArchiveItem",
    "LinuxTrialArchiveProvenance",
    "SurveyTrialArchiveItem",
    "SurveyTrialArchiveProvenance",
    "WebTrialArchiveItem",
    "WebTrialArchiveProvenance",
]
