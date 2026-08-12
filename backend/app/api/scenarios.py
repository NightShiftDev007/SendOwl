"""HTTP boundary for immutable decision scenarios."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DatabaseConnector
from app.scenarios.contracts import ScenarioCreateRequest, ScenarioDetail, ScenariosResponse
from app.scenarios.errors import ScenarioNotFoundError
from app.scenarios.repository import create_scenario, get_scenario, list_scenarios
from app.world_models.errors import WorldModelNotFoundError, WorldSnapshotNotFoundError

SCENARIOS_UNAVAILABLE_DETAIL = "Scenario data is unavailable because DATABASE_URL is not configured"


async def require_scenario_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Provide one database session or fail explicitly when persistence is unavailable."""
    connector: DatabaseConnector | None = getattr(request.app.state, "database", None)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=SCENARIOS_UNAVAILABLE_DETAIL,
        )
    async with connector.session() as session:
        yield session


ScenarioSession = Annotated[AsyncSession, Depends(require_scenario_session)]


def _not_found(
    error: ScenarioNotFoundError | WorldModelNotFoundError | WorldSnapshotNotFoundError,
) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))


def create_scenarios_router() -> APIRouter:
    """Create immutable scenario routes."""
    router = APIRouter(prefix="/api/v2/scenarios", tags=["scenarios"])

    @router.post("", response_model=ScenarioDetail, status_code=status.HTTP_201_CREATED)
    async def add_scenario(
        request: ScenarioCreateRequest,
        session: ScenarioSession,
    ) -> ScenarioDetail:
        """Create and atomically seal one scenario against an exact world snapshot."""
        try:
            return await create_scenario(session, request)
        except (WorldModelNotFoundError, WorldSnapshotNotFoundError) as error:
            raise _not_found(error) from error

    @router.get("", response_model=ScenariosResponse)
    async def scenarios(session: ScenarioSession) -> ScenariosResponse:
        """List immutable scenario summaries after content verification."""
        return await list_scenarios(session)

    @router.get("/{scenario_id}", response_model=ScenarioDetail)
    async def scenario(scenario_id: UUID, session: ScenarioSession) -> ScenarioDetail:
        """Return one complete immutable scenario after digest verification."""
        try:
            return await get_scenario(session, scenario_id)
        except ScenarioNotFoundError as error:
            raise _not_found(error) from error

    return router
