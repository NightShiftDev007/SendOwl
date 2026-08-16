"""Read-only Evidence Bundle projections over sealed WorldSnapshot storage."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.evidence.contracts import (
    EvidenceBundleContent,
    EvidenceBundleDetail,
    EvidenceBundleItem,
    EvidenceBundlePolicyContent,
    EvidenceBundlePolicyItem,
    EvidenceBundlesResponse,
    EvidenceBundleSummary,
)
from app.evidence.errors import EvidenceBundleItemNotFoundError, EvidenceBundleNotFoundError
from app.evidence.hashing import calculate_evidence_bundle_sha256
from app.world_models.models import (
    WorldModelRecord,
    WorldSnapshotEvidenceRecord,
    WorldSnapshotPolicyEvidenceRecord,
    WorldSnapshotRecord,
)
from app.world_models.repository import (
    get_world_snapshot,
    get_world_snapshot_evidence_content,
    get_world_snapshot_policy_evidence_content,
)


def _bundle_summary(
    snapshot: WorldSnapshotRecord,
    world_model_title: str,
    item_count: int,
    policy_item_count: int,
) -> EvidenceBundleSummary:
    if snapshot.sealed_at is None:
        raise RuntimeError(f"world snapshot {snapshot.id} is not sealed")
    return EvidenceBundleSummary(
        id=snapshot.id,
        bundle_sha256=calculate_evidence_bundle_sha256(
            snapshot.id,
            snapshot.snapshot_sha256,
        ),
        title=world_model_title,
        world_model_id=snapshot.world_model_id,
        world_snapshot_id=snapshot.id,
        version=snapshot.version,
        verification=snapshot.verification,
        snapshot_sha256=snapshot.snapshot_sha256,
        item_count=item_count,
        policy_item_count=policy_item_count,
        created_at=snapshot.created_at,
    )


async def list_evidence_bundles(session: AsyncSession) -> EvidenceBundlesResponse:
    """List sealed bundles without loading their potentially large captured text."""
    item_count = (
        select(func.count(WorldSnapshotEvidenceRecord.position))
        .where(WorldSnapshotEvidenceRecord.snapshot_id == WorldSnapshotRecord.id)
        .correlate(WorldSnapshotRecord)
        .scalar_subquery()
    )
    policy_item_count = (
        select(func.count(WorldSnapshotPolicyEvidenceRecord.position))
        .where(WorldSnapshotPolicyEvidenceRecord.snapshot_id == WorldSnapshotRecord.id)
        .correlate(WorldSnapshotRecord)
        .scalar_subquery()
    )
    rows = (
        await session.execute(
            select(
                WorldSnapshotRecord,
                WorldModelRecord.title,
                item_count.label("item_count"),
                policy_item_count.label("policy_item_count"),
            )
            .join(
                WorldModelRecord,
                WorldModelRecord.id == WorldSnapshotRecord.world_model_id,
            )
            .where(WorldSnapshotRecord.sealed_at.is_not(None))
            .order_by(WorldSnapshotRecord.created_at.desc(), WorldSnapshotRecord.id.asc())
        )
    ).all()
    items = tuple(
        _bundle_summary(snapshot, world_model_title, int(count), int(policy_count))
        for snapshot, world_model_title, count, policy_count in rows
    )
    return EvidenceBundlesResponse(items=items, total=len(items))


async def _bundle_source(
    session: AsyncSession,
    bundle_id: UUID,
) -> tuple[WorldSnapshotRecord, str]:
    row = (
        await session.execute(
            select(WorldSnapshotRecord, WorldModelRecord.title)
            .join(
                WorldModelRecord,
                WorldModelRecord.id == WorldSnapshotRecord.world_model_id,
            )
            .where(
                WorldSnapshotRecord.id == bundle_id,
                WorldSnapshotRecord.sealed_at.is_not(None),
            )
        )
    ).one_or_none()
    if row is None:
        raise EvidenceBundleNotFoundError(f"sealed evidence bundle {bundle_id} was not found")
    return row[0], row[1]


async def get_evidence_bundle(
    session: AsyncSession,
    bundle_id: UUID,
) -> EvidenceBundleDetail:
    """Return one bundle after the existing snapshot reader verifies all frozen content."""
    snapshot, world_model_title = await _bundle_source(session, bundle_id)
    verified = await get_world_snapshot(session, snapshot.world_model_id, snapshot.id)
    items = tuple(
        EvidenceBundleItem(
            position=position,
            kind="media_article",
            article_id=evidence.article_id,
            source_name=evidence.source_name,
            original_url=evidence.original_url,
            title=evidence.title,
            published_at=evidence.published_at,
            captured_at=evidence.captured_at,
            country_code=evidence.country_code,
            excerpt=evidence.excerpt,
            captured_text_sha256=evidence.captured_text_sha256,
        )
        for position, evidence in enumerate(verified.evidence)
    )
    policy_items = tuple(
        EvidenceBundlePolicyItem(
            **evidence.model_dump(mode="python"),
            position=position,
            kind="policy_document",
        )
        for position, evidence in enumerate(verified.policy_evidence)
    )
    summary = _bundle_summary(snapshot, world_model_title, len(items), len(policy_items))
    return EvidenceBundleDetail(
        **summary.model_dump(),
        items=items,
        policy_items=policy_items,
    )


async def get_evidence_bundle_content(
    session: AsyncSession,
    bundle_id: UUID,
    article_id: UUID,
) -> EvidenceBundleContent:
    """Return exact frozen text only when it belongs to the verified bundle."""
    bundle = await get_evidence_bundle(session, bundle_id)
    item = next(
        (candidate for candidate in bundle.items if candidate.article_id == article_id),
        None,
    )
    if item is None:
        raise EvidenceBundleItemNotFoundError(
            f"article {article_id} was not found in sealed evidence bundle {bundle_id}"
        )
    content = await get_world_snapshot_evidence_content(
        session,
        bundle.world_model_id,
        bundle.world_snapshot_id,
        article_id,
    )
    if content.captured_text_sha256 != item.captured_text_sha256:
        raise RuntimeError(
            f"evidence bundle {bundle_id} article {article_id} metadata/content digest mismatch"
        )
    return EvidenceBundleContent(
        bundle_id=bundle.id,
        bundle_sha256=bundle.bundle_sha256,
        article_id=content.article_id,
        captured_text=content.captured_text,
        captured_text_sha256=content.captured_text_sha256,
    )


async def get_evidence_bundle_policy_content(
    session: AsyncSession,
    bundle_id: UUID,
    policy_version_id: UUID,
) -> EvidenceBundlePolicyContent:
    """Return exact frozen Policy text only when it belongs to the verified bundle."""
    bundle = await get_evidence_bundle(session, bundle_id)
    item = next(
        (
            candidate
            for candidate in bundle.policy_items
            if candidate.policy_version_id == policy_version_id
        ),
        None,
    )
    if item is None:
        raise EvidenceBundleItemNotFoundError(
            f"Policy version {policy_version_id} was not found in sealed evidence bundle "
            f"{bundle_id}"
        )
    content = await get_world_snapshot_policy_evidence_content(
        session,
        bundle.world_model_id,
        bundle.world_snapshot_id,
        policy_version_id,
    )
    if content.content_sha256 != item.content_sha256:
        raise RuntimeError(
            f"evidence bundle {bundle_id} Policy version {policy_version_id} "
            "metadata/content digest mismatch"
        )
    return EvidenceBundlePolicyContent(
        bundle_id=bundle.id,
        bundle_sha256=bundle.bundle_sha256,
        policy_version_id=content.policy_version_id,
        captured_text=content.captured_text,
        content_sha256=content.content_sha256,
    )


__all__ = [
    "get_evidence_bundle",
    "get_evidence_bundle_content",
    "get_evidence_bundle_policy_content",
    "list_evidence_bundles",
]
