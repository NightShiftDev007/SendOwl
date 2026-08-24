"""RSS/Atom and same-site web discovery for native media collection."""

from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree

from app.media.collection.urls import normalize_url


@dataclass(frozen=True, slots=True)
class DiscoveredArticle:
    url: str
    title: str
    summary: str
    published_at: datetime | None


def _parse_time(value: str) -> datetime | None:
    normalized = value.strip()
    if not normalized:
        return None
    try:
        parsed = parsedate_to_datetime(normalized)
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _text(element: ElementTree.Element | None) -> str:
    return "" if element is None or element.text is None else " ".join(element.text.split())


def discover_feed_articles(
    content: str, base_url: str, limit: int
) -> tuple[DiscoveredArticle, ...]:
    root = ElementTree.fromstring(content)
    items: list[DiscoveredArticle] = []
    seen: set[str] = set()
    local_name = root.tag.rsplit("}", 1)[-1].casefold()
    entries = root.findall(".//item") if local_name == "rss" else root.findall(".//{*}entry")
    for entry in entries:
        if len(items) >= limit:
            break
        link_element = entry.find("link") if local_name == "rss" else entry.find("{*}link")
        link = _text(link_element)
        if not link and link_element is not None:
            link = str(link_element.attrib.get("href") or "")
        title = _text(entry.find("title") if local_name == "rss" else entry.find("{*}title"))
        summary = _text(
            entry.find("description") if local_name == "rss" else entry.find("{*}summary")
        )
        published = _text(
            entry.find("pubDate") if local_name == "rss" else entry.find("{*}published")
        ) or _text(entry.find("{*}updated"))
        if not link or not title:
            continue
        normalized_url = normalize_url(urljoin(base_url, link))
        if normalized_url in seen:
            continue
        seen.add(normalized_url)
        items.append(
            DiscoveredArticle(
                url=normalized_url,
                title=title,
                summary=summary,
                published_at=_parse_time(published),
            )
        )
    return tuple(items)


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.page_title = ""
        self._href: str | None = None
        self._link_text: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag.casefold() == "a" and attributes.get("href"):
            self._href = str(attributes["href"])
            self._link_text = []
        elif tag.casefold() == "title":
            self._in_title = True

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._link_text.append(data)
        if self._in_title:
            self.page_title += data

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "a" and self._href is not None:
            text = " ".join(" ".join(self._link_text).split())
            self.links.append((self._href, text))
            self._href = None
            self._link_text = []
        elif tag.casefold() == "title":
            self._in_title = False


def discover_web_articles(content: str, base_url: str, limit: int) -> tuple[DiscoveredArticle, ...]:
    parser = _LinkParser()
    parser.feed(content)
    base_host = urlsplit(base_url).hostname
    items: list[DiscoveredArticle] = []
    seen: set[str] = set()
    for href, title in parser.links:
        if len(items) >= limit:
            break
        if len(title) < 8:
            continue
        absolute = urljoin(base_url, href)
        if urlsplit(absolute).hostname != base_host:
            continue
        normalized_url = normalize_url(absolute)
        if normalized_url in seen or normalized_url == normalize_url(base_url):
            continue
        seen.add(normalized_url)
        items.append(
            DiscoveredArticle(
                url=normalized_url,
                title=title[:1000],
                summary="",
                published_at=None,
            )
        )
    return tuple(items)
