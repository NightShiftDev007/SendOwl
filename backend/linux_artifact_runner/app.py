"""Allowlisted Linux artifact runner for the fixed MatrAIx note-to-CSV task."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Final
from uuid import UUID

TASK_ID: Final = "matraix/linux-note-to-csv"
TASK_VERSION: Final = "1.0.0"
TASK_SCHEMA_VERSION: Final = "matraix-linux-task/note-to-csv-v1"
RUNNER_SCHEMA_VERSION: Final = "matraix-linux-artifact-runner/v1"
MAX_REQUEST_BYTES: Final = 16_384
MAX_RESPONSE_BYTES: Final = 16_384
ARTIFACT_ROOT: Final = Path(os.environ.get("LINUX_ARTIFACT_ROOT", "/linux-artifacts"))
EXPECTED_ROWS: Final = (
    ("oat milk", 2, "urgent"),
    ("batteries", 4, "normal"),
    ("trash bags", 1, "low"),
)
SATISFACTION_VALUES: Final = frozenset({"yes", "partially", "no"})


def _compact_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _runner_spec() -> dict[str, object]:
    return {
        "schema_version": RUNNER_SCHEMA_VERSION,
        "task_id": TASK_ID,
        "task_version": TASK_VERSION,
        "artifact_names": (
            "cleaned_list.csv",
            "submission.json",
            "user_feedback.json",
            "verifier.json",
        ),
        "execution_kind": "linux_artifact_runner",
        "computer_use": False,
        "command_execution": False,
    }


RUNNER_SPEC_SHA256: Final = _sha256_bytes(_compact_json(_runner_spec()))


@dataclass(frozen=True, slots=True)
class Feedback:
    need_constraint_satisfaction: str
    personal_preference_satisfaction: str
    overall_experience_rating: int
    reason: str


@dataclass(frozen=True, slots=True)
class RunRequest:
    trial_id: UUID
    reason: str
    feedback: Feedback


def _required_text(value: object, field_name: str, minimum: int, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not minimum <= len(normalized) <= maximum or "\x00" in normalized:
        raise ValueError(f"{field_name} must contain {minimum}..{maximum} characters")
    return normalized


def _parse_feedback(value: object) -> Feedback:
    if not isinstance(value, dict) or set(value) != {
        "need_constraint_satisfaction",
        "personal_preference_satisfaction",
        "overall_experience_rating",
        "reason",
    }:
        raise ValueError("feedback must contain only the fixed self-report fields")
    need = value["need_constraint_satisfaction"]
    preference = value["personal_preference_satisfaction"]
    rating = value["overall_experience_rating"]
    if need not in SATISFACTION_VALUES or preference not in SATISFACTION_VALUES:
        raise ValueError("feedback satisfaction values are invalid")
    if not isinstance(rating, int) or isinstance(rating, bool) or not 1 <= rating <= 10:
        raise ValueError("overall_experience_rating must be an integer from 1 to 10")
    return Feedback(
        need_constraint_satisfaction=need,
        personal_preference_satisfaction=preference,
        overall_experience_rating=rating,
        reason=_required_text(value["reason"], "feedback.reason", 1, 2_000),
    )


def _parse_request(raw: bytes) -> RunRequest:
    try:
        payload: object = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("request body must be valid UTF-8 JSON") from error
    if not isinstance(payload, dict) or set(payload) != {
        "trial_id",
        "task_id",
        "task_version",
        "rows",
        "reason",
        "feedback",
    }:
        raise ValueError("request body does not match the fixed note-to-CSV contract")
    if payload["task_id"] != TASK_ID or payload["task_version"] != TASK_VERSION:
        raise ValueError("request task identity does not match the fixed runner contract")
    try:
        trial_id = UUID(str(payload["trial_id"]))
    except (TypeError, ValueError) as error:
        raise ValueError("trial_id must be a valid UUID string") from error
    rows = payload["rows"]
    if not isinstance(rows, list) or len(rows) != len(EXPECTED_ROWS):
        raise ValueError("rows must contain exactly the three fixed note records")
    normalized_rows: list[tuple[str, int, str]] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"item", "quantity", "priority"}:
            raise ValueError("each row must contain only item, quantity, and priority")
        item = _required_text(row["item"], "row.item", 1, 100)
        quantity = row["quantity"]
        priority = row["priority"]
        if not isinstance(quantity, int) or isinstance(quantity, bool) or not 1 <= quantity <= 100:
            raise ValueError("row.quantity must be an integer from 1 to 100")
        if priority not in {"urgent", "normal", "low"}:
            raise ValueError("row.priority is invalid")
        normalized_rows.append((item, quantity, priority))
    if tuple(normalized_rows) != EXPECTED_ROWS:
        raise ValueError("rows do not exactly represent the frozen MatrAIx source note")
    return RunRequest(
        trial_id=trial_id,
        reason=_required_text(payload["reason"], "reason", 10, 2_000),
        feedback=_parse_feedback(payload["feedback"]),
    )


def _write_artifacts(request: RunRequest) -> dict[str, object]:
    ARTIFACT_ROOT.mkdir(mode=0o750, parents=True, exist_ok=True)
    final_directory = ARTIFACT_ROOT / str(request.trial_id)
    if final_directory.exists():
        raise FileExistsError("trial artifacts already exist")
    temporary_directory = Path(tempfile.mkdtemp(prefix=".pending-", dir=ARTIFACT_ROOT))
    try:
        csv_path = temporary_directory / "cleaned_list.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(("item", "quantity", "priority"))
            writer.writerows(EXPECTED_ROWS)
        submission = {
            "output_file": "/app/output/cleaned_list.csv",
            "rows_written": 3,
            "format": "csv",
            "reason": request.reason,
        }
        feedback = {
            "needConstraintSatisfaction": request.feedback.need_constraint_satisfaction,
            "personalPreferenceSatisfaction": request.feedback.personal_preference_satisfaction,
            "overallExperienceRating": request.feedback.overall_experience_rating,
            "reason": request.feedback.reason,
        }
        submission_path = temporary_directory / "submission.json"
        feedback_path = temporary_directory / "user_feedback.json"
        submission_path.write_bytes(_compact_json(submission))
        feedback_path.write_bytes(_compact_json(feedback))
        file_hashes = {
            "cleaned_list.csv": _sha256_bytes(csv_path.read_bytes()),
            "submission.json": _sha256_bytes(submission_path.read_bytes()),
            "user_feedback.json": _sha256_bytes(feedback_path.read_bytes()),
        }
        verifier = {
            "schema_version": "matraix-linux-note-to-csv-verifier/v1",
            "passed": True,
            "task_id": TASK_ID,
            "task_version": TASK_VERSION,
            "trial_id": str(request.trial_id),
            "row_count": 3,
            "file_sha256": file_hashes,
        }
        verifier_path = temporary_directory / "verifier.json"
        verifier_path.write_bytes(_compact_json(verifier))
        file_hashes["verifier.json"] = _sha256_bytes(verifier_path.read_bytes())
        artifact_sha256 = _sha256_bytes(
            _compact_json(
                {
                    "schema_version": RUNNER_SCHEMA_VERSION,
                    "task_id": TASK_ID,
                    "task_version": TASK_VERSION,
                    "trial_id": str(request.trial_id),
                    "file_sha256": file_hashes,
                }
            )
        )
        temporary_directory.rename(final_directory)
        return {
            "task_id": TASK_ID,
            "task_version": TASK_VERSION,
            "task_schema_version": TASK_SCHEMA_VERSION,
            "runner_schema_version": RUNNER_SCHEMA_VERSION,
            "runner_spec_sha256": RUNNER_SPEC_SHA256,
            "execution_kind": "linux_artifact_runner",
            "computer_use": False,
            "verifier_passed": True,
            "row_count": 3,
            "file_sha256": file_hashes,
            "artifact_sha256": artifact_sha256,
        }
    except BaseException:
        shutil.rmtree(temporary_directory, ignore_errors=True)
        raise


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "SendOwlLinuxArtifactRunner/1.0"

    def _write_json(self, status: HTTPStatus, payload: object) -> None:
        body = _compact_json(payload)
        if len(body) > MAX_RESPONSE_BYTES:
            raise RuntimeError("runner response exceeded the fixed size limit")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path != "/ready":
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "route_not_found"})
            return
        self._write_json(
            HTTPStatus.OK,
            {
                "status": "ready",
                "task_id": TASK_ID,
                "task_version": TASK_VERSION,
                "task_schema_version": TASK_SCHEMA_VERSION,
                "runner_schema_version": RUNNER_SCHEMA_VERSION,
                "runner_spec_sha256": RUNNER_SPEC_SHA256,
                "execution_kind": "linux_artifact_runner",
                "computer_use": False,
            },
        )

    def do_POST(self) -> None:
        if self.path != "/v1/note-to-csv-runs":
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "route_not_found"})
            return
        content_length = self.headers.get("Content-Length", "")
        if not content_length.isdecimal() or int(content_length) > MAX_REQUEST_BYTES:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_content_length"})
            return
        if self.headers.get("Content-Type") != "application/json":
            self._write_json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "json_required"})
            return
        try:
            request = _parse_request(self.rfile.read(int(content_length)))
            response = _write_artifacts(request)
        except ValueError as error:
            self._write_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(error)})
            return
        except FileExistsError:
            self._write_json(HTTPStatus.CONFLICT, {"error": "trial_artifacts_already_exist"})
            return
        except OSError as error:
            self.log_error("artifact run failed: %s", type(error).__name__)
            self._write_json(
                HTTPStatus.BAD_GATEWAY,
                {"error": "artifact_run_failed", "error_type": type(error).__name__},
            )
            return
        self._write_json(HTTPStatus.OK, response)

    def log_message(self, format: str, *args: object) -> None:
        print(
            json.dumps(
                {"message": format % args, "client": self.client_address[0]},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            flush=True,
        )


def main() -> None:
    ARTIFACT_ROOT.mkdir(mode=0o750, parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", 8000), RequestHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
