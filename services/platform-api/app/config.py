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
    max_task_input_tokens: int = Field(default=200_000, ge=1)
    max_task_retries: int = Field(default=2, ge=0, le=5)
