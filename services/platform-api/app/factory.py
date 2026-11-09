"""Run and resume a task. Status changes only through the workflow graph."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.budgets import BudgetLimits, load_budgets
from app.config import Settings
from app.effects import EFFECTS, EffectContext
from app.errors import GateBlocked
from app.gates import exception_is_valid, failed_checks, required_checks
from app.models import Approval, Project, ReleaseException, Task
from app.registry import audit, get_project
from app.state import FactoryState, initial_state
from app.teams import role_can
from app.workflow import transition

_TERMINAL = frozenset({"delivered", "failed"})
_STEP_LIMIT = 40


def _dump(state: FactoryState) -> str:
    return json.dumps(state)


def _load(raw: str) -> FactoryState:
    loaded = json.loads(raw)
    if not isinstance(loaded, dict):
        message = "task state is not an object"
        raise ValueError(message)
    return cast(FactoryState, loaded)


def _context(session: Session, settings: Settings, workspace_root: Path, budgets: BudgetLimits) -> EffectContext:
    return EffectContext(session=session, settings=settings, budgets=budgets, workspace_root=workspace_root)


def advance(state: FactoryState, ctx: EffectContext) -> FactoryState:
    steps = 0
    while state["status"] not in _TERMINAL and steps < _STEP_LIMIT:
        steps += 1
        state = EFFECTS[state["status"]](state, ctx)
        if _waiting(state):
            return state
        nxt = transition(state)
        if nxt["status"] == state["status"]:
            return nxt
        state = nxt
    if state["status"] in _TERMINAL:
        state = EFFECTS[state["status"]](state, ctx)
    return state


def _waiting(state: FactoryState) -> bool:
    if state["status"] == "spec" and not state["spec_approved"]:
        return True
    return state["status"] == "awaiting_approval" and not state["delivery_approved"]


def start_task(
    session: Session,
    settings: Settings,
    *,
    project_id: str,
    brief: str,
    template: str,
    mode: str,
    actor: str,
    actor_role: str,
    idempotency_key: str | None,
    workspace_root: Path,
    budgets: BudgetLimits | None = None,
) -> Task:
    if idempotency_key:
        existing = session.scalar(select(Task).where(Task.idempotency_key == idempotency_key))
        if existing is not None:
            return existing
    if not role_can(actor_role, "create"):
        message = "actor cannot create a task"
        raise PermissionError(message)
    project = get_project(session, project_id)
    limits = budgets or load_budgets()
    task_id = str(uuid.uuid4())
    workspace = str((workspace_root / task_id).resolve())
    state = initial_state(
        brief=brief,
        template=template,
        mode=mode,
        project_id=project.id,
        task_id=task_id,
        actor=actor,
        workspace=workspace,
        started_at=datetime.now(UTC).isoformat(),
        max_retries=limits.retries,
        max_tool_calls=limits.tool_calls,
        untrusted=project.untrusted,
        isolation=project.isolation,
    )
    task = Task(
        id=task_id,
        project_id=project.id,
        idempotency_key=idempotency_key,
        status=state["status"],
        state_json=_dump(state),
        created_at=datetime.now(UTC),
    )
    session.add(task)
    session.flush()
    return _persist(session, task, advance(state, _context(session, settings, workspace_root, limits)))


def approve_task(
    session: Session,
    settings: Settings,
    *,
    task_id: str,
    kind: str,
    approver: str,
    approver_role: str,
    workspace_root: Path,
    budgets: BudgetLimits | None = None,
) -> Task:
    if approver_role == "coding" or not role_can(approver_role, "approve"):
        message = "the coding agent cannot approve its own change"
        raise PermissionError(message)
    task = session.get(Task, task_id)
    if task is None:
        message = "task not found"
        raise KeyError(message)
    state = _load(task.state_json)
    if kind == "spec":
        state["spec_approved"] = True
    elif kind == "delivery":
        _require_gates(session, state)
        state["delivery_approved"] = True
    elif kind == "production_release":
        audit(session, approver, "release.requested", task.project_id, "deploy not performed")
    else:
        message = f"unknown approval: {kind}"
        raise ValueError(message)
    session.add(
        Approval(
            id=str(uuid.uuid4()),
            task_id=task.id,
            kind=kind,
            approver=approver,
            artifact=state["pr_body"],
            created_at=datetime.now(UTC),
        )
    )
    audit(session, approver, f"approval.{kind}", task.project_id, task.id)
    if kind == "production_release":
        task.state_json = _dump(state)
        return task
    limits = budgets or load_budgets()
    return _persist(session, task, advance(state, _context(session, settings, workspace_root, limits)))


def _require_gates(session: Session, state: FactoryState) -> None:
    project = session.get(Project, state["project_id"])
    exception_valid = False
    if project is not None:
        rows = session.scalars(
            select(ReleaseException).where(ReleaseException.project_id == project.id)
        ).all()
        now = datetime.now(UTC)
        exception_valid = any(
            exception_is_valid(row.approver, row.finding_id, row.reason, row.expires_at, now) for row in rows
        )
    failed = failed_checks(
        {"tests": state["tests_passed"], "review": state["review_ok"], "scan": state["scan_ok"]},
        required_checks(),
        exception_valid,
    )
    if failed:
        raise GateBlocked(failed[0])


def _persist(session: Session, task: Task, state: FactoryState) -> Task:
    task.state_json = _dump(state)
    task.status = state["status"]
    session.flush()
    return task
