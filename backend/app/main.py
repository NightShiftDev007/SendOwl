"""FastAPI application factory for the V2 control plane."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.decision_reports import create_decision_reports_router
from app.api.decision_threads import create_decision_threads_router
from app.api.evidence_bundles import create_evidence_bundles_router
from app.api.matraix_surveys import create_matraix_surveys_router
from app.api.media import create_media_router
from app.api.populations import create_populations_router
from app.api.report_questions import create_report_questions_router
from app.api.scenarios import create_scenarios_router
from app.api.semantic_experiments import create_semantic_experiments_router
from app.api.simulation_runs import create_simulation_runs_router
from app.api.system import create_system_router
from app.api.world_graphs import create_world_graphs_router
from app.api.world_models import create_world_models_router
from app.config import RuntimeSettings, load_runtime_settings
from app.database import DatabaseConnector


def create_app(settings: RuntimeSettings) -> FastAPI:
    """Create an isolated application instance with the V2 routes."""
    database = (
        DatabaseConnector.create(settings.database_url)
        if settings.database_url is not None
        else None
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        """Own the database connector lifecycle without mutating the schema."""
        yield
        if database is not None:
            await database.close()

    application = FastAPI(
        title="AI Decision Center V2",
        description="Evidence-driven decision experiments and simulation orchestration.",
        version="0.1.0",
        docs_url="/api/v2/docs",
        redoc_url=None,
        openapi_url="/api/v2/openapi.json",
        lifespan=lifespan,
    )
    application.state.database = database
    application.include_router(create_system_router(settings))
    application.include_router(create_decision_threads_router())
    application.include_router(create_decision_reports_router())
    application.include_router(create_report_questions_router())
    application.include_router(create_media_router())
    application.include_router(create_evidence_bundles_router())
    application.include_router(create_matraix_surveys_router())
    application.include_router(create_populations_router())
    application.include_router(create_world_models_router())
    application.include_router(create_world_graphs_router())
    application.include_router(create_scenarios_router())
    application.include_router(create_semantic_experiments_router())
    application.include_router(create_simulation_runs_router())
    return application


app = create_app(load_runtime_settings(os.environ))
