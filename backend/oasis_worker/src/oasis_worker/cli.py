import argparse
import contextlib
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from oasis_worker.contracts import ErrorBody, ErrorResult, JobSpec
from oasis_worker.daemon import load_daemon_settings, run_daemon
from oasis_worker.engine import run_job
from oasis_worker.errors import OasisWorkerError

MAX_JOB_SPEC_BYTES = 256 * 1024


def _run_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oasis-worker",
        description="Run one real OASIS 0.2.5 Reddit manual-action smoke job.",
    )
    parser.add_argument("--job-spec", required=True, help="Path to one strict JSON job spec")
    return parser


def _daemon_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog="oasis-worker daemon",
        description="Poll PostgreSQL and run real OASIS 0.2.5 platform smoke jobs.",
    )


def _load_spec(path: Path) -> JobSpec:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise OasisWorkerError(f"cannot read job spec {path}: {error}") from error
    if len(raw) > MAX_JOB_SPEC_BYTES:
        raise OasisWorkerError(
            f"job spec exceeds {MAX_JOB_SPEC_BYTES} bytes: {path} has {len(raw)} bytes"
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise OasisWorkerError(
            f"job spec must be UTF-8: {path}, invalid byte at offset {error.start}"
        ) from error
    return JobSpec.model_validate_json(text)


def _write_error(error: Exception) -> None:
    payload = ErrorResult(
        error=ErrorBody(type=type(error).__name__, message=str(error)),
    )
    sys.stderr.write(payload.model_dump_json(indent=2) + "\n")


def main(arguments: Sequence[str]) -> int:
    if arguments and arguments[0] == "daemon":
        _daemon_parser().parse_args(arguments[1:])
        try:
            settings = load_daemon_settings(os.environ)
            run_daemon(settings)
        except (OasisWorkerError, ValidationError, RuntimeError) as error:
            _write_error(error)
            return 1
        return 0
    args = _run_parser().parse_args(arguments)
    try:
        spec = _load_spec(Path(args.job_spec))
        with contextlib.redirect_stdout(sys.stderr):
            import asyncio

            result = asyncio.run(run_job(spec))
    except (OasisWorkerError, ValidationError, json.JSONDecodeError) as error:
        _write_error(error)
        return 1
    sys.stdout.write(result.model_dump_json(indent=2) + "\n")
    return 0
