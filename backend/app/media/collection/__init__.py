"""Pure media-collection primitives used by persistence and worker adapters."""

from app.media.collection.builders import (
    CollectedArticle,
    build_collected_article,
    build_evidence_item,
)
from app.media.collection.errors import (
    ArticleContentExtractionError,
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
    "ArticleContentExtractionError",
    "CollectedArticle",
    "ContentStatus",
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
    "normalize_url",
]
