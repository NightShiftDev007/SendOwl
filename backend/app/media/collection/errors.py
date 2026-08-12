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


class DuplicateCompanyProfileError(MediaCollectionError):
    """Raised when one matching operation receives a company identity more than once."""


class AmbiguousCompanyAliasError(MediaCollectionError):
    """Raised when the same normalized alias resolves to multiple companies."""


class AmbiguousCompanyMentionError(MediaCollectionError):
    """Raised when overlapping text ranges resolve to different companies."""


class CompanyAliasMatchLimitError(MediaCollectionError):
    """Raised as soon as a bounded matcher resolves one match beyond its limit."""

    def __init__(self, observed_matches: int, limit: int) -> None:
        if observed_matches <= limit:
            raise ValueError(
                "alias match limit failure requires observed_matches > limit; "
                f"observed_matches={observed_matches}, limit={limit}"
            )
        self.observed_matches = observed_matches
        self.limit = limit
        super().__init__(
            "company alias match limit exceeded; "
            f"observed matches: {observed_matches}; limit: {limit}"
        )
