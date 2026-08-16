"""Transactional persistence and verified reads for MatrAIx populations."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.populations.contracts import (
    CohortCreateRequest,
    CohortDatasetRef,
    CohortDetail,
    CohortMember,
    CohortsResponse,
    CohortSummary,
    DatasetsResponse,
    DatasetSummary,
    PersonaAttribute,
    PersonasResponse,
    PersonaSummary,
    StoredPersonaProfile,
)
from app.populations.errors import (
    PopulationCohortNotFoundError,
    PopulationDatasetNotFoundError,
    PopulationPersonaSelectionError,
)
from app.populations.hashing import calculate_cohort_sha256, calculate_persona_profile_sha256
from app.populations.models import (
    CohortMemberRecord,
    CohortRecord,
    PersonaDatasetRecord,
    PersonaRecord,
)


def _require_sealed_dataset(dataset: PersonaDatasetRecord) -> None:
    """Reject reads of an imported dataset whose atomic assembly is unfinished."""
    if dataset.sealed_at is None:
        raise RuntimeError(f"persona dataset {dataset.id} is not sealed")


def _require_sealed_cohort(cohort: CohortRecord) -> None:
    """Reject reads of a cohort whose atomic assembly is unfinished."""
    if cohort.sealed_at is None:
        raise RuntimeError(f"cohort {cohort.id} is not sealed")


def _dataset_summary(dataset: PersonaDatasetRecord) -> DatasetSummary:
    _require_sealed_dataset(dataset)
    return DatasetSummary(
        id=dataset.id,
        slug=dataset.slug,
        display_name=dataset.display_name,
        schema_version=dataset.schema_version,
        parent_pool=dataset.parent_pool,
        source_repository=dataset.source_repository,
        persona_count=dataset.persona_count,
        manifest_sha256=dataset.manifest_sha256,
        dataset_sha256=dataset.dataset_sha256,
        created_at=dataset.created_at,
    )


def _stored_profile(persona: PersonaRecord) -> StoredPersonaProfile:
    """Validate one persisted profile and its denormalized integrity fields."""
    profile = StoredPersonaProfile.model_validate(persona.profile_json, strict=True)
    mismatched_columns: list[str] = []
    if profile.persona_id != persona.persona_id:
        mismatched_columns.append("persona_id")
    if profile.display_name != persona.display_name:
        mismatched_columns.append("display_name")
    if profile.source != persona.source:
        mismatched_columns.append("source")
    if mismatched_columns:
        raise RuntimeError(
            f"persona {persona.id} profile disagrees with columns: " + ", ".join(mismatched_columns)
        )
    actual_digest = calculate_persona_profile_sha256(profile)
    if actual_digest != persona.profile_sha256:
        raise RuntimeError(f"persona {persona.id} content does not match profile_sha256")
    return profile


def _persona_summary(persona: PersonaRecord) -> PersonaSummary:
    profile = _stored_profile(persona)
    return PersonaSummary(
        id=persona.id,
        dataset_id=persona.dataset_id,
        persona_id=persona.persona_id,
        display_name=persona.display_name,
        source=persona.source,
        profile_sha256=persona.profile_sha256,
        attributes=tuple(
            PersonaAttribute(name=name, value=value)
            for name, value in sorted(profile.dimensions.items())
        ),
    )


def _cohort_dataset_ref(dataset: PersonaDatasetRecord) -> CohortDatasetRef:
    _require_sealed_dataset(dataset)
    return CohortDatasetRef(
        id=dataset.id,
        slug=dataset.slug,
        dataset_sha256=dataset.dataset_sha256,
    )


def _cohort_detail(
    cohort: CohortRecord,
    dataset: PersonaDatasetRecord,
    member_records: tuple[CohortMemberRecord, ...],
    personas_by_id: dict[UUID, PersonaRecord],
) -> CohortDetail:
    """Rebuild and verify one cohort solely from frozen population tables."""
    _require_sealed_cohort(cohort)
    _require_sealed_dataset(dataset)
    if cohort.dataset_id != dataset.id:
        raise RuntimeError(f"cohort {cohort.id} received a different dataset")
    if any(member.cohort_id != cohort.id for member in member_records):
        raise RuntimeError(f"cohort {cohort.id} received a member owned by another cohort")
    if any(member.dataset_id != cohort.dataset_id for member in member_records):
        raise RuntimeError(f"cohort {cohort.id} contains a member from another dataset")
    missing_personas = tuple(
        member.persona_id for member in member_records if member.persona_id not in personas_by_id
    )
    if missing_personas:
        raise RuntimeError(
            f"cohort {cohort.id} references missing persona records: "
            + ", ".join(str(persona_id) for persona_id in missing_personas)
        )
    members = tuple(
        CohortMember(
            position=member.position,
            persona=_persona_summary(personas_by_id[member.persona_id]),
        )
        for member in member_records
    )
    if len(members) != cohort.persona_count:
        raise RuntimeError(
            f"cohort {cohort.id} persona_count is {cohort.persona_count}, "
            f"but {len(members)} members were stored"
        )
    actual_digest = calculate_cohort_sha256(
        cohort.title,
        dataset.dataset_sha256,
        tuple((member.persona.persona_id, member.persona.profile_sha256) for member in members),
    )
    if actual_digest != cohort.cohort_sha256:
        raise RuntimeError(f"cohort {cohort.id} content does not match cohort_sha256")
    return CohortDetail(
        id=cohort.id,
        title=cohort.title,
        dataset=_cohort_dataset_ref(dataset),
        persona_count=cohort.persona_count,
        cohort_sha256=cohort.cohort_sha256,
        created_at=cohort.created_at,
        members=members,
    )


def _cohort_summary(detail: CohortDetail) -> CohortSummary:
    return CohortSummary(
        id=detail.id,
        title=detail.title,
        dataset=detail.dataset,
        persona_count=detail.persona_count,
        cohort_sha256=detail.cohort_sha256,
        created_at=detail.created_at,
    )


async def _get_sealed_dataset(
    session: AsyncSession,
    dataset_id: UUID,
) -> PersonaDatasetRecord:
    dataset = await session.scalar(
        select(PersonaDatasetRecord).where(
            PersonaDatasetRecord.id == dataset_id,
            PersonaDatasetRecord.sealed_at.is_not(None),
        )
    )
    if dataset is None:
        raise PopulationDatasetNotFoundError(f"persona dataset {dataset_id} was not found")
    return dataset


async def list_datasets(session: AsyncSession) -> DatasetsResponse:
    """List every sealed persona dataset version in deterministic order."""
    datasets = tuple(
        (
            await session.execute(
                select(PersonaDatasetRecord)
                .where(PersonaDatasetRecord.sealed_at.is_not(None))
                .order_by(
                    PersonaDatasetRecord.created_at.desc(),
                    PersonaDatasetRecord.id.asc(),
                )
            )
        )
        .scalars()
        .all()
    )
    return DatasetsResponse(
        items=tuple(_dataset_summary(dataset) for dataset in datasets),
        total=len(datasets),
    )


async def list_personas(
    session: AsyncSession,
    dataset_id: UUID,
    q: str | None,
    page: int,
    page_size: int,
) -> PersonasResponse:
    """Return one deterministic page from an exact frozen dataset version."""
    await _get_sealed_dataset(session, dataset_id)
    conditions: list[object] = [PersonaRecord.dataset_id == dataset_id]
    if q is not None:
        conditions.append(
            or_(
                PersonaRecord.persona_id.icontains(q, autoescape=True),
                PersonaRecord.display_name.icontains(q, autoescape=True),
                PersonaRecord.source.icontains(q, autoescape=True),
            )
        )
    total = int(
        await session.scalar(select(func.count()).select_from(PersonaRecord).where(*conditions))
        or 0
    )
    records = tuple(
        (
            await session.execute(
                select(PersonaRecord)
                .where(*conditions)
                .order_by(PersonaRecord.position, PersonaRecord.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return PersonasResponse(
        items=tuple(_persona_summary(persona) for persona in records),
        page=page,
        page_size=page_size,
        total=total,
    )


async def load_persona_match_scan(
    session: AsyncSession,
    dataset_id: UUID,
    scan_limit: int,
) -> tuple[CohortDatasetRef, int, tuple[PersonaSummary, ...]]:
    """Load one bounded, integrity-checked Persona prefix for cross-domain candidate matching."""
    dataset = await _get_sealed_dataset(session, dataset_id)
    records = tuple(
        (
            await session.execute(
                select(PersonaRecord)
                .where(PersonaRecord.dataset_id == dataset_id)
                .order_by(PersonaRecord.position, PersonaRecord.id)
                .limit(scan_limit)
            )
        )
        .scalars()
        .all()
    )
    return (
        _cohort_dataset_ref(dataset),
        dataset.persona_count,
        tuple(_persona_summary(record) for record in records),
    )


def _cohort_advisory_lock_key(cohort_sha256: str) -> int:
    """Map one content address to PostgreSQL's signed 64-bit lock space."""
    unsigned_key = int(cohort_sha256[:16], 16)
    return unsigned_key - (1 << 64) if unsigned_key >= (1 << 63) else unsigned_key


