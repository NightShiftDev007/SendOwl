"""Builders and explicit dependency probes for V2 system discovery."""

import asyncio

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import RuntimeSettings
from app.database import DatabaseConnector
from app.system.contracts import (
    CapabilityDescriptor,
    CapabilityStatus,
    ConfigurationState,
    ConnectivityState,
    DependencyName,
    DependencyReadiness,
    HealthResponse,
    HealthStatus,
    ReadinessPhase,
    ReadinessResponse,
    ReadinessStatus,
    RuntimeConfigurationReadiness,
    SystemCapabilities,
)


def build_health_response() -> HealthResponse:
    """Build the deterministic API liveness response."""
    return HealthResponse(
        status=HealthStatus.OK,
        service="ai-decision-center-v2",
        version="0.1.0",
    )


def configuration_state(is_configured: bool) -> ConfigurationState:
    """Map explicit configuration presence to the public readiness contract."""
    if is_configured:
        return ConfigurationState.CONFIGURED
    return ConfigurationState.NOT_CONFIGURED


async def probe_database_connectivity(
    database: DatabaseConnector,
) -> ConnectivityState:
    """Run the minimum query required to prove database connectivity."""
    try:
        async with asyncio.timeout(3):
            async with database.engine.connect() as connection:
                result = await connection.execute(text("SELECT 1"))
                if result.scalar_one() != 1:
                    return ConnectivityState.FAILED
    except (OSError, SQLAlchemyError, TimeoutError):
        return ConnectivityState.FAILED
    return ConnectivityState.CONNECTED


async def build_readiness_response(
    settings: RuntimeSettings,
    database: DatabaseConnector | None,
) -> ReadinessResponse:
    """Describe media/evidence readiness using a real database probe."""
    database_configuration = configuration_state(settings.database_url is not None)
    if settings.database_url is None:
        database_connectivity = ConnectivityState.NOT_CHECKED
    elif database is None:
        database_connectivity = ConnectivityState.FAILED
    else:
        database_connectivity = await probe_database_connectivity(database)

    readiness_status = (
        ReadinessStatus.READY
        if database_connectivity is ConnectivityState.CONNECTED
        else ReadinessStatus.NOT_READY
    )
    return ReadinessResponse(
        status=readiness_status,
        phase=ReadinessPhase.MEDIA_EVIDENCE,
        runtime=RuntimeConfigurationReadiness(
            app_env=configuration_state(settings.app_env is not None),
        ),
        dependencies=(
            DependencyReadiness(
                name=DependencyName.DATABASE,
                configuration=database_configuration,
                connectivity=database_connectivity,
                required_for_phase=True,
            ),
            DependencyReadiness(
                name=DependencyName.REDIS,
                configuration=configuration_state(settings.redis_url is not None),
                connectivity=ConnectivityState.NOT_CHECKED,
                required_for_phase=False,
            ),
        ),
    )


