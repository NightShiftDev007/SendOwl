"""Default SandOwl media collector worker."""

import asyncio
import logging
import os
from datetime import UTC, datetime
from uuid import UUID

from app.config import load_runtime_settings
from app.database import DatabaseConnector
from app.media.collection.repository import (
    complete_native_collection_failure,
    complete_native_collection_success,
    heartbeat_native_collection_worker,
    list_due_native_media_sources,
    start_native_collection_run,
)
from app.media.collection.service import collect_native_source

LOGGER = logging.getLogger("sandowl.native_media_collection")
DEFAULT_SCAN_INTERVAL_SECONDS = 60
DEFAULT_SOURCE_BATCH_SIZE = 5


def _positive_integer(environment: dict[str, str], name: str, default: int, maximum: int) -> int:
    raw = environment.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if value < 1 or value > maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return value


async def run_worker(environment: dict[str, str]) -> None:
    settings = load_runtime_settings(environment)
    if settings.database_url is None:
        raise RuntimeError("DATABASE_URL is required for native media collection")
    worker_id = environment.get("MEDIA_COLLECTION_WORKER_ID", "sandowl-native-media-collector")
    if not worker_id or len(worker_id) > 128:
        raise ValueError("MEDIA_COLLECTION_WORKER_ID must contain 1 to 128 characters")
    interval = _positive_integer(
        environment,
        "MEDIA_COLLECTION_SCAN_INTERVAL_SECONDS",
        DEFAULT_SCAN_INTERVAL_SECONDS,
        3600,
    )
    batch_size = _positive_integer(
        environment,
        "MEDIA_COLLECTION_SOURCE_BATCH_SIZE",
        DEFAULT_SOURCE_BATCH_SIZE,
        50,
    )
    connector = DatabaseConnector.create(settings.database_url)
    started_at = datetime.now(UTC)
    try:
        while True:
            async with connector.session() as session:
                await heartbeat_native_collection_worker(session, worker_id, started_at)
                sources = await list_due_native_media_sources(session, batch_size)
            for source in sources:
                async with connector.session() as session:
                    run = await start_native_collection_run(session, UUID(source.id), worker_id)
                if run is None:
                    continue
                try:
                    batch = await asyncio.to_thread(collect_native_source, source)
                except Exception as error:
                    LOGGER.warning(
                        "native media collection failed",
                        extra={"source_id": source.id, "error_type": type(error).__name__},
                    )
                    async with connector.session() as session:
                        await complete_native_collection_failure(session, run.id, error)
                else:
                    async with connector.session() as session:
                        await complete_native_collection_success(session, run.id, batch)
            await asyncio.sleep(interval)
    finally:
        await connector.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker(dict(os.environ)))


if __name__ == "__main__":
    main()
