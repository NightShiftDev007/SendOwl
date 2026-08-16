"""Transactional persistence for versioned, immutable world-model snapshots."""

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.evidence.revisions import (
    calculate_captured_text_sha256,
    calculate_evidence_revision_sha256,
    combine_article_text,
)
from app.media.locking import IMPORT_ADVISORY_LOCK_KEY
from app.media.models import MediaArticleRecord, MediaSourceRecord
from app.policy_evidence.hashing import calculate_policy_content_sha256
from app.policy_evidence.models import (
    PolicyDocumentRecord,
    PolicyDocumentVersionRecord,
    PolicySourceRecord,
)
from app.world_models.contracts import (
    ModelDetail,
    ModelSummary,
    SnapshotDetail,
    SnapshotEvidence,
    SnapshotEvidenceContent,
    SnapshotPolicyEvidence,
    SnapshotPolicyEvidenceContent,
    SnapshotSummary,
    Verification,
    WorldModelCreateRequest,
    WorldModelsResponse,
    WorldSnapshotCreateRequest,
    WorldSnapshotEvidenceSelection,
    WorldSnapshotPolicyEvidenceSelection,
)
from app.world_models.errors import (
    SnapshotEvidenceLimitError,
    SnapshotEvidenceSelectionError,
    SnapshotPolicyEvidenceSelectionError,
    WorldModelNotFoundError,
    WorldSnapshotEvidenceNotFoundError,
    WorldSnapshotNotFoundError,
    WorldSnapshotPolicyEvidenceNotFoundError,
    WorldSnapshotRevisionConflictError,
)
from app.world_models.hashing import calculate_snapshot_sha256
from app.world_models.models import (
    WorldModelRecord,
    WorldSnapshotEvidenceRecord,
    WorldSnapshotPolicyEvidenceRecord,
    WorldSnapshotRecord,
)

SNAPSHOT_EXCERPT_LENGTH = 280
MAX_SNAPSHOT_CAPTURED_TEXT_UTF8_BYTES_PER_ARTICLE = 2 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class PreparedEvidence:
    """Validated public evidence plus its complete frozen text."""

    item: SnapshotEvidence
    captured_text: str


@dataclass(frozen=True, slots=True)
class PreparedPolicyEvidence:
    """Validated immutable Policy version plus its complete frozen text."""

    item: SnapshotPolicyEvidence
    captured_text: str


def _article_excerpt(title: str, content: str | None, summary: str | None) -> str:
    for value in (summary, content, title):
        if value is None:
            continue
        excerpt = value[:SNAPSHOT_EXCERPT_LENGTH].strip()
        if excerpt:
            return excerpt
    raise ValueError("selected media article has no non-whitespace title, summary, or content")


def _validate_captured_text_byte_count(article_id: UUID, captured_text_bytes: int) -> None:
    if captured_text_bytes > MAX_SNAPSHOT_CAPTURED_TEXT_UTF8_BYTES_PER_ARTICLE:
        raise SnapshotEvidenceLimitError(
            resource="captured_text UTF-8 bytes per article",
            article_ids=(article_id,),
            actual=captured_text_bytes,
            limit=MAX_SNAPSHOT_CAPTURED_TEXT_UTF8_BYTES_PER_ARTICLE,
        )


def _stale_selection_article_ids(
    selections: tuple[WorldSnapshotEvidenceSelection, ...],
    current_revision_by_id: dict[UUID, str],
) -> tuple[UUID, ...]:
    return tuple(
        selection.article_id
        for selection in selections
        if selection.article_id in current_revision_by_id
        and current_revision_by_id[selection.article_id] != selection.evidence_revision_sha256
    )


def _selected_article_metadata_statement(
    article_ids: tuple[UUID, ...],
) -> Select[tuple[UUID, UUID, bool, int]]:
    captured_text_size = func.octet_length(
        MediaArticleRecord.title + "\n" + func.coalesce(MediaArticleRecord.content, "")
    ).label("captured_text_size")
    return (
        select(
            MediaArticleRecord.id.label("article_id"),
            MediaArticleRecord.source_id.label("source_id"),
            MediaArticleRecord.is_duplicate,
            captured_text_size,
        )
        .where(
            MediaArticleRecord.id.in_(article_ids),
            MediaArticleRecord.source_present.is_(True),
        )
        .order_by(MediaArticleRecord.id)
        .with_for_update(of=MediaArticleRecord)
    )


