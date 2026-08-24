"""HTTP boundary for single-run research projects."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DatabaseConnector
from app.populations.errors import PopulationCohortNotFoundError
from app.report_agents.contracts import ReportAgentRun
from app.report_agents.repository import (
    create_research_run_report_agent,
    find_research_run_report_agent,
)
from app.research_projects.agenda_context import (
    capture_project_agenda_context,
    get_project_agenda_context,
)
from app.research_projects.contracts import (
    ResearchProjectAgendaContext,
    ResearchProjectCreateRequest,
    ResearchProjectDetail,
    ResearchProjectsResponse,
    ResearchRunEventsResponse,
    ResearchRunGraphMemoryResponse,
    ResearchRunReport,
    ResearchRunReportsResponse,
    ResearchSimulationPlan,
    ResearchSimulationRunCreateRequest,
    ResearchSimulationRunDetail,
    ResearchSimulationRunsResponse,
)
from app.research_projects.errors import (
    ResearchProjectNotFoundError,
    ResearchSimulationRunNotFoundError,
)
from app.research_projects.models import ResearchProjectRecord
from app.research_projects.repository import (
    create_research_project,
    create_research_simulation_run,
    get_research_project,
    get_research_run_report,
    get_research_simulation_run,
    list_research_projects,
    list_research_run_events,
    list_research_run_graph_memory,
    list_research_run_reports,
    list_research_simulation_runs,
    preview_research_simulation_plan,
)
from app.semantic_experiments.errors import SemanticExperimentUnavailableError
from app.world_graphs.errors import WorldGraphNotFoundError
from app.world_models.errors import WorldModelNotFoundError, WorldSnapshotNotFoundError

RESEARCH_PROJECTS_UNAVAILABLE_DETAIL = (
    "Research projects are unavailable because DATABASE_URL is not configured"
)


async def require_research_project_session(request: Request) -> AsyncIterator[AsyncSession]:
    connector: DatabaseConnector | None = getattr(request.app.state, "database", None)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=RESEARCH_PROJECTS_UNAVAILABLE_DETAIL,
        )
    async with connector.session() as session:
        yield session


ResearchProjectSession = Annotated[AsyncSession, Depends(require_research_project_session)]


def _not_found(error: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))


def create_research_projects_router() -> APIRouter:
    """Create routes for projects and independent configured runs."""
    router = APIRouter(prefix="/api/v2/research-projects", tags=["research-projects"])

    @router.post("", response_model=ResearchProjectDetail, status_code=status.HTTP_201_CREATED)
    async def add_research_project(
        request: ResearchProjectCreateRequest,
        session: ResearchProjectSession,
    ) -> ResearchProjectDetail:
        try:
            return await create_research_project(session, request)
        except (
            WorldModelNotFoundError,
            WorldSnapshotNotFoundError,
            WorldGraphNotFoundError,
        ) as error:
            raise _not_found(error) from error
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(error),
            ) from error

    @router.get("", response_model=ResearchProjectsResponse)
    async def research_projects(session: ResearchProjectSession) -> ResearchProjectsResponse:
        return await list_research_projects(session)

    @router.get("/reports", response_model=ResearchRunReportsResponse)
    async def research_run_reports(
        session: ResearchProjectSession,
    ) -> ResearchRunReportsResponse:
        return await list_research_run_reports(session)

    @router.get("/{project_id}", response_model=ResearchProjectDetail)
    async def research_project(
        project_id: UUID,
        session: ResearchProjectSession,
    ) -> ResearchProjectDetail:
        try:
            return await get_research_project(session, project_id)
        except ResearchProjectNotFoundError as error:
            raise _not_found(error) from error

    @router.get(
        "/{project_id}/agenda-context",
        response_model=ResearchProjectAgendaContext | None,
    )
    async def project_agenda_context(
        project_id: UUID,
        session: ResearchProjectSession,
    ) -> ResearchProjectAgendaContext | None:
        try:
            await get_research_project(session, project_id)
        except ResearchProjectNotFoundError as error:
            raise _not_found(error) from error
        return await get_project_agenda_context(session, project_id)

    @router.post(
        "/{project_id}/agenda-context",
        response_model=ResearchProjectAgendaContext,
        status_code=status.HTTP_201_CREATED,
    )
    async def freeze_project_agenda_context(
        project_id: UUID,
        session: ResearchProjectSession,
    ) -> ResearchProjectAgendaContext:
        project = await session.get(ResearchProjectRecord, project_id)
        if project is None:
            raise _not_found(
                ResearchProjectNotFoundError(f"research project {project_id} was not found")
            )
        return await capture_project_agenda_context(session, project, commit=True)

    @router.post(
        "/{project_id}/runs/plan-preview",
        response_model=ResearchSimulationPlan,
    )
    async def research_simulation_plan_preview(
        project_id: UUID,
        request: ResearchSimulationRunCreateRequest,
        session: ResearchProjectSession,
    ) -> ResearchSimulationPlan:
        """Preview the deterministic schedule without creating a run or calling a model."""
        try:
            return await preview_research_simulation_plan(session, project_id, request)
        except (ResearchProjectNotFoundError, PopulationCohortNotFoundError) as error:
            raise _not_found(error) from error
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(error),
            ) from error

    @router.post(
        "/{project_id}/runs",
        response_model=ResearchSimulationRunDetail,
        status_code=status.HTTP_201_CREATED,
    )
    async def add_research_simulation_run(
        project_id: UUID,
        request: ResearchSimulationRunCreateRequest,
        session: ResearchProjectSession,
    ) -> ResearchSimulationRunDetail:
        try:
            return await create_research_simulation_run(session, project_id, request)
        except (ResearchProjectNotFoundError, PopulationCohortNotFoundError) as error:
            raise _not_found(error) from error
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(error),
            ) from error
        except SemanticExperimentUnavailableError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(error),
            ) from error

    @router.get("/{project_id}/runs", response_model=ResearchSimulationRunsResponse)
    async def research_simulation_runs(
        project_id: UUID,
        session: ResearchProjectSession,
    ) -> ResearchSimulationRunsResponse:
        try:
            return await list_research_simulation_runs(session, project_id)
        except ResearchProjectNotFoundError as error:
            raise _not_found(error) from error

    @router.get("/{project_id}/runs/{run_id}", response_model=ResearchSimulationRunDetail)
    async def research_simulation_run(
        project_id: UUID,
        run_id: UUID,
        session: ResearchProjectSession,
    ) -> ResearchSimulationRunDetail:
        try:
            return await get_research_simulation_run(session, project_id, run_id)
        except ResearchSimulationRunNotFoundError as error:
            raise _not_found(error) from error

    @router.get(
        "/{project_id}/runs/{run_id}/events",
        response_model=ResearchRunEventsResponse,
    )
    async def research_run_events(
        project_id: UUID,
        run_id: UUID,
        session: ResearchProjectSession,
    ) -> ResearchRunEventsResponse:
        try:
            return await list_research_run_events(session, project_id, run_id)
        except (ResearchProjectNotFoundError, ResearchSimulationRunNotFoundError) as error:
            raise _not_found(error) from error

    @router.get(
        "/{project_id}/runs/{run_id}/graph-memory",
        response_model=ResearchRunGraphMemoryResponse,
    )
    async def research_run_graph_memory(
        project_id: UUID,
        run_id: UUID,
        session: ResearchProjectSession,
    ) -> ResearchRunGraphMemoryResponse:
        try:
            return await list_research_run_graph_memory(session, project_id, run_id)
        except (ResearchProjectNotFoundError, ResearchSimulationRunNotFoundError) as error:
            raise _not_found(error) from error

    @router.get(
        "/{project_id}/runs/{run_id}/report",
        response_model=ResearchRunReport,
    )
    async def research_run_report(
        project_id: UUID,
        run_id: UUID,
        session: ResearchProjectSession,
    ) -> ResearchRunReport:
        try:
            return await get_research_run_report(session, project_id, run_id)
        except (
            ResearchProjectNotFoundError,
            ResearchSimulationRunNotFoundError,
        ) as error:
            raise _not_found(error) from error

    @router.post(
        "/{project_id}/runs/{run_id}/report-agent",
        response_model=ReportAgentRun,
        status_code=status.HTTP_201_CREATED,
    )
    async def research_run_report_agent(
        project_id: UUID,
        run_id: UUID,
        session: ResearchProjectSession,
    ) -> ReportAgentRun:
        """Seal an idempotent ReportAgent scope over one completed simulation run."""
        try:
            return await create_research_run_report_agent(session, project_id, run_id)
        except (
            ResearchProjectNotFoundError,
            ResearchSimulationRunNotFoundError,
        ) as error:
            raise _not_found(error) from error

    @router.get(
        "/{project_id}/runs/{run_id}/report-agent",
        response_model=ReportAgentRun | None,
    )
    async def existing_research_run_report_agent(
        project_id: UUID,
        run_id: UUID,
        session: ResearchProjectSession,
    ) -> ReportAgentRun | None:
        """Read the optional ReportAgent scope without creating or enqueueing work."""
        try:
            await get_research_run_report(session, project_id, run_id)
        except (
            ResearchProjectNotFoundError,
            ResearchSimulationRunNotFoundError,
        ) as error:
            raise _not_found(error) from error
        return await find_research_run_report_agent(session, run_id)

    return router
