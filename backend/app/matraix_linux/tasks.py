"""Frozen public identity for the MatrAIx note-to-CSV source task."""

import hashlib
import json

from app.matraix_linux.contracts import MatraixLinuxTask, MatraixLinuxTaskSource

TASK_ID = "matraix/linux-note-to-csv"
TASK_VERSION = "1.0.0"
TASK_SCHEMA_VERSION = "matraix-linux-task/note-to-csv-v1"
RUNNER_SCHEMA_VERSION = "matraix-linux-artifact-runner/v1"
RUNNER_SPEC_SHA256 = "ec2a5c1dd6ae8daa9163f3d5749654ef8fcb53f750bcf6614f9a9883f0e01354"
PROMPT_SCHEMA_VERSION = "matraix-linux-note-to-csv/v1"
RUNNER_VERSION = "1.0.0"
SOURCE_PATH = "application/tasks/example-computer-use-linux_note-to-csv"
TASK_TITLE = "Note to CSV cleanup"
TASK_INSTRUCTION = (
    "Transform the frozen three-line shopping note into cleaned_list.csv with the exact "
    "item,quantity,priority header and a matching submission.json."
)
TASK_CONTEXT = "oat milk | 2 | urgent\nbatteries | 4 | normal\ntrash bags | 1 | low"


def _task_spec_payload() -> dict[str, object]:
    return {
        "schema_version": TASK_SCHEMA_VERSION,
        "task_id": TASK_ID,
        "version": TASK_VERSION,
        "source_project": "MatrAIx",
        "canonical_path": SOURCE_PATH,
        "title": TASK_TITLE,
        "instruction": TASK_INSTRUCTION,
        "context": TASK_CONTEXT,
        "execution_kind": "linux_artifact_runner",
        "computer_use": False,
        "required_artifacts": (
            "cleaned_list.csv",
            "submission.json",
            "user_feedback.json",
            "verifier.json",
        ),
    }


TASK_SPEC_SHA256 = hashlib.sha256(
    json.dumps(
        _task_spec_payload(),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
).hexdigest()


def build_linux_task() -> MatraixLinuxTask:
    return MatraixLinuxTask(
        task_id=TASK_ID,
        version=TASK_VERSION,
        schema_version=TASK_SCHEMA_VERSION,
        title=TASK_TITLE,
        domain="software",
        source=MatraixLinuxTaskSource(
            kind="source_sample",
            project="MatrAIx",
            canonical_path=SOURCE_PATH,
            production_sut=False,
        ),
        execution_kind="linux_artifact_runner",
        computer_use=False,
        instruction=TASK_INSTRUCTION,
        context=TASK_CONTEXT,
        required_artifacts=(
            "cleaned_list.csv",
            "submission.json",
            "user_feedback.json",
            "verifier.json",
        ),
        task_spec_sha256=TASK_SPEC_SHA256,
        runner_schema_version=RUNNER_SCHEMA_VERSION,
        runner_spec_sha256=RUNNER_SPEC_SHA256,
        limitations=(
            "This is a fixed MatrAIx source sample executed by an isolated artifact runner.",
            "It does not expose a shell, arbitrary paths, desktop Computer Use, or Harbor.",
            "Persona feedback is synthetic model output, not human research or benchmark reward.",
        ),
    )
