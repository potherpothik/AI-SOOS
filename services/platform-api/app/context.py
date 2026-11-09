"""Graphify context. The graph is built with no model key and no skill install."""

import json
import subprocess
from pathlib import Path

import yaml  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.budgets import BudgetLimits
from app.cost import clip_lines, compress_prompt
from app.ledger import charge
from app.models import Finding
from app.paths import repo_root
from app.process import run_tool, tool_path
from app.state import FactoryState

_SKIP = {"graphify-out", ".git", ".scan", "__pycache__"}


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _skipped(path: Path) -> bool:
    return bool(_SKIP.intersection(path.parts))


def file_list(workspace: Path) -> str:
    lines: list[str] = []
    for path in sorted(workspace.rglob("*")):
        if path.is_file() and not _skipped(path):
            lines.append(path.relative_to(workspace).as_posix())
    return "\n".join(lines)


def workspace_text(workspace: Path) -> str:
    parts: list[str] = []
    for path in sorted(workspace.rglob("*")):
        if not path.is_file() or _skipped(path):
            continue
        if path.suffix not in {".py", ".md", ".txt", ".yaml", ".yml", ".html"}:
            continue
        parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def _run(argv: list[str], workspace: Path, timeout: int) -> subprocess.CompletedProcess[str] | None:
    try:
        return run_tool(argv, workspace, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None


def graph_query(workspace: Path, brief: str) -> str:
    """Return a graph query. `graphify update --code-only` is rejected by graphify 0.9, so this uses extract."""
    binary = tool_path("graphify")
    fallback = clip_lines(file_list(workspace))
    if binary is None:
        return fallback
    extracted = _run(
        [binary, "extract", str(workspace), "--code-only", "--no-cluster", "--out", str(workspace)],
        workspace,
        90,
    )
    graph = workspace / "graphify-out" / "graph.json"
    if extracted is None or not graph.is_file() or graph.stat().st_size == 0:
        return fallback
    queried = _run([binary, "query", brief, "--budget", "2000", "--graph", str(graph)], workspace, 30)
    if queried is None or not queried.stdout.strip():
        return fallback
    return queried.stdout.strip()


def append_hubs(workspace: Path) -> None:
    binary = tool_path("graphify")
    graph = workspace / "graphify-out" / "graph.json"
    if binary is None or not graph.is_file():
        return
    completed = _run([binary, "god-nodes", "--json", "--graph", str(graph)], workspace, 30)
    if completed is None or not completed.stdout.strip():
        return
    design = workspace / "DESIGN.md"
    body = design.read_text(encoding="utf-8") if design.is_file() else "# Design\n"
    marker = "\n## Hubs\n"
    if marker in body:
        body = body.split(marker)[0].rstrip() + "\n"
    design.write_text(body + marker + "\n" + completed.stdout.strip() + "\n", encoding="utf-8")


def asvs_rules() -> str:
    loaded = yaml.safe_load((repo_root() / "policies" / "asvs" / "checklist.yaml").read_text(encoding="utf-8"))
    items = loaded.get("items", []) if isinstance(loaded, dict) else []
    lines = [str(item.get("text", "")) for item in items if isinstance(item, dict)]
    return "\n".join(f"- {line}" for line in lines if line)


def record_context(
    session: Session,
    limits: BudgetLimits,
    state: FactoryState,
    full_text: str,
    query: str,
    prompt_cache: bool,
) -> str:
    compressed = compress_prompt(query, True)
    charge(
        session,
        limits,
        project_id=state["project_id"],
        task_id=state["task_id"],
        model="context-full",
        input_tokens=estimate_tokens(full_text),
        output_tokens=0,
        usd=0.0,
        prompt=full_text,
        prompt_cache=prompt_cache,
    )
    charge(
        session,
        limits,
        project_id=state["project_id"],
        task_id=state["task_id"],
        model="graphify-query",
        input_tokens=estimate_tokens(compressed),
        output_tokens=0,
        usd=0.0,
        prompt=compressed,
        prompt_cache=prompt_cache,
    )
    return compressed


def finding_text(session: Session, task_id: str, test_output: str) -> str:
    rows = session.scalars(select(Finding).where(Finding.task_id == task_id)).all()
    lines = [f"{row.severity}: {row.message}" for row in rows]
    if test_output:
        lines.append(test_output)
    return clip_lines("\n".join(lines))


def parse_file_map(reply: str) -> dict[str, str]:
    text = reply.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if isinstance(loaded, dict) and isinstance(loaded.get("files"), dict):
        loaded = loaded["files"]
    if not isinstance(loaded, dict):
        return {}
    files: dict[str, str] = {}
    for key, value in loaded.items():
        if isinstance(key, str) and isinstance(value, str):
            files[key] = value
    return files