def build_system_capabilities() -> SystemCapabilities:
    """Build the explicit first-stage domain capability inventory."""
    return SystemCapabilities(
        api_version="v2",
        product="AI Decision Center",
        capabilities=(
            CapabilityDescriptor(
                name="media",
                state=CapabilityStatus.RUNTIME_READY,
                source="AgendaScope",
                contracts=(
                    "MediaSource",
                    "MediaArticle",
                    "MediaSourceEvidenceResponse",
                    "MediaFirstUtterancesResponse",
                    "MediaSyncStatus",
                ),
            ),
            CapabilityDescriptor(
                name="evidence",
                state=CapabilityStatus.RUNTIME_READY,
                source="AI Decision Center V2",
                contracts=(
                    "EvidenceBundleSummary",
                    "EvidenceBundleDetail",
                    "EvidenceBundleContent",
                ),
            ),
            CapabilityDescriptor(
                name="world_models",
                state=CapabilityStatus.RUNTIME_READY,
                source="AI Decision Center V2",
                contracts=("WorldModel", "WorldSnapshot"),
            ),
            CapabilityDescriptor(
                name="world_graphs",
                state=CapabilityStatus.RUNTIME_READY,
                source="Qwen + PostgreSQL",
                contracts=(
                    "SemanticWorldGraph",
                    "SemanticWorldGraphSearchResponse",
                    "SemanticWorldGraphEdgeHistory",
                    "SemanticWorldGraphPersonaMatches",
                    "GraphPersonaCohortOrigin",
                    "GraphPersonaCohortCreation",
                    "GraphPersonaCohortOriginsResponse",
                    "GraphNode",
                    "GraphEdge",
                ),
            ),
            CapabilityDescriptor(
                name="decision_threads",
                state=CapabilityStatus.RUNTIME_READY,
                source="AI Decision Center integration layer",
                contracts=("DecisionThread", "DecisionThreadRevision"),
            ),
            CapabilityDescriptor(
                name="decision_reports",
                state=CapabilityStatus.RUNTIME_READY,
                source="AI Decision Center + MiroFish report structure",
                contracts=("DecisionReport", "DecisionReportSection"),
            ),
            CapabilityDescriptor(
                name="report_questions",
                state=CapabilityStatus.RUNTIME_READY,
                source="Qwen + PostgreSQL evidence graph",
                contracts=(
                    "ReportQuestion",
                    "ReportQuestionContext",
                    "ReportAnswerCitation",
                ),
            ),
            CapabilityDescriptor(
                name="tasks.mirofish.persona_interview",
                state=CapabilityStatus.RUNTIME_READY,
                source="MiroFish interaction pattern + MatrAIx Persona + Qwen",
                contracts=(
                    "PersonaInterview",
                    "PersonaInterviewPersona",
                    "PersonaInterviewSession",
                ),
            ),
            CapabilityDescriptor(
                name="scenarios",
                state=CapabilityStatus.RUNTIME_READY,
                source="AI Decision Center V2",
                contracts=("Scenario", "ScenarioVariant", "Intervention"),
            ),
            CapabilityDescriptor(
                name="populations.matraix",
                state=CapabilityStatus.RUNTIME_READY,
                source="MatrAIx",
                contracts=("PersonaDataset", "Persona", "Cohort"),
            ),
            CapabilityDescriptor(
                name="simulations.matraix",
                state=CapabilityStatus.CONTRACT_READY,
                source="MatrAIx",
                contracts=("MatrAIxEvaluationSpec", "EngineResult"),
            ),
            CapabilityDescriptor(
                name="tasks.matraix.survey",
                state=CapabilityStatus.RUNTIME_READY,
                source="MatrAIx + Qwen",
                contracts=(
                    "MatraixSurveyExperiment",
                    "MatraixSurveyTrial",
                    "SurveyInstrument",
                    "ParentProgress",
                ),
            ),
            CapabilityDescriptor(
                name="tasks.matraix.chat",
                state=CapabilityStatus.RUNTIME_READY,
                source="MatrAIx source sample + Qwen",
                contracts=(
                    "MatraixChatTask",
                    "MatraixChatEvaluation",
                    "MatraixChatTrial",
                    "MatraixChatAtifProjection",
                    "ParentProgress",
                ),
            ),
            CapabilityDescriptor(
                name="tasks.matraix.web",
                state=CapabilityStatus.RUNTIME_READY,
                source="MatrAIx Playwright source sample + Qwen + immutable retry lineage",
                contracts=(
                    "MatraixWebTask",
                    "MatraixWebEvaluation",
                    "MatraixWebTrial",
                    "WebPageObservation",
                    "ParentProgress",
                ),
            ),
            CapabilityDescriptor(
                name="tasks.matraix.linux_artifact",
                state=CapabilityStatus.RUNTIME_READY,
                source=(
                    "MatrAIx Linux source sample + Qwen + isolated artifact runner "
                    "+ immutable retry lineage"
                ),
                contracts=(
                    "MatraixLinuxTask",
                    "MatraixLinuxEvaluation",
                    "MatraixLinuxTrial",
                    "LinuxTrialResult",
                    "ParentProgress",
                ),
            ),
            CapabilityDescriptor(
                name="trials.matraix.archive",
                state=CapabilityStatus.RUNTIME_READY,
                source="MatrAIx Survey + Chat + Web + Linux durable records",
                contracts=(
                    "MatraixTrialArchiveResponse",
                    "MatraixTrialArchiveStatistics",
                    "MatraixTrialIntegrityVerification",
                    "SurveyTrialArchiveItem",
                    "ChatTrialArchiveItem",
                    "WebTrialArchiveItem",
                    "LinuxTrialArchiveItem",
                ),
            ),
            CapabilityDescriptor(
                name="jobs.matraix.batch_registry",
                state=CapabilityStatus.RUNTIME_READY,
                source="MatrAIx Survey + Chat + Web + Linux sealed parent registry",
                contracts=(
                    "MatraixBatchRegistrySummary",
                    "MatraixBatchRegistryDetail",
                    "MatraixBatchRegistryCandidatesResponse",
                    "WebBatchRegistryItem",
                    "WebBatchRegistryCandidate",
                    "LinuxBatchRegistryItem",
                    "LinuxBatchRegistryCandidate",
                    "MatraixNativeBatchLaunchRequest",
                    "MatraixNativeBatchLaunchResult",
                ),
            ),
            CapabilityDescriptor(
                name="simulations.oasis",
                state=CapabilityStatus.RUNTIME_READY,
                source="AI Decision Center V1 / OASIS",
                contracts=(
                    "OasisSimulationSpec",
                    "SemanticExperiment",
                    "SemanticTrial",
                    "SemanticTrialEvent",
                ),
            ),
        ),
    )
