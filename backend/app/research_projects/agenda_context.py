"""Immutable AgendaScope research context captured for one Project."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.media.models import (
    MediaFirstUtteranceRecord,
    MediaPropagationEdgeRecord,
    MediaPropagationEventRecord,
    MediaSourceRecord,
    MediaTopicArticleRecord,
    MediaTopicRecord,
    MediaTopicSnapshotRecord,
)
from app.media.sync_models import MediaSyncRunRecord
from app.research_projects.contracts import (
    ResearchAgendaFirstUtterance,
    ResearchAgendaPropagationEdge,
    ResearchAgendaPropagationEvent,
    ResearchAgendaSnapshot,
    ResearchAgendaTopic,
    ResearchProjectAgendaContext,
    ResearchProjectAgendaPayload,
)
from app.research_projects.models import (
    ResearchProjectAgendaContextRecord,
    ResearchProjectRecord,
)
from app.world_models.models import WorldSnapshotEvidenceRecord


def canonical_agenda_context_json(payload: ResearchProjectAgendaPayload) -> str:
    return json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def calculate_agenda_context_sha256(payload: ResearchProjectAgendaPayload) -> str:
    return sha256(canonical_agenda_context_json(payload).encode("utf-8")).hexdigest()


async def _topic_context(
    session: AsyncSession,
    topic: MediaTopicRecord,
    linked_article_ids: tuple[UUID, ...],
) -> ResearchAgendaTopic:
    snapshot_rows = tuple(
        (
            await session.execute(
                select(MediaTopicSnapshotRecord)
                .where(MediaTopicSnapshotRecord.topic_id == topic.id)
                .order_by(
                    MediaTopicSnapshotRecord.window_end.desc(),
                    MediaTopicSnapshotRecord.country_code,
                    MediaTopicSnapshotRecord.id,
                )
                .limit(24)
            )
        )
        .scalars()
        .all()
    )
    event_rows = tuple(
        (
            await session.execute(
                select(MediaPropagationEventRecord, MediaSourceRecord.name)
                .outerjoin(
                    MediaSourceRecord,
                    MediaSourceRecord.id == MediaPropagationEventRecord.origin_source_id,
                )
                .where(MediaPropagationEventRecord.topic_id == topic.id)
                .order_by(
                    MediaPropagationEventRecord.origin_at.desc(),
                    MediaPropagationEventRecord.id,
                )
                .limit(10)
            )
        ).all()
    )
    propagation: list[ResearchAgendaPropagationEvent] = []
    for event, source_name in event_rows:
        edges = tuple(
            (
                await session.execute(
                    select(MediaPropagationEdgeRecord)
                    .where(MediaPropagationEdgeRecord.event_id == event.id)
                    .order_by(MediaPropagationEdgeRecord.position)
                    .limit(20)
                )
            )
            .scalars()
            .all()
        )
        propagation.append(
            ResearchAgendaPropagationEvent(
                id=event.id,
                status=event.status,
                confidence=event.confidence,
                origin_country_code=event.origin_country_code,
                origin_source_name=source_name,
                origin_at=event.origin_at,
                origin_confidence=event.origin_confidence,
                detection_method=event.detection_method,
                edges=tuple(
                    ResearchAgendaPropagationEdge(
                        position=edge.position,
                        from_country_code=edge.from_country_code,
                        to_country_code=edge.to_country_code,
                        lag_hours=float(edge.lag_hours),
                        first_media_name=edge.first_media_name,
                        first_article_id=edge.first_article_id,
                        first_published_at=edge.first_published_at,
                        observation_source=edge.observation_source,
                    )
                    for edge in edges
                ),
            )
        )
    utterance_rows = tuple(
        (
            await session.execute(
                select(MediaFirstUtteranceRecord)
                .where(MediaFirstUtteranceRecord.topic_id == topic.id)
                .order_by(
                    MediaFirstUtteranceRecord.occurred_at.desc().nullslast(),
                    MediaFirstUtteranceRecord.id,
                )
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    return ResearchAgendaTopic(
        id=topic.id,
        name=topic.name_zh or topic.name,
        summary=topic.summary_zh,
        category=topic.topic_category,
        status=topic.status,
        lifecycle_state=topic.lifecycle_state,
        first_seen_at=topic.first_seen_at,
        last_seen_at=topic.last_seen_at,
        linked_article_ids=linked_article_ids,
        salience=tuple(
            ResearchAgendaSnapshot(
                country_code=item.country_code,
                window_start=item.window_start,
                window_end=item.window_end,
                granularity=item.granularity,
                article_count=item.article_count,
                salience_score=float(item.salience_score),
                salience_rank=item.salience_rank,
            )
            for item in snapshot_rows
        ),
        propagation=tuple(propagation),
        first_utterances=tuple(
            ResearchAgendaFirstUtterance(
                id=item.id,
                entity_name=item.entity_name,
                entity_type=item.entity_type,
                country_code=item.country_code,
                article_id=item.article_id,
                occurred_at=item.occurred_at,
                evidence_quote=item.evidence_quote,
                model_name=item.model_name,
                prompt_version=item.prompt_version,
            )
            for item in utterance_rows
        ),
    )


async def capture_project_agenda_context(
    session: AsyncSession,
    project: ResearchProjectRecord,
    *,
    commit: bool,
) -> ResearchProjectAgendaContext:
    existing = await session.get(ResearchProjectAgendaContextRecord, project.id)
    if existing is not None:
        return project_agenda_context_detail(existing)
    article_ids = tuple(
        (
            await session.execute(
                select(WorldSnapshotEvidenceRecord.article_id)
                .where(WorldSnapshotEvidenceRecord.snapshot_id == project.world_snapshot_id)
                .order_by(WorldSnapshotEvidenceRecord.position)
            )
        ).scalars()
    )
    topic_links = tuple(
        (
            await session.execute(
                select(MediaTopicRecord, MediaTopicArticleRecord.article_id)
                .join(
                    MediaTopicArticleRecord,
                    MediaTopicArticleRecord.topic_id == MediaTopicRecord.id,
                )
                .where(MediaTopicArticleRecord.article_id.in_(article_ids))
                .order_by(MediaTopicRecord.id, MediaTopicArticleRecord.article_id)
            )
        ).all()
    )
    article_ids_by_topic: dict[UUID, list[UUID]] = {}
    topics_by_id: dict[UUID, MediaTopicRecord] = {}
    for topic, article_id in topic_links:
        topics_by_id[topic.id] = topic
        article_ids_by_topic.setdefault(topic.id, []).append(article_id)
    topics = tuple(
        [
            await _topic_context(
                session,
                topics_by_id[topic_id],
                tuple(article_ids_by_topic[topic_id]),
            )
            for topic_id in sorted(topics_by_id, key=str)
        ]
    )
    latest_sync = (
        (
            await session.execute(
                select(MediaSyncRunRecord)
                .where(MediaSyncRunRecord.status == "succeeded")
                .order_by(MediaSyncRunRecord.completed_at.desc(), MediaSyncRunRecord.id)
                .limit(1)
            )
        )
        .scalars()
        .one_or_none()
    )
    payload = ResearchProjectAgendaPayload(
        schema_version="sandowl-project-agenda-context/v1",
        snapshot_sha256=project.snapshot_sha256,
        frozen_article_ids=article_ids,
        topics=topics,
        source_sync_run_id=latest_sync.id if latest_sync is not None else None,
        source_observed_at=latest_sync.source_observed_at if latest_sync is not None else None,
        limitations=(
            "议题、传播链和首发观察来自捕获时的 AgendaScope 导入读模型，不是事实裁决。",
            "没有关联议题表示冻结文章在捕获时未匹配已导入议题，不会由系统猜测补齐。",
        ),
    )
    captured_at = datetime.now(UTC)
    record = ResearchProjectAgendaContextRecord(
        project_id=project.id,
        project_sha256=project.project_sha256,
        schema_version=payload.schema_version,
        payload_json=payload.model_dump(mode="json"),
        context_sha256=calculate_agenda_context_sha256(payload),
        source_sync_run_id=payload.source_sync_run_id,
        source_observed_at=payload.source_observed_at,
        captured_at=captured_at,
    )
    session.add(record)
    if commit:
        await session.commit()
    return project_agenda_context_detail(record)


def project_agenda_context_detail(
    record: ResearchProjectAgendaContextRecord,
) -> ResearchProjectAgendaContext:
    payload = ResearchProjectAgendaPayload.model_validate_json(
        json.dumps(record.payload_json, ensure_ascii=False, allow_nan=False),
        strict=True,
    )
    if calculate_agenda_context_sha256(payload) != record.context_sha256:
        raise RuntimeError(f"project Agenda context {record.project_id} hash mismatch")
    if (
        payload.schema_version != record.schema_version
        or payload.source_sync_run_id != record.source_sync_run_id
        or payload.source_observed_at != record.source_observed_at
    ):
        raise RuntimeError(f"project Agenda context {record.project_id} metadata mismatch")
    return ResearchProjectAgendaContext(
        project_id=record.project_id,
        project_sha256=record.project_sha256,
        payload=payload,
        context_sha256=record.context_sha256,
        captured_at=record.captured_at,
    )


async def get_project_agenda_context(
    session: AsyncSession,
    project_id: UUID,
) -> ResearchProjectAgendaContext | None:
    record = await session.get(ResearchProjectAgendaContextRecord, project_id)
    return None if record is None else project_agenda_context_detail(record)
