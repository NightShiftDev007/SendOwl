"""Explicit failures for sealed Evidence Bundle projections."""


class EvidenceError(RuntimeError):
    """Base failure for immutable evidence resources."""


class EvidenceBundleNotFoundError(EvidenceError):
    """Raised when a sealed evidence bundle does not exist."""


class EvidenceBundleItemNotFoundError(EvidenceError):
    """Raised when an article is not present in a sealed bundle."""


__all__ = [
    "EvidenceBundleItemNotFoundError",
    "EvidenceBundleNotFoundError",
    "EvidenceError",
]
