"""System liveness, readiness, and capability endpoints."""

from fastapi import APIRouter, Request, Response, status

from app.config import RuntimeSettings
from app.database import DatabaseConnector
from app.system.contracts import (
    HealthResponse,
    ReadinessResponse,
    ReadinessStatus,
    SystemCapabilities,
)
from app.system.service import (
    build_health_response,
    build_readiness_response,
    build_system_capabilities,
)


def create_system_router(settings: RuntimeSettings) -> APIRouter:
    """Create system routes bound to one immutable configuration snapshot."""
    router = APIRouter(tags=["system"])

    @router.get("/health", response_model=HealthResponse)
    def get_health() -> HealthResponse:
        """Report whether the V2 API process can serve requests."""
        return build_health_response()

    @router.get("/readyz", response_model=ReadinessResponse)
    async def get_deployment_readiness(
        request: Request,
        response: Response,
    ) -> ReadinessResponse:
        """Probe every dependency required to serve the current product phase."""
        database: DatabaseConnector | None = getattr(request.app.state, "database", None)
        readiness = await build_readiness_response(settings, database)
        if readiness.status is ReadinessStatus.NOT_READY:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return readiness

    @router.get("/api/v2/system/readiness", response_model=ReadinessResponse)
    async def get_readiness(request: Request) -> ReadinessResponse:
        """Report diagnostic readiness using the same real dependency probes."""
        database: DatabaseConnector | None = getattr(request.app.state, "database", None)
        return await build_readiness_response(settings, database)

    @router.get("/api/v2/system/capabilities", response_model=SystemCapabilities)
    def get_system_capabilities() -> SystemCapabilities:
        """Expose the explicit V2 domain and engine boundaries."""
        return build_system_capabilities()

    return router
