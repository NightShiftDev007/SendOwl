"""Contracts returned by system discovery endpoints."""

from enum import StrEnum

from app.shared.contracts import ContractModel, NonEmptyText


class HealthStatus(StrEnum):
    """Process-level health states."""

    OK = "ok"


class HealthResponse(ContractModel):
    """Stable liveness response for local and container probes."""

    status: HealthStatus
    service: NonEmptyText
    version: NonEmptyText


class ReadinessStatus(StrEnum):
    """Whether the service can perform the work required in its current phase."""

    READY = "ready"
    NOT_READY = "not_ready"


class ReadinessPhase(StrEnum):
    """Current implementation phase used to interpret dependency requirements."""

    MEDIA_EVIDENCE = "media_evidence"


class ConfigurationState(StrEnum):
    """Whether an optional runtime integration has explicit configuration."""

    CONFIGURED = "configured"
    NOT_CONFIGURED = "not_configured"


class ConnectivityState(StrEnum):
    """Whether a dependency connectivity probe was performed."""

    CONNECTED = "connected"
    FAILED = "failed"
    NOT_CHECKED = "not_checked"


class RuntimeConfigurationReadiness(ContractModel):
    """Non-dependency runtime configuration state."""

    app_env: ConfigurationState


class DependencyName(StrEnum):
    """Named external dependencies planned for later implementation phases."""

    DATABASE = "database"
    REDIS = "redis"


class DependencyReadiness(ContractModel):
    """Truthful configuration and probe state for one external dependency."""

    name: DependencyName
    configuration: ConfigurationState
    connectivity: ConnectivityState
    required_for_phase: bool


class ReadinessResponse(ContractModel):
    """Current phase readiness backed by explicit dependency probes."""

    status: ReadinessStatus
    phase: ReadinessPhase
    runtime: RuntimeConfigurationReadiness
    dependencies: tuple[DependencyReadiness, ...]


class CapabilityStatus(StrEnum):
    """Implementation maturity exposed without overstating V2 readiness."""

    CONTRACT_READY = "contract_ready"
    RUNTIME_READY = "runtime_ready"
    LEGACY_READONLY = "legacy_readonly"


class CapabilityDescriptor(ContractModel):
    """One domain boundary and the contracts available in the foundation."""

    name: NonEmptyText
    state: CapabilityStatus
    source: NonEmptyText
    contracts: tuple[NonEmptyText, ...]


class SystemCapabilities(ContractModel):
    """Machine-readable inventory for frontend and deployment discovery."""

    api_version: NonEmptyText
    product: NonEmptyText
    capabilities: tuple[CapabilityDescriptor, ...]
