"""HTTP boundary for immutable deterministic decision reports."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DatabaseConnector
from app.decision_reports.contracts import (
    DecisionReport,
    DecisionReportsResponse,
    DecisionReportsV2Response,
    DecisionReportV2,
)
from app.decision_reports.errors import DecisionReportNotFoundError, DecisionReportUnavailableError
from app.decision_reports.repository import (
    generate_decision_report,
    generate_decision_report_v2,
    get_decision_report,
    get_decision_report_v2,
    list_decision_reports,
    list_decision_reports_v2,
    render_report_markdown,
    render_report_v2_markdown,
)
from app.legacy_adc import reject_legacy_adc_write
from app.scenarios.errors import ScenarioNotFoundError
from app.semantic_experiments.errors import SemanticExperimentNotFoundError
from app.world_models.errors import WorldModelNotFoundError, WorldSnapshotNotFoundError


async def require_decision_report_session(request: Request) -> AsyncIterator[AsyncSession]:
    connector: DatabaseConnector | None = getattr(request.app.state, "database", None)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Decision reports are unavailable because DATABASE_URL is not configured",
        )
    async with connector.session() as session:
        yield session


DecisionReportSession = Annotated[AsyncSession, Depends(require_decision_report_session)]


def create_decision_reports_router() -> APIRouter:
    router = APIRouter(prefix="/api/v2/decision-reports", tags=["decision-reports"])

    @router.get("", response_model=DecisionReportsResponse)
    async def index(session: DecisionReportSession) -> DecisionReportsResponse:
        return await list_decision_reports(session)

    @router.post(
        "/from-experiment/{experiment_id}",
        response_model=DecisionReport,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(reject_legacy_adc_write)],
    )
    async def generate(experiment_id: UUID, session: DecisionReportSession) -> DecisionReport:
        try:
            return await generate_decision_report(session, experiment_id)
        except SemanticExperimentNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except DecisionReportUnavailableError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(error),
            ) from error

    @router.get("/v2", response_model=DecisionReportsV2Response)
    async def index_v2(session: DecisionReportSession) -> DecisionReportsV2Response:
        return await list_decision_reports_v2(session)

    @router.post(
        "/v2/from-experiment/{experiment_id}",
        response_model=DecisionReportV2,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(reject_legacy_adc_write)],
    )
    async def generate_v2(experiment_id: UUID, session: DecisionReportSession) -> DecisionReportV2:
        try:
            return await generate_decision_report_v2(session, experiment_id)
        except (SemanticExperimentNotFoundError, ScenarioNotFoundError) as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except (WorldModelNotFoundError, WorldSnapshotNotFoundError) as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except DecisionReportUnavailableError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(error),
            ) from error

    @router.get("/v2/{report_id}", response_model=DecisionReportV2)
    async def detail_v2(report_id: UUID, session: DecisionReportSession) -> DecisionReportV2:
        try:
            return await get_decision_report_v2(session, report_id)
        except DecisionReportNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.get("/v2/{report_id}/markdown")
    async def markdown_v2(report_id: UUID, session: DecisionReportSession) -> Response:
        try:
            report = await get_decision_report_v2(session, report_id)
        except DecisionReportNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        filename = f"decision-report-v2-{report.id}.md"
        return Response(
            content=render_report_v2_markdown(report),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.get("/{report_id}", response_model=DecisionReport)
    async def detail(report_id: UUID, session: DecisionReportSession) -> DecisionReport:
        try:
            return await get_decision_report(session, report_id)
        except DecisionReportNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.get("/{report_id}/markdown")
    async def markdown(report_id: UUID, session: DecisionReportSession) -> Response:
        try:
            report = await get_decision_report(session, report_id)
        except DecisionReportNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        filename = f"decision-report-{report.id}.md"
        return Response(
            content=render_report_markdown(report),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return router
