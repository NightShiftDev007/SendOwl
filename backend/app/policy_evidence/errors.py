"""Typed Policy evidence domain errors."""


class PolicyEvidenceError(RuntimeError):
    """Base Policy evidence failure."""


class PolicyDocumentNotFoundError(PolicyEvidenceError, LookupError):
    """Requested Policy document does not exist."""


class PolicyVersionNotFoundError(PolicyEvidenceError, LookupError):
    """Requested Policy version does not exist."""


class PolicyEvidenceSelectionError(PolicyEvidenceError, ValueError):
    """Policy directory or capture selection is invalid."""