def _selected_source_statement(source_ids: tuple[UUID, ...]) -> Select[tuple[MediaSourceRecord]]:
    return (
        select(MediaSourceRecord)
        .where(MediaSourceRecord.id.in_(source_ids))
        .order_by(MediaSourceRecord.id)
        .with_for_update(of=MediaSourceRecord)
    )


def _prepare_article(
    article: MediaArticleRecord,
    source: MediaSourceRecord,
    captured_text: str,
    captured_text_sha256: str,
) -> PreparedEvidence:
    return PreparedEvidence(
        item=SnapshotEvidence(
            article_id=article.id,
            source_name=source.name,
            original_url=article.url,
            title=article.title,
            published_at=article.published_at,
            captured_at=article.crawled_at,
            country_code=article.country_code,
            excerpt=_article_excerpt(article.title, article.content, article.summary),
            captured_text_sha256=captured_text_sha256,
        ),
        captured_text=captured_text,
    )


async def _load_selected_evidence(
    session: AsyncSession,
    selections: tuple[WorldSnapshotEvidenceSelection, ...],
) -> tuple[PreparedEvidence, ...]:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": IMPORT_ADVISORY_LOCK_KEY},
    )
    article_ids = tuple(selection.article_id for selection in selections)
    metadata_rows = (await session.execute(_selected_article_metadata_statement(article_ids))).all()
    metadata_by_id = {row.article_id: row for row in metadata_rows}
    missing_ids = tuple(
        article_id for article_id in article_ids if article_id not in metadata_by_id
    )
    duplicate_ids = tuple(
        article_id
        for article_id in article_ids
        if article_id in metadata_by_id and metadata_by_id[article_id].is_duplicate
    )
    if missing_ids or duplicate_ids:
        raise SnapshotEvidenceSelectionError(
            missing_article_ids=missing_ids,
            duplicate_article_ids=duplicate_ids,
        )
    for article_id in article_ids:
        _validate_captured_text_byte_count(
            article_id,
            int(metadata_by_id[article_id].captured_text_size),
        )

    source_ids = tuple(sorted({row.source_id for row in metadata_rows}))
    source_rows = tuple(
        (await session.execute(_selected_source_statement(source_ids))).scalars().all()
    )
    source_by_id = {source.id: source for source in source_rows}
    missing_source_ids = tuple(
        source_id for source_id in source_ids if source_id not in source_by_id
    )
    if missing_source_ids:
        raise RuntimeError(
            "selected media articles have no source rows despite foreign-key integrity; "
            "source IDs: " + ", ".join(str(value) for value in missing_source_ids)
        )

    selected_by_id: dict[UUID, MediaArticleRecord] = {}
    rows = await session.stream(
        select(MediaArticleRecord)
        .where(MediaArticleRecord.id.in_(article_ids))
        .order_by(MediaArticleRecord.id)
        .execution_options(yield_per=1)
    )
    async for article in rows.scalars():
        selected_by_id[article.id] = article
    missing_loaded_ids = tuple(
        article_id for article_id in article_ids if article_id not in selected_by_id
    )
    if missing_loaded_ids:
        raise RuntimeError(
            "selected media articles disappeared after their rows were locked; article IDs: "
            + ", ".join(str(value) for value in missing_loaded_ids)
        )

    prepared_by_id: dict[UUID, PreparedEvidence] = {}
    current_revision_by_id: dict[UUID, str] = {}
    for selection in selections:
        article = selected_by_id[selection.article_id]
        metadata = metadata_by_id[selection.article_id]
        if article.source_id != metadata.source_id:
            raise RuntimeError(
                f"selected media article {article.id} changed source_id after its row was locked"
            )
        source = source_by_id[article.source_id]
        captured_text = combine_article_text(article.title, article.content)
        _validate_captured_text_byte_count(article.id, len(captured_text.encode("utf-8")))
        captured_digest = calculate_captured_text_sha256(article.title, article.content)
        current_revision_by_id[article.id] = calculate_evidence_revision_sha256(
            article.title,
            article.content,
            article.summary,
            article.url,
            article.published_at,
            article.crawled_at,
            article.country_code,
            source.id,
            source.name,
        )
        prepared_by_id[article.id] = _prepare_article(
            article,
            source,
            captured_text,
            captured_digest,
        )
    stale_ids = _stale_selection_article_ids(selections, current_revision_by_id)
    if stale_ids:
        raise WorldSnapshotRevisionConflictError(stale_article_ids=stale_ids)
    return tuple(prepared_by_id[article_id] for article_id in article_ids)


