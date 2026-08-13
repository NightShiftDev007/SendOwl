"""Explicit semantic experiment domain failures."""


class SemanticExperimentNotFoundError(LookupError):
    """Raised when an experiment resource does not exist."""


class SemanticTrialNotFoundError(LookupError):
    """Raised when a trial resource does not exist."""


class SemanticExperimentSelectionError(ValueError):
    """Raised when immutable scenario/cohort selections cannot be executed."""


class SemanticExperimentUnavailableError(RuntimeError):
    """Raised when no unique live semantic worker configuration is available."""
