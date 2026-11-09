"""Side effects for one workflow status. Each effect can run again safely."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent import CodingAgent
from app.budgets import BudgetLimits
from app.config import Settings
from app.context import (
    append_hubs,
    asvs_rules,
    finding_text,
    graph_query,
    parse_file_map,
    record_context,
    workspace_text,
)
from app.errors import MissingSecretError
from app.ledger import charge
from app.models import Finding, Repository, UsageRecord
from app.paths import repo_root
from app.process import run_tool, tool_path
from app.review import review_diff
from app.runner import run_tests, visual_check, workspace_diff
from app.security_runner import scan_workspace
from app.specs import generate_documents, write_documents
from app.state import FactoryState
from app.workspace import assert_isolation, write_policy

TEMPLATES = ("api-service", "marketing-site", "saas", "ai-agent")


@dataclass
class EffectContext:
    session: Session
    settings: Settings
    budgets: BudgetLimits
    workspace_root: Path


def _workspace(state: FactoryState) -> Path:
    return Path(state["workspace"])


def _model_ready(state: FactoryState, ctx: EffectContext) -> bool:
    return state["mode"] == "model" and bool(ctx.settings.model_api_key and ctx.settings.model_name)


def _has_product(workspace: Path) -> bool:
    return any((workspace / name).exists() for name in ("service.py", "agent.py", "index.html"))


def _copy_template(state: FactoryState, workspace: Path) -> int:
    source = repo_root() / "templates" / state["template"]
    agent = CodingAgent(workspace)
    for path in sorted(source.rglob("*")):
        if path.is_file():
            agent.write(path.relative_to(source).as_posix(), path.read_text(encoding="utf-8"))
    return agent.tool_calls


def _refresh_context(state: FactoryState, ctx: EffectContext) -> str:
    workspace = _workspace(state)
    query = graph_query(workspace, state["brief"])
    compressed = record_context(
        ctx.session,
        ctx.budgets,
        state,
        workspace_text(workspace),
        query,
        ctx.settings.prompt_cache,
    )
    append_hubs(workspace)
    return compressed


def _coding_prompt(state: FactoryState, ctx: EffectContext, graph_text: str) -> str:
    from app.memory import query_memory

    hits = query_memory(ctx.session, state["project_id"], state["brief"])
    memory = "\n".join(f"{item.path}:{item.symbol}" for item in hits)
    findings = finding_text(ctx.session, state["task_id"], state["test_output"])
    return (
        f"{asvs_rules()}\n\n"
        f"Findings:\n{findings}\n\n"
        f"Memory:\n{memory}\n\n"
        f"Context:\n{graph_text}\n\n"
        f"Brief:\n{state['brief']}\n\n"
        "Reply with a JSON object mapping a relative path to file contents.\n"
    )


def _write_reply(workspace: Path, reply: str) -> int:
    files = parse_file_map(reply)
    if not files:
        return 0
    agent = CodingAgent(workspace)
    for path, content in files.items():
        try:
            agent.write(path, content)
        except PermissionError:
            continue
    return agent.tool_calls


def _guard(state: FactoryState, ctx: EffectContext) -> None:
    del state, ctx


def _record_zero_cost(ctx: EffectContext, state: FactoryState) -> None:
    existing = ctx.session.scalar(select(UsageRecord).where(UsageRecord.task_id == state["task_id"]))
    if existing is not None:
        return
    charge(
        ctx.session,
        ctx.budgets,
        project_id=state["project_id"],
        task_id=state["task_id"],
        model="template",
        input_tokens=0,
        output_tokens=0,
        usd=0.0,
        prompt=state["brief"],
        prompt_cache=ctx.settings.prompt_cache,
    )


def effect_brief(state: FactoryState, ctx: EffectContext) -> FactoryState:
    _guard(state, ctx)
    assert_isolation(state["isolation"], state["untrusted"])
    return state


def effect_spec(state: FactoryState, ctx: EffectContext) -> FactoryState:
    _guard(state, ctx)
    if state["template"] not in TEMPLATES:
        message = f"unknown template: {state['template']}"
        raise ValueError(message)
    write_documents(_workspace(state), generate_documents(state["brief"], state["template"]))
    return state


def effect_approved(state: FactoryState, ctx: EffectContext) -> FactoryState:
    _guard(state, ctx)
    return state


def effect_workspace(state: FactoryState, ctx: EffectContext) -> FactoryState:
    _guard(state, ctx)
    workspace = _workspace(state)
    write_policy(workspace, ctx.settings.workspace_backend)
    git = tool_path("git")
    if git is not None and not (workspace / ".git").exists():
        run_tool([git, "init"], workspace, timeout=15)
        run_tool([git, "checkout", "-b", state["branch"]], workspace, timeout=15)
    return state


def effect_coding(state: FactoryState, ctx: EffectContext) -> FactoryState:
    _guard(state, ctx)
    workspace = _workspace(state)
    if not _model_ready(state, ctx) and not _has_product(workspace):
        state["tool_calls"] += _copy_template(state, workspace)
    graph_text = _refresh_context(state, ctx)
    if _model_ready(state, ctx):
        from app.gateway import complete

        reply = complete(ctx.session, ctx.settings, ctx.budgets, state, _coding_prompt(state, ctx, graph_text))
        written = _write_reply(workspace, reply)
        state["tool_calls"] += written
        if written:
            _refresh_context(state, ctx)
            return state
    if not _has_product(workspace):
        state["tool_calls"] += _copy_template(state, workspace)
        _refresh_context(state, ctx)
    elif not _model_ready(state, ctx):
        _record_zero_cost(ctx, state)
    return state


def effect_verifying(state: FactoryState, ctx: EffectContext) -> FactoryState:
    _guard(state, ctx)
    passed, output = run_tests(_workspace(state))
    state["tests_passed"] = passed
    state["test_output"] = output
    html = _workspace(state) / "index.html"
    if html.is_file():
        visual = visual_check(html)
        state["visual"] = visual.status
        if visual.status == "failed":
            state["tests_passed"] = False
    return state


def effect_repairing(state: FactoryState, ctx: EffectContext) -> FactoryState:
    _guard(state, ctx)
    state["retries"] += 1
    return state


def effect_reviewing(state: FactoryState, ctx: EffectContext) -> FactoryState:
    _guard(state, ctx)
    findings = review_diff(workspace_diff(_workspace(state)))
    _store_findings(ctx, state["task_id"], "review", findings)
    high = any(item.severity == "high" for item in findings)
    state["review_ok"] = not high
    state["rewrite"] = high and _model_ready(state, ctx) and state["retries"] < state["max_retries"]
    blockers = [item for item in state["blockers"] if item != "review"]
    if high:
        blockers.append("review")
    state["blockers"] = blockers
    return state


def effect_scanning(state: FactoryState, ctx: EffectContext) -> FactoryState:
    _guard(state, ctx)
    findings = scan_workspace(_workspace(state), ctx.settings.run_semgrep)
    _store_findings(ctx, state["task_id"], "scan", findings)
    high = any(item.severity == "high" for item in findings)
    state["scan_ok"] = not high
    state["rewrite"] = high and _model_ready(state, ctx) and state["retries"] < state["max_retries"]
    blockers = [item for item in state["blockers"] if item != "scan"]
    if high:
        blockers.append("scan")
    state["blockers"] = blockers
    return state


def effect_awaiting(state: FactoryState, ctx: EffectContext) -> FactoryState:
    _guard(state, ctx)
    from app.delivery import build_pr_body, open_pull_request

    workspace = _workspace(state)
    files = sorted(
        path.relative_to(workspace).as_posix()
        for path in workspace.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and ".git" not in path.parts
    )
    scans = "clean" if state["scan_ok"] and state["review_ok"] else "findings recorded"
    body = build_pr_body(
        summary=state["brief"],
        files=files,
        tests=state["test_output"] or "not run",
        scans=scans,
        cost_usd=0.0,
        limitations="Merge and production deploy stay manual.",
    )
    state["pr_body"] = body
    repo = ctx.session.scalar(select(Repository).where(Repository.project_id == state["project_id"]))
    if repo is None or not ctx.settings.github_token:
        state["missing"] = "AISOOS_GITHUB_TOKEN"
        return state
    try:
        open_pull_request(
            ctx.settings.github_token,
            repo.url,
            state["branch"],
            f"AI-SOOS {state['task_id']}",
            body,
        )
    except MissingSecretError as exc:
        state["missing"] = exc.variable
    return state


def effect_delivered(state: FactoryState, ctx: EffectContext) -> FactoryState:
    from app.ledger import mark_accepted
    from app.memory import index_workspace

    mark_accepted(ctx.session, state["task_id"])
    if not ctx.session.scalars(select(UsageRecord).where(UsageRecord.task_id == state["task_id"])).first():
        _record_zero_cost(ctx, state)
        mark_accepted(ctx.session, state["task_id"])
    index_workspace(ctx.session, state["project_id"], _workspace(state))
    return state


def effect_failed(state: FactoryState, _ctx: EffectContext) -> FactoryState:
    return state


EFFECTS = {
    "brief": effect_brief,
    "spec": effect_spec,
    "approved": effect_approved,
    "workspace": effect_workspace,
    "coding": effect_coding,
    "verifying": effect_verifying,
    "repairing": effect_repairing,
    "reviewing": effect_reviewing,
    "scanning": effect_scanning,
    "awaiting_approval": effect_awaiting,
    "delivered": effect_delivered,
    "failed": effect_failed,
}


def _store_findings(ctx: EffectContext, task_id: str, source: str, findings: Sequence[object]) -> None:
    existing = ctx.session.scalars(select(Finding).where(Finding.task_id == task_id, Finding.source == source)).all()
    for row in existing:
        ctx.session.delete(row)
    for item in findings:
        severity = str(getattr(item, "severity", "low"))
        line = int(getattr(item, "line", 0))
        message = str(getattr(item, "message", ""))
        ctx.session.add(
            Finding(
                id=str(uuid.uuid4()),
                task_id=task_id,
                source=source,
                severity=severity,
                line=line,
                message=message,
            )
        )
