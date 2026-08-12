"""HTTP boundary for durable OASIS platform-smoke execution."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DatabaseConnector
from app.scenarios.errors import ScenarioNotFoundError
from app.simulations.contracts import (
    OasisReadiness,
    PlatformSmokeCreateRequest,
    PlatformSmokeRunDetail,
    PlatformSmokeRunsResponse,
)
from app.simulations.errors import (
    PlatformSmokeRunNotFoundError,
    PlatformSmokeUnavailableError,
    PlatformSmokeVariantError,
)
from app.simulations.repository import (
    create_platform_smoke_run,
    get_oasis_readiness,
    get_platform_smoke_run,
    list_platform_smoke_runs,
)

SIMULATION_RUNS_UNAVAILABLE_DETAIL = (
    "Simulation run data is unavailable because DATABASE_URL is not configured"
)


async def require_simulation_run_session(request: Request) -> AsyncIterator[AsyncSession]:
    connector: DatabaseConnector | None = getattr(request.app.state, "database", None)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=SIMULATION_RUNS_UNAVAILABLE_DETAIL,
        )
    async with connector.session() as session:
        yield session


SimulationRunSession = Annotated[AsyncSession, Depends(require_simulation_run_session)]


def create_simulation_runs_router() -> APIRouter:
    """Create OASIS platform-smoke run and readiness routes."""
    router = APIRouter(tags=["simulations"])

    @router.post(
        "/api/v2/simulation-runs/platform-smoke",
        response_model=PlatformSmokeRunDetail,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def enqueue_platform_smoke(
        request: PlatformSmokeCreateRequest,
        session: SimulationRunSession,
    ) -> PlatformSmokeRunDetail:
        try:
            return await create_platform_smoke_run(
                session,
                request.scenario_id,
                request.variant_id,
                request.seed,
            )
        except ScenarioNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except PlatformSmokeVariantError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(error),
            ) from error
        except PlatformSmokeUnavailableError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(error),
            ) from error

    @router.get(
        "/api/v2/simulation-runs/platform-smoke",
        response_model=PlatformSmokeRunsResponse,
    )
    async def platform_smoke_runs(session: SimulationRunSession) -> PlatformSmokeRunsResponse:
        return await list_platform_smoke_runs(session)

    @router.get(
        "/api/v2/simulation-runs/platform-smoke/{run_id}",
        response_model=PlatformSmokeRunDetail,
    )
    async def platform_smoke_run(
        run_id: UUID,
        session: SimulationRunSession,
    ) -> PlatformSmokeRunDetail:
        try:
            return await get_platform_smoke_run(session, run_id)
        except PlatformSmokeRunNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.get("/api/v2/simulations/oasis/readiness", response_model=OasisReadiness)
    async def oasis_readiness(session: SimulationRunSession) -> OasisReadiness:
        return await get_oasis_readiness(session)

    return router
