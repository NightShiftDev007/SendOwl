"""Pure construction of collected articles and evidence-linked company mentions."""

from datetime import UTC, datetime

from app.companies.contracts import CompanyAlias, CompanyProfile
from app.evidence.contracts import calculate_content_sha256
from app.media.collection import (
    ContentStatus,
    ExtractedArticleContent,
    build_collected_article,
    build_evidence_item,
    calculate_url_sha256,
)
from app.media.contracts import MediaSource, MediaSourceKind


def test_builders_connect_normalized_article_evidence_and_exact_company_mentions() -> None:
    source = MediaSource(
        source_id="source-001",
        name="Example Business Media",
        canonical_url="https://example.com",
        kind=MediaSourceKind.RSS,
    )
    extraction = ExtractedArticleContent(
        content="星河科技发布新品，并宣布扩大研发投入。",
        summary="星河科技发布新品。",
        method="stdlib_html",
        status=ContentStatus.FULL,
        failures=(),
    )
    company = CompanyProfile(
        company_id="company-001",
        canonical_name="星河科技有限公司",
        jurisdiction="CN",
        aliases=(
            CompanyAlias(
                value="星河科技",
                language="zh",
                evidence_ids=("registry-001",),
            ),
        ),
    )
    raw_url = "HTTPS://Example.com:443/articles/1/?utm_source=wechat#comments"

    collected = build_collected_article(
        article_id="article-001",
        source=source,
        url=raw_url,
        title="星河科技发布新品",
        author=None,
        extraction=extraction,
        language="zh-CN",
        published_at=datetime(2026, 8, 12, 8, 0, tzinfo=UTC),
        captured_at=datetime(2026, 8, 12, 8, 5, tzinfo=UTC),
    )
    built_evidence = build_evidence_item(
        evidence_id="evidence-001",
        collected_article=collected,
        companies=(company,),
    )

    assert collected.normalized_url == "https://example.com/articles/1"
    assert str(collected.article.url) == collected.normalized_url
    assert collected.url_sha256 == calculate_url_sha256(raw_url)
    assert collected.content_sha256 == calculate_content_sha256(collected.article.content)
    assert collected.summary == extraction.summary
    assert built_evidence.evidence_item.content_sha256 == collected.content_sha256
    assert built_evidence.evidence_item.company_ids == ("company-001",)
    assert len(built_evidence.company_mentions) == 1
    mention = built_evidence.company_mentions[0]
    assert mention.surface_form == "星河科技"
    assert collected.article.content[mention.start_offset : mention.end_offset] == "星河科技"
