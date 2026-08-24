"""Strict contracts for deterministic, evidence-linked reports."""

from datetime import date
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    ConfigDict,
    Field,
    FiniteFloat,
    HttpUrl,
    StringConstraints,
    model_validator,
)

from app.semantic_experiments.contracts import (
    ComparisonState,
    PromptSchemaVersion,
    SemanticModelName,
    SemanticStatus,
)
from app.shared.contracts import ContractModel, Identifier, Sha256Digest

type ReportSectionKind = Literal["scope", "comparison", "limitations", "provenance"]
type MetricName = Literal[
    "observed_action_count",
    "authored_content_count",
    "reaction_count",
    "do_nothing_count",
]
type ReportTitle = Annotated[
    str,
    StringConstraints(min_length=1, max_length=300, pattern=r"^[^\r\n]+$", strip_whitespace=True),
]
type ReportBody = Annotated[str, StringConstraints(min_length=1, max_length=40_000)]


class DecisionReportMetric(ContractModel):
    metric: MetricName
    alternative_id: UUID
    alternative_name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    baseline_mean: FiniteFloat
    alternative_mean: FiniteFloat
    mean_delta: FiniteFloat
    stddev_delta: Annotated[float, Field(strict=True, ge=0.0, allow_inf_nan=False)]
    paired_seed_count: Annotated[int, Field(ge=1, le=2)]


class DecisionReportSection(ContractModel):
    position: Annotated[int, Field(ge=0, le=3)]
    kind: ReportSectionKind
    title: ReportTitle
    body_markdown: ReportBody
    metrics: tuple[DecisionReportMetric, ...]


class DecisionReport(ContractModel):
    id: UUID
    experiment_id: UUID
    experiment_sha256: Sha256Digest
    scenario_id: UUID
    scenario_sha256: Sha256Digest
    cohort_id: UUID
    cohort_sha256: Sha256Digest
    title: ReportTitle
    report_sha256: Sha256Digest
    generator_version: Literal["deterministic-findings/v1"]
    created_at: AwareDatetime
    sections: Annotated[tuple[DecisionReportSection, ...], Field(min_length=4, max_length=4)]

    @model_validator(mode="after")
    def validate_sections(self) -> Self:
        if tuple(section.position for section in self.sections) != (0, 1, 2, 3):
            raise ValueError("report section positions must be contiguous from zero")
        if tuple(section.kind for section in self.sections) != (
            "scope",
            "comparison",
            "limitations",
            "provenance",
        ):
            raise ValueError("report sections must use the fixed findings outline")
        return self


class DecisionReportsResponse(ContractModel):
    items: tuple[DecisionReport, ...]
    total: Annotated[int, Field(ge=0)]


type DecisionReportV2SectionKind = Literal[
    "evidence",
    "assumptions",
    "experiment",
    "observation",
    "comparison",
    "analysis",
    "limitations",
]
type DecisionReportV2MetricName = MetricName
type DecisionReportV2EvidenceKind = Literal["media_article", "policy_document"]
type DecisionReportV2AnalysisType = Literal[
    "accounting_explanation",
    "scope_explanation",
    "boundary_explanation",
]
type DecisionReportV2LimitationCode = Literal[
    "sample_size",
    "synthetic_inputs",
    "model_dependency",
    "simulation_boundary",
    "evidence_boundary",
    "clock_semantics",
    "no_prediction_or_recommendation",
]
type DecisionReportV2LimitationSeverity = Literal["material", "context"]