async def _load_selected_policy_evidence(
    session: AsyncSession,
    selections: tuple[WorldSnapshotPolicyEvidenceSelection, ...],
) -> tuple[PreparedPolicyEvidence, ...]:
    if not selections:
        return ()
    version_ids = tuple(selection.policy_version_id for selection in selections)
    rows = tuple(
        (
            await session.execute(
                select(
                    PolicyDocumentVersionRecord,
                    PolicyDocumentRecord,
                    PolicySourceRecord,
                )
                .join(
                    PolicyDocumentRecord,
                    PolicyDocumentRecord.id == PolicyDocumentVersionRecord.document_id,
                )
                .join(
                    PolicySourceRecord,
                    PolicySourceRecord.id == PolicyDocumentRecord.source_id,
                )
                .where(PolicyDocumentVersionRecord.id.in_(version_ids))
                .order_by(PolicyDocumentVersionRecord.id)
            )
        ).all()
    )
    row_by_id = {version.id: (version, document, source) for version, document, source in rows}
    missing_ids = tuple(version_id for version_id in version_ids if version_id not in row_by_id)
    mismatched_ids = tuple(
        selection.policy_version_id
        for selection in selections
        if selection.policy_version_id in row_by_id
        and row_by_id[selection.policy_version_id][0].version_sha256 != selection.version_sha256
    )
    if missing_ids or mismatched_ids:
        raise SnapshotPolicyEvidenceSelectionError(
            missing_policy_version_ids=missing_ids,
            mismatched_policy_version_ids=mismatched_ids,
        )

    prepared: list[PreparedPolicyEvidence] = []
    for selection in selections:
        version, document, source = row_by_id[selection.policy_version_id]
        actual_content_sha256 = calculate_policy_content_sha256(version.captured_text)
        if actual_content_sha256 != version.content_sha256:
            raise RuntimeError(
                f"Policy version {version.id} captured text does not match content_sha256"
            )
        prepared.append(
            PreparedPolicyEvidence(
                item=SnapshotPolicyEvidence(
                    policy_version_id=version.id,
                    authority_name=source.authority_name,
                    jurisdiction_code=source.jurisdiction_code,
                    homepage_url=source.homepage_url,
                    canonical_identifier=document.canonical_identifier,
                    source_sha256=source.source_sha256,
                    document_sha256=document.document_sha256,
                    version=version.version,
                    title=version.title,
                    original_url=version.original_url,
                    language=version.language,
                    publication_date=version.publication_date,
                    effective_from=version.effective_from,
                    effective_until=version.effective_until,
                    captured_at=version.captured_at,
                    content_sha256=version.content_sha256,
                    version_sha256=version.version_sha256,
                ),
                captured_text=version.captured_text,
            )
        )
    return tuple(prepared)


