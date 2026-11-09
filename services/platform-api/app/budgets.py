"""Hard budgets loaded from the policy file."""

from dataclasses import dataclass
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from app.paths import repo_root


@dataclass(frozen=True)
class BudgetLimits:
    monthly_usd: float
    per_project_usd: float
    input_tokens: int
    output_tokens: int
    tool_calls: int
    retries: int
    wall_clock_minutes: int


def load_budgets(path: Path | None = None) -> BudgetLimits:
    policy = path or (repo_root() / "policies" / "model-budgets" / "budgets.yaml")
    loaded = yaml.safe_load(policy.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        message = "budget policy must be a mapping"
        raise ValueError(message)
    levels = loaded["levels"]
    per_task = levels["per_task"]
    return BudgetLimits(
        monthly_usd=float(levels["monthly_platform_usd"]),
        per_project_usd=float(levels["per_project_usd"]),
        input_tokens=int(per_task["input_tokens"]),
        output_tokens=int(per_task["output_tokens"]),
        tool_calls=int(per_task["tool_calls"]),
        retries=int(per_task["retries"]),
        wall_clock_minutes=int(per_task["wall_clock_minutes"]),
    )
