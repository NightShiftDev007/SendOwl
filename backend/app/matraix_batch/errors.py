"""Explicit MatrAIx batch registry failures."""


class MatraixBatchRegistryNotFoundError(LookupError):
    """A sealed registry or selected sealed parent does not exist."""


class MatraixBatchRegistryIntegrityError(RuntimeError):
    """Stored registry, parent, or trial data does not match its content address."""


class MatraixBatchRegistryPageOutOfRangeError(ValueError):
    """A requested bounded parent page begins after the final candidate."""


__all__ = [
    "MatraixBatchRegistryIntegrityError",
    "MatraixBatchRegistryNotFoundError",
    "MatraixBatchRegistryPageOutOfRangeError",
]
