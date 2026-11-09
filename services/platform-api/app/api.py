"""HTTP API for the control plane."""

import json
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import Settings
from app.cost import load_benchmark_tasks, skipped_benchmarks, summarize
from app.db import init_db, session_scope
from app.errors import MissingSecretError
from app.factory import approve_task, start_task
from app.maintenance import propose_update
from app.models import AuthorizationRecord, Project, ReleaseException, UsageRecord
from app.paths import repo_root
from app.registry import create_project
from app.security_runner import dynamic_scan_allowed
from app.teams import add_member, perform_deploy

router = APIRouter()


class ProjectIn(BaseModel):
    organization: str
    name: str
    owner: str
    actor_role: str = "owner"
    repository_url: str | None = None
    template: str = "api-service"
    untrusted: bool = False
    isolation: str = "local"


class GenerateIn(BaseModel):
    brief: str = Field(min_length=1)
    template: str = "api-service"
    mode: str = "model"
    idempotency_key: str | None = None
    actor: str = "local"
    actor_role: str = "owner"


class ApprovalIn(BaseModel):
    kind: str
    approver: str
    approver_role: str = "owner"


class MemberIn(BaseModel):
    user_name: str
    role: str
    actor: str = "local"


class MaintenanceIn(BaseModel):
    package: str
    from_version: str
    to_version: str
    actor: str = "local"


class ExceptionIn(BaseModel):
    approver: str
    finding_id: str
    reason: str
    expires_at: datetime


class AuthorizationIn(BaseModel):
    host: str
    signer: str
    statement: str
    allow_production: bool = False


def _settings(request: Request) -> Settings:
    settings = request.app.state.settings
    if not isinstance(settings, Settings):
        message = "settings are not configured"
        raise RuntimeError(message)
    return settings


def _root(request: Request) -> Path:
    root = request.app.state.workspace_root
    if not isinstance(root, Path):
        return repo_root() / "workspaces"
    return root


def _ready(request: Request) -> None:
    if getattr(request.app.state, "db_ready", False):
        return
    init_db(request.app.state.engine)
    request.app.state.db_ready = True


@router.post("/projects")
def post_project(body: ProjectIn, request: Request) -> dict[str, str]:
    _ready(request)
    with session_scope(request.app.state.sessions) as session:
        project = create_project(
            session,
            organization=body.organization,
            name=body.name,
            owner=body.owner,
            actor_role=body.actor_role,
            repository_url=body.repository_url,
            template=body.template,
            isolation=body.isolation,
            untrusted=body.untrusted,
        )
        return {"id": project.id, "name": project.name}


@router.post("/projects/{project_id}/generate")
def post_generate(project_id: str, body: GenerateIn, request: Request) -> dict[str, str]:
    settings = _settings(request)
    if body.mode == "model" and not settings.model_api_key:
        raise MissingSecretError("AISOOS_MODEL_API_KEY")
    if body.mode == "model" and not settings.model_name:
        raise MissingSecretError("AISOOS_MODEL_NAME")
    _ready(request)
    with session_scope(request.app.state.sessions) as session:
        task = start_task(
            session,
            settings,
            project_id=project_id,
            brief=body.brief,
            template=body.template,
            mode=body.mode,
            actor=body.actor,
            actor_role=body.actor_role,
            idempotency_key=body.idempotency_key,
            workspace_root=_root(request),
        )
        loaded = json.loads(task.state_json)
        missing = loaded["missing"] if isinstance(loaded, dict) else ""
        return {"id": task.id, "status": task.status, "missing": str(missing)}


@router.post("/tasks/{task_id}/approvals")
def post_approval(task_id: str, body: ApprovalIn, request: Request) -> dict[str, str | bool]:
    settings = _settings(request)
    _ready(request)
    with session_scope(request.app.state.sessions) as session:
        task = approve_task(
            session,
            settings,
            task_id=task_id,
            kind=body.kind,
            approver=body.approver,
            approver_role=body.approver_role,
            workspace_root=_root(request),
        )
        deployed = False
        if body.kind == "production_release":
            try:
                perform_deploy()
            except PermissionError:
                deployed = False
        return {"id": task.id, "status": task.status, "deployed": deployed}


@router.get("/projects/{project_id}/cost")
def get_cost(project_id: str, request: Request) -> dict[str, float | int | None]:
    _ready(request)
    with session_scope(request.app.state.sessions) as session:
        rows = session.scalars(select(UsageRecord).where(UsageRecord.project_id == project_id)).all()
        return summarize(list(rows))


@router.post("/projects/{project_id}/members")
def post_member(project_id: str, body: MemberIn, request: Request) -> dict[str, str]:
    _ready(request)
    with session_scope(request.app.state.sessions) as session:
        project = session.get(Project, project_id)
        if project is None:
            message = "project not found"
            raise KeyError(message)
        member = add_member(session, project.organization_id, body.user_name, body.role, body.actor)
        return {"id": member.id, "role": member.role}


@router.post("/projects/{project_id}/maintenance")
def post_maintenance(project_id: str, body: MaintenanceIn, request: Request) -> dict[str, str]:
    _ready(request)
    with session_scope(request.app.state.sessions) as session:
        proposal = propose_update(
            session,
            project_id=project_id,
            package=body.package,
            from_version=body.from_version,
            to_version=body.to_version,
            actor=body.actor,
        )
        return {"id": proposal.id, "status": proposal.status}


@router.post("/projects/{project_id}/exceptions")
def post_exception(project_id: str, body: ExceptionIn, request: Request) -> dict[str, str]:
    _ready(request)
    with session_scope(request.app.state.sessions) as session:
        row = ReleaseException(
            id=str(uuid.uuid4()),
            project_id=project_id,
            approver=body.approver,
            finding_id=body.finding_id,
            reason=body.reason,
            expires_at=body.expires_at,
        )
        session.add(row)
        return {"id": row.id}


@router.post("/projects/{project_id}/authorization")
def post_authorization(project_id: str, body: AuthorizationIn, request: Request) -> dict[str, str | bool]:
    _ready(request)
    allowed = dynamic_scan_allowed(body.host, body.signer, body.statement, body.allow_production)
    with session_scope(request.app.state.sessions) as session:
        row = AuthorizationRecord(
            id=str(uuid.uuid4()),
            project_id=project_id,
            host=body.host,
            signer=body.signer,
            statement=body.statement,
            allow_production=body.allow_production,
        )
        session.add(row)
        return {"id": row.id, "dynamic_scan_allowed": allowed}


@router.get("/benchmarks")
def get_benchmarks(request: Request) -> dict[str, list[dict[str, str]]]:
    settings = _settings(request)
    tasks = load_benchmark_tasks(repo_root() / "evals" / "cost-benchmarks" / "tasks.yaml")
    if not settings.model_api_key:
        return {"results": skipped_benchmarks(tasks, "AISOOS_MODEL_API_KEY")}
    named = [
        {"task": task["name"], "skipped": "call the eval runner; this request does not call a model"}
        for task in tasks
    ]
    return {"results": named}
