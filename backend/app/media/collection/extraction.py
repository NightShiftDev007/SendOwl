"""Dependency-free article extraction with an explicit, inspectable fallback chain."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from html.parser import HTMLParser

from app.media.collection.errors import (
    ArticleContentExtractionError,
    InvalidExtractionConfigurationError,
    InvalidExtractorResultError,
)

type ContentExtractor = Callable[[str, str], str | None]


class ContentStatus(StrEnum):
    """Quality of the content retained for an article snapshot."""

    FULL = "full"
    PARTIAL = "partial"


@dataclass(frozen=True, slots=True)
class ExtractorStep:
    """A named extractor callable whose result can be audited."""

    name: str
    extract: ContentExtractor

    def __post_init__(self) -> None:
        if not isinstance(self.name, str):
            raise TypeError(f"extractor name must be str, got {type(self.name).__name__}")
        if not self.name.strip():
            raise InvalidExtractionConfigurationError("extractor name must not be empty")
        if not callable(self.extract):
            raise InvalidExtractionConfigurationError(
                f"extractor {self.name!r} must provide a callable"
            )


@dataclass(frozen=True, slots=True)
class ExtractionFailure:
    """Why one step in the intentional fallback chain did not produce usable content."""

    extractor_name: str
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.extractor_name, str) or not self.extractor_name.strip():
            raise ArticleContentExtractionError("failure extractor_name must not be empty")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ArticleContentExtractionError("failure reason must not be empty")


@dataclass(frozen=True, slots=True)
class ExtractedArticleContent:
    """Content and summary selected by the fallback chain."""

    content: str
    summary: str
    method: str
    status: ContentStatus
    failures: tuple[ExtractionFailure, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.content, str) or not self.content.strip():
            raise ArticleContentExtractionError("extracted article content must not be empty")
        if not isinstance(self.summary, str) or not self.summary.strip():
            raise ArticleContentExtractionError("extracted article summary must not be empty")
        if not isinstance(self.method, str) or not self.method.strip():
            raise ArticleContentExtractionError("extraction method must not be empty")
        if not isinstance(self.status, ContentStatus):
            raise TypeError(
                f"extraction status must be ContentStatus, got {type(self.status).__name__}"
            )
        if not isinstance(self.failures, tuple) or any(
            not isinstance(failure, ExtractionFailure) for failure in self.failures
        ):
            raise TypeError("extraction failures must be a tuple of ExtractionFailure values")


_IGNORED_TAGS = frozenset({"head", "noscript", "script", "style", "svg", "template"})
_BLOCK_TAGS = frozenset(
    {
        "article",
        "aside",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "figure",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }
)
_STDLIB_EXTRACTOR_NAME = "stdlib_html"
_TITLE_SUMMARY_METHOD = "title_summary"


class _VisibleTextParser(HTMLParser):
    """Small adapter around the standard-library HTML parser."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_tags: list[str] = []
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        normalized_tag = tag.casefold()
        if self._ignored_tags:
            if normalized_tag in _IGNORED_TAGS:
                self._ignored_tags.append(normalized_tag)
            return
        if normalized_tag in _IGNORED_TAGS:
            self._ignored_tags.append(normalized_tag)
            return
        if normalized_tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if not self._ignored_tags and tag.casefold() in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.casefold()
        if self._ignored_tags:
            if normalized_tag == self._ignored_tags[-1]:
                self._ignored_tags.pop()
            return
        if normalized_tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_tags:
            self._parts.append(data)

    def visible_text(self) -> str:
        """Return normalized visible text accumulated by the parser."""
        return _clean_text(" ".join(self._parts))


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def extract_html_text(html: str, url: str) -> str | None:
    """Extract visible HTML text using only the Python standard library."""
    del url
    if not isinstance(html, str):
        raise TypeError(f"html must be str, got {type(html).__name__}")
    if not html.strip():
        return None
    parser = _VisibleTextParser()
    parser.feed(html)
    parser.close()
    return parser.visible_text() or None


def build_article_summary(content: str, supplied_summary: str, maximum_characters: int) -> str:
    """Prefer the supplied summary and otherwise derive one from retained content."""
    if not isinstance(content, str):
        raise TypeError(f"content must be str, got {type(content).__name__}")
    if not isinstance(supplied_summary, str):
        raise TypeError(f"supplied_summary must be str, got {type(supplied_summary).__name__}")
    if isinstance(maximum_characters, bool) or not isinstance(maximum_characters, int):
        raise TypeError("maximum_characters must be int")
    if maximum_characters <= 0:
        raise InvalidExtractionConfigurationError(
            f"maximum summary characters must be positive, got {maximum_characters}"
        )
    cleaned_content = _clean_text(content)
    cleaned_summary = _clean_text(supplied_summary)
    summary_source = cleaned_summary or cleaned_content
    if not summary_source:
        raise ArticleContentExtractionError("cannot build a summary from empty content")
    return summary_source[:maximum_characters].rstrip()


