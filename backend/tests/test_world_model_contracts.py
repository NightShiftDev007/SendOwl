"""Strict public-contract and deterministic-hash checks for world snapshots."""

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.evidence.revisions import calculate_captured_text_sha256
from app.policy_evidence.hashing import (
    calculate_policy_content_sha256,
    calculate_policy_document_sha256,
    calculate_policy_source_sha256,
    calculate_policy_version_sha256,
)
from app.world_models.contracts import (
    SnapshotEvidence,
    SnapshotEvidenceContent,
    SnapshotPolicyEvidence,
    WorldModelCreateRequest,
    WorldSnapshotCreateRequest,
    WorldSnapshotEvidenceSelection,
    WorldSnapshotPolicyEvidenceSelection,
)
from app.world_models.errors import SnapshotEvidenceLimitError
from app.world_models.hashing import calculate_snapshot_sha256, canonical_snapshot_json
from app.world_models.repository import (
    MAX_SNAPSHOT_CAPTURED_TEXT_UTF8_BYTES_PER_ARTICLE,
    _selected_article_metadata_statement,
    _selected_source_statement,
    _stale_selection_article_ids,
    _validate_captured_text_byte_count,
)


def _snapshot_evidence(article_id: object) -> SnapshotEvidence:
    title = "Verified event report"
    content = "The event was confirmed by the cited source."
    return SnapshotEvidence(
        article_id=article_id,
        source_name="Example News",
        original_url="https://example.com/event",
        title=title,
        published_at=datetime(2026, 8, 12, 8, 0, tzinfo=UTC),
        captured_at=datetime(2026, 8, 12, 8, 30, tzinfo=UTC),
        country_code="US",
        excerpt=content,
        captured_text_sha256=calculate_captured_text_sha256(title, content),
    )


def _snapshot_policy_evidence(policy_version_id: object) -> SnapshotPolicyEvidence:
    homepage_url = "https://policy.example.gov/"
    original_url = "https://policy.example.gov/documents/17"
    source_sha256 = calculate_policy_source_sha256("Example Authority", "EX", homepage_url)
    document_sha256 = calculate_policy_document_sha256(source_sha256, "EX-2026-17")
    content_sha256 = calculate_policy_content_sha256("Frozen Policy text")
    publication_date = date(2026, 8, 1)
    effective_from = date(2026, 9, 1)
    version_sha256 = calculate_policy_version_sha256(
        document_sha256,
        "Example Policy",
        original_url,
        "en",
        publication_date,
        effective_from,
        None,
        content_sha256,
    )
    return SnapshotPolicyEvidence(
        policy_version_id=policy_version_id,
        authority_name="Example Authority",
        jurisdiction_code="EX",
        homepage_url=homepage_url,
        canonical_identifier="EX-2026-17",
        source_sha256=source_sha256,
        document_sha256=document_sha256,
        version=1,
        title="Example Policy",
        original_url=original_url,
        language="en",
        publication_date=publication_date,
        effective_from=effective_from,
        effective_until=None,
        captured_at=datetime(2026, 8, 16, tzinfo=UTC),
        content_sha256=content_sha256,
        version_sha256=version_sha256,
    )


def test_create_contract_is_generic_and_rejects_duplicate_article_ids() -> None:
    article_id = uuid4()
    digest = "a" * 64
    request = WorldModelCreateRequest.model_validate(
        {
            "title": "Verified world context",
            "evidence": [{"article_id": str(article_id), "evidence_revision_sha256": digest}],
            "policy_evidence": [],
            "verification": "human_confirmed",
        },
        strict=True,
    )
    assert request.model_dump().keys() == {
        "title",
        "evidence",
        "policy_evidence",
        "verification",
    }
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
                    {"article_id": str(article_id), "evidence_revision_sha256": digest},
                    {"article_id": str(article_id), "evidence_revision_sha256": digest},
                ],
                "policy_evidence": [],
                "verification": "human_confirmed",
            },
            strict=True,
        )


def test_request_contract_reports_the_invalid_uuid_position() -> None:
    with pytest.raises(ValidationError) as raised:
        WorldSnapshotCreateRequest.model_validate(
            {
                "evidence": [
                    {"article_id": str(uuid4()), "evidence_revision_sha256": "a" * 64},
                    {"article_id": "not-a-uuid", "evidence_revision_sha256": "b" * 64},
                ],
                "policy_evidence": [],
                "verification": "human_confirmed",
            },
            strict=True,
        )
    assert raised.value.errors()[0]["loc"] == ("evidence", 1, "article_id")