class DecisionReportV2Payload(ContractModel):
    """Strict discriminated payload stored beside one V2 report section."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class DecisionReportV2SnapshotRef(DecisionReportV2Payload):
    world_model_id: UUID
    world_snapshot_id: UUID
    version: Annotated[int, Field(ge=1)]
    snapshot_sha256: Sha256Digest
    created_at: AwareDatetime
    sealed_at: AwareDatetime
    verification: Literal["human_confirmed"]


class DecisionReportV2EvidenceSource(DecisionReportV2Payload):
    evidence_kind: DecisionReportV2EvidenceKind
    source_id: UUID
    source_name: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    original_url: HttpUrl
    title: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    published_at: AwareDatetime | None
    publication_date: date | None
    captured_at: AwareDatetime
    content_sha256: Sha256Digest
    identity_sha256: Sha256Digest
    excerpt: Annotated[str, StringConstraints(min_length=1, max_length=280)]


class DecisionReportV2EvidenceBoundary(DecisionReportV2Payload):
    status: Literal["frozen_source_copy_not_independent_fact_check"]
    statements: Annotated[tuple[str, ...], Field(min_length=1, max_length=10)]


class DecisionReportV2EvidencePayload(DecisionReportV2Payload):
    payload_kind: Literal["evidence"]
    world_snapshot: DecisionReportV2SnapshotRef
    sources: Annotated[
        tuple[DecisionReportV2EvidenceSource, ...], Field(min_length=1, max_length=50)
    ]
    evidence_boundary: DecisionReportV2EvidenceBoundary


class DecisionReportV2Intervention(DecisionReportV2Payload):
    id: UUID
    kind: Literal["initial_post"]
    actor: Literal["scenario_actor"]
    channel: Literal["reddit"]
    content: Annotated[str, StringConstraints(min_length=1, max_length=4000)]
    offset_minutes: Annotated[int, Field(ge=0, le=1440)]
    provenance: Literal["scenario_assumption"]
    synthetic_label: Annotated[str, StringConstraints(min_length=1, max_length=64)] | None


class DecisionReportV2Variant(DecisionReportV2Payload):
    id: UUID
    position: Annotated[int, Field(ge=0, le=5)]
    role: Literal["baseline", "alternative"]
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    hypothesis: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    interventions: tuple[DecisionReportV2Intervention, ...]

    @model_validator(mode="after")
    def validate_role(self) -> Self:
        if self.role == "baseline" and (self.position != 0 or self.interventions):
            raise ValueError("V2 baseline must be position zero and have no interventions")
        if self.role == "alternative" and (self.position < 1 or not self.interventions):
            raise ValueError("V2 alternative must have a positive position and interventions")
        return self


class DecisionReportV2ScenarioRef(DecisionReportV2Payload):
    id: UUID
    scenario_sha256: Sha256Digest
    title: ReportTitle
    decision_question: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    world_snapshot_id: UUID
    snapshot_sha256: Sha256Digest
    variants: Annotated[tuple[DecisionReportV2Variant, ...], Field(min_length=2, max_length=3)]


class DecisionReportV2AssumptionsPayload(DecisionReportV2Payload):
    payload_kind: Literal["assumptions"]
    scenario: DecisionReportV2ScenarioRef
    assumption_boundary: Annotated[tuple[str, ...], Field(min_length=1, max_length=10)]


class DecisionReportV2ExperimentRef(DecisionReportV2Payload):
    id: UUID
    experiment_sha256: Sha256Digest
    status: SemanticStatus
    scenario_id: UUID
    scenario_sha256: Sha256Digest
    cohort_id: UUID
    cohort_sha256: Sha256Digest
    dataset_sha256: Sha256Digest
    persona_count: Annotated[int, Field(ge=1, le=8)]
    variants: Annotated[tuple[DecisionReportV2Variant, ...], Field(min_length=2, max_length=3)]
    seeds: Annotated[tuple[int, ...], Field(min_length=1, max_length=2)]
    rounds: Annotated[int, Field(ge=1, le=3)]
    minutes_per_round: Annotated[int, Field(ge=15, le=240)]
    model_name: SemanticModelName
    semantic_config_sha256: Sha256Digest
    prompt_schema_version: PromptSchemaVersion
    engine_version: Annotated[str, StringConstraints(min_length=1, max_length=32)] | None
    camel_version: Annotated[str, StringConstraints(min_length=1, max_length=32)] | None


class DecisionReportV2TrialFailure(DecisionReportV2Payload):
    code: Identifier
    message: Annotated[str, StringConstraints(min_length=1, max_length=4000)]


class DecisionReportV2Trial(DecisionReportV2Payload):
    id: UUID
    variant_id: UUID
    role: Literal["baseline", "alternative"]
    seed: Annotated[int, Field(ge=0, le=4_294_967_295)]
    trial_sha256: Sha256Digest
    status: SemanticStatus
    created_at: AwareDatetime
    started_at: AwareDatetime | None
    completed_at: AwareDatetime | None
    artifact_sha256: Sha256Digest | None
    rounds_completed: Annotated[int, Field(ge=1, le=3)] | None
    failure: DecisionReportV2TrialFailure | None


class DecisionReportV2ExperimentPayload(DecisionReportV2Payload):
    payload_kind: Literal["experiment"]
    experiment: DecisionReportV2ExperimentRef
    trials: Annotated[tuple[DecisionReportV2Trial, ...], Field(min_length=2, max_length=6)]


class DecisionReportV2NormalizedCounts(DecisionReportV2Payload):
    scenario_initial_posts: Annotated[int, Field(ge=0)]
    generated_posts: Annotated[int, Field(ge=0)]
    comments: Annotated[int, Field(ge=0)]
    reactions: Annotated[int, Field(ge=0)]
    do_nothing: Annotated[int, Field(ge=0)]
    observed_actions: Annotated[int, Field(ge=0)]
    authored_content: Annotated[int, Field(ge=0)]


class DecisionReportV2EventClockBoundary(DecisionReportV2Payload):
    observed_at_raw_semantics: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    recorded_at_semantics: Annotated[str, StringConstraints(min_length=1, max_length=500)]


class DecisionReportV2ObservationTrial(DecisionReportV2Payload):
    trial_id: UUID
    variant_id: UUID
    seed: Annotated[int, Field(ge=0, le=4_294_967_295)]
    status: SemanticStatus
    event_count: Annotated[int, Field(ge=0)]
    events_sha256: Sha256Digest
    event_endpoint: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    normalized_counts: DecisionReportV2NormalizedCounts
    event_clock_boundary: DecisionReportV2EventClockBoundary


class DecisionReportV2ObservationStatement(DecisionReportV2Payload):
    statement: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    basis: Annotated[tuple[str, ...], Field(min_length=1, max_length=10)]


class DecisionReportV2ObservationPayload(DecisionReportV2Payload):
    payload_kind: Literal["observation"]
    trials: Annotated[
        tuple[DecisionReportV2ObservationTrial, ...], Field(min_length=2, max_length=6)
    ]
    behavior_changes: Annotated[
        tuple[DecisionReportV2ObservationStatement, ...], Field(min_length=1, max_length=20)
    ]


class DecisionReportV2MetricVariant(DecisionReportV2Payload):
    variant_id: UUID
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    role: Literal["baseline", "alternative"]
    mean: FiniteFloat
    stddev: Annotated[float, Field(strict=True, ge=0.0, allow_inf_nan=False)]
    n: Annotated[int, Field(ge=1, le=2)]


class DecisionReportV2MetricAlternative(DecisionReportV2Payload):
    variant_id: UUID
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    mean: FiniteFloat
    stddev: Annotated[float, Field(strict=True, ge=0.0, allow_inf_nan=False)]
    n: Annotated[int, Field(ge=1, le=2)]
    mean_delta: FiniteFloat
    stddev_delta: Annotated[float, Field(strict=True, ge=0.0, allow_inf_nan=False)]
    paired_seeds: Annotated[tuple[int, ...], Field(min_length=1, max_length=2)]
    paired_seed_count: Annotated[int, Field(ge=1, le=2)]

    @model_validator(mode="after")
    def validate_seed_count(self) -> Self:
        if self.paired_seed_count != len(self.paired_seeds):
            raise ValueError("paired_seed_count must equal the paired seed list length")
        return self


class DecisionReportV2Metric(DecisionReportV2Payload):
    metric: DecisionReportV2MetricName
    variants: Annotated[
        tuple[DecisionReportV2MetricVariant, ...], Field(min_length=2, max_length=3)
    ]
    alternatives: Annotated[
        tuple[DecisionReportV2MetricAlternative, ...], Field(min_length=1, max_length=2)
    ]


class DecisionReportV2ComparisonPayload(DecisionReportV2Payload):
    payload_kind: Literal["comparison"]
    metrics: tuple[DecisionReportV2Metric, ...]
    comparison_state: ComparisonState
    pairing_rule: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    comparison_boundary: Annotated[tuple[str, ...], Field(min_length=1, max_length=10)]


class DecisionReportV2AnalysisStatement(DecisionReportV2Payload):
    statement_id: Identifier
    text: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    basis: Annotated[tuple[str, ...], Field(min_length=1, max_length=10)]
    allowed_type: DecisionReportV2AnalysisType


class DecisionReportV2AnalysisPayload(DecisionReportV2Payload):
    payload_kind: Literal["analysis"]
    statements: Annotated[
        tuple[DecisionReportV2AnalysisStatement, ...], Field(min_length=1, max_length=20)
    ]
    prohibited_claims: Annotated[tuple[str, ...], Field(min_length=1, max_length=10)]


class DecisionReportV2LimitationItem(DecisionReportV2Payload):
    code: DecisionReportV2LimitationCode
    text: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    severity: DecisionReportV2LimitationSeverity


class DecisionReportV2LimitationsPayload(DecisionReportV2Payload):
    payload_kind: Literal["limitations"]
    items: Annotated[tuple[DecisionReportV2LimitationItem, ...], Field(min_length=1, max_length=10)]


type DecisionReportV2PayloadUnion = Annotated[
    DecisionReportV2EvidencePayload
    | DecisionReportV2AssumptionsPayload
    | DecisionReportV2ExperimentPayload
    | DecisionReportV2ObservationPayload
    | DecisionReportV2ComparisonPayload
    | DecisionReportV2AnalysisPayload
    | DecisionReportV2LimitationsPayload,
    Field(discriminator="payload_kind"),
]


class DecisionReportV2Section(ContractModel):
    position: Annotated[int, Field(ge=0, le=6)]
    kind: DecisionReportV2SectionKind
    title: ReportTitle
    body_markdown: ReportBody
    data: DecisionReportV2PayloadUnion

    @model_validator(mode="after")
    def validate_payload_kind(self) -> Self:
        if self.data.payload_kind != self.kind:
            raise ValueError("V2 report section kind must match its payload kind")
        return self


class DecisionReportV2(ContractModel):
    id: UUID
    experiment_id: UUID
    experiment_sha256: Sha256Digest
    scenario_id: UUID
    scenario_sha256: Sha256Digest
    cohort_id: UUID
    cohort_sha256: Sha256Digest
    world_snapshot_id: UUID
    world_snapshot_sha256: Sha256Digest
    title: ReportTitle
    report_sha256: Sha256Digest
    generator_version: Literal["decision-report/v2"]
    created_at: AwareDatetime
    sections: Annotated[tuple[DecisionReportV2Section, ...], Field(min_length=7, max_length=7)]

    @model_validator(mode="after")
    def validate_sections(self) -> Self:
        expected = (
            "evidence",
            "assumptions",
            "experiment",
            "observation",
            "comparison",
            "analysis",
            "limitations",
        )
        positions = tuple(section.position for section in self.sections)
        kinds = tuple(section.kind for section in self.sections)
        if positions != tuple(range(7)):
            raise ValueError("V2 report section positions must be contiguous from zero")
        if kinds != expected:
            raise ValueError("V2 report sections must use the fixed seven-part outline")
        return self


class DecisionReportsV2Response(ContractModel):
    items: tuple[DecisionReportV2, ...]
    total: Annotated[int, Field(ge=0)]
