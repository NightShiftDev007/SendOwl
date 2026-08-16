"""Explicit media-query failures translated at the HTTP boundary."""


class MediaTopicNotFoundError(LookupError):
    """Raised when an imported media topic identity does not exist."""


class MediaArticleNotFoundError(LookupError):
    """Raised when one non-duplicate imported article identity does not exist."""


class MediaSourceNotFoundError(LookupError):
    """Raised when an imported media source identity does not exist."""


class MediaSourceEvidencePageOutOfRangeError(ValueError):
    """Raised when a requested source evidence page has no first item."""
