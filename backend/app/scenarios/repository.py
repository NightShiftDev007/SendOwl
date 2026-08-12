"""Transactional persistence for immutable decision scenarios."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.scenarios.contracts import (
    Intervention,
    ScenarioCreateRequest,
    ScenarioDetail,
    ScenarioSnapshotRef,
    ScenariosResponse,
    ScenarioSummary,
    ScenarioVariant,
)
from app.scenarios.errors import ScenarioNotFoundError
from app.scenarios.hashing import calculate_scenario_sha256
from app.scenarios.models import (
    ScenarioInterventionRecord,
    ScenarioRecord,
    ScenarioVariantRecord,
)
from app.world_models.contracts import SnapshotDetail
from app.world_models.repository import get_world_snapshot


def _snapshot_ref(snapshot: SnapshotDetail) -> ScenarioSnapshotRef:
    """Copy the exact immutable world state addressed by a scenario."""
    return ScenarioSnapshotRef(
        world_model_id=snapshot.world_model_id,
        world_snapshot_id=snapshot.id,
        version=snapshot.version,
        snapshot_sha256=snapshot.snapshot_sha256,
        company_name=snapshot.company.canonical_name,
        evidence_count=len(snapshot.evidence),
    )


def _request_variants(
    request: ScenarioCreateRequest,
) -> tuple[ScenarioVariant, tuple[ScenarioVariant, ...]]:
    """Assign stable server identities and positions to validated request paths."""
    baseline = ScenarioVariant(
        id=uuid4(),
        position=0,
        name=request.baseline.name,
        hypothesis=request.baseline.hypothesis,
        interventions=(),
    )
    alternatives = tuple(
        ScenarioVariant(
            id=uuid4(),
            position=variant_position,
            name=alternative.name,
            hypothesis=alternative.hypothesis,
            interventions=tuple(
                Intervention(
                    id=uuid4(),
                    position=intervention_position,
                    kind=item.kind,
                    actor=item.actor,
                    channel=item.channel,
                    content=item.content,
                    offset_minutes=item.offset_minutes,
                )
                for intervention_position, item in enumerate(alternative.interventions)
            ),
        )
        for variant_position, alternative in enumerate(request.alternatives, start=1)
    )
    return baseline, alternatives


def _scenario_records(
    scenario_id: UUID,
    request: ScenarioCreateRequest,
    snapshot: ScenarioSnapshotRef,
    baseline: ScenarioVariant,
    alternatives: tuple[ScenarioVariant, ...],
    scenario_sha256: str,
    created_at: datetime,
) -> tuple[
    ScenarioRecord,
    tuple[ScenarioVariantRecord, ...],
    tuple[ScenarioInterventionRecord, ...],
]:
    """Build one unsealed parent and all normalized child rows."""
    scenario = ScenarioRecord(
        id=scenario_id,
        title=request.title,
        decision_question=request.decision_question,
        world_model_id=snapshot.world_model_id,
        world_snapshot_id=snapshot.world_snapshot_id,
        snapshot_version=snapshot.version,
        snapshot_sha256=snapshot.snapshot_sha256,
        snapshot_company_name=snapshot.company_name,
        snapshot_evidence_count=snapshot.evidence_count,
        scenario_sha256=scenario_sha256,
        created_at=created_at,
        sealed_at=None,
    )
    all_variants = (baseline,) + alternatives
    variant_records = tuple(
        ScenarioVariantRecord(
            id=variant.id,
            scenario_id=scenario_id,
            position=variant.position,
            role="baseline" if variant.position == 0 else "alternative",
            name=variant.name,
            hypothesis=variant.hypothesis,
        )
        for variant in all_variants
    )
    intervention_records = tuple(
        ScenarioInterventionRecord(
            id=intervention.id,
            scenario_id=scenario_id,
            variant_id=variant.id,
            position=intervention.position,
            kind=intervention.kind,
            actor=intervention.actor,
            channel=intervention.channel,
            content=intervention.content,
            offset_minutes=intervention.offset_minutes,
        )
        for variant in alternatives
        for intervention in variant.interventions
    )
    return scenario, variant_records, intervention_records


def _scenario_advisory_lock_key(scenario_sha256: str) -> int:
    """Map one content address to PostgreSQL's signed 64-bit advisory-lock space."""
    unsigned_key = int(scenario_sha256[:16], 16)
    return unsigned_key - (1 << 64) if unsigned_key >= (1 << 63) else unsigned_key


