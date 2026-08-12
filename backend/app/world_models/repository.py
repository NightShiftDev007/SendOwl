"""Transactional persistence for versioned, immutable world-model snapshots."""

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.companies.contracts import CompanyAliasMatch, CompanyEvidenceContext
from app.companies.coverage import (
    build_evidence_contexts,
    calculate_captured_text_sha256,
    calculate_evidence_revision_sha256,
    combine_article_text,
    unique_matched_aliases,
)
from app.companies.repository import PersistedCompanyIdentity, load_company_identity
from app.media.collection.aliases import find_company_alias_matches_bounded
from app.media.collection.errors import CompanyAliasMatchLimitError
from app.media.locking import IMPORT_ADVISORY_LOCK_KEY
from app.media.models import MediaArticleRecord, MediaSourceRecord
from app.world_models.contracts import (
    ModelDetail,
    ModelSummary,
    SnapshotCompany,
    SnapshotDetail,
    SnapshotEvidence,
    SnapshotEvidenceContent,
    SnapshotSummary,
    Verification,
    WorldModelCreateRequest,
    WorldModelsResponse,
    WorldSnapshotCreateRequest,
    WorldSnapshotEvidenceSelection,
)
from app.world_models.errors import (
    SnapshotEvidenceLimitError,
    SnapshotEvidenceSelectionError,
    WorldModelNotFoundError,
    WorldSnapshotEvidenceNotFoundError,
    WorldSnapshotNotFoundError,
    WorldSnapshotRevisionConflictError,
)
from app.world_models.hashing import calculate_snapshot_sha256
from app.world_models.models import (
    WorldModelRecord,
    WorldSnapshotEvidenceRecord,
    WorldSnapshotMentionRecord,
    WorldSnapshotRecord,
)

SNAPSHOT_CONTEXT_RADIUS = 120
SNAPSHOT_EXCERPT_LENGTH = 280
MAX_SNAPSHOT_CAPTURED_TEXT_UTF8_BYTES_PER_ARTICLE = 2 * 1024 * 1024
MAX_SNAPSHOT_EXACT_ALIAS_MATCHES_PER_ARTICLE = 200
MAX_SNAPSHOT_TOTAL_MENTIONS = 2000


@dataclass(frozen=True, slots=True)
class PreparedMention:
    """One exact alias match paired with its copied display context."""

    match: CompanyAliasMatch
    context: CompanyEvidenceContext


@dataclass(frozen=True, slots=True)
class PreparedEvidence:
    """Validated public evidence plus fields retained only for snapshot integrity."""

    item: SnapshotEvidence
    captured_text: str
    mentions: tuple[PreparedMention, ...]


def _snapshot_company(identity: PersistedCompanyIdentity) -> SnapshotCompany:
    return SnapshotCompany(
        id=identity.item.id,
        canonical_name=identity.item.canonical_name,
        aliases=identity.item.aliases,
    )


def _article_excerpt(title: str, content: str | None, summary: str | None) -> str:
    """Apply the same deterministic summary/content/title precedence as media browsing."""
    for value in (summary, content, title):
        if value is None:
            continue
        excerpt = value[:SNAPSHOT_EXCERPT_LENGTH].strip()
        if excerpt:
            return excerpt
    raise ValueError("selected media article has no non-whitespace title, summary, or content")


def _validate_captured_text_byte_count(article_id: UUID, captured_text_bytes: int) -> None:
    """Reject one article before its full text is loaded or alias matched."""
    if captured_text_bytes > MAX_SNAPSHOT_CAPTURED_TEXT_UTF8_BYTES_PER_ARTICLE:
        raise SnapshotEvidenceLimitError(
            resource="captured_text UTF-8 bytes per article",
            article_ids=(article_id,),
            actual=captured_text_bytes,
            limit=MAX_SNAPSHOT_CAPTURED_TEXT_UTF8_BYTES_PER_ARTICLE,
        )


def _validate_snapshot_mention_limit(
    article_ids: tuple[UUID, ...],
    mention_count: int,
) -> None:
    """Reject a selected set whose aggregate mentions exceed the snapshot bound."""
    if mention_count > MAX_SNAPSHOT_TOTAL_MENTIONS:
        raise SnapshotEvidenceLimitError(
            resource="exact alias mentions per snapshot",
            article_ids=article_ids,
            actual=mention_count,
            limit=MAX_SNAPSHOT_TOTAL_MENTIONS,
        )


