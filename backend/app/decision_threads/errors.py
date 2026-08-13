"""Explicit decision-thread failures."""


class DecisionThreadNotFoundError(LookupError):
    """Raised when a decision thread identity does not exist."""


class DecisionThreadSelectionError(ValueError):
    """Raised when selected immutable resources do not form one consistent chain."""
