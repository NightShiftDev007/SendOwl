"""Pure media-collection primitives used by persistence and worker adapters."""

from app.media.collection.aliases import (
    find_company_alias_matches,
    find_company_alias_matches_bounded,
    find_company_mentions,
)
from app.media.collection.builders import (
    CollectedArticle,
    EvidenceBuildResult,
    build_collected_article,
    build_evidence_item,
)
from app.media.collection.errors import (
    AmbiguousCompanyAliasError,
    AmbiguousCompanyMentionError,
    ArticleContentExtractionError,
    CompanyAliasMatchLimitError,
    DuplicateCompanyProfileError,
    InvalidArticleUrlError,
    InvalidExtractionConfigurationError,
    InvalidExtractorResultError,
    MediaCollectionError,
)
from app.media.collection.extraction import (
    ContentStatus,
    ExtractedArticleContent,
    ExtractionFailure,
    ExtractorStep,
    build_article_summary,
    extract_article_content,
    extract_html_text,
)
from app.media.collection.urls import calculate_sha256, calculate_url_sha256, normalize_url

__all__ = [
    "AmbiguousCompanyAliasError",
    "AmbiguousCompanyMentionError",
    "ArticleContentExtractionError",
    "CompanyAliasMatchLimitError",
    "CollectedArticle",
    "ContentStatus",
    "DuplicateCompanyProfileError",
    "EvidenceBuildResult",
    "ExtractedArticleContent",
    "ExtractionFailure",
    "ExtractorStep",
    "InvalidArticleUrlError",
    "InvalidExtractionConfigurationError",
    "InvalidExtractorResultError",
    "MediaCollectionError",
    "build_article_summary",
    "build_collected_article",
    "build_evidence_item",
    "calculate_sha256",
    "calculate_url_sha256",
    "extract_article_content",
    "extract_html_text",
    "find_company_alias_matches",
    "find_company_alias_matches_bounded",
    "find_company_mentions",
    "normalize_url",
]
