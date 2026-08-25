"""Native RSS/Web collection pipeline independent of AgendaScope runtime."""

from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

from app.media.collection.discovery import (
    DiscoveredArticle,
    discover_feed_articles,
    discover_web_articles,
)
from app.media.collection.extraction import ExtractedArticleContent, extract_article_content
from app.media.collection.transport import FetchedDocument, fetch_public_document

MAXIMUM_ARTICLES_PER_SOURCE = 50


@dataclass(frozen=True, slots=True)
class NativeCollectionSource:
    id: str
    homepage_url: str
    feed_url: str | None
    collection_mode: str
    language: str
    country_code: str
    etag: str | None
    last_modified: str | None


@dataclass(frozen=True, slots=True)
class NativeCollectedArticle:
    discovered: DiscoveredArticle
    extraction: ExtractedArticleContent
    fetch_error: str | None


@dataclass(frozen=True, slots=True)
class NativeCollectionBatch:
    fetched_url: str
    etag: str | None
    last_modified: str | None
    articles: tuple[NativeCollectedArticle, ...]
    discovered_count: int
    not_modified: bool
    collected_at: datetime


def _article_title(document: FetchedDocument, fallback: str) -> str:
    lowered = document.body.casefold()
    start = lowered.find("<title")
    if start >= 0:
        start = lowered.find(">", start)
        end = lowered.find("</title>", start)
        if start >= 0 and end > start:
            title = " ".join(document.body[start + 1 : end].split())
            if title:
                return title[:1000]
    return fallback[:1000]


def collect_native_source(
    source: NativeCollectionSource,
    fetcher=fetch_public_document,
) -> NativeCollectionBatch:
    entry_url = source.feed_url if source.collection_mode == "rss" else source.homepage_url
    if entry_url is None:
        raise ValueError("RSS source is missing feed_url")
    entry_document = fetcher(
        entry_url,
        etag=source.etag,
        last_modified=source.last_modified,
    )
    if entry_document.status_code == 304:
        return NativeCollectionBatch(
            fetched_url=entry_document.url,
            etag=entry_document.etag,
            last_modified=entry_document.last_modified,
            articles=(),
            discovered_count=0,
            not_modified=True,
            collected_at=datetime.now(UTC),
        )
    discovered = (
        discover_feed_articles(entry_document.body, entry_document.url, MAXIMUM_ARTICLES_PER_SOURCE)
        if source.collection_mode == "rss"
        else discover_web_articles(
            entry_document.body, entry_document.url, MAXIMUM_ARTICLES_PER_SOURCE
        )
    )
    articles: list[NativeCollectedArticle] = []
    for item in discovered:
        try:
            document = fetcher(item.url)
        except Exception as error:
            extraction = extract_article_content(
                html="",
                url=item.url,
                title=item.title,
                supplied_summary=item.summary,
                extractors=(),
                minimum_content_characters=80,
                maximum_summary_characters=280,
            )
            fetch_error = f"{type(error).__name__}: {str(error)[:300]}"
        else:
            extraction = extract_article_content(
                html=document.body,
                url=document.url,
                title=_article_title(document, item.title),
                supplied_summary=item.summary,
                extractors=(),
                minimum_content_characters=80,
                maximum_summary_characters=280,
            )
            fetch_error = None
        articles.append(
            NativeCollectedArticle(
                discovered=item,
                extraction=extraction,
                fetch_error=fetch_error,
            )
        )
    return NativeCollectionBatch(
        fetched_url=entry_document.url,
        etag=entry_document.etag,
        last_modified=entry_document.last_modified,
        articles=tuple(articles),
        discovered_count=len(discovered),
        not_modified=False,
        collected_at=datetime.now(UTC),
    )


def source_domain(url: str) -> str:
    return (urlsplit(url).hostname or "unknown").casefold()
