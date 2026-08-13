"""Explicit report question failures."""


class ReportQuestionNotFoundError(LookupError):
    """Raised when a report question does not exist."""


class ReportQuestionUnavailableError(ValueError):
    """Raised when cited answering prerequisites are unavailable."""