def _snapshot_records(
    world_model_id: UUID,
    version: int,
    verification: Verification,
    evidence: tuple[PreparedEvidence, ...],
    policy_evidence: tuple[PreparedPolicyEvidence, ...],
    created_at: datetime,
) -> tuple[
    WorldSnapshotRecord,
    tuple[WorldSnapshotEvidenceRecord, ...],
    tuple[WorldSnapshotPolicyEvidenceRecord, ...],
]:
    snapshot_id = uuid4()
    public_evidence = tuple(item.item for item in evidence)
    public_policy_evidence = tuple(item.item for item in policy_evidence)
    snapshot = WorldSnapshotRecord(
        id=snapshot_id,
        world_model_id=world_model_id,
        version=version,
        verification=verification,
        snapshot_sha256=calculate_snapshot_sha256(
            world_model_id,
            version,
            verification,
            public_evidence,
            public_policy_evidence,
        ),
        created_at=created_at,
        sealed_at=None,
    )
    records = tuple(
        WorldSnapshotEvidenceRecord(
            snapshot_id=snapshot_id,
            position=position,
            article_id=prepared.item.article_id,
            source_name=prepared.item.source_name,
            original_url=str(prepared.item.original_url),
            title=prepared.item.title,
            captured_text=prepared.captured_text,
            published_at=prepared.item.published_at,
            captured_at=prepared.item.captured_at,
            country_code=prepared.item.country_code,
            excerpt=prepared.item.excerpt,
            captured_text_sha256=prepared.item.captured_text_sha256,
        )
        for position, prepared in enumerate(evidence)
    )
    policy_records = tuple(
        WorldSnapshotPolicyEvidenceRecord(
            snapshot_id=snapshot_id,
            position=position,
            policy_version_id=prepared.item.policy_version_id,
            authority_name=prepared.item.authority_name,
            jurisdiction_code=prepared.item.jurisdiction_code,
            homepage_url=str(prepared.item.homepage_url),
            canonical_identifier=prepared.item.canonical_identifier,
            source_sha256=prepared.item.source_sha256,
            document_sha256=prepared.item.document_sha256,
            version=prepared.item.version,
            title=prepared.item.title,
            original_url=str(prepared.item.original_url),
            language=prepared.item.language,
            publication_date=prepared.item.publication_date,
            effective_from=prepared.item.effective_from,
            effective_until=prepared.item.effective_until,
            captured_at=prepared.item.captured_at,
            captured_text=prepared.captured_text,
            content_sha256=prepared.item.content_sha256,
            version_sha256=prepared.item.version_sha256,
        )
        for position, prepared in enumerate(policy_evidence)
    )
    return snapshot, records, policy_records


def _require_sealed_snapshot(snapshot: WorldSnapshotRecord) -> None:
    if snapshot.sealed_at is None:
        raise RuntimeError(f"snapshot {snapshot.id} is not sealed")


def _snapshot_summary(
    snapshot: WorldSnapshotRecord,
    evidence_count: int,
    policy_evidence_count: int,
) -> SnapshotSummary:
    _require_sealed_snapshot(snapshot)
    return SnapshotSummary(
        id=snapshot.id,
        version=snapshot.version,
        evidence_count=evidence_count,
        policy_evidence_count=policy_evidence_count,
        snapshot_sha256=snapshot.snapshot_sha256,
        created_at=snapshot.created_at,
    )