async def _lock_cohort_content(session: AsyncSession, cohort_sha256: str) -> None:
    """Serialize identical immutable cohort requests before insertion."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": _cohort_advisory_lock_key(cohort_sha256)},
    )


async def _selected_personas(
    session: AsyncSession,
    dataset_id: UUID,
    requested_ids: tuple[UUID, ...],
) -> tuple[PersonaRecord, ...]:
    records = tuple(
        (
            await session.execute(
                select(PersonaRecord).where(
                    PersonaRecord.dataset_id == dataset_id,
                    PersonaRecord.id.in_(requested_ids),
                )
            )
        )
        .scalars()
        .all()
    )
    by_id = {record.id: record for record in records}
    missing_ids = tuple(persona_id for persona_id in requested_ids if persona_id not in by_id)
    if missing_ids:
        raise PopulationPersonaSelectionError(dataset_id, missing_ids)
    ordered = tuple(by_id[persona_id] for persona_id in requested_ids)
    for persona in ordered:
        _stored_profile(persona)
    return ordered


async def _load_cohort_details(
    session: AsyncSession,
    cohorts: tuple[CohortRecord, ...],
) -> tuple[CohortDetail, ...]:
    if not cohorts:
        return ()
    cohort_ids = tuple(cohort.id for cohort in cohorts)
    dataset_ids = tuple({cohort.dataset_id for cohort in cohorts})
    datasets = tuple(
        (
            await session.execute(
                select(PersonaDatasetRecord).where(PersonaDatasetRecord.id.in_(dataset_ids))
            )
        )
        .scalars()
        .all()
    )
    dataset_by_id = {dataset.id: dataset for dataset in datasets}
    missing_dataset_ids = tuple(
        dataset_id for dataset_id in dataset_ids if dataset_id not in dataset_by_id
    )
    if missing_dataset_ids:
        raise RuntimeError(
            "cohorts reference missing datasets: "
            + ", ".join(str(dataset_id) for dataset_id in missing_dataset_ids)
        )
    member_records = tuple(
        (
            await session.execute(
                select(CohortMemberRecord)
                .where(CohortMemberRecord.cohort_id.in_(cohort_ids))
                .order_by(CohortMemberRecord.cohort_id, CohortMemberRecord.position)
            )
        )
        .scalars()
        .all()
    )
    persona_ids = tuple({member.persona_id for member in member_records})
    personas = (
        tuple(
            (await session.execute(select(PersonaRecord).where(PersonaRecord.id.in_(persona_ids))))
            .scalars()
            .all()
        )
        if persona_ids
        else ()
    )
    personas_by_id = {persona.id: persona for persona in personas}
    members_by_cohort: dict[UUID, list[CohortMemberRecord]] = {
        cohort_id: [] for cohort_id in cohort_ids
    }
    for member in member_records:
        members_by_cohort[member.cohort_id].append(member)
    return tuple(
        _cohort_detail(
            cohort,
            dataset_by_id[cohort.dataset_id],
            tuple(members_by_cohort[cohort.id]),
            personas_by_id,
        )
        for cohort in cohorts
    )


async def ensure_cohort(
    session: AsyncSession,
    request: CohortCreateRequest,
) -> CohortDetail:
    """Validate and seal one cohort inside the caller-owned transaction."""
    dataset = await _get_sealed_dataset(session, request.dataset_id)
    personas = await _selected_personas(session, dataset.id, request.persona_ids)
    cohort_sha256 = calculate_cohort_sha256(
        request.title,
        dataset.dataset_sha256,
        tuple((persona.persona_id, persona.profile_sha256) for persona in personas),
    )
    await _lock_cohort_content(session, cohort_sha256)
    existing = await session.scalar(
        select(CohortRecord).where(CohortRecord.cohort_sha256 == cohort_sha256)
    )
    if existing is not None:
        return (await _load_cohort_details(session, (existing,)))[0]

    created_at = datetime.now(UTC)
    cohort = CohortRecord(
        id=uuid4(),
        title=request.title,
        dataset_id=dataset.id,
        persona_count=len(personas),
        cohort_sha256=cohort_sha256,
        created_at=created_at,
        sealed_at=None,
    )
    members = tuple(
        CohortMemberRecord(
            cohort_id=cohort.id,
            dataset_id=dataset.id,
            persona_id=persona.id,
            position=position,
        )
        for position, persona in enumerate(personas)
    )
    session.add(cohort)
    await session.flush((cohort,))
    session.add_all(members)
    await session.flush(members)
    cohort.sealed_at = created_at
    await session.flush((cohort,))
    return _cohort_detail(
        cohort,
        dataset,
        members,
        {persona.id: persona for persona in personas},
    )


async def create_cohort(
    session: AsyncSession,
    request: CohortCreateRequest,
) -> CohortDetail:
    """Atomically validate, content-address, persist, and seal one cohort."""
    result = await ensure_cohort(session, request)
    await session.commit()
    return result


async def list_cohorts(session: AsyncSession) -> CohortsResponse:
    """List sealed cohorts after reconstructing and verifying each digest."""
    cohorts = tuple(
        (
            await session.execute(
                select(CohortRecord)
                .where(CohortRecord.sealed_at.is_not(None))
                .order_by(CohortRecord.created_at.desc(), CohortRecord.id.asc())
            )
        )
        .scalars()
        .all()
    )
    details = await _load_cohort_details(session, cohorts)
    return CohortsResponse(
        items=tuple(_cohort_summary(detail) for detail in details),
        total=len(details),
    )


async def get_cohort(session: AsyncSession, cohort_id: UUID) -> CohortDetail:
    """Return one complete immutable cohort after digest verification."""
    cohort = await session.scalar(
        select(CohortRecord).where(
            CohortRecord.id == cohort_id,
            CohortRecord.sealed_at.is_not(None),
        )
    )
    if cohort is None:
        raise PopulationCohortNotFoundError(f"cohort {cohort_id} was not found")
    return (await _load_cohort_details(session, (cohort,)))[0]
