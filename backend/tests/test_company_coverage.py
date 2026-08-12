"""Pure exact-match coverage contexts and escaped SQL candidate behavior."""

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

from app.companies.contracts import MatchableCompany
from app.companies.coverage import (
    build_evidence_contexts,
    calculate_captured_text_sha256,
    calculate_evidence_revision_sha256,
    canonical_evidence_revision_json,
    combine_article_text,
    unique_matched_aliases,
)
from app.companies.repository import company_candidate_condition
from app.media.collection.aliases import find_company_alias_matches
from app.media.repository import escaped_ilike_contains_pattern


def test_coverage_uses_shared_longest_boundary_matcher_and_combined_text_offsets() -> None:
    combined_text = combine_article_text(
        "阿里巴巴集团发布财报",
        "阿里营收增长，SuperOpenAI不匹配。",
    )
    company = MatchableCompany(
        company_id="company-alibaba",
        names=("阿里巴巴集团", "阿里巴巴", "阿里"),
    )

    matches = find_company_alias_matches(combined_text, (company,))
    contexts = build_evidence_contexts(combined_text, matches, context_radius=4)

    assert tuple(match.alias for match in matches) == ("阿里巴巴集团", "阿里")
    assert unique_matched_aliases(matches) == ("阿里巴巴集团", "阿里")
    assert combined_text[matches[0].start_offset : matches[0].end_offset] == "阿里巴巴集团"
    assert contexts[0].context == combined_text[0 : matches[0].end_offset + 4]
    assert contexts[1].end_offset <= len(combined_text)


def test_sql_candidate_patterns_escape_postgresql_wildcards() -> None:
    assert escaped_ilike_contains_pattern(r"ACME_100%\\CN") == r"%ACME\_100\%\\\\CN%"

    compiled = str(company_candidate_condition(("ACME_100%",)).compile())

    assert "lower(media_articles.title) LIKE lower(:title_1) ESCAPE" in compiled
    assert "lower(media_articles.content) LIKE lower(:content_1) ESCAPE" in compiled


def test_coverage_revision_digest_hashes_exact_offset_text() -> None:
    combined_text = combine_article_text("  Acme title", "Body  \n")

    digest = calculate_captured_text_sha256("  Acme title", "Body  \n")

    assert digest == sha256(combined_text.encode("utf-8")).hexdigest()


def test_evidence_revision_digest_is_canonical_and_covers_frozen_provenance() -> None:
    source_id = uuid4()
    published_at = datetime(2026, 8, 12, 8, 30, tzinfo=UTC)
    crawled_at = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
    arguments = (
        "Acme title",
        "Acme body",
        "Acme summary",
        "https://example.com/acme",
        published_at,
        crawled_at,
        "US",
        source_id,
        "Example News",
    )

    canonical_json = canonical_evidence_revision_json(*arguments)
    digest = calculate_evidence_revision_sha256(*arguments)

    assert digest == sha256(canonical_json.encode("utf-8")).hexdigest()
    assert json.loads(canonical_json) == {
        "content": "Acme body",
        "country_code": "US",
        "crawled_at": "2026-08-12T09:00:00.000000Z",
        "published_at": "2026-08-12T08:30:00.000000Z",
        "source_id": str(source_id),
        "source_name": "Example News",
        "summary": "Acme summary",
        "title": "Acme title",
        "url": "https://example.com/acme",
    }
    equivalent_offset_arguments = (
        *arguments[:4],
        published_at.astimezone(UTC) + timedelta(hours=0),
        crawled_at,
        *arguments[6:],
    )
    assert calculate_evidence_revision_sha256(*equivalent_offset_arguments) == digest

    for index, replacement in (
        (0, "Changed title"),
        (1, "Changed body"),
        (2, "Changed summary"),
        (3, "https://example.com/changed"),
        (4, published_at + timedelta(seconds=1)),
        (5, crawled_at + timedelta(seconds=1)),
        (6, "CN"),
        (7, uuid4()),
        (8, "Changed News"),
    ):
        changed_arguments = (*arguments[:index], replacement, *arguments[index + 1 :])
        assert calculate_evidence_revision_sha256(*changed_arguments) != digest
