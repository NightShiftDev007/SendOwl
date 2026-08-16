"""Capture and read immutable Policy evidence."""

from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.policy_evidence.contracts import (
    PolicyDocumentCaptureRequest,
    PolicyDocumentDetail,
    PolicyDocumentsResponse,
    PolicyDocumentSummary,
    PolicySource,
    PolicyVersionCaptureRequest,
    PolicyVersionContent,
    PolicyVersionSummary,
)
from app.policy_evidence.errors import (
    PolicyDocumentNotFoundError,
    PolicyEvidenceSelectionError,
    PolicyVersionNotFoundError,
)
from app.policy_evidence.hashing import (
    calculate_policy_content_sha256,
    calculate_policy_document_sha256,
    calculate_policy_source_sha256,
    calculate_policy_version_sha256,
)
from app.policy_evidence.models import (
    PolicyDocumentRecord,
    PolicyDocumentVersionRecord,
    PolicySourceRecord,
)


def _source(record: PolicySourceRecord) -> PolicySource:
    return PolicySource(
        id=record.id,
        authority_name=record.authority_name,
        jurisdiction_code=record.jurisdiction_code,
        homepage_url=record.homepage_url,
        source_sha256=record.source_sha256,
        created_at=record.created_at,
    )


def _version(record: PolicyDocumentVersionRecord) -> PolicyVersionSummary:
    return PolicyVersionSummary(
        id=record.id,
        version=record.version,
        title=record.title,
        original_url=record.original_url,
        language=record.language,
        publication_date=record.publication_date,
        effective_from=record.effective_from,
        effective_until=record.effective_until,
        captured_at=record.captured_at,
        verification=record.verification,
        content_sha256=record.content_sha256,
        version_sha256=record.version_sha256,
    )


def _summary(
    document: PolicyDocumentRecord,
    source: PolicySourceRecord,
    versions: tuple[PolicyDocumentVersionRecord, ...],
) -> PolicyDocumentSummary:
    if not versions:
        raise RuntimeError(f"Policy document {document.id} has no captured versions")
    return PolicyDocumentSummary(
        id=document.id,
        source=_source(source),
        canonical_identifier=document.canonical_identifier,
        document_sha256=document.document_sha256,
        created_at=document.created_at,
        version_count=len(versions),
        latest_version=_version(versions[-1]),
    )


def _detail(
    document: PolicyDocumentRecord,
    source: PolicySourceRecord,
    versions: tuple[PolicyDocumentVersionRecord, ...],
) -> PolicyDocumentDetail:
    summary = _summary(document, source, versions)
    return PolicyDocumentDetail(
        **summary.model_dump(mode="python"),
        versions=tuple(_version(version) for version in versions),
    )


async def _document_records(
    session: AsyncSession,
    document_id: UUID,
) -> tuple[
    PolicyDocumentRecord,
    PolicySourceRecord,
    tuple[PolicyDocumentVersionRecord, ...],
]:
    row = (
        await session.execute(
            select(PolicyDocumentRecord, PolicySourceRecord)
            .join(
                PolicySourceRecord,
                PolicySourceRecord.id == PolicyDocumentRecord.source_id,
            )
            .where(PolicyDocumentRecord.id == document_id)
        )
    ).one_or_none()
    if row is None:
        raise PolicyDocumentNotFoundError(f"Policy document {document_id} was not found")
    document, source = row
    versions = tuple(
        (
            await session.execute(
                select(PolicyDocumentVersionRecord)
                .where(PolicyDocumentVersionRecord.document_id == document_id)
                .order_by(PolicyDocumentVersionRecord.version)
            )
        )
        .scalars()
        .all()
    )
    return document, source, versions


async def _lock_identity(session: AsyncSession, digest: str) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:digest, 0))"),
        {"digest": digest},
    )


def _new_version_record(
    document: PolicyDocumentRecord,
    request: PolicyVersionCaptureRequest | PolicyDocumentCaptureRequest,
    version: int,
    captured_at: datetime,
) -> PolicyDocumentVersionRecord:
    content_sha256 = calculate_policy_content_sha256(request.captured_text)
    version_sha256 = calculate_policy_version_sha256(
        document.document_sha256,
        request.title,
        str(request.original_url),
        request.language,
        request.publication_date,
        request.effective_from,
        request.effective_until,
        content_sha256,
    )
    return PolicyDocumentVersionRecord(
        id=uuid4(),
        document_id=document.id,
        version=version,
        title=request.title,
        original_url=str(request.original_url),
        language=request.language,
        publication_date=request.publication_date,
        effective_from=request.effective_from,
        effective_until=request.effective_until,
        captured_at=captured_at,
        verification=request.verification,
        captured_text=request.captured_text,
        content_sha256=content_sha256,
        version_sha256=version_sha256,
    )


