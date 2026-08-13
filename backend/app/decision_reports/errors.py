"""Explicit report generation failures."""


class DecisionReportNotFoundError(LookupError):
    """Raised when a report identity does not exist."""


class DecisionReportUnavailableError(ValueError):
    """Raised when an experiment cannot produce a deterministic report."""
