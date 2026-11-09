"""Team membership. Production deploy stays a manual action for every role."""

import json
import uuid

from sqlalchemy.orm import Session

from app.models import Membership
from app.registry import audit

_ACTIONS: dict[str, frozenset[str]] = {
    "owner": frozenset({"read", "create", "approve", "exception"}),
    "approver": frozenset({"read", "approve", "exception"}),
    "member": frozenset({"read", "create"}),
    "viewer": frozenset({"read"}),
}


def role_can(role: str, action: str) -> bool:
    if action == "deploy":
        return False
    return action in _ACTIONS.get(role, frozenset())


def add_member(session: Session, organization_id: str, user_name: str, role: str, actor: str) -> Membership:
    if role not in _ACTIONS:
        message = f"unknown role: {role}"
        raise ValueError(message)
    member = Membership(
        id=str(uuid.uuid4()),
        organization_id=organization_id,
        user_name=user_name,
        role=role,
    )
    session.add(member)
    audit(session, actor, "member.add", None, f"{user_name}:{role}")
    return member


def effective_policy(raw: str) -> dict[str, object]:
    loaded = json.loads(raw or "{}")
    if not isinstance(loaded, dict):
        loaded = {}
    base: dict[str, object] = {"deploy": False, "network": "deny"}
    for key, value in loaded.items():
        if key == "deploy":
            continue
        base[str(key)] = value
    base["deploy"] = False
    return base


def perform_deploy() -> None:
    message = "production deploy is a manual action"
    raise PermissionError(message)
