"""Fixed MatrAIx Linux artifact runner behavior and HTTP boundary."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Thread
from typing import cast
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import UUID

import pytest

from linux_artifact_runner import app

TRIAL_ID = UUID("31000000-0000-4000-8000-000000000001")


def _request_body(trial_id: UUID) -> dict[str, object]:
    return {
        "trial_id": str(trial_id),
        "task_id": app.TASK_ID,
        "task_version": app.TASK_VERSION,
        "rows": [
            {"item": item, "quantity": quantity, "priority": priority}
            for item, quantity, priority in app.EXPECTED_ROWS
        ],
        "reason": "A fixed CSV preserves the three note fields in a portable table.",
        "feedback": {
            "need_constraint_satisfaction": "yes",
            "personal_preference_satisfaction": "yes",
            "overall_experience_rating": 9,
            "reason": "The result is compact and can be sorted without changing the note.",
        },
    }


def _read_json(url: str) -> object:
    with urlopen(url, timeout=2) as response:  # noqa: S310 - local test server only
        return json.loads(response.read())


def _post_json(url: str, body: object) -> object:
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=2) as response:  # noqa: S310 - local test server only
        return json.loads(response.read())


def test_runner_writes_only_the_fixed_verified_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app, "ARTIFACT_ROOT", tmp_path)
    request = app._parse_request(app._compact_json(_request_body(TRIAL_ID)))

    result = app._write_artifacts(request)
    trial_directory = tmp_path / str(TRIAL_ID)

    assert (trial_directory / "cleaned_list.csv").read_text() == (
        "item,quantity,priority\noat milk,2,urgent\nbatteries,4,normal\ntrash bags,1,low\n"
    )
    assert json.loads((trial_directory / "submission.json").read_text()) == {
        "format": "csv",
        "output_file": "/app/output/cleaned_list.csv",
        "reason": "A fixed CSV preserves the three note fields in a portable table.",
        "rows_written": 3,
    }
    verifier = json.loads((trial_directory / "verifier.json").read_text())
    assert verifier["passed"] is True
    assert verifier["row_count"] == 3
    assert result["computer_use"] is False
    assert result["execution_kind"] == "linux_artifact_runner"
    assert result["artifact_sha256"] == (
        "fe6a758055d15fb24be1ea2e9d884e4d1842a2babae8cd31ecd70be173929218"
    )


def test_runner_rejects_unknown_rows_and_extra_execution_input() -> None:
    body = _request_body(TRIAL_ID)
    rows = cast(list[dict[str, object]], body["rows"])
    rows[0] = {**rows[0], "item": "shell command"}
    body["command"] = "touch /tmp/escaped"

    with pytest.raises(ValueError, match="fixed note-to-CSV contract"):
        app._parse_request(app._compact_json(body))


def test_runner_http_contract_is_versioned_and_conflict_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app, "ARTIFACT_ROOT", tmp_path)
    server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.RequestHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    base_url = f"http://{host}:{port}"
    try:
        ready = cast(dict[str, object], _read_json(f"{base_url}/ready"))
        assert ready == {
            "status": "ready",
            "task_id": app.TASK_ID,
            "task_version": app.TASK_VERSION,
            "task_schema_version": app.TASK_SCHEMA_VERSION,
            "runner_schema_version": app.RUNNER_SCHEMA_VERSION,
            "runner_spec_sha256": app.RUNNER_SPEC_SHA256,
            "execution_kind": "linux_artifact_runner",
            "computer_use": False,
        }
        result = cast(
            dict[str, object],
            _post_json(f"{base_url}/v1/note-to-csv-runs", _request_body(TRIAL_ID)),
        )
        assert result["verifier_passed"] is True
        with pytest.raises(HTTPError) as conflict:
            _post_json(f"{base_url}/v1/note-to-csv-runs", _request_body(TRIAL_ID))
        assert conflict.value.code == 409
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
