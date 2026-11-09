"""AI-SOOS platform API: control-plane entry point."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api import router
from app.config import Settings
from app.db import make_engine, make_session_factory
from app.errors import BudgetExceeded, GateBlocked, MissingSecretError
from app.paths import repo_root

settings = Settings()


class HealthResponse(BaseModel):
    status: str
    environment: str
    version: str


def create_app(app_settings: Settings | None = None) -> FastAPI:
    active = app_settings or settings
    application = FastAPI(
        title="AI-SOOS Platform API",
        version="0.1.0",
        docs_url="/docs" if active.environment != "production" else None,
        redoc_url=None,
    )
    application.state.settings = active
    application.state.engine = make_engine(active.database_url)
    application.state.sessions = make_session_factory(application.state.engine)
    application.state.workspace_root = repo_root() / "workspaces"
    application.state.db_ready = False
    application.include_router(router)

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", environment=active.environment, version=application.version)

    @application.exception_handler(MissingSecretError)
    async def missing_secret(_request: Request, exc: MissingSecretError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"missing": exc.variable})

    @application.exception_handler(PermissionError)
    async def forbidden(_request: Request, exc: PermissionError) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @application.exception_handler(GateBlocked)
    async def gate_blocked(_request: Request, exc: GateBlocked) -> JSONResponse:
        return JSONResponse(status_code=409, content={"check": exc.check})

    @application.exception_handler(BudgetExceeded)
    async def budget(_request: Request, exc: BudgetExceeded) -> JSONResponse:
        return JSONResponse(status_code=409, content={"limit": exc.limit})

    @application.exception_handler(KeyError)
    async def missing(_request: Request, _exc: KeyError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "not found"})

    @application.exception_handler(ValueError)
    async def bad_request(_request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return application


app = create_app()
