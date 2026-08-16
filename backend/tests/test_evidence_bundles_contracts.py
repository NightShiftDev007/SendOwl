"""Evidence Bundle addressing and strict projection invariants."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.evidence.contracts import (
    EvidenceBundleContent,
    EvidenceBundleDetail,
    EvidenceBundleItem,
    EvidenceBundleSummary,
    calculate_content_sha256,
)
from app.evidence.hashing import (
    calculate_evidence_bundle_sha256,
    canonical_evidence_bundle_json,
)
from app.world_models.contracts import SnapshotEvidence
from app.world_models.hashing import calculate_snapshot_sha256


def _bundle_values() -> tuple[dict[str, object], EvidenceBundleItem]:
    bundle_id = uuid4()
    world_model_id = uuid4()
    article_id = uuid4()
    captured_text = "Evidence title\nVerified frozen article body."
    captured_digest = calculate_content_sha256(captured_text)
    evidence = SnapshotEvidence(
        article_id=article_id,
        source_name="Example Media",
        original_url="https://example.com/evidence",
        title="Evidence title",
        published_at=datetime(2026, 8, 13, 1, 0, tzinfo=UTC),
        captured_at=datetime(2026, 8, 13, 1, 5, tzinfo=UTC),
        country_code="CN",
        excerpt="Verified frozen article body.",
        captured_text_sha256=captured_digest,
    )
    snapshot_sha256 = calculate_snapshot_sha256(
        world_model_id,
        1,
        "human_confirmed",
        (evidence,),
        (),
    )
    item = EvidenceBundleItem(
        position=0,
        kind="media_article",
        **evidence.model_dump(),
    )
    return (
        {
            "id": bundle_id,
            "bundle_sha256": calculate_evidence_bundle_sha256(bundle_id, snapshot_sha256),
            "title": "Verified evidence baseline",
            "world_model_id": world_model_id,
            "world_snapshot_id": bundle_id,
            "version": 1,
            "verification": "human_confirmed",
            "snapshot_sha256": snapshot_sha256,
            "item_count": 1,
            "policy_item_count": 0,
            "created_at": datetime(2026, 8, 13, 1, 10, tzinfo=UTC),
        },
        item,
    )


def test_bundle_address_is_canonical_and_recomputable_from_summary() -> None:
    values, _ = _bundle_values()
    bundle_id = values["id"]
    snapshot_sha256 = values["snapshot_sha256"]
    assert canonical_evidence_bundle_json(bundle_id, snapshot_sha256) == (
        '{"bundle_id":"'
        + str(bundle_id)
        + '","schema_version":"evidence-bundle/v1","snapshot_sha256":"'
        + str(snapshot_sha256)
        + '"}'
    )

    summary = EvidenceBundleSummary(**values)

    assert summary.bundle_sha256 == calculate_evidence_bundle_sha256(
        summary.id,
        summary.snapshot_sha256,
    )


def test_bundle_detail_recomputes_snapshot_identity_from_ordered_items() -> None:
    values, item = _bundle_values()

    detail = EvidenceBundleDetail(**values, items=(item,), policy_items=())

    assert detail.id == detail.world_snapshot_id
    with pytest.raises(ValidationError, match="bundle item positions must be contiguous"):
        EvidenceBundleDetail(
            **values,
            items=(item.model_copy(update={"position": 1}),),
            policy_items=(),
        )
    with pytest.raises(ValidationError, match="bundle items do not match snapshot_sha256"):
        EvidenceBundleDetail(
            **values,
            items=(item.model_copy(update={"title": "Altered evidence title"}),),
            policy_items=(),
        )


def test_bundle_summary_and_content_reject_forged_digests() -> None:
    values, item = _bundle_values()
    with pytest.raises(ValidationError, match="bundle_sha256 must bind"):
        EvidenceBundleSummary(**{**values, "bundle_sha256": "0" * 64})

    content = "Evidence title\nVerified frozen article body."
    valid = EvidenceBundleContent(
        bundle_id=values["id"],
        bundle_sha256=values["bundle_sha256"],
        article_id=item.article_id,
        captured_text=content,
        captured_text_sha256=calculate_content_sha256(content),
    )
    assert valid.captured_text == content
    with pytest.raises(ValidationError, match="captured_text_sha256 must match"):
        EvidenceBundleContent(
            bundle_id=values["id"],
            bundle_sha256=values["bundle_sha256"],
            article_id=item.article_id,
            captured_text=content,
            captured_text_sha256="0" * 64,
        )
