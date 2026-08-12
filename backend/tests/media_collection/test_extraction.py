"""Explicit article-body extraction and summary fallback behavior."""

import pytest

from app.media.collection import (
    ArticleContentExtractionError,
    ContentStatus,
    ExtractorStep,
    extract_article_content,
)


def _failing_extractor(html: str, url: str) -> str | None:
    del html, url
    raise RuntimeError("parser unavailable")


def _short_extractor(html: str, url: str) -> str | None:
    del html, url
    return "short"


def test_extraction_records_failures_before_standard_library_success() -> None:
    html = """
    <html>
      <head><title>Ignored title</title><script>ignored()</script></head>
      <body><article><h1>星河科技发布新品</h1><p>新品将在全国市场正式销售。</p></article></body>
    </html>
    """

    result = extract_article_content(
        html=html,
        url="https://example.com/article",
        title="星河科技发布新品",
        supplied_summary="",
        extractors=(
            ExtractorStep(name="external_failure", extract=_failing_extractor),
            ExtractorStep(name="external_short", extract=_short_extractor),
        ),
        minimum_content_characters=10,
        maximum_summary_characters=200,
    )

    assert result.status is ContentStatus.FULL
    assert result.method == "stdlib_html"
    assert result.content == "星河科技发布新品 新品将在全国市场正式销售。"
    assert result.summary == result.content
    assert tuple(failure.extractor_name for failure in result.failures) == (
        "external_failure",
        "external_short",
    )
    assert result.failures[0].reason == "RuntimeError: parser unavailable"
    assert result.failures[1].reason == "extracted 5 characters; minimum is 10"


def test_extraction_uses_explicit_title_summary_fallback_for_empty_html() -> None:
    result = extract_article_content(
        html="",
        url="https://example.com/article",
        title="星河科技发布新品",
        supplied_summary="该产品将在全国市场正式销售。",
        extractors=(ExtractorStep(name="external", extract=_failing_extractor),),
        minimum_content_characters=10,
        maximum_summary_characters=12,
    )

    assert result.status is ContentStatus.PARTIAL
    assert result.method == "title_summary"
    assert result.content == "星河科技发布新品\n该产品将在全国市场正式销售。"
    assert result.summary == "该产品将在全国市场正式销"
    assert tuple(failure.reason for failure in result.failures) == (
        "HTML input is empty",
        "HTML input is empty",
    )


def test_extraction_raises_when_every_fallback_is_empty() -> None:
    with pytest.raises(
        ArticleContentExtractionError,
        match="title/summary fallback was empty",
    ):
        extract_article_content(
            html="",
            url="https://example.com/article",
            title="",
            supplied_summary="",
            extractors=(),
            minimum_content_characters=10,
            maximum_summary_characters=100,
        )
