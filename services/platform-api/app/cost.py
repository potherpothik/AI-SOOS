"""Cost metrics and optional context compression. Compression is off unless configured."""

from collections.abc import Callable
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from app.models import UsageRecord


def anomaly_task_ids(records: list[UsageRecord]) -> list[str]:
    """Tasks whose spend is more than three times the median task spend."""
    totals: dict[str, float] = {}
    for row in records:
        totals[row.task_id] = totals.get(row.task_id, 0.0) + row.usd
    values = sorted(totals.values())
    if not values:
        return []
    middle = values[len(values) // 2]
    if middle == 0:
        return []
    return [task_id for task_id, spent in totals.items() if spent > middle * 3]


def summarize(records: list[UsageRecord]) -> dict[str, float | int | None]:
    accepted = {row.task_id for row in records if row.accepted}
    accepted_rows = [row for row in records if row.task_id in accepted]
    count = len(accepted)
    accepted_usd = float(sum(row.usd for row in accepted_rows))
    tokens = sum(row.input_tokens + row.output_tokens + row.cached_tokens for row in accepted_rows)
    per_cost = (accepted_usd / count) if count else None
    per_tokens = (tokens / count) if count else None
    return {
        "accepted_tasks": count,
        "cost_per_accepted_task": per_cost,
        "tokens_per_accepted_task": per_tokens,
        "total_usd": float(sum(row.usd for row in records)),
    }


def choose_route(measurements: list[dict[str, object]]) -> str | None:
    successful = [item for item in measurements if item.get("success") is True]
    if not successful:
        return None

    def price(item: dict[str, object]) -> float:
        value = item["usd"]
        if isinstance(value, int | float):
            return float(value)
        return 0.0

    best = min(successful, key=price)
    model = best.get("model")
    return model if isinstance(model, str) else None


def clip_lines(text: str, max_lines: int = 40) -> str:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    half = max_lines // 2
    omitted = len(lines) - max_lines
    return "\n".join(lines[:half] + [f"... {omitted} lines omitted ..."] + lines[-half:])


def compress_prompt(text: str, enabled: bool, compressor: Callable[[str], str] | None = None) -> str:
    if not enabled:
        return text
    if compressor is not None:
        return compressor(text)
    try:
        from headroom import compress
    except ImportError:
        return clip_lines(text)
    try:
        result = compress([{"role": "user", "content": text}], model="gpt-4o-mini")
    except Exception:
        return clip_lines(text)
    messages = getattr(result, "messages", None)
    if isinstance(messages, list) and messages and isinstance(messages[0], dict):
        content = messages[0].get("content")
        if isinstance(content, str) and content:
            return content
    return clip_lines(text)


def load_benchmark_tasks(path: Path) -> list[dict[str, str]]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        return []
    tasks = loaded.get("tasks", [])
    if not isinstance(tasks, list):
        return []
    return [item for item in tasks if isinstance(item, dict) and "name" in item]


def skipped_benchmarks(tasks: list[dict[str, str]], variable: str) -> list[dict[str, str]]:
    return [{"task": task["name"], "skipped": variable} for task in tasks]