def _stale_selection_article_ids(
    selections: tuple[WorldSnapshotEvidenceSelection, ...],
    current_revision_by_id: dict[UUID, str],
) -> tuple[UUID, ...]:
    """Return changed, still-present articles in original request order."""
    return tuple(
        selection.article_id
        for selection in selections
        if selection.article_id in current_revision_by_id
        and current_revision_by_id[selection.article_id] != selection.evidence_revision_sha256
    )


def _selected_article_metadata_statement(
    article_ids: tuple[UUID, ...],
) -> Select[tuple[UUID, UUID, bool, int]]:
    """Lock selected media rows before checking size or loading mutable text."""
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
        .where(MediaArticleRecord.id.in_(article_ids))
        .order_by(MediaArticleRecord.id)
        .with_for_update(of=MediaArticleRecord)
    )


def _selected_source_statement(source_ids: tuple[UUID, ...]) -> Select[tuple[MediaSourceRecord]]:
    """Lock every selected source in UUID order after selected article rows."""
    return (
        select(MediaSourceRecord)
        .where(MediaSourceRecord.id.in_(source_ids))
        .order_by(MediaSourceRecord.id)
        .with_for_update(of=MediaSourceRecord)
    )


def _prepare_article(
    article: MediaArticleRecord,
    source: MediaSourceRecord,
    identity: PersistedCompanyIdentity,
    captured_text: str,
    captured_text_sha256: str,
) -> PreparedEvidence | None:
    try:
        matches = find_company_alias_matches_bounded(
            captured_text,
            (identity.matchable,),
            MAX_SNAPSHOT_EXACT_ALIAS_MATCHES_PER_ARTICLE,
        )
    except CompanyAliasMatchLimitError as error:
        raise SnapshotEvidenceLimitError(
            resource="exact alias matches per article",
            article_ids=(article.id,),
            actual=error.observed_matches,
            limit=error.limit,
        ) from error
    if not matches:
        return None
    contexts = build_evidence_contexts(captured_text, matches, SNAPSHOT_CONTEXT_RADIUS)
    mentions = tuple(
        PreparedMention(match=match, context=context)
        for match, context in zip(matches, contexts, strict=True)
    )
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
            matched_aliases=unique_matched_aliases(matches),
            evidence_contexts=contexts,
        ),
        captured_text=captured_text,
        mentions=mentions,
    )


