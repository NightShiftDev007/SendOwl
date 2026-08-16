"""Explicit fixed Linux trial failures."""


class MatraixLinuxTrialNotFoundError(LookupError):
    """Raised when a Linux trial does not exist."""


class MatraixLinuxEvaluationNotFoundError(LookupError):
    """Raised when a sealed Linux evaluation parent does not exist."""


class MatraixLinuxSelectionError(ValueError):
    """Raised when the requested Cohort or Persona is invalid."""


class MatraixLinuxUnavailableError(RuntimeError):
    """Raised when no correctly pinned Linux worker is ready."""
