"""Shared PostgreSQL lock for isolated media refresh execution."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

IMPORT_ADVISORY_LOCK_KEY = 4_702_957_910_035_286_337


class MediaImportLockError(RuntimeError):
    """Raised when PostgreSQL cannot prove lock acquisition or release."""


async def try_acquire_import_lock(connection: AsyncConnection) -> bool:
    """Acquire the process-wide session lock without waiting behind another run."""
    result = await connection.execute(
        text("SELECT pg_try_advisory_lock(:lock_key)"),
        {"lock_key": IMPORT_ADVISORY_LOCK_KEY},
    )
    acquired = result.scalar_one()
    if not isinstance(acquired, bool):
        raise MediaImportLockError("PostgreSQL returned an invalid media import lock result")
    return acquired


async def release_import_lock(connection: AsyncConnection) -> None:
    """Release a lock owned by this exact target database session."""
    result = await connection.execute(
        text("SELECT pg_advisory_unlock(:lock_key)"),
        {"lock_key": IMPORT_ADVISORY_LOCK_KEY},
    )
    released = result.scalar_one()
    if released is not True:
        raise MediaImportLockError("PostgreSQL did not release the owned media import lock")


__all__ = [
    "IMPORT_ADVISORY_LOCK_KEY",
    "MediaImportLockError",
    "release_import_lock",
    "try_acquire_import_lock",
]
