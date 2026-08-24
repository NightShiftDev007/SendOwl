"""Explicit failures for bounded ReportAgent evidence runs."""


class ReportAgentError(RuntimeError):
    """Base failure for a bounded ReportAgent evidence operation."""


class ReportAgentRunNotFoundError(ReportAgentError):
    """Raised when a requested evidence run does not exist."""


class ReportAgentScopeError(ReportAgentError):
    """Raised when a run input or tool target is outside its frozen snapshot."""


class ReportAgentToolBudgetExhaustedError(ReportAgentError):
    """Raised when a run has consumed its explicit tool-call budget."""


class ReportAgentDraftNotFoundError(ReportAgentError):
    """Raised when a requested cited draft does not exist."""


class ReportAgentDraftUnavailableError(ReportAgentError):
    """Raised when a cited draft cannot be queued from the current evidence reads."""


class ReportAgentDraftRetryError(ReportAgentError):
    """Raised when a cited draft cannot create another immutable retry attempt."""


__all__ = [
    "ReportAgentError",
    "ReportAgentDraftNotFoundError",
    "ReportAgentDraftRetryError",
    "ReportAgentDraftUnavailableError",
    "ReportAgentRunNotFoundError",
    "ReportAgentScopeError",
    "ReportAgentToolBudgetExhaustedError",
]
