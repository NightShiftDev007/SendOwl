"""Explicit failures raised by the media collection domain."""


class MediaCollectionError(ValueError):
    """Base class for invalid collection input or an unusable collection result."""


class InvalidArticleUrlError(MediaCollectionError):
    """Raised when an article URL cannot be converted to a stable HTTP(S) identity."""


class InvalidExtractionConfigurationError(MediaCollectionError):
    """Raised when the configured content-extraction chain is ambiguous or invalid."""


class InvalidExtractorResultError(MediaCollectionError):
    """Raised when an injected extractor violates its declared return contract."""


class ArticleContentExtractionError(MediaCollectionError):
    """Raised when neither HTML extraction nor title/summary fallback yields content."""
