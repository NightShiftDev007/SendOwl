"""Explicit scenario persistence failures."""


class ScenarioNotFoundError(LookupError):
    """Raised when an immutable scenario identity does not exist."""
