"""Project registry. A role check runs before any privileged write."""

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, Membership, Organization, Project, Repository

_CREATE_ROLES = frozenset({"owner", "member", "approver"})


def _new_id() -> str:
    return str(uuid.uuid4())


def audit(session: Session, actor: str, action: str, project_id: str | None, detail: str) -> None:
    session.add(
        AuditEvent(
            id=_new_id(),
            actor=actor,
            action=action,
            project_id=project_id,
            detail=detail,
            created_at=datetime.now(UTC),
        )
    )


def create_project(
    session: Session,
    *,
    organization: str,
    name: str,
    owner: str,
    actor_role: str,
    repository_url: str | None = None,
    template: str = "api-service",
    isolation: str = "local",
    untrusted: bool = False,
) -> Project:
    if actor_role not in _CREATE_ROLES:
        message = "actor cannot create a project"
        raise PermissionError(message)
    org = session.scalar(select(Organization).where(Organization.name == organization))
    if org is None:
        org = Organization(id=_new_id(), name=organization)
        session.add(org)
        session.flush()
    session.add(
        Membership(id=_new_id(), organization_id=org.id, user_name=owner, role=actor_role)
    )
    project = Project(
        id=_new_id(),
        organization_id=org.id,
        name=name,
        owner=owner,
        template=template,
        isolation=isolation,
        untrusted=untrusted,
        policy_json=json.dumps({"deploy": False, "network": "deny"}),
    )
    session.add(project)
    session.flush()
    if repository_url:
        session.add(Repository(id=_new_id(), project_id=project.id, url=repository_url))
    audit(session, owner, "project.create", project.id, name)
    return project


def get_project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        message = "project not found"
        raise KeyError(message)
    return project
