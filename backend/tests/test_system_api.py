"""Real ASGI smoke tests for the V2 system boundary."""

from types import TracebackType

from fastapi.testclient import TestClient

from app.config import load_runtime_settings
from app.main import create_app
from app.system.contracts import CapabilityStatus, SystemCapabilities


class SuccessfulProbeResult:
    """Minimum successful scalar result returned by the readiness connector."""

    def scalar_one(self) -> int:
        return 1


class SuccessfulProbeConnection:
    """Connection facade proving that the route executes SELECT 1."""

    async def execute(self, statement: object) -> SuccessfulProbeResult:
        assert str(statement) == "SELECT 1"
        return SuccessfulProbeResult()


class SuccessfulProbeContext:
    """Async connection context used by the in-process readiness smoke test."""

    async def __aenter__(self) -> SuccessfulProbeConnection:
        return SuccessfulProbeConnection()

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class SuccessfulProbeEngine:
    """Engine facade for a deterministic configured-connector probe."""

    def connect(self) -> SuccessfulProbeContext:
        return SuccessfulProbeContext()


class SuccessfulProbeConnector:
    """Configured connector exposing only the engine surface used by readiness."""

    engine = SuccessfulProbeEngine()


class FailedProbeContext:
    """Connection context that exposes a database outage without a real network call."""

    async def __aenter__(self) -> SuccessfulProbeConnection:
        raise OSError("connection refused for postgresql://app:secret@database/internal")

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class FailedProbeEngine:
    """Engine facade for a deterministic database connection failure."""

    def connect(self) -> FailedProbeContext:
        return FailedProbeContext()


class FailedProbeConnector:
    """Configured connector whose dependency is unavailable."""

    engine = FailedProbeEngine()


def create_test_client(environment: dict[str, str]) -> TestClient:
    return TestClient(create_app(load_runtime_settings(environment)))


def test_health_endpoint() -> None:
    client = create_test_client({})

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "ai-decision-center-v2",
        "version": "0.1.0",
    }


def test_capabilities_endpoint_exposes_all_foundation_domains() -> None:
    client = create_test_client({})

    response = client.get("/api/v2/system/capabilities")

    assert response.status_code == 200
    capabilities = SystemCapabilities.model_validate_json(response.content)
    assert {capability.name for capability in capabilities.capabilities} == {
        "media",
        "evidence",
        "world_models",
        "world_graphs",
        "decision_threads",
        "decision_reports",
        "report_questions",
        "scenarios",
        "populations.matraix",
        "simulations.matraix",
        "tasks.matraix.survey",
        "simulations.oasis",
    }
    states_by_name = {capability.name: capability.state for capability in capabilities.capabilities}
    assert states_by_name["media"] is CapabilityStatus.RUNTIME_READY
    assert states_by_name["world_models"] is CapabilityStatus.RUNTIME_READY
    assert states_by_name["world_graphs"] is CapabilityStatus.RUNTIME_READY
    assert states_by_name["decision_threads"] is CapabilityStatus.RUNTIME_READY
    assert states_by_name["decision_reports"] is CapabilityStatus.RUNTIME_READY
    assert states_by_name["report_questions"] is CapabilityStatus.RUNTIME_READY
    assert states_by_name["evidence"] is CapabilityStatus.RUNTIME_READY
    assert states_by_name["scenarios"] is CapabilityStatus.RUNTIME_READY
    assert states_by_name["populations.matraix"] is CapabilityStatus.RUNTIME_READY
    assert states_by_name["simulations.matraix"] is CapabilityStatus.CONTRACT_READY
    assert states_by_name["tasks.matraix.survey"] is CapabilityStatus.RUNTIME_READY
    assert states_by_name["simulations.oasis"] is CapabilityStatus.RUNTIME_READY


def test_readyz_returns_503_when_required_database_is_not_configured() -> None:
    client = create_test_client({})

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "phase": "media_evidence",
        "runtime": {"app_env": "not_configured"},
        "dependencies": [
            {
                "name": "database",
                "configuration": "not_configured",
                "connectivity": "not_checked",
                "required_for_phase": True,
            },
            {
                "name": "redis",
                "configuration": "not_configured",
                "connectivity": "not_checked",
                "required_for_phase": False,
            },
        ],
    }


def test_diagnostic_readiness_is_truthful_without_database_configuration() -> None:
    client = create_test_client({})

    response = client.get("/api/v2/system/readiness")

    assert response.status_code == 200
    assert response.json()["status"] == "not_ready"
    assert response.json()["dependencies"][0] == {
        "name": "database",
        "configuration": "not_configured",
        "connectivity": "not_checked",
        "required_for_phase": True,
    }


def test_readyz_and_diagnostic_readiness_probe_a_configured_database() -> None:
    application = create_app(
        load_runtime_settings(
            {
                "APP_ENV": "development",
                "DATABASE_URL": "postgresql://app:secret@postgres:5432/ai_decision_center",
                "REDIS_URL": "redis://:secret@redis:6379/0",
            }
        )
    )
    application.state.database = SuccessfulProbeConnector()
    client = TestClient(application)

    deployment_response = client.get("/readyz")
    diagnostic_response = client.get("/api/v2/system/readiness")

    assert deployment_response.status_code == 200
    assert diagnostic_response.status_code == 200
    readiness = diagnostic_response.json()
    assert readiness["status"] == "ready"
    assert readiness["phase"] == "media_evidence"
    assert readiness["runtime"] == {"app_env": "configured"}
    assert [dependency["configuration"] for dependency in readiness["dependencies"]] == [
        "configured",
        "configured",
    ]
    assert [dependency["connectivity"] for dependency in readiness["dependencies"]] == [
        "connected",
        "not_checked",
    ]
    assert [dependency["required_for_phase"] for dependency in readiness["dependencies"]] == [
        True,
        False,
    ]


def test_readyz_returns_503_without_exposing_database_failure_details() -> None:
    application = create_app(
        load_runtime_settings(
            {
                "DATABASE_URL": "postgresql://app:secret@database:5432/ai_decision_center",
            }
        )
    )
    application.state.database = FailedProbeConnector()
    client = TestClient(application)

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["dependencies"][0]["connectivity"] == "failed"
    assert "secret" not in response.text
    assert "postgresql" not in response.text
