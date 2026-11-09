"""AI-SOOS platform API: control-plane entry point.

Kept deliberately small. Authentication, projects, approvals, and audit are added
as separate modules with their own tests.
"""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from app.config import Settings

settings = Settings()

app = FastAPI(
    title="AI-SOOS Platform API",
    version="0.1.0",
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url=None,
)


class HealthResponse(BaseModel):
    status: str
    environment: str
    version: str


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", environment=settings.environment, version=app.version)