def _validate_extractor_steps(extractors: tuple[ExtractorStep, ...]) -> None:
    names: dict[str, str] = {}
    for extractor in extractors:
        normalized_name = extractor.name.strip().casefold()
        if normalized_name == _STDLIB_EXTRACTOR_NAME:
            raise InvalidExtractionConfigurationError(
                f"extractor name {_STDLIB_EXTRACTOR_NAME!r} is reserved for the built-in fallback"
            )
        existing_name = names.get(normalized_name)
        if existing_name is not None:
            raise InvalidExtractionConfigurationError(
                f"extractor names must be unique; {existing_name!r} and {extractor.name!r} collide"
            )
        names[normalized_name] = extractor.name


def _run_extractor(
    step: ExtractorStep,
    html: str,
    url: str,
) -> tuple[str | None, ExtractionFailure | None]:
    try:
        extracted = step.extract(html, url)
    except Exception as error:
        return None, ExtractionFailure(
            extractor_name=step.name,
            reason=f"{type(error).__name__}: {error}",
        )
    if extracted is not None and not isinstance(extracted, str):
        raise InvalidExtractorResultError(
            f"extractor {step.name!r} must return str or None, got {type(extracted).__name__}"
        )
    cleaned = _clean_text(extracted or "")
    if not cleaned:
        return None, ExtractionFailure(
            extractor_name=step.name,
            reason="extractor returned no visible text",
        )
    return cleaned, None


def extract_article_content(
    html: str,
    url: str,
    title: str,
    supplied_summary: str,
    extractors: tuple[ExtractorStep, ...],
    minimum_content_characters: int,
    maximum_summary_characters: int,
) -> ExtractedArticleContent:
    """Run injected extractors, the standard fallback, then title/summary fallback."""
    string_inputs = {
        "html": html,
        "url": url,
        "title": title,
        "supplied_summary": supplied_summary,
    }
    for field_name, value in string_inputs.items():
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be str, got {type(value).__name__}")
    if not isinstance(extractors, tuple) or any(
        not isinstance(extractor, ExtractorStep) for extractor in extractors
    ):
        raise TypeError("extractors must be a tuple of ExtractorStep values")
    if isinstance(minimum_content_characters, bool) or not isinstance(
        minimum_content_characters, int
    ):
        raise TypeError("minimum_content_characters must be int")
    if minimum_content_characters <= 0:
        raise InvalidExtractionConfigurationError(
            f"minimum content characters must be positive, got {minimum_content_characters}"
        )
    if isinstance(maximum_summary_characters, bool) or not isinstance(
        maximum_summary_characters, int
    ):
        raise TypeError("maximum_summary_characters must be int")
    if maximum_summary_characters <= 0:
        raise InvalidExtractionConfigurationError(
            f"maximum summary characters must be positive, got {maximum_summary_characters}"
        )
    _validate_extractor_steps(extractors)

    failures: list[ExtractionFailure] = []
    steps = (*extractors, ExtractorStep(name=_STDLIB_EXTRACTOR_NAME, extract=extract_html_text))
    for step in steps:
        if not html.strip():
            failures.append(
                ExtractionFailure(
                    extractor_name=step.name,
                    reason="HTML input is empty",
                )
            )
            continue
        content, failure = _run_extractor(step, html, url)
        if failure is not None:
            failures.append(failure)
            continue
        if content is None:
            raise RuntimeError(f"extractor {step.name!r} returned neither content nor failure")
        if len(content) < minimum_content_characters:
            failures.append(
                ExtractionFailure(
                    extractor_name=step.name,
                    reason=(
                        f"extracted {len(content)} characters; "
                        f"minimum is {minimum_content_characters}"
                    ),
                )
            )
            continue
        summary = build_article_summary(content, supplied_summary, maximum_summary_characters)
        return ExtractedArticleContent(
            content=content,
            summary=summary,
            method=step.name,
            status=ContentStatus.FULL,
            failures=tuple(failures),
        )

    cleaned_title = _clean_text(title)
    cleaned_supplied_summary = _clean_text(supplied_summary)
    fallback_parts = tuple(part for part in (cleaned_title, cleaned_supplied_summary) if part)
    if fallback_parts:
        fallback_content = "\n".join(fallback_parts)
        summary = build_article_summary(
            fallback_content,
            cleaned_supplied_summary or cleaned_title,
            maximum_summary_characters,
        )
        return ExtractedArticleContent(
            content=fallback_content,
            summary=summary,
            method=_TITLE_SUMMARY_METHOD,
            status=ContentStatus.PARTIAL,
            failures=tuple(failures),
        )

    attempted_methods = ", ".join(failure.extractor_name for failure in failures)
    raise ArticleContentExtractionError(
        "article content extraction failed and title/summary fallback was empty; "
        f"attempted methods: {attempted_methods}"
    )
