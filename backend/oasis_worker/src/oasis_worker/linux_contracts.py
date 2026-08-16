"""Strict worker contracts for the fixed MatrAIx Linux artifact task."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from oasis_worker.contracts import RequiredText, Sha256, StrictModel
from oasis_worker.semantic_contracts import SemanticPersona

LINUX_TASK_ID = "matraix/linux-note-to-csv"
LINUX_TASK_VERSION = "1.0.0"
LINUX_TASK_SCHEMA_VERSION = "matraix-linux-task/note-to-csv-v1"
LINUX_TASK_SPEC_SHA256 = "0a4bf540dec44e3ea488a2884eb1b4d3233470616e87c9ff370847b0509155a9"
LINUX_RUNNER_SCHEMA_VERSION = "matraix-linux-artifact-runner/v1"
LINUX_RUNNER_SPEC_SHA256 = "ec2a5c1dd6ae8daa9163f3d5749654ef8fcb53f750bcf6614f9a9883f0e01354"
LINUX_PROMPT_SCHEMA_VERSION = "matraix-linux-note-to-csv/v1"
LINUX_RUNNER_VERSION = "1.0.0"
LINUX_TOOL_NAME = "submit_note_to_csv"


class LinuxRuntimeConfig(StrictModel):
    api_key: Annotated[str, StringConstraints(min_length=1, max_length=8192, strict=True)] = Field(
        repr=False
    )
    provider_base_url: Annotated[
        str, StringConstraints(min_length=1, max_length=2000, strict=True)
    ] = Field(repr=False)
    runner_base_url: Annotated[
        str, StringConstraints(min_length=1, max_length=2000, strict=True)
    ] = Field(repr=False)
    model_name: Annotated[RequiredText, Field(max_length=200)]
    config_sha256: Sha256
    prompt_schema_version: Literal["matraix-linux-note-to-csv/v1"]
    runner_schema_version: Literal["matraix-linux-artifact-runner/v1"]
    runner_spec_sha256: Literal["ec2a5c1dd6ae8daa9163f3d5749654ef8fcb53f750bcf6614f9a9883f0e01354"]


class LinuxFrozenTrial(StrictModel):
    id: UUID
    status: Literal["running"]
    created_at: datetime
    cohort_id: UUID
    cohort_title: Annotated[RequiredText, Field(max_length=200)]
    cohort_sha256: Sha256
    dataset_sha256: Sha256
    persona_position: Annotated[int, Field(ge=0, le=99)]
    persona_id: UUID
    persona_external_id: Annotated[RequiredText, Field(max_length=128)]
    persona_display_name: Annotated[RequiredText, Field(max_length=200)]
    persona_profile_sha256: Sha256
    task_spec_sha256: Literal["0a4bf540dec44e3ea488a2884eb1b4d3233470616e87c9ff370847b0509155a9"]
    runner_spec_sha256: Literal["ec2a5c1dd6ae8daa9163f3d5749654ef8fcb53f750bcf6614f9a9883f0e01354"]
    model_name: Annotated[RequiredText, Field(max_length=200)]
    linux_config_sha256: Sha256
    prompt_schema_version: Literal["matraix-linux-note-to-csv/v1"]
    trial_sha256: Sha256
    persona: SemanticPersona

    @model_validator(mode="after")
    def validate_persona(self) -> Self:
        if (
            self.persona.id != self.persona_id
            or self.persona.position != self.persona_position
            or self.persona.persona_id != self.persona_external_id
            or self.persona.display_name != self.persona_display_name
            or self.persona.profile_sha256 != self.persona_profile_sha256
        ):
            raise ValueError("Linux trial Persona does not match its frozen binding")
        return self


class LinuxSubmission(StrictModel):
    reason: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=10, max_length=2000, strict=True),
    ]
    need_constraint_satisfaction: Literal["yes", "partially", "no"]
    personal_preference_satisfaction: Literal["yes", "partially", "no"]
    overall_experience_rating: Annotated[int, Field(strict=True, ge=1, le=10)]
    feedback_reason: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=2000, strict=True),
    ]


class LinuxFileHashes(StrictModel):
    cleaned_list_csv: Sha256
    submission_json: Sha256
    user_feedback_json: Sha256
    verifier_json: Sha256


class LinuxRunnerResponse(StrictModel):
    task_id: Literal["matraix/linux-note-to-csv"]
    task_version: Literal["1.0.0"]
    task_schema_version: Literal["matraix-linux-task/note-to-csv-v1"]
    runner_schema_version: Literal["matraix-linux-artifact-runner/v1"]
    runner_spec_sha256: Literal["ec2a5c1dd6ae8daa9163f3d5749654ef8fcb53f750bcf6614f9a9883f0e01354"]
    execution_kind: Literal["linux_artifact_runner"]
    computer_use: Literal[False]
    verifier_passed: Literal[True]
    row_count: Literal[3]
    file_sha256: dict[str, Sha256]
    artifact_sha256: Sha256

    @model_validator(mode="after")
    def validate_files(self) -> Self:
        expected = {
            "cleaned_list.csv",
            "submission.json",
            "user_feedback.json",
            "verifier.json",
        }
        if set(self.file_sha256) != expected:
            raise ValueError("Linux runner returned an unexpected artifact set")
        return self


class LinuxSuccess(StrictModel):
    runner_version: Literal["1.0.0"]
    model_name: Annotated[RequiredText, Field(max_length=200)]
    linux_config_sha256: Sha256
    prompt_schema_version: Literal["matraix-linux-note-to-csv/v1"]
    runner_schema_version: Literal["matraix-linux-artifact-runner/v1"]
    runner_spec_sha256: Literal["ec2a5c1dd6ae8daa9163f3d5749654ef8fcb53f750bcf6614f9a9883f0e01354"]
    artifact_sha256: Sha256
    file_sha256: LinuxFileHashes
    result_sha256: Sha256
    reason: Annotated[RequiredText, Field(min_length=10, max_length=2000)]
    need_constraint_satisfaction: Literal["yes", "partially", "no"]
    personal_preference_satisfaction: Literal["yes", "partially", "no"]
    overall_experience_rating: Annotated[int, Field(ge=1, le=10)]
    feedback_reason: Annotated[RequiredText, Field(max_length=2000)]