def _evidence_from_record(evidence: WorldSnapshotEvidenceRecord) -> SnapshotEvidence:
    actual_digest = sha256(evidence.captured_text.encode("utf-8")).hexdigest()
    if actual_digest != evidence.captured_text_sha256:
        raise RuntimeError(
            f"snapshot {evidence.snapshot_id} evidence position {evidence.position} "
            "captured text does not match captured_text_sha256"
        )
    return SnapshotEvidence(
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


def _policy_evidence_from_record(
    evidence: WorldSnapshotPolicyEvidenceRecord,
) -> SnapshotPolicyEvidence:
    actual_digest = calculate_policy_content_sha256(evidence.captured_text)
    if actual_digest != evidence.content_sha256:
        raise RuntimeError(
            f"snapshot {evidence.snapshot_id} Policy evidence position {evidence.position} "
            "captured text does not match content_sha256"
        )
    return SnapshotPolicyEvidence(
        policy_version_id=evidence.policy_version_id,
        authority_name=evidence.authority_name,
        jurisdiction_code=evidence.jurisdiction_code,
        homepage_url=evidence.homepage_url,
        canonical_identifier=evidence.canonical_identifier,
        source_sha256=evidence.source_sha256,
        document_sha256=evidence.document_sha256,
        version=evidence.version,
        title=evidence.title,
        original_url=evidence.original_url,
        language=evidence.language,
        publication_date=evidence.publication_date,
        effective_from=evidence.effective_from,
        effective_until=evidence.effective_until,
        captured_at=evidence.captured_at,
        content_sha256=evidence.content_sha256,
        version_sha256=evidence.version_sha256,
    )


def _snapshot_detail(
    snapshot: WorldSnapshotRecord,
    evidence_records: tuple[WorldSnapshotEvidenceRecord, ...],
    policy_evidence_records: tuple[WorldSnapshotPolicyEvidenceRecord, ...],
) -> SnapshotDetail:
    _require_sealed_snapshot(snapshot)
    evidence = tuple(_evidence_from_record(record) for record in evidence_records)
    policy_evidence = tuple(
        _policy_evidence_from_record(record) for record in policy_evidence_records
    )
    actual_digest = calculate_snapshot_sha256(
        snapshot.world_model_id,
        snapshot.version,
        snapshot.verification,
        evidence,
        policy_evidence,
    )
    if actual_digest != snapshot.snapshot_sha256:
        raise RuntimeError(f"snapshot {snapshot.id} content does not match snapshot_sha256")
    return SnapshotDetail(
        id=snapshot.id,
        world_model_id=snapshot.world_model_id,
        version=snapshot.version,
        verification=snapshot.verification,
        snapshot_sha256=snapshot.snapshot_sha256,
        created_at=snapshot.created_at,
        evidence=evidence,
        policy_evidence=policy_evidence,
    )


async def _load_snapshot_detail(
    session: AsyncSession,
    snapshot: WorldSnapshotRecord,
) -> SnapshotDetail:
    records = tuple(
        (
            await session.execute(
                select(WorldSnapshotEvidenceRecord)
                .where(WorldSnapshotEvidenceRecord.snapshot_id == snapshot.id)
                .order_by(WorldSnapshotEvidenceRecord.position)
            )
        )
        .scalars()
        .all()
    )
    policy_records = tuple(
        (
            await session.execute(
                select(WorldSnapshotPolicyEvidenceRecord)
                .where(WorldSnapshotPolicyEvidenceRecord.snapshot_id == snapshot.id)
                .order_by(WorldSnapshotPolicyEvidenceRecord.position)
            )
        )
        .scalars()
        .all()
    )
    return _snapshot_detail(snapshot, records, policy_records)


async def _persist_snapshot(
    session: AsyncSession,
    snapshot: WorldSnapshotRecord,
    evidence: tuple[WorldSnapshotEvidenceRecord, ...],
    policy_evidence: tuple[WorldSnapshotPolicyEvidenceRecord, ...],
) -> None:
    session.add(snapshot)
    await session.flush((snapshot,))
    session.add_all(evidence)
    await session.flush(evidence)
    session.add_all(policy_evidence)
    await session.flush(policy_evidence)
    snapshot.sealed_at = snapshot.created_at
    await session.flush((snapshot,))


async def create_world_model(
    session: AsyncSession,
    request: WorldModelCreateRequest,
) -> ModelDetail:
    prepared_evidence = await _load_selected_evidence(session, request.evidence)
    prepared_policy_evidence = await _load_selected_policy_evidence(
        session,
        request.policy_evidence,
    )
    model_id = uuid4()
    created_at = datetime.now(UTC)
    model = WorldModelRecord(id=model_id, title=request.title, created_at=created_at)
    session.add(model)
    await session.flush()
    snapshot, evidence_records, policy_evidence_records = _snapshot_records(
        model_id,
        1,
        request.verification,
        prepared_evidence,
        prepared_policy_evidence,
        created_at,
    )
    await _persist_snapshot(session, snapshot, evidence_records, policy_evidence_records)
    snapshot_detail = _snapshot_detail(snapshot, evidence_records, policy_evidence_records)
    result = ModelDetail(
        id=model.id,
        title=model.title,
        created_at=model.created_at,
        snapshots=(
            _snapshot_summary(
                snapshot,
                len(evidence_records),
                len(policy_evidence_records),
            ),
        ),
        latest_snapshot=snapshot_detail,
    )
    await session.commit()
    return result


async def _snapshot_child_counts(
    session: AsyncSession,
    snapshot_ids: tuple[UUID, ...],
) -> tuple[dict[UUID, int], dict[UUID, int]]:
    evidence_rows = (
        await session.execute(
            select(
                WorldSnapshotEvidenceRecord.snapshot_id,
                func.count(WorldSnapshotEvidenceRecord.position),
            )
            .where(WorldSnapshotEvidenceRecord.snapshot_id.in_(snapshot_ids))
            .group_by(WorldSnapshotEvidenceRecord.snapshot_id)
        )
    ).all()
    policy_rows = (
        await session.execute(
            select(
                WorldSnapshotPolicyEvidenceRecord.snapshot_id,
                func.count(WorldSnapshotPolicyEvidenceRecord.position),
            )
            .where(WorldSnapshotPolicyEvidenceRecord.snapshot_id.in_(snapshot_ids))
            .group_by(WorldSnapshotPolicyEvidenceRecord.snapshot_id)
        )
    ).all()
    return (
        {snapshot_id: int(count) for snapshot_id, count in evidence_rows},
        {snapshot_id: int(count) for snapshot_id, count in policy_rows},
    )


async def list_world_models(session: AsyncSession) -> WorldModelsResponse:
    models = tuple(
        (
            await session.execute(
                select(WorldModelRecord).order_by(
                    WorldModelRecord.created_at.desc(),
                    WorldModelRecord.id.asc(),
                )
            )
        )
        .scalars()
        .all()
    )
    if not models:
        return WorldModelsResponse(items=(), total=0)
    model_ids = tuple(model.id for model in models)
    snapshots = tuple(
        (
            await session.execute(
                select(WorldSnapshotRecord)
                .where(WorldSnapshotRecord.world_model_id.in_(model_ids))
                .order_by(WorldSnapshotRecord.world_model_id, WorldSnapshotRecord.version)
            )
        )
        .scalars()
        .all()
    )
    counts, policy_counts = await _snapshot_child_counts(
        session,
        tuple(item.id for item in snapshots),
    )
    grouped: dict[UUID, list[WorldSnapshotRecord]] = {model_id: [] for model_id in model_ids}
    for snapshot in snapshots:
        grouped[snapshot.world_model_id].append(snapshot)
    items: list[ModelSummary] = []
    for model in models:
        if not grouped[model.id]:
            raise RuntimeError(f"world model {model.id} has no snapshots")
        latest = grouped[model.id][-1]
        items.append(
            ModelSummary(
                id=model.id,
                title=model.title,
                created_at=model.created_at,
                latest_snapshot=_snapshot_summary(
                    latest,
                    counts.get(latest.id, 0),
                    policy_counts.get(latest.id, 0),
                ),
            )
        )
    return WorldModelsResponse(items=tuple(items), total=len(items))


async def get_world_model(session: AsyncSession, model_id: UUID) -> ModelDetail:
    model = await session.scalar(select(WorldModelRecord).where(WorldModelRecord.id == model_id))
    if model is None:
        raise WorldModelNotFoundError(f"world model {model_id} was not found")
    snapshots = tuple(
        (
            await session.execute(
                select(WorldSnapshotRecord)
                .where(WorldSnapshotRecord.world_model_id == model_id)
                .order_by(WorldSnapshotRecord.version)
            )
        )
        .scalars()
        .all()
    )
    if not snapshots:
        raise RuntimeError(f"world model {model_id} has no snapshots")
    counts, policy_counts = await _snapshot_child_counts(
        session,
        tuple(item.id for item in snapshots),
    )
    return ModelDetail(
        id=model.id,
        title=model.title,
        created_at=model.created_at,
        snapshots=tuple(
            _snapshot_summary(
                item,
                counts.get(item.id, 0),
                policy_counts.get(item.id, 0),
            )
            for item in snapshots
        ),
        latest_snapshot=await _load_snapshot_detail(session, snapshots[-1]),
    )


async def append_world_snapshot(
    session: AsyncSession,
    model_id: UUID,
    request: WorldSnapshotCreateRequest,
) -> SnapshotDetail:
    model = await session.scalar(
        select(WorldModelRecord).where(WorldModelRecord.id == model_id).with_for_update()
    )
    if model is None:
        raise WorldModelNotFoundError(f"world model {model_id} was not found")
    latest_version = await session.scalar(
        select(func.max(WorldSnapshotRecord.version)).where(
            WorldSnapshotRecord.world_model_id == model_id
        )
    )
    if latest_version is None:
        raise RuntimeError(f"world model {model_id} has no snapshots")
    prepared_evidence = await _load_selected_evidence(session, request.evidence)
    prepared_policy_evidence = await _load_selected_policy_evidence(
        session,
        request.policy_evidence,
    )
    snapshot, records, policy_records = _snapshot_records(
        model_id,
        int(latest_version) + 1,
        request.verification,
        prepared_evidence,
        prepared_policy_evidence,
        datetime.now(UTC),
    )
    await _persist_snapshot(session, snapshot, records, policy_records)
    result = _snapshot_detail(snapshot, records, policy_records)
    await session.commit()
    return result


async def get_world_snapshot(
    session: AsyncSession,
    model_id: UUID,
    snapshot_id: UUID,
) -> SnapshotDetail:
    model_exists = await session.scalar(
        select(WorldModelRecord.id).where(WorldModelRecord.id == model_id)
    )
    if model_exists is None:
        raise WorldModelNotFoundError(f"world model {model_id} was not found")
    snapshot = await session.scalar(
        select(WorldSnapshotRecord).where(
            WorldSnapshotRecord.id == snapshot_id,
            WorldSnapshotRecord.world_model_id == model_id,
        )
    )
    if snapshot is None:
        raise WorldSnapshotNotFoundError(
            f"snapshot {snapshot_id} was not found for world model {model_id}"
        )
    return await _load_snapshot_detail(session, snapshot)


async def get_world_snapshot_evidence_content(
    session: AsyncSession,
    model_id: UUID,
    snapshot_id: UUID,
    article_id: UUID,
) -> SnapshotEvidenceContent:
    model_exists = await session.scalar(
        select(WorldModelRecord.id).where(WorldModelRecord.id == model_id)
    )
    if model_exists is None:
        raise WorldModelNotFoundError(f"world model {model_id} was not found")
    snapshot = await session.scalar(
        select(WorldSnapshotRecord).where(
            WorldSnapshotRecord.id == snapshot_id,
            WorldSnapshotRecord.world_model_id == model_id,
        )
    )
    if snapshot is None:
        raise WorldSnapshotNotFoundError(
            f"snapshot {snapshot_id} was not found for world model {model_id}"
        )
    _require_sealed_snapshot(snapshot)
    evidence = await session.scalar(
        select(WorldSnapshotEvidenceRecord).where(
            WorldSnapshotEvidenceRecord.snapshot_id == snapshot_id,
            WorldSnapshotEvidenceRecord.article_id == article_id,
        )
    )
    if evidence is None:
        raise WorldSnapshotEvidenceNotFoundError(
            f"article {article_id} was not found in snapshot {snapshot_id}"
        )
    actual_digest = sha256(evidence.captured_text.encode("utf-8")).hexdigest()
    if actual_digest != evidence.captured_text_sha256:
        raise RuntimeError(
            f"snapshot {snapshot_id} article {article_id} captured text "
            "does not match captured_text_sha256"
        )
    return SnapshotEvidenceContent(
        article_id=evidence.article_id,
        captured_text=evidence.captured_text,
        captured_text_sha256=evidence.captured_text_sha256,
    )


async def get_world_snapshot_policy_evidence_content(
    session: AsyncSession,
    model_id: UUID,
    snapshot_id: UUID,
    policy_version_id: UUID,
) -> SnapshotPolicyEvidenceContent:
    model_exists = await session.scalar(
        select(WorldModelRecord.id).where(WorldModelRecord.id == model_id)
    )
    if model_exists is None:
        raise WorldModelNotFoundError(f"world model {model_id} was not found")
    snapshot = await session.scalar(
        select(WorldSnapshotRecord).where(
            WorldSnapshotRecord.id == snapshot_id,
            WorldSnapshotRecord.world_model_id == model_id,
        )
    )
    if snapshot is None:
        raise WorldSnapshotNotFoundError(
            f"snapshot {snapshot_id} was not found for world model {model_id}"
        )
    _require_sealed_snapshot(snapshot)
    evidence = await session.scalar(
        select(WorldSnapshotPolicyEvidenceRecord).where(
            WorldSnapshotPolicyEvidenceRecord.snapshot_id == snapshot_id,
            WorldSnapshotPolicyEvidenceRecord.policy_version_id == policy_version_id,
        )
    )
    if evidence is None:
        raise WorldSnapshotPolicyEvidenceNotFoundError(
            f"Policy version {policy_version_id} was not found in snapshot {snapshot_id}"
        )
    actual_digest = calculate_policy_content_sha256(evidence.captured_text)
    if actual_digest != evidence.content_sha256:
        raise RuntimeError(
            f"snapshot {snapshot_id} Policy version {policy_version_id} captured text "
            "does not match content_sha256"
        )
    return SnapshotPolicyEvidenceContent(
        policy_version_id=evidence.policy_version_id,
        captured_text=evidence.captured_text,
        content_sha256=evidence.content_sha256,
    )
