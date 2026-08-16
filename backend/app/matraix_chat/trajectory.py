"""ATIF-v1.7 projection for recorded MatrAIx Chat transcripts."""

import hashlib
import json
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from app.matraix_chat.contracts import MatraixChatTrial
from app.matraix_chat.hashing import calculate_transcript_sha256
from app.shared.contracts import ContractModel, NonEmptyText, Sha256Digest

PROJECTION_SCHEMA_VERSION = "sendowl-chat-atif-projection/v1"
ATIF_SCHEMA_VERSION = "ATIF-v1.7"
ATIF_AGENT_NAME = "Acme support source sample"
ATIF_AGENT_VERSION = "1.0.0"
ATIF_NOTES = (
    "Derived from SendOwl's recorded Chat transcript. User steps are synthetic Persona "
    "messages; agent steps are deterministic Acme source-sample responses."
)
ATIF_LIMITATIONS = (
    "This ATIF-v1.7 trajectory is derived from SendOwl's recorded Chat transcript, not "
    "imported Harbor telemetry.",
    "User steps are synthetic Persona messages; agent steps are deterministic Acme "
    "source-sample responses.",
    "Reasoning, tool calls, observations, token metrics, rewards, screenshots, and "
    "recordings were not captured and are not inferred.",
)


class AtifAgent(ContractModel):
    """Observed evaluated application identity."""

    name: Literal["Acme support source sample"]
    version: Literal["1.0.0"]


class AtifUserStep(ContractModel):
    """One recorded synthetic Persona message."""

    step_id: Annotated[int, Field(ge=1, le=40)]
    timestamp: AwareDatetime
    source: Literal["user"]
    message: NonEmptyText


class AtifAgentStep(ContractModel):
    """One recorded deterministic support application response."""

    step_id: Annotated[int, Field(ge=1, le=40)]
    timestamp: AwareDatetime
    source: Literal["agent"]
    message: NonEmptyText
    llm_call_count: Literal[0]


type AtifStep = Annotated[AtifUserStep | AtifAgentStep, Field(discriminator="source")]


class AtifFinalMetrics(ContractModel):
    """Only the aggregate that is directly observable from the transcript."""

    total_steps: Annotated[int, Field(ge=1, le=40)]


class AtifTrajectory(ContractModel):
    """A strict ATIF-v1.7 subset with unsupported optional fields omitted."""

    schema_version: Literal["ATIF-v1.7"]
    session_id: NonEmptyText
    trajectory_id: NonEmptyText
    agent: AtifAgent
    steps: Annotated[tuple[AtifStep, ...], Field(min_length=1, max_length=40)]
    notes: NonEmptyText
    final_metrics: AtifFinalMetrics

    @model_validator(mode="after")
    def validate_steps(self) -> Self:
        if tuple(step.step_id for step in self.steps) != tuple(range(1, len(self.steps) + 1)):
            raise ValueError("ATIF step IDs must be contiguous and start at one")
        if any(
            step.source != ("user" if index % 2 == 0 else "agent")
            for index, step in enumerate(self.steps)
        ):
            raise ValueError("ATIF Chat steps must alternate user then agent")
        if self.final_metrics.total_steps != len(self.steps):
            raise ValueError("ATIF total_steps must equal the observed step count")
        return self


class MatraixChatAtifProjection(ContractModel):
    """Content-addressed projection plus explicit provenance limitations."""

    projection_schema_version: Literal["sendowl-chat-atif-projection/v1"]
    projection_sha256: Sha256Digest
    completeness: Literal["complete", "partial"]
    source_trial_sha256: Sha256Digest
    source_transcript_sha256: Sha256Digest
    limitations: Annotated[tuple[NonEmptyText, ...], Field(min_length=3, max_length=3)]
    trajectory: AtifTrajectory


class MatraixChatTrajectoryUnavailableError(RuntimeError):
    """A trial has not recorded any transcript step yet."""


def _step(
    position: int,
    role: Literal["customer", "support"],
    content: str,
    recorded_at: AwareDatetime,
) -> AtifStep:
    if role == "customer":
        return AtifUserStep(
            step_id=position + 1,
            timestamp=recorded_at,
            source="user",
            message=content,
        )
    return AtifAgentStep(
        step_id=position + 1,
        timestamp=recorded_at,
        source="agent",
        message=content,
        llm_call_count=0,
    )


def _projection_sha256(
    trial: MatraixChatTrial,
    transcript_sha256: str,
    completeness: Literal["complete", "partial"],
    steps: tuple[AtifStep, ...],
) -> str:
    material = {
        "agent": {"name": ATIF_AGENT_NAME, "version": ATIF_AGENT_VERSION},
        "completeness": completeness,
        "final_metrics": {"total_steps": len(steps)},
        "limitations": ATIF_LIMITATIONS,
        "notes": ATIF_NOTES,
        "projection_schema_version": PROJECTION_SCHEMA_VERSION,
        "schema_version": ATIF_SCHEMA_VERSION,
        "session_id": str(trial.id),
        "source_transcript_sha256": transcript_sha256,
        "source_trial_sha256": trial.trial_sha256,
        "steps": tuple(step.model_dump(mode="json") for step in steps),
    }
    canonical = json.dumps(
        material,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def project_chat_trial_atif(trial: MatraixChatTrial) -> MatraixChatAtifProjection:
    """Project one integrity-checked Chat transcript without inventing telemetry."""
    if not trial.transcript:
        raise MatraixChatTrajectoryUnavailableError(
            f"MatrAIx Chat trial {trial.id} has not recorded a transcript"
        )
    steps = tuple(
        _step(message.position, message.role, message.content, message.recorded_at)
        for message in trial.transcript
    )
    transcript_sha256 = calculate_transcript_sha256(trial.trial_sha256, trial.transcript)
    completeness: Literal["complete", "partial"] = (
        "complete" if trial.status == "succeeded" else "partial"
    )
    projection_sha256 = _projection_sha256(
        trial,
        transcript_sha256,
        completeness,
        steps,
    )
    return MatraixChatAtifProjection(
        projection_schema_version=PROJECTION_SCHEMA_VERSION,
        projection_sha256=projection_sha256,
        completeness=completeness,
        source_trial_sha256=trial.trial_sha256,
        source_transcript_sha256=transcript_sha256,
        limitations=ATIF_LIMITATIONS,
        trajectory=AtifTrajectory(
            schema_version=ATIF_SCHEMA_VERSION,
            session_id=str(trial.id),
            trajectory_id=f"urn:sha256:{projection_sha256}",
            agent=AtifAgent(name=ATIF_AGENT_NAME, version=ATIF_AGENT_VERSION),
            steps=steps,
            notes=ATIF_NOTES,
            final_metrics=AtifFinalMetrics(total_steps=len(steps)),
        ),
    )
