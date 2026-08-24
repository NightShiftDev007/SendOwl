"""Explicit Agent Interaction failures."""


class AgentInteractionNotFoundError(LookupError):
    """Raised when an interaction does not exist."""


class AgentInteractionUnavailableError(ValueError):
    """Raised when a frozen interaction scope cannot be established."""