async def _lock_scenario_content(
    session: AsyncSession,
    scenario_sha256: str,
) -> None:
    """Serialize identical immutable specs before checking or inserting them."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": _scenario_advisory_lock_key(scenario_sha256)},
    )


def _require_sealed_scenario(scenario: ScenarioRecord) -> None:
    """Reject reads of a scenario whose atomic construction is unfinished."""
    if scenario.sealed_at is None:
        raise RuntimeError(f"scenario {scenario.id} is not sealed")


def _snapshot_ref_from_record(scenario: ScenarioRecord) -> ScenarioSnapshotRef:
    return ScenarioSnapshotRef(
        world_model_id=scenario.world_model_id,
        world_snapshot_id=scenario.world_snapshot_id,
        version=scenario.snapshot_version,
        snapshot_sha256=scenario.snapshot_sha256,
        company_name=scenario.snapshot_company_name,
        evidence_count=scenario.snapshot_evidence_count,
    )


def _interventions_by_variant(
    interventions: tuple[ScenarioInterventionRecord, ...],
) -> dict[UUID, tuple[ScenarioInterventionRecord, ...]]:
    grouped: dict[UUID, list[ScenarioInterventionRecord]] = {}
    for intervention in interventions:
        grouped.setdefault(intervention.variant_id, []).append(intervention)
    return {variant_id: tuple(items) for variant_id, items in grouped.items()}


def _variant_from_record(
    variant: ScenarioVariantRecord,
    interventions: tuple[ScenarioInterventionRecord, ...],
) -> ScenarioVariant:
    return ScenarioVariant(
        id=variant.id,
        position=variant.position,
        name=variant.name,
        hypothesis=variant.hypothesis,
        interventions=tuple(
            Intervention(
                id=item.id,
                position=item.position,
                kind=item.kind,
                actor=item.actor,
                channel=item.channel,
                content=item.content,
                offset_minutes=item.offset_minutes,
            )
            for item in interventions
        ),
    )


def _scenario_detail(
    scenario: ScenarioRecord,
    variants: tuple[ScenarioVariantRecord, ...],
    interventions: tuple[ScenarioInterventionRecord, ...],
) -> ScenarioDetail:
    """Rebuild and verify one scenario solely from immutable scenario tables."""
    _require_sealed_scenario(scenario)
    if any(item.scenario_id != scenario.id for item in variants):
        raise RuntimeError(f"scenario {scenario.id} received a variant owned by another scenario")
    if any(item.scenario_id != scenario.id for item in interventions):
        raise RuntimeError(
            f"scenario {scenario.id} received an intervention owned by another scenario"
        )
    baseline_records = tuple(item for item in variants if item.role == "baseline")
    alternative_records = tuple(item for item in variants if item.role == "alternative")
    unknown_roles = tuple(
        item.role for item in variants if item.role not in ("baseline", "alternative")
    )
    if unknown_roles:
        raise RuntimeError(f"scenario {scenario.id} has unknown variant roles: {unknown_roles}")
    if len(baseline_records) != 1:
        raise RuntimeError(f"scenario {scenario.id} must have exactly one baseline variant")
    grouped_interventions = _interventions_by_variant(interventions)
    known_variant_ids = {item.id for item in variants}
    orphan_variant_ids = tuple(
        variant_id for variant_id in grouped_interventions if variant_id not in known_variant_ids
    )
    if orphan_variant_ids:
        raise RuntimeError(
            f"scenario {scenario.id} has interventions for unknown variants: {orphan_variant_ids}"
        )
    baseline_record = baseline_records[0]
    baseline = _variant_from_record(
        baseline_record,
        grouped_interventions.get(baseline_record.id, ()),
    )
    alternatives = tuple(
        _variant_from_record(item, grouped_interventions.get(item.id, ()))
        for item in alternative_records
    )
    snapshot = _snapshot_ref_from_record(scenario)
    actual_digest = calculate_scenario_sha256(
        scenario.title,
        scenario.decision_question,
        snapshot,
        baseline,
        alternatives,
    )
    if actual_digest != scenario.scenario_sha256:
        raise RuntimeError(f"scenario {scenario.id} content does not match scenario_sha256")
    return ScenarioDetail(
        id=scenario.id,
        title=scenario.title,
        decision_question=scenario.decision_question,
        created_at=scenario.created_at,
        scenario_sha256=scenario.scenario_sha256,
        snapshot=snapshot,
        baseline=baseline,
        alternatives=alternatives,
    )


def _scenario_summary(detail: ScenarioDetail) -> ScenarioSummary:
    return ScenarioSummary(
        id=detail.id,
        title=detail.title,
        decision_question=detail.decision_question,
        created_at=detail.created_at,
        scenario_sha256=detail.scenario_sha256,
        snapshot=detail.snapshot,
    )


async def _persist_scenario(
    session: AsyncSession,
    scenario: ScenarioRecord,
    variants: tuple[ScenarioVariantRecord, ...],
    interventions: tuple[ScenarioInterventionRecord, ...],
) -> None:
    """Persist a complete draft and perform its only permitted parent update."""
    session.add(scenario)
    await session.flush((scenario,))
    session.add_all(variants)
    await session.flush(variants)
    session.add_all(interventions)
    await session.flush(interventions)
    scenario.sealed_at = scenario.created_at
    await session.flush((scenario,))


async def create_scenario(
    session: AsyncSession,
    request: ScenarioCreateRequest,
) -> ScenarioDetail:
    """Atomically validate a world snapshot, construct a scenario, and seal it."""
    snapshot_detail = await get_world_snapshot(
        session,
        request.world_model_id,
        request.world_snapshot_id,
    )
    snapshot = _snapshot_ref(snapshot_detail)
    baseline, alternatives = _request_variants(request)
    scenario_sha256 = calculate_scenario_sha256(
        request.title,
        request.decision_question,
        snapshot,
        baseline,
        alternatives,
    )
    await _lock_scenario_content(session, scenario_sha256)
    existing_scenario = await session.scalar(
        select(ScenarioRecord).where(ScenarioRecord.scenario_sha256 == scenario_sha256)
    )
    if existing_scenario is not None:
        existing_detail = (await _load_scenario_details(session, (existing_scenario,)))[0]
        await session.commit()
        return existing_detail

    scenario, variants, interventions = _scenario_records(
        uuid4(),
        request,
        snapshot,
        baseline,
        alternatives,
        scenario_sha256,
        datetime.now(UTC),
    )
    await _persist_scenario(session, scenario, variants, interventions)
    result = _scenario_detail(scenario, variants, interventions)
    await session.commit()
    return result


async def _load_scenario_details(
    session: AsyncSession,
    scenarios: tuple[ScenarioRecord, ...],
) -> tuple[ScenarioDetail, ...]:
    if not scenarios:
        return ()
    scenario_ids = tuple(item.id for item in scenarios)
    variants = tuple(
        (
            await session.execute(
                select(ScenarioVariantRecord)
                .where(ScenarioVariantRecord.scenario_id.in_(scenario_ids))
                .order_by(ScenarioVariantRecord.scenario_id, ScenarioVariantRecord.position)
            )
        )
        .scalars()
        .all()
    )
    interventions = tuple(
        (
            await session.execute(
                select(ScenarioInterventionRecord)
                .where(ScenarioInterventionRecord.scenario_id.in_(scenario_ids))
                .order_by(
                    ScenarioInterventionRecord.scenario_id,
                    ScenarioInterventionRecord.variant_id,
                    ScenarioInterventionRecord.position,
                )
            )
        )
        .scalars()
        .all()
    )
    variants_by_scenario: dict[UUID, list[ScenarioVariantRecord]] = {
        scenario_id: [] for scenario_id in scenario_ids
    }
    for variant in variants:
        variants_by_scenario[variant.scenario_id].append(variant)
    interventions_by_scenario: dict[UUID, list[ScenarioInterventionRecord]] = {
        scenario_id: [] for scenario_id in scenario_ids
    }
    for intervention in interventions:
        interventions_by_scenario[intervention.scenario_id].append(intervention)
    return tuple(
        _scenario_detail(
            scenario,
            tuple(variants_by_scenario[scenario.id]),
            tuple(interventions_by_scenario[scenario.id]),
        )
        for scenario in scenarios
    )


async def list_scenarios(session: AsyncSession) -> ScenariosResponse:
    """List sealed scenarios after reconstructing and checking every digest."""
    scenarios = tuple(
        (
            await session.execute(
                select(ScenarioRecord).order_by(
                    ScenarioRecord.created_at.desc(),
                    ScenarioRecord.id.asc(),
                )
            )
        )
        .scalars()
        .all()
    )
    details = await _load_scenario_details(session, scenarios)
    return ScenariosResponse(
        items=tuple(_scenario_summary(item) for item in details),
        total=len(details),
    )


async def get_scenario(session: AsyncSession, scenario_id: UUID) -> ScenarioDetail:
    """Load one immutable scenario and verify its canonical content address."""
    scenario = await session.scalar(select(ScenarioRecord).where(ScenarioRecord.id == scenario_id))
    if scenario is None:
        raise ScenarioNotFoundError(f"scenario {scenario_id} was not found")
    return (await _load_scenario_details(session, (scenario,)))[0]