def test_request_contract_rejects_duplicate_policy_versions() -> None:
    policy_version_id = uuid4()
    selection = {
        "policy_version_id": str(policy_version_id),
        "version_sha256": "a" * 64,
    }
    with pytest.raises(ValidationError, match="duplicate Policy version IDs"):
        WorldSnapshotCreateRequest.model_validate(
            {
                "evidence": [
                    {
                        "article_id": str(uuid4()),
                        "evidence_revision_sha256": "b" * 64,
                    }
                ],
                "policy_evidence": [selection, selection],
                "verification": "human_confirmed",
            },
            strict=True,
        )
    assert WorldSnapshotPolicyEvidenceSelection.model_validate(selection).policy_version_id == (
        policy_version_id
    )


def test_snapshot_evidence_content_preserves_exact_frozen_whitespace() -> None:
    article_id = uuid4()
    captured_text = "  Title  \nBody with trailing whitespace  \n"
    digest = calculate_captured_text_sha256("  Title  ", "Body with trailing whitespace  \n")
    content = SnapshotEvidenceContent(
        article_id=article_id,
        captured_text=captured_text,
        captured_text_sha256=digest,
    )
    assert content.captured_text == captured_text


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
    assert _stale_selection_article_ids(
        selections,
        {first_id: "f" * 64, second_id: "e" * 64},
    ) == (first_id, second_id)


def test_snapshot_metadata_query_locks_media_rows_before_loading_text() -> None:
    sql = str(
        _selected_article_metadata_statement((uuid4(), uuid4())).compile(
            dialect=postgresql.dialect()
        )
    )
    assert "octet_length" in sql
    assert "ORDER BY media_articles.id" in sql
    assert "FOR UPDATE OF media_articles" in sql
    source_sql = str(
        _selected_source_statement((uuid4(), uuid4())).compile(dialect=postgresql.dialect())
    )
    assert "ORDER BY media_sources.id" in source_sql
    assert "FOR UPDATE OF media_sources" in source_sql


def test_snapshot_captured_text_limit_reports_article_actual_and_limit() -> None:
    article_id = uuid4()
    oversized_text = "界" * (
        MAX_SNAPSHOT_CAPTURED_TEXT_UTF8_BYTES_PER_ARTICLE // len("界".encode()) + 1
    )
    with pytest.raises(SnapshotEvidenceLimitError) as raised:
        _validate_captured_text_byte_count(article_id, len(oversized_text.encode("utf-8")))
    assert raised.value.article_ids == (article_id,)
    assert raised.value.limit == MAX_SNAPSHOT_CAPTURED_TEXT_UTF8_BYTES_PER_ARTICLE


def test_snapshot_v2_hash_is_generic_canonical_and_order_sensitive() -> None:
    model_id = uuid4()
    evidence = (_snapshot_evidence(uuid4()), _snapshot_evidence(uuid4()))
    canonical = canonical_snapshot_json(model_id, 1, "human_confirmed", evidence, ())
    assert '"schema_version":"world-snapshot/v2"' in canonical
    assert "company" not in canonical
    assert "alias" not in canonical
    assert calculate_snapshot_sha256(
        model_id,
        1,
        "human_confirmed",
        evidence,
        (),
    ) != calculate_snapshot_sha256(
        model_id,
        1,
        "human_confirmed",
        tuple(reversed(evidence)),
        (),
    )


def test_snapshot_v3_hash_binds_ordered_policy_versions_without_changing_v2() -> None:
    model_id = uuid4()
    evidence = (_snapshot_evidence(uuid4()),)
    first_policy = _snapshot_policy_evidence(uuid4())
    second_policy = _snapshot_policy_evidence(uuid4())

    v2 = canonical_snapshot_json(model_id, 1, "human_confirmed", evidence, ())
    v3 = canonical_snapshot_json(
        model_id,
        1,
        "human_confirmed",
        evidence,
        (first_policy, second_policy),
    )

    assert '"schema_version":"world-snapshot/v2"' in v2
    assert '"policy_evidence"' not in v2
    assert '"schema_version":"world-snapshot/v3"' in v3
    assert str(first_policy.policy_version_id) in v3
    assert calculate_snapshot_sha256(
        model_id,
        1,
        "human_confirmed",
        evidence,
        (first_policy, second_policy),
    ) != calculate_snapshot_sha256(
        model_id,
        1,
        "human_confirmed",
        evidence,
        (second_policy, first_policy),
    )


def test_captured_text_digest_uses_title_newline_and_optional_content() -> None:
    assert calculate_captured_text_sha256("Title", None) == calculate_captured_text_sha256(
        "Title", ""
    )
    assert calculate_captured_text_sha256("Title", "Body") != calculate_captured_text_sha256(
        "Title", "body"
    )
