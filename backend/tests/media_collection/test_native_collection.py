"""Native SandOwl media discovery, extraction, and configuration tests."""

import socket

import pytest
from pydantic import ValidationError

from app.media.collection.contracts import (
    NativeMediaCollectionConfigRequest,
    NativeMediaSourceCreateRequest,
)
from app.media.collection.discovery import discover_feed_articles, discover_web_articles
from app.media.collection.service import NativeCollectionSource, collect_native_source
from app.media.collection.topics import title_similarity
from app.media.collection.transport import (
    FetchedDocument,
    MediaFetchError,
    validate_public_media_url,
)

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Example News</title>
<item><title>First public report</title><link>https://news.example.test/a</link>
<description>Direct summary.</description><pubDate>Tue, 18 Aug 2026 05:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_feed_and_web_discovery_are_bounded_and_same_site() -> None:
    feed = discover_feed_articles(RSS, "https://news.example.test/feed.xml", 10)
    assert tuple(item.url for item in feed) == ("https://news.example.test/a",)
    assert feed[0].published_at is not None

    web = discover_web_articles(
        "<html><a href='/one'>A sufficiently descriptive headline</a>"
        "<a href='https://other.example/two'>External headline is ignored</a></html>",
        "https://news.example.test/",
        10,
    )
    assert tuple(item.url for item in web) == ("https://news.example.test/one",)
    assert title_similarity("共享充电宝误扣费处理", "共享充电宝扣费争议") > 0.3


def test_native_collection_uses_feed_discovery_and_article_extraction() -> None:
    documents = {
        "https://news.example.test/feed.xml": FetchedDocument(
            url="https://news.example.test/feed.xml",
            body=RSS,
            status_code=200,
            content_type="application/rss+xml",
            etag='"feed-v1"',
            last_modified=None,
        ),
        "https://news.example.test/a": FetchedDocument(
            url="https://news.example.test/a",
            body="<html><title>First public report</title><article>"
            + "Evidence " * 30
            + "</article></html>",
            status_code=200,
            content_type="text/html",
            etag=None,
            last_modified=None,
        ),
    }

    def fetcher(url: str, **kwargs) -> FetchedDocument:
        del kwargs
        return documents[url]

    batch = collect_native_source(
        NativeCollectionSource(
            id="source-1",
            homepage_url="https://news.example.test/",
            feed_url="https://news.example.test/feed.xml",
            collection_mode="rss",
            language="en",
            country_code="US",
            etag=None,
            last_modified=None,
        ),
        fetcher=fetcher,
    )

    assert batch.discovered_count == 1
    assert batch.etag == '"feed-v1"'
    assert batch.articles[0].extraction.status == "full"
    assert batch.articles[0].fetch_error is None


def test_collection_requests_require_explicit_feed_and_reject_extra_fields() -> None:
    with pytest.raises(ValidationError):
        NativeMediaSourceCreateRequest.model_validate(
            {
                "name": "Example",
                "country_code": "US",
                "homepage_url": "https://example.test/",
                "media_type": "online",
                "language": "en",
                "collection_mode": "rss",
                "feed_url": None,
                "poll_interval_seconds": 900,
            }
        )
    with pytest.raises(ValidationError):
        NativeMediaCollectionConfigRequest.model_validate(
            {
                "enabled": True,
                "collection_mode": "web",
                "feed_url": None,
                "poll_interval_seconds": 900,
                "external_database_url": "postgresql://not-allowed",
            }
        )


def test_public_transport_rejects_private_addresses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))],
    )
    with pytest.raises(MediaFetchError, match="non-public"):
        validate_public_media_url("http://internal.example.test/article")
