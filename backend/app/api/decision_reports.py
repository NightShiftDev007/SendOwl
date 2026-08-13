"""HTTP boundary for immutable deterministic decision reports."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DatabaseConnector
from app.decision_reports.contracts import DecisionReport, DecisionReportsResponse
from app.decision_reports.errors import DecisionReportNotFoundError, DecisionReportUnavailableError
from app.decision_reports.repository import (
    generate_decision_report,
    get_decision_report,
    list_decision_reports,
    render_report_markdown,
)
from app.semantic_experiments.errors import SemanticExperimentNotFoundError


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
