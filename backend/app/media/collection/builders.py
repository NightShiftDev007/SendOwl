"""Pure builders connecting collection output to media, evidence, and company contracts."""

from dataclasses import dataclass
from datetime import datetime

from app.companies.contracts import CompanyMention, CompanyProfile
from app.evidence.contracts import EvidenceItem, EvidenceKind
from app.media.collection.aliases import find_company_mentions
from app.media.collection.extraction import ExtractedArticleContent
from app.media.collection.urls import calculate_sha256, calculate_url_sha256, normalize_url
from app.media.contracts import MediaArticle, MediaSource


@dataclass(frozen=True, slots=True)
class CollectedArticle:
    """A validated article snapshot plus persistence-ready deterministic metadata."""

    article: MediaArticle
    normalized_url: str
    url_sha256: str
    content_sha256: str
    summary: str
    extraction: ExtractedArticleContent


@dataclass(frozen=True, slots=True)
class EvidenceBuildResult:
    """One evidence item and the exact company mentions that justify its company links."""

    evidence_item: EvidenceItem
    company_mentions: tuple[CompanyMention, ...]


def build_collected_article(
    article_id: str,
    source: MediaSource,
    url: str,
    title: str,
    author: str | None,
    extraction: ExtractedArticleContent,
    language: str,
    published_at: datetime,
    captured_at: datetime,
) -> CollectedArticle:
    """Validate a collected snapshot and calculate stable URL/content identities."""
    if not isinstance(source, MediaSource):
        raise TypeError(f"source must be MediaSource, got {type(source).__name__}")
    if not isinstance(extraction, ExtractedArticleContent):
        raise TypeError(
            f"extraction must be ExtractedArticleContent, got {type(extraction).__name__}"
        )
    normalized_url = normalize_url(url)
    article = MediaArticle(
        article_id=article_id,
        source=source,
        url=normalized_url,
        title=title,
        author=author,
        content=extraction.content,
        language=language,
        published_at=published_at,
        captured_at=captured_at,
    )
    return CollectedArticle(
        article=article,
        normalized_url=normalized_url,
        url_sha256=calculate_url_sha256(normalized_url),
        content_sha256=calculate_sha256(article.content),
        summary=extraction.summary,
        extraction=extraction,
    )


def _ordered_company_ids(mentions: tuple[CompanyMention, ...]) -> tuple[str, ...]:
    ordered_ids: list[str] = []
    seen_ids: set[str] = set()
    for mention in mentions:
        if mention.company_id in seen_ids:
            continue
        seen_ids.add(mention.company_id)
        ordered_ids.append(mention.company_id)
    return tuple(ordered_ids)


def build_evidence_item(
    evidence_id: str,
    collected_article: CollectedArticle,
    companies: tuple[CompanyProfile, ...],
) -> EvidenceBuildResult:
    """Build content-addressed evidence and deterministic company mention ranges."""
    if not isinstance(collected_article, CollectedArticle):
        raise TypeError(
            f"collected_article must be CollectedArticle, got {type(collected_article).__name__}"
        )
    if not isinstance(companies, tuple) or any(
        not isinstance(company, CompanyProfile) for company in companies
    ):
        raise TypeError("companies must be a tuple of CompanyProfile values")
    mentions = find_company_mentions(
        content=collected_article.article.content,
        evidence_id=evidence_id,
        companies=companies,
    )
    evidence_item = EvidenceItem(
        evidence_id=evidence_id,
        kind=EvidenceKind.MEDIA_ARTICLE,
        article=collected_article.article,
        content_sha256=collected_article.content_sha256,
        company_ids=_ordered_company_ids(mentions),
    )
    return EvidenceBuildResult(
        evidence_item=evidence_item,
        company_mentions=mentions,
    )
