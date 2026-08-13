"""Contract validation smoke tests for external media input."""

import json

import pytest
from pydantic import ValidationError

from app.evidence.contracts import EvidenceBundle, EvidenceItem, calculate_content_sha256
from app.media.contracts import MediaArticle


def build_raw_article() -> dict[str, object]:
    return {
        "article_id": "article-001",
        "source": {
            "source_id": "source-001",
            "name": "Example Media",
            "canonical_url": "https://example.com",
            "kind": "web",
        },
        "url": "https://example.com/articles/1",
        "title": "Company announces a product recall",
        "author": None,
        "content": "The company announced a voluntary product recall.",
        "language": "en",
        "published_at": "2026-08-12T08:00:00Z",
        "captured_at": "2026-08-12T08:05:00Z",
        "collector_internal_state": "ignored",
    }


def build_raw_evidence(evidence_id: str) -> dict[str, object]:
    raw_article = build_raw_article()
    content = str(raw_article["content"])
    return {
        "evidence_id": evidence_id,
        "kind": "media_article",
        "article": raw_article,
        "content_sha256": calculate_content_sha256(content),
    }


def test_media_article_validates_strict_json_and_ignores_extras() -> None:
    raw_article = build_raw_article()

    article = MediaArticle.model_validate_json(json.dumps(raw_article))

    assert article.article_id == "article-001"
    assert "collector_internal_state" not in article.model_dump()

    invalid_article = raw_article | {"title": 123}
    with pytest.raises(ValidationError):
        MediaArticle.model_validate_json(json.dumps(invalid_article))


def test_evidence_item_rejects_a_digest_that_does_not_match_content() -> None:
    raw_evidence = build_raw_evidence("evidence-001")

    evidence = EvidenceItem.model_validate_json(json.dumps(raw_evidence))

    assert evidence.content_sha256 == calculate_content_sha256(evidence.article.content)

    invalid_evidence = raw_evidence | {"content_sha256": "0" * 64}
    with pytest.raises(ValidationError, match="must match the captured article content"):
        EvidenceItem.model_validate_json(json.dumps(invalid_evidence))


def test_evidence_bundle_rejects_duplicate_evidence_ids() -> None:
    raw_evidence = build_raw_evidence("evidence-001")
    raw_bundle: dict[str, object] = {
        "bundle_id": "bundle-001",
        "title": "Product recall evidence",
        "created_at": "2026-08-12T08:10:00Z",
        "items": [raw_evidence, raw_evidence],
    }

    with pytest.raises(
        ValidationError,
        match="items must use unique evidence_id values; duplicates: evidence-001",
    ):
        EvidenceBundle.model_validate_json(json.dumps(raw_bundle))
