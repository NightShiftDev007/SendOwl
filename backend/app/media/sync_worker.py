"""Optional fixed-delay worker for isolated AgendaScope media refreshes."""

import asyncio
import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass

from app.media.import_agendascope import (
    ImportConfigurationError,
    ImportRuntimeError,
    ImportSettings,
    SourceSchemaError,
    load_import_settings,
)
from app.media.sync_contracts import MediaSyncRunStatus
from app.media.sync_repository import MediaSyncExecution, run_scheduled_media_sync

LOGGER = logging.getLogger("sendowl.media_sync")
INTERVAL_VARIABLE = "MEDIA_SYNC_INTERVAL_SECONDS"
WORKER_ID_VARIABLE = "MEDIA_SYNC_WORKER_ID"
MINIMUM_INTERVAL_SECONDS = 60
MAXIMUM_INTERVAL_SECONDS = 86_400
DATABASE_RETRY_DELAYS_SECONDS = (1, 5)


@dataclass(frozen=True, slots=True)
class MediaSyncWorkerSettings:
    """Validated worker configuration without implicit source credentials."""

    import_settings: ImportSettings
    worker_id: str
    interval_seconds: int


def _required_environment_value(environment: Mapping[str, str], variable_name: str) -> str:
    value = environment.get(variable_name)
    if value is None or not value.strip():
        raise ImportConfigurationError(f"{variable_name} must be configured for media sync")
    return value.strip()


def _parse_interval(value: str) -> int:
    if not value.isascii() or not value.isdecimal():
        raise ImportConfigurationError(
            f"{INTERVAL_VARIABLE} must be an integer from {MINIMUM_INTERVAL_SECONDS} "
            f"to {MAXIMUM_INTERVAL_SECONDS}"
        )
    interval = int(value)
    if interval < MINIMUM_INTERVAL_SECONDS or interval > MAXIMUM_INTERVAL_SECONDS:
        raise ImportConfigurationError(
            f"{INTERVAL_VARIABLE} must be from {MINIMUM_INTERVAL_SECONDS} "
            f"to {MAXIMUM_INTERVAL_SECONDS}"
        )
    return interval


def load_worker_settings(environment: Mapping[str, str]) -> MediaSyncWorkerSettings:
    """Load explicit source, attestation, identity, and cadence settings."""
    worker_id = _required_environment_value(environment, WORKER_ID_VARIABLE)
    if len(worker_id) > 128 or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", worker_id) is None:
        raise ImportConfigurationError(
            f"{WORKER_ID_VARIABLE} must be a 1 to 128 character stable identifier"
        )
    interval = _parse_interval(_required_environment_value(environment, INTERVAL_VARIABLE))
    return MediaSyncWorkerSettings(
        import_settings=load_import_settings(environment),
        worker_id=worker_id,
        interval_seconds=interval,
    )


def _result_totals(execution: MediaSyncExecution) -> tuple[int, int, int, int]:
    result = execution.import_result
    if result is None:
        return (0, 0, 0, 0)
    counts = (
        result.sources,
        result.articles,
        result.topics,
        result.topic_articles,
        result.topic_snapshots,
        result.propagation_events,
        result.propagation_edges,
        result.first_utterances,
    )
    return (
        sum(count.read for count in counts),
        sum(count.inserted for count in counts),
        sum(count.updated for count in counts),
        sum(count.skipped for count in counts),
    )


async def _run_with_database_retries(
    settings: MediaSyncWorkerSettings,
) -> MediaSyncExecution:
    last_error: ImportRuntimeError | None = None
    attempt_count = len(DATABASE_RETRY_DELAYS_SECONDS) + 1
    for attempt in range(1, attempt_count + 1):
        try:
            return await run_scheduled_media_sync(
                settings.import_settings,
                settings.worker_id,
                settings.interval_seconds,
            )
        except ImportRuntimeError as error:
            last_error = error
            LOGGER.warning(
                "scheduled media sync database attempt failed",
                extra={
                    "attempt": attempt,
                    "attempt_count": attempt_count,
                    "error_type": type(error).__name__,
                    "worker_id": settings.worker_id,
                },
            )
            if attempt < attempt_count:
                await asyncio.sleep(DATABASE_RETRY_DELAYS_SECONDS[attempt - 1])
    if last_error is None:
        raise ImportRuntimeError("Scheduled media sync exhausted retries without an error")
    raise last_error


async def run_worker(settings: MediaSyncWorkerSettings) -> None:
    """Run immediately, then repeat with a fixed delay after every terminal attempt."""
    while True:
        try:
            execution = await _run_with_database_retries(settings)
            totals = _result_totals(execution)
            log_method = (
                LOGGER.warning
                if execution.status is MediaSyncRunStatus.SKIPPED_CONCURRENT
                else LOGGER.info
            )
            log_method(
                "scheduled media sync reached a terminal state",
                extra={
                    "run_id": str(execution.run_id),
                    "status": execution.status.value,
                    "rows_read": totals[0],
                    "rows_inserted": totals[1],
                    "rows_updated": totals[2],
                    "rows_skipped": totals[3],
                    "worker_id": settings.worker_id,
                },
            )
        except ImportRuntimeError as error:
            LOGGER.error(
                "scheduled media sync will wait after exhausted database retries",
                extra={
                    "error_type": type(error).__name__,
                    "worker_id": settings.worker_id,
                },
            )
        await asyncio.sleep(settings.interval_seconds)


async def _run() -> int:
    try:
        settings = load_worker_settings(os.environ)
        await run_worker(settings)
    except (ImportConfigurationError, SourceSchemaError) as error:
        LOGGER.error(
            "media sync worker stopped on a non-retryable configuration or schema error",
            extra={"error_type": type(error).__name__, "safe_message": str(error)},
        )
        return 2
    return 0


def main() -> None:
    """Run the optional worker until it is stopped or explicitly misconfigured."""
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
