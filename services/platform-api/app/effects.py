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
from app.errors import BudgetExceeded, MissingSecretError
from app.ledger import charge, wall_clock_exceeded
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


def _guard(state: FactoryState, ctx: EffectContext) -> None:
    if wall_clock_exceeded(state["started_at"], ctx.budgets.wall_clock_minutes):
        raise BudgetExceeded("wall_clock_minutes")
    if state["tool_calls"] > state["max_tool_calls"]:
        raise BudgetExceeded("tool_calls")


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
    if state["mode"] == "model":
        from app.gateway import complete

        complete(ctx.session, ctx.settings, ctx.budgets, state)
    workspace = _workspace(state)
    if (workspace / "service.py").exists() or (workspace / "agent.py").exists() or (workspace / "index.html").exists():
        return state
    source = repo_root() / "templates" / state["template"]
    agent = CodingAgent(workspace)
    for path in sorted(source.rglob("*")):
        if path.is_file():
            agent.write(path.relative_to(source).as_posix(), path.read_text(encoding="utf-8"))
    state["tool_calls"] += agent.tool_calls
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
    state["blockers"] = ["review"] if high else []
    return state


def effect_scanning(state: FactoryState, ctx: EffectContext) -> FactoryState:
    _guard(state, ctx)
    findings = scan_workspace(_workspace(state), ctx.settings.run_semgrep)
    _store_findings(ctx, state["task_id"], "scan", findings)
    high = any(item.severity == "high" for item in findings)
    state["scan_ok"] = not high
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
    from app.models import MemoryEntry

    mark_accepted(ctx.session, state["task_id"])
    if not ctx.session.scalars(select(UsageRecord).where(UsageRecord.task_id == state["task_id"])).first():
        _record_zero_cost(ctx, state)
        mark_accepted(ctx.session, state["task_id"])
    already = ctx.session.scalars(
        select(MemoryEntry).where(MemoryEntry.project_id == state["project_id"])
    ).first()
    if already is None:
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
