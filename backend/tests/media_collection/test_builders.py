"""Pure construction of collected articles and generic evidence items."""

from datetime import UTC, datetime

from app.evidence.contracts import calculate_content_sha256
from app.media.collection import (
    ContentStatus,
    ExtractedArticleContent,
    build_collected_article,
    build_evidence_item,
    calculate_url_sha256,
)
from app.media.contracts import MediaSource, MediaSourceKind


def test_builders_connect_normalized_article_to_generic_evidence() -> None:
    source = MediaSource(
        source_id="source-001",
        name="Example Media",
        canonical_url="https://example.com",
        kind=MediaSourceKind.RSS,
    )
    extraction = ExtractedArticleContent(
        content="A verified event was reported.",
        summary="Verified event report.",
        method="stdlib_html",
        status=ContentStatus.FULL,
        failures=(),
    )
    raw_url = "HTTPS://Example.com:443/articles/1/?utm_source=wechat#comments"
    collected = build_collected_article(
        article_id="article-001",
        source=source,
        url=raw_url,
        title="Verified event",
        author=None,
        extraction=extraction,
        language="en",
        published_at=datetime(2026, 8, 12, 8, 0, tzinfo=UTC),
        captured_at=datetime(2026, 8, 12, 8, 5, tzinfo=UTC),
    )
    evidence = build_evidence_item("evidence-001", collected)

    assert collected.normalized_url == "https://example.com/articles/1"
    assert str(collected.article.url) == collected.normalized_url
    assert collected.url_sha256 == calculate_url_sha256(raw_url)
    assert collected.content_sha256 == calculate_content_sha256(collected.article.content)
    assert evidence.content_sha256 == collected.content_sha256
    assert evidence.evidence_id == "evidence-001"
