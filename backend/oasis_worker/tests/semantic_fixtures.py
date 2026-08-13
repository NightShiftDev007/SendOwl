from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from oasis_worker.semantic_contracts import (
    ClaimedSemanticTrial,
    CohortIntegrityInput,
    DatasetIntegrityInput,
    PersonaProfile,
    PersonaProvenance,
    ScenarioIntegrityInput,
    ScenarioVariantIntegrity,
    SemanticExperiment,
    SemanticIntervention,
    SemanticPersona,
    SemanticVariant,
)
from oasis_worker.semantic_hashing import (
    cohort_sha256,
    experiment_sha256,
    persona_profile_sha256,
    scenario_sha256,
    trial_sha256,
)

SCENARIO_ID = UUID("10000000-0000-4000-8000-000000000001")
BASELINE_ID = UUID("10000000-0000-4000-8000-000000000002")
ALT_ONE_ID = UUID("10000000-0000-4000-8000-000000000003")
ALT_TWO_ID = UUID("10000000-0000-4000-8000-000000000004")
DATASET_ID = UUID("20000000-0000-4000-8000-000000000001")
COHORT_ID = UUID("20000000-0000-4000-8000-000000000002")
EXPERIMENT_ID = UUID("30000000-0000-4000-8000-000000000001")
TRIAL_ID = UUID("30000000-0000-4000-8000-000000000002")
DATASET_SHA256 = "d" * 64
CONFIG_SHA256 = "c" * 64


def _profile(position: int) -> PersonaProfile:
    dimensions = {
        "age_band": f"{20 + position}-29",
        "coding_activity": "No coding activity",
        "interest": "industrial policy",
        **{f"signal_{index:02d}": f"value-{position}-{index}" for index in range(45)},
    }
    return PersonaProfile(
        display_name=f"Persona {position}",
        dimensions=dimensions,
        persona_id=f"persona-{position}",
        provenance=PersonaProvenance(
            hf_repo=None,
            origin_persona_id=f"source row / {position}",
            origin_source_row_index=position,
            parent_pool=None,
        ),
        source="dev-sample",
        version="v1",
    )


def _personas(count: int) -> tuple[SemanticPersona, ...]:
    values: list[SemanticPersona] = []
    for position in range(count):
        profile = _profile(position)
        values.append(
            SemanticPersona(
                id=UUID(f"40000000-0000-4000-8000-{position + 1:012d}"),
                position=position,
                persona_id=profile.persona_id,
                display_name=profile.display_name,
                source=profile.source,
                profile=profile,
                profile_sha256=persona_profile_sha256(profile),
            )
        )
    return tuple(values)


def build_trial(persona_count: int, selected_position: int) -> ClaimedSemanticTrial:
    baseline = ScenarioVariantIntegrity(
        id=BASELINE_ID,
        role="baseline",
        position=0,
        name="Baseline",
        hypothesis="No intervention changes behavior.",
        interventions=(),
    )
    alt_one_intervention = SemanticIntervention(
        id=UUID("60000000-0000-4000-8000-000000000001"),
        position=0,
        kind="initial_post",
        actor="scenario_actor",
        channel="reddit",
        content="First policy intervention.",
        offset_minutes=0,
    )
    alt_two_intervention = SemanticIntervention(
        id=UUID("60000000-0000-4000-8000-000000000002"),
        position=0,
        kind="initial_post",
        actor="scenario_actor",
        channel="reddit",
        content="Selected policy intervention.",
        offset_minutes=15,
    )
    alt_one = ScenarioVariantIntegrity(
        id=ALT_ONE_ID,
        role="alternative",
        position=1,
        name="Alternative one",
        hypothesis="The first intervention changes discussion.",
        interventions=(alt_one_intervention,),
    )
    alt_two = ScenarioVariantIntegrity(
        id=ALT_TWO_ID,
        role="alternative",
        position=2,
        name="Alternative two",
        hypothesis="The selected intervention changes discussion.",
        interventions=(alt_two_intervention,),
    )
    scenario = ScenarioIntegrityInput(
        id=SCENARIO_ID,
        title="Policy choice",
        decision_question="How will this audience discuss the policy?",
        world_model_id=UUID("50000000-0000-4000-8000-000000000001"),
        world_snapshot_id=UUID("50000000-0000-4000-8000-000000000002"),
        snapshot_version=1,
        snapshot_sha256="a" * 64,
        snapshot_evidence_count=1,
        scenario_sha256="0" * 64,
        variants=(baseline, alt_one, alt_two),
    )
    scenario = scenario.model_copy(update={"scenario_sha256": scenario_sha256(scenario)})

    personas = _personas(persona_count)
    cohort = CohortIntegrityInput(
        id=COHORT_ID,
        dataset_id=DATASET_ID,
        title="Test cohort",
        persona_count=persona_count,
        cohort_sha256="0" * 64,
        personas=personas,
    )
    cohort = cohort.model_copy(update={"cohort_sha256": cohort_sha256(cohort, DATASET_SHA256)})
    dataset = DatasetIntegrityInput(
        id=DATASET_ID,
        slug="large-dataset",
        display_name="Large sealed dataset",
        schema_version="v1",
        parent_pool=None,
        source_repository=None,
        persona_count=1_000_000,
        manifest_sha256="b" * 64,
        dataset_sha256=DATASET_SHA256,
    )
    selected_alt = alt_two
    variants = (
        SemanticVariant(
            experiment_position=0,
            role=baseline.role,
            id=baseline.id,
            scenario_position=baseline.position,
            name=baseline.name,
            hypothesis=baseline.hypothesis,
            intervention_count=0,
            interventions=(),
        ),
        SemanticVariant(
            experiment_position=1,
            role=selected_alt.role,
            id=selected_alt.id,
            scenario_position=selected_alt.position,
            name=selected_alt.name,
            hypothesis=selected_alt.hypothesis,
            intervention_count=1,
            interventions=selected_alt.interventions,
        ),
    )
    experiment = SemanticExperiment(
        id=EXPERIMENT_ID,
        scenario_id=scenario.id,
        scenario_sha256=scenario.scenario_sha256,
        scenario_title=scenario.title,
        decision_question=scenario.decision_question,
        cohort_id=cohort.id,
        cohort_sha256=cohort.cohort_sha256,
        cohort_title=cohort.title,
        dataset_sha256=dataset.dataset_sha256,
        persona_count=persona_count,
        rounds=1,
        minutes_per_round=15,
        model_name="deterministic-local-model",
        semantic_config_sha256=CONFIG_SHA256,
        prompt_schema_version="matraix-semantic-profile/v1",
        experiment_sha256="0" * 64,
        variants=variants,
        seeds=(7,),
    )
    experiment = experiment.model_copy(update={"experiment_sha256": experiment_sha256(experiment)})
    selected = experiment.variants[selected_position]
    return ClaimedSemanticTrial(
        id=TRIAL_ID,
        status="running",
        created_at=datetime(2026, 8, 12, tzinfo=UTC),
        experiment=experiment,
        variant_position=selected_position,
        variant_role=selected.role,
        scenario_variant_id=selected.id,
        scenario_position=selected.scenario_position,
        variant_name=selected.name,
        variant_hypothesis=selected.hypothesis,
        seed=7,
        trial_sha256=trial_sha256(experiment, selected_position, 7),
        scenario=scenario,
        dataset=dataset,
        cohort=cohort,
    )