async def capture_policy_document(
    session: AsyncSession,
    request: PolicyDocumentCaptureRequest,
) -> PolicyDocumentDetail:
    captured_at = datetime.now(UTC)
    source_sha256 = calculate_policy_source_sha256(
        request.source.authority_name,
        request.source.jurisdiction_code,
        str(request.source.homepage_url),
    )
    document_sha256 = calculate_policy_document_sha256(
        source_sha256,
        request.canonical_identifier,
    )
    await _lock_identity(session, source_sha256)
    await _lock_identity(session, document_sha256)
    source = await session.scalar(
        select(PolicySourceRecord).where(PolicySourceRecord.source_sha256 == source_sha256)
    )
    if source is None:
        source = PolicySourceRecord(
            id=uuid4(),
            authority_name=request.source.authority_name,
            jurisdiction_code=request.source.jurisdiction_code,
            homepage_url=str(request.source.homepage_url),
            source_sha256=source_sha256,
            created_at=captured_at,
        )
        session.add(source)
        await session.flush((source,))
    document = await session.scalar(
        select(PolicyDocumentRecord).where(PolicyDocumentRecord.document_sha256 == document_sha256)
    )
    if document is None:
        document = PolicyDocumentRecord(
            id=uuid4(),
            source_id=source.id,
            canonical_identifier=request.canonical_identifier,
            document_sha256=document_sha256,
            created_at=captured_at,
        )
        session.add(document)
        await session.flush((document,))
    candidate = _new_version_record(document, request, 1, captured_at)
    existing = await session.scalar(
        select(PolicyDocumentVersionRecord).where(
            PolicyDocumentVersionRecord.version_sha256 == candidate.version_sha256
        )
    )
    if existing is None:
        version_count = int(
            await session.scalar(
                select(func.count())
                .select_from(PolicyDocumentVersionRecord)
                .where(PolicyDocumentVersionRecord.document_id == document.id)
            )
            or 0
        )
        if version_count >= 100:
            raise PolicyEvidenceSelectionError(
                f"Policy document {document.id} reached the 100-version limit"
            )
        candidate.version = version_count + 1
        session.add(candidate)
        await session.flush((candidate,))
    await session.commit()
    return await get_policy_document(session, document.id)


async def append_policy_version(
    session: AsyncSession,
    document_id: UUID,
    request: PolicyVersionCaptureRequest,
) -> PolicyDocumentDetail:
    document = await session.get(PolicyDocumentRecord, document_id)
    if document is None:
        raise PolicyDocumentNotFoundError(f"Policy document {document_id} was not found")
    await _lock_identity(session, document.document_sha256)
    version_count = int(
        await session.scalar(
            select(func.count())
            .select_from(PolicyDocumentVersionRecord)
            .where(PolicyDocumentVersionRecord.document_id == document_id)
        )
        or 0
    )
    candidate = _new_version_record(document, request, version_count + 1, datetime.now(UTC))
    existing = await session.scalar(
        select(PolicyDocumentVersionRecord).where(
            PolicyDocumentVersionRecord.version_sha256 == candidate.version_sha256
        )
    )
    if existing is None:
        if version_count >= 100:
            raise PolicyEvidenceSelectionError(
                f"Policy document {document_id} reached the 100-version limit"
            )
        session.add(candidate)
        await session.flush((candidate,))
    await session.commit()
    return await get_policy_document(session, document_id)


async def list_policy_documents(
    session: AsyncSession,
    page: int,
    page_size: int,
) -> PolicyDocumentsResponse:
    total = int(await session.scalar(select(func.count()).select_from(PolicyDocumentRecord)) or 0)
    if total == 0:
        return PolicyDocumentsResponse(items=(), page=1, page_size=page_size, total=0)
    if (page - 1) * page_size >= total:
        raise PolicyEvidenceSelectionError("requested Policy document page starts beyond total")
    rows = tuple(
        (
            await session.execute(
                select(PolicyDocumentRecord, PolicySourceRecord)
                .join(
                    PolicySourceRecord,
                    PolicySourceRecord.id == PolicyDocumentRecord.source_id,
                )
                .order_by(PolicyDocumentRecord.created_at.desc(), PolicyDocumentRecord.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    document_ids = tuple(document.id for document, _source_record in rows)
    version_records = tuple(
        (
            await session.execute(
                select(PolicyDocumentVersionRecord)
                .where(PolicyDocumentVersionRecord.document_id.in_(document_ids))
                .order_by(
                    PolicyDocumentVersionRecord.document_id,
                    PolicyDocumentVersionRecord.version,
                )
            )
        )
        .scalars()
        .all()
    )
    versions_by_document: dict[UUID, list[PolicyDocumentVersionRecord]] = defaultdict(list)
    for version in version_records:
        versions_by_document[version.document_id].append(version)
    return PolicyDocumentsResponse(
        items=tuple(
            _summary(document, source, tuple(versions_by_document[document.id]))
            for document, source in rows
        ),
        page=page,
        page_size=page_size,
        total=total,
    )


async def get_policy_document(
    session: AsyncSession,
    document_id: UUID,
) -> PolicyDocumentDetail:
    document, source, versions = await _document_records(session, document_id)
    return _detail(document, source, versions)


async def get_policy_version_content(
    session: AsyncSession,
    document_id: UUID,
    version_id: UUID,
) -> PolicyVersionContent:
    version = await session.scalar(
        select(PolicyDocumentVersionRecord).where(
            PolicyDocumentVersionRecord.id == version_id,
            PolicyDocumentVersionRecord.document_id == document_id,
        )
    )
    if version is None:
        document_exists = await session.get(PolicyDocumentRecord, document_id)
        if document_exists is None:
            raise PolicyDocumentNotFoundError(f"Policy document {document_id} was not found")
        raise PolicyVersionNotFoundError(
            f"Policy version {version_id} was not found in document {document_id}"
        )
    return PolicyVersionContent(
        document_id=document_id,
        version_id=version.id,
        captured_text=version.captured_text,
        content_sha256=version.content_sha256,
    )


__all__ = [
    "append_policy_version",
    "capture_policy_document",
    "get_policy_document",
    "get_policy_version_content",
    "list_policy_documents",
]
