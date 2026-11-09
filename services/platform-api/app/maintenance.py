"""Maintenance proposes a pull request and does not merge it."""

import uuid

from sqlalchemy.orm import Session

from app.models import MaintenanceRequest
from app.registry import audit


def propose_update(
    session: Session,
    *,
    project_id: str,
    package: str,
    from_version: str,
    to_version: str,
    actor: str,
) -> MaintenanceRequest:
    request = MaintenanceRequest(
        id=str(uuid.uuid4()),
        project_id=project_id,
        package=package,
        from_version=from_version,
        to_version=to_version,
        status="proposed",
    )
    session.add(request)
    audit(session, actor, "maintenance.propose", project_id, f"{package} {from_version} -> {to_version}")
    return request


def merge_request(_request: MaintenanceRequest) -> None:
    message = "maintenance requests are not merged by the platform"
    raise PermissionError(message)
