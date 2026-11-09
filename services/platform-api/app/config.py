"""Settings loaded from environment variables. Secrets are never defaulted in code."""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="AISOOS_", extra="ignore")

    environment: Literal["development", "test", "staging", "production"] = "development"
    database_url: str = Field(
        default="postgresql+psycopg://aisoos:aisoos@localhost:5432/aisoos",
        description="Local default for development only. Production must inject this.",
    )
    redis_url: str = "redis://localhost:6379/0"
    monthly_budget_usd: float = Field(default=50.0, ge=0)
    per_project_budget_usd: float = Field(default=10.0, ge=0)
    max_task_input_tokens: int = Field(default=200_000, ge=1)
    max_task_output_tokens: int = Field(default=40_000, ge=1)
    max_task_retries: int = Field(default=2, ge=0, le=5)
    model_api_key: str = ""
    model_name: str = ""
    github_token: str = ""
    workspace_backend: Literal["local", "docker"] = "local"
    prompt_cache: bool = False
    compress_context: bool = False
    retention_hours: int = Field(default=24, ge=0)
    run_semgrep: bool = True
