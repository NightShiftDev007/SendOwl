"""Strict public-contract and deterministic-hash checks for world snapshots."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.companies.contracts import CompanyEvidenceContext
from app.companies.coverage import calculate_captured_text_sha256
from app.world_models.contracts import (
    SnapshotCompany,
    SnapshotEvidence,
    SnapshotEvidenceContent,
    WorldModelCreateRequest,
    WorldSnapshotCreateRequest,
    WorldSnapshotEvidenceSelection,
)
from app.world_models.errors import SnapshotEvidenceLimitError
from app.world_models.hashing import calculate_snapshot_sha256, canonical_snapshot_json
from app.world_models.repository import (
    MAX_SNAPSHOT_CAPTURED_TEXT_UTF8_BYTES_PER_ARTICLE,
    MAX_SNAPSHOT_TOTAL_MENTIONS,
    _selected_article_metadata_statement,
    _selected_source_statement,
    _stale_selection_article_ids,
    _validate_captured_text_byte_count,
    _validate_snapshot_mention_limit,
)


def _snapshot_evidence(article_id: object) -> SnapshotEvidence:
    captured_at = datetime(2026, 8, 12, 8, 30, tzinfo=UTC)
    title = "Acme opens a verified facility"
    content = "Acme confirmed the new facility."
    return SnapshotEvidence(
        article_id=article_id,
        source_name="Example News",
        original_url="https://example.com/acme-facility",
        title=title,
        published_at=datetime(2026, 8, 12, 8, 0, tzinfo=UTC),
        captured_at=captured_at,
        country_code="US",
        excerpt=content,
        captured_text_sha256=calculate_captured_text_sha256(title, content),
        matched_aliases=("Acme",),
        evidence_contexts=(
            CompanyEvidenceContext(
                alias="Acme",
                start_offset=0,
                end_offset=4,
                context=f"{title}\n{content}",
            ),
        ),
    )


def test_create_contract_accepts_json_array_and_rejects_duplicate_article_ids() -> None:
    article_id = uuid4()
    digest = "a" * 64

    request = WorldModelCreateRequest.model_validate(
        {
            "title": "Verified Acme context",
            "company_id": str(uuid4()),
            "evidence": [
                {
                    "article_id": str(article_id),
                    "evidence_revision_sha256": digest,
                }
            ],
            "verification": "human_confirmed",
        },
        strict=True,
    )

    assert request.evidence == (
        WorldSnapshotEvidenceSelection(
            article_id=article_id,
            evidence_revision_sha256=digest,
        ),
    )
    with pytest.raises(ValidationError, match="duplicate article IDs"):
        WorldSnapshotCreateRequest.model_validate(
            {
                "evidence": [
                    {
                        "article_id": str(article_id),
                        "evidence_revision_sha256": digest,
                    },
                    {
                        "article_id": str(article_id),
                        "evidence_revision_sha256": digest,
                    },
                ],
                "verification": "human_confirmed",
            },
            strict=True,
        )


def test_request_contract_reports_the_invalid_uuid_position() -> None:
    with pytest.raises(ValidationError) as raised:
        WorldSnapshotCreateRequest.model_validate(
            {
                "evidence": [
                    {
                        "article_id": str(uuid4()),
                        "evidence_revision_sha256": "a" * 64,
                    },
                    {
                        "article_id": "not-a-uuid",
                        "evidence_revision_sha256": "b" * 64,
                    },
                ],
                "verification": "human_confirmed",
            },
            strict=True,
        )

    assert raised.value.errors()[0]["loc"] == ("evidence", 1, "article_id")
    assert "not-a-uuid" in raised.value.errors()[0]["msg"]


def test_snapshot_evidence_content_preserves_exact_frozen_whitespace() -> None:
    article_id = uuid4()
    captured_text = "  Title  \nBody with trailing whitespace  \n"
    digest = calculate_captured_text_sha256("  Title  ", "Body with trailing whitespace  \n")

    content = SnapshotEvidenceContent(
        article_id=article_id,
        captured_text=captured_text,
        captured_text_sha256=digest,
    )

    assert content.model_dump() == {
        "article_id": article_id,
        "captured_text": captured_text,
        "captured_text_sha256": digest,
    }


def test_revision_comparison_reports_stale_articles_in_request_order() -> None:
    first_id = uuid4()
    second_id = uuid4()
    missing_id = uuid4()
    selections = (
        WorldSnapshotEvidenceSelection(
            article_id=first_id,
            evidence_revision_sha256="a" * 64,
        ),
        WorldSnapshotEvidenceSelection(
            article_id=missing_id,
            evidence_revision_sha256="b" * 64,
        ),
        WorldSnapshotEvidenceSelection(
            article_id=second_id,
            evidence_revision_sha256="c" * 64,
        ),
    )

    stale = _stale_selection_article_ids(
        selections,
        {
            first_id: "f" * 64,
            second_id: "e" * 64,
        },
    )

    assert stale == (first_id, second_id)


def test_snapshot_metadata_query_locks_media_rows_before_loading_text() -> None:
    statement = _selected_article_metadata_statement((uuid4(), uuid4()))

    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert "octet_length" in sql
    assert "ORDER BY media_articles.id" in sql
    assert "FOR UPDATE OF media_articles" in sql

    source_sql = str(
        _selected_source_statement((uuid4(), uuid4())).compile(dialect=postgresql.dialect())
    )
    assert "ORDER BY media_sources.id" in source_sql
    assert "FOR UPDATE OF media_sources" in source_sql


def test_snapshot_resource_limits_report_article_actual_and_limit() -> None:
    article_id = uuid4()
    oversized_text = "界" * (
        MAX_SNAPSHOT_CAPTURED_TEXT_UTF8_BYTES_PER_ARTICLE // len("界".encode()) + 1
    )

    with pytest.raises(SnapshotEvidenceLimitError) as captured_text_error:
        _validate_captured_text_byte_count(article_id, len(oversized_text.encode("utf-8")))
    assert captured_text_error.value.article_ids == (article_id,)
    assert captured_text_error.value.actual == len(oversized_text.encode("utf-8"))
    assert captured_text_error.value.limit == MAX_SNAPSHOT_CAPTURED_TEXT_UTF8_BYTES_PER_ARTICLE

    with pytest.raises(SnapshotEvidenceLimitError) as snapshot_match_error:
        _validate_snapshot_mention_limit(
            (article_id,),
            MAX_SNAPSHOT_TOTAL_MENTIONS + 1,
        )
    assert snapshot_match_error.value.article_ids == (article_id,)
    assert snapshot_match_error.value.limit == MAX_SNAPSHOT_TOTAL_MENTIONS


def test_snapshot_hash_is_canonical_and_order_sensitive() -> None:
    model_id = uuid4()
    company = SnapshotCompany(id=uuid4(), canonical_name="Acme", aliases=("Acme Inc.",))
    first = _snapshot_evidence(uuid4())
    second = _snapshot_evidence(uuid4())
    evidence = (first, second)

    first_json = canonical_snapshot_json(
        model_id,
        1,
        "human_confirmed",
        company,
        evidence,
    )
    second_json = canonical_snapshot_json(
        model_id,
        1,
        "human_confirmed",
        company,
        evidence,
    )

    assert first_json == second_json
    assert calculate_snapshot_sha256(
        model_id,
        1,
        "human_confirmed",
        company,
        evidence,
    ) != calculate_snapshot_sha256(
        model_id,
        1,
        "human_confirmed",
        company,
        tuple(reversed(evidence)),
    )


def test_captured_text_digest_uses_title_newline_and_optional_content() -> None:
    assert calculate_captured_text_sha256("Title", None) == calculate_captured_text_sha256(
        "Title", ""
    )
    assert calculate_captured_text_sha256("Title", "Body") != calculate_captured_text_sha256(
        "Title", "body"
    )