async def _load_selected_evidence(
    session: AsyncSession,
    selections: tuple[WorldSnapshotEvidenceSelection, ...],
    identity: PersistedCompanyIdentity,
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
            unmatched_article_ids=(),
        )
    for article_id in article_ids:
        text_size = int(metadata_by_id[article_id].captured_text_size)
        _validate_captured_text_byte_count(article_id, text_size)

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
    missing_loaded_article_ids = tuple(
        article_id for article_id in article_ids if article_id not in selected_by_id
    )
    if missing_loaded_article_ids:
        raise RuntimeError(
            "selected media articles disappeared after their rows were locked; article IDs: "
            + ", ".join(str(value) for value in missing_loaded_article_ids)
        )

    captured_text_by_id: dict[UUID, str] = {}
    current_captured_text_digest_by_id: dict[UUID, str] = {}
    current_revision_by_id: dict[UUID, str] = {}
    for selection in selections:
        article = selected_by_id.get(selection.article_id)
        if article is None:
            continue
        metadata = metadata_by_id[selection.article_id]
        if article.source_id != metadata.source_id:
            raise RuntimeError(
                f"selected media article {article.id} changed source_id after its row was locked"
            )
        source = source_by_id[article.source_id]
        captured_text = combine_article_text(article.title, article.content)
        _validate_captured_text_byte_count(
            selection.article_id,
            len(captured_text.encode("utf-8")),
        )
        current_captured_text_digest = calculate_captured_text_sha256(
            article.title,
            article.content,
        )
        current_revision = calculate_evidence_revision_sha256(
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
        captured_text_by_id[selection.article_id] = captured_text
        current_captured_text_digest_by_id[selection.article_id] = current_captured_text_digest
        current_revision_by_id[selection.article_id] = current_revision
    stale_ids = _stale_selection_article_ids(selections, current_revision_by_id)
    if stale_ids:
        raise WorldSnapshotRevisionConflictError(stale_article_ids=stale_ids)

    prepared_by_id: dict[UUID, PreparedEvidence] = {}
    unmatched_ids: list[UUID] = []
    prepared_article_ids: list[UUID] = []
    total_mentions = 0
    for article_id in article_ids:
        article = selected_by_id[article_id]
        source = source_by_id[article.source_id]
        captured_text = captured_text_by_id[article_id]
        prepared = _prepare_article(
            article,
            source,
            identity,
            captured_text,
            current_captured_text_digest_by_id[article_id],
        )
        if prepared is None:
            unmatched_ids.append(article_id)
            continue
        prepared_by_id[article_id] = prepared
        prepared_article_ids.append(article_id)
        total_mentions += len(prepared.mentions)
        _validate_snapshot_mention_limit(tuple(prepared_article_ids), total_mentions)

    if unmatched_ids:
        raise SnapshotEvidenceSelectionError(
            missing_article_ids=(),
            duplicate_article_ids=(),
            unmatched_article_ids=tuple(unmatched_ids),
        )
    return tuple(prepared_by_id[article_id] for article_id in article_ids)


def _snapshot_records(
    world_model_id: UUID,
    version: int,
    verification: Verification,
    company: SnapshotCompany,
    evidence: tuple[PreparedEvidence, ...],
    created_at: datetime,
) -> tuple[
    WorldSnapshotRecord,
    tuple[WorldSnapshotEvidenceRecord, ...],
    tuple[WorldSnapshotMentionRecord, ...],
]:
    snapshot_id = uuid4()
    public_evidence = tuple(item.item for item in evidence)
    snapshot = WorldSnapshotRecord(
        id=snapshot_id,
        world_model_id=world_model_id,
        version=version,
        verification=verification,
        snapshot_sha256=calculate_snapshot_sha256(
            world_model_id,
            version,
            verification,
            company,
            public_evidence,
        ),
        created_at=created_at,
        sealed_at=None,
        company_id=company.id,
        company_canonical_name=company.canonical_name,
        company_aliases=list(company.aliases),
    )
    evidence_records = tuple(
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
    mention_records = tuple(
        WorldSnapshotMentionRecord(
            snapshot_id=snapshot_id,
            evidence_position=evidence_position,
            position=mention_position,
            alias=mention.match.alias,
            surface_form=mention.match.surface_form,
            start_offset=mention.match.start_offset,
            end_offset=mention.match.end_offset,
            context=mention.context.context,
        )
        for evidence_position, prepared in enumerate(evidence)
        for mention_position, mention in enumerate(prepared.mentions)
    )
    return snapshot, evidence_records, mention_records


def _snapshot_summary(snapshot: WorldSnapshotRecord, evidence_count: int) -> SnapshotSummary:
    _require_sealed_snapshot(snapshot)
    return SnapshotSummary(
        id=snapshot.id,
        version=snapshot.version,
        company_name=snapshot.company_canonical_name,
        evidence_count=evidence_count,
        snapshot_sha256=snapshot.snapshot_sha256,
        created_at=snapshot.created_at,
    )


def _snapshot_company_from_record(snapshot: WorldSnapshotRecord) -> SnapshotCompany:
    return SnapshotCompany(
        id=snapshot.company_id,
        canonical_name=snapshot.company_canonical_name,
        aliases=tuple(snapshot.company_aliases),
    )


def _require_sealed_snapshot(snapshot: WorldSnapshotRecord) -> None:
    """Reject reads of a snapshot whose atomic capture has not been sealed."""
    if snapshot.sealed_at is None:
        raise RuntimeError(f"snapshot {snapshot.id} is not sealed")


def _mentions_by_evidence_position(
    mentions: tuple[WorldSnapshotMentionRecord, ...],
) -> dict[int, tuple[WorldSnapshotMentionRecord, ...]]:
    grouped: dict[int, list[WorldSnapshotMentionRecord]] = {}
    for mention in mentions:
        grouped.setdefault(mention.evidence_position, []).append(mention)
    return {position: tuple(values) for position, values in grouped.items()}


def _evidence_from_record(
    evidence: WorldSnapshotEvidenceRecord,
    mentions: tuple[WorldSnapshotMentionRecord, ...],
) -> SnapshotEvidence:
    actual_digest = sha256(evidence.captured_text.encode("utf-8")).hexdigest()
    if actual_digest != evidence.captured_text_sha256:
        raise RuntimeError(
            f"snapshot {evidence.snapshot_id} evidence position {evidence.position} "
            "captured text does not match captured_text_sha256"
        )
    for mention in mentions:
        if mention.end_offset > len(evidence.captured_text):
            raise RuntimeError(
                f"snapshot {evidence.snapshot_id} mention {mention.position} exceeds captured text"
            )
        if (
            evidence.captured_text[mention.start_offset : mention.end_offset]
            != mention.surface_form
        ):
            raise RuntimeError(
                f"snapshot {evidence.snapshot_id} mention {mention.position} "
                "surface form is corrupt"
            )
    matched_aliases: list[str] = []
    seen_aliases: set[str] = set()
    for mention in mentions:
        alias_key = mention.alias.casefold()
        if alias_key in seen_aliases:
            continue
        seen_aliases.add(alias_key)
        matched_aliases.append(mention.alias)
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
        matched_aliases=tuple(matched_aliases),
        evidence_contexts=tuple(
            CompanyEvidenceContext(
                alias=mention.alias,
                start_offset=mention.start_offset,
                end_offset=mention.end_offset,
                context=mention.context,
            )
            for mention in mentions
        ),
    )


def _snapshot_detail(
    snapshot: WorldSnapshotRecord,
    evidence_records: tuple[WorldSnapshotEvidenceRecord, ...],
    mention_records: tuple[WorldSnapshotMentionRecord, ...],
) -> SnapshotDetail:
    _require_sealed_snapshot(snapshot)
    mentions_by_position = _mentions_by_evidence_position(mention_records)
    evidence = tuple(
        _evidence_from_record(record, mentions_by_position.get(record.position, ()))
        for record in evidence_records
    )
    company = _snapshot_company_from_record(snapshot)
    actual_snapshot_digest = calculate_snapshot_sha256(
        snapshot.world_model_id,
        snapshot.version,
        snapshot.verification,
        company,
        evidence,
    )
    if actual_snapshot_digest != snapshot.snapshot_sha256:
        raise RuntimeError(f"snapshot {snapshot.id} content does not match snapshot_sha256")
    return SnapshotDetail(
        id=snapshot.id,
        world_model_id=snapshot.world_model_id,
        version=snapshot.version,
        verification=snapshot.verification,
        snapshot_sha256=snapshot.snapshot_sha256,
        created_at=snapshot.created_at,
        company=company,
        evidence=evidence,
    )


async def _load_snapshot_detail(
    session: AsyncSession,
    snapshot: WorldSnapshotRecord,
) -> SnapshotDetail:
    evidence_records = tuple(
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
    mention_records = tuple(
        (
            await session.execute(
                select(WorldSnapshotMentionRecord)
                .where(WorldSnapshotMentionRecord.snapshot_id == snapshot.id)
                .order_by(
                    WorldSnapshotMentionRecord.evidence_position,
                    WorldSnapshotMentionRecord.position,
                )
            )
        )
        .scalars()
        .all()
    )
    return _snapshot_detail(snapshot, evidence_records, mention_records)


async def _persist_snapshot(
    session: AsyncSession,
    snapshot: WorldSnapshotRecord,
    evidence: tuple[WorldSnapshotEvidenceRecord, ...],
    mentions: tuple[WorldSnapshotMentionRecord, ...],
) -> None:
    session.add(snapshot)
    await session.flush((snapshot,))
    session.add_all(evidence)
    await session.flush(evidence)
    session.add_all(mentions)
    await session.flush(mentions)
    snapshot.sealed_at = snapshot.created_at
    await session.flush((snapshot,))


async def create_world_model(
    session: AsyncSession,
    request: WorldModelCreateRequest,
) -> ModelDetail:
    """Atomically create one persistent model and its version-one snapshot."""
    identity = await load_company_identity(session, request.company_id)
    company = _snapshot_company(identity)
    prepared_evidence = await _load_selected_evidence(
        session,
        request.evidence,
        identity,
    )
    model_id = uuid4()
    created_at = datetime.now(UTC)
    model = WorldModelRecord(
        id=model_id,
        title=request.title,
        company_id=request.company_id,
        created_at=created_at,
    )
    session.add(model)
    await session.flush()
    snapshot, evidence_records, mention_records = _snapshot_records(
        model_id,
        1,
        request.verification,
        company,
        prepared_evidence,
        created_at,
    )
    await _persist_snapshot(session, snapshot, evidence_records, mention_records)
    snapshot_detail = _snapshot_detail(snapshot, evidence_records, mention_records)
    result = ModelDetail(
        id=model.id,
        title=model.title,
        company_id=model.company_id,
        created_at=model.created_at,
        snapshots=(_snapshot_summary(snapshot, len(evidence_records)),),
        latest_snapshot=snapshot_detail,
    )
    await session.commit()
    return result


async def list_world_models(session: AsyncSession) -> WorldModelsResponse:
    """List models using only persistent model and frozen snapshot tables."""
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
    count_rows = (
        await session.execute(
            select(
                WorldSnapshotEvidenceRecord.snapshot_id,
                func.count(WorldSnapshotEvidenceRecord.position),
            )
            .where(
                WorldSnapshotEvidenceRecord.snapshot_id.in_(tuple(item.id for item in snapshots))
            )
            .group_by(WorldSnapshotEvidenceRecord.snapshot_id)
        )
    ).all()
    counts = {snapshot_id: int(count) for snapshot_id, count in count_rows}
    snapshots_by_model: dict[UUID, list[WorldSnapshotRecord]] = {
        model_id: [] for model_id in model_ids
    }
    for snapshot in snapshots:
        snapshots_by_model[snapshot.world_model_id].append(snapshot)
    items: list[ModelSummary] = []
    for model in models:
        model_snapshots = snapshots_by_model[model.id]
        if not model_snapshots:
            raise RuntimeError(f"world model {model.id} has no snapshots")
        latest = model_snapshots[-1]
        items.append(
            ModelSummary(
                id=model.id,
                title=model.title,
                company_id=model.company_id,
                company_name=latest.company_canonical_name,
                created_at=model.created_at,
                latest_snapshot=_snapshot_summary(latest, counts.get(latest.id, 0)),
            )
        )
    return WorldModelsResponse(items=tuple(items), total=len(items))


async def get_world_model(session: AsyncSession, model_id: UUID) -> ModelDetail:
    """Load a model and latest detail without joining mutable company or media data."""
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
    count_rows = (
        await session.execute(
            select(
                WorldSnapshotEvidenceRecord.snapshot_id,
                func.count(WorldSnapshotEvidenceRecord.position),
            )
            .where(
                WorldSnapshotEvidenceRecord.snapshot_id.in_(tuple(item.id for item in snapshots))
            )
            .group_by(WorldSnapshotEvidenceRecord.snapshot_id)
        )
    ).all()
    counts = {snapshot_id: int(count) for snapshot_id, count in count_rows}
    latest_detail = await _load_snapshot_detail(session, snapshots[-1])
    return ModelDetail(
        id=model.id,
        title=model.title,
        company_id=model.company_id,
        created_at=model.created_at,
        snapshots=tuple(_snapshot_summary(item, counts.get(item.id, 0)) for item in snapshots),
        latest_snapshot=latest_detail,
    )


async def append_world_snapshot(
    session: AsyncSession,
    model_id: UUID,
    request: WorldSnapshotCreateRequest,
) -> SnapshotDetail:
    """Lock one model row and append its next version in the same transaction."""
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
    identity = await load_company_identity(session, model.company_id)
    company = _snapshot_company(identity)
    prepared_evidence = await _load_selected_evidence(
        session,
        request.evidence,
        identity,
    )
    snapshot, evidence_records, mention_records = _snapshot_records(
        model_id,
        int(latest_version) + 1,
        request.verification,
        company,
        prepared_evidence,
        datetime.now(UTC),
    )
    await _persist_snapshot(session, snapshot, evidence_records, mention_records)
    result = _snapshot_detail(snapshot, evidence_records, mention_records)
    await session.commit()
    return result


async def get_world_snapshot(
    session: AsyncSession,
    model_id: UUID,
    snapshot_id: UUID,
) -> SnapshotDetail:
    """Load one frozen snapshot without consulting mutable source tables."""
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
    """Load exact frozen text without consulting mutable company or media tables."""
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
