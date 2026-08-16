"""Explicit failures for the read-only MatrAIx trial archive."""


class MatraixTrialArchiveIntegrityError(RuntimeError):
    """Stored parent or trial content does not match its immutable address."""


class MatraixTrialArchivePageOutOfRangeError(ValueError):
    """The requested page begins beyond the immutable result snapshot."""


__all__ = [
    "MatraixTrialArchiveIntegrityError",
    "MatraixTrialArchivePageOutOfRangeError",
]
