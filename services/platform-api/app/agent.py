"""One coding role. It can edit the workspace and cannot approve the change."""

from pathlib import Path

import yaml  # type: ignore[import-untyped]

from app.paths import repo_root


def load_roles() -> dict[str, object]:
    loaded = yaml.safe_load(
        (repo_root() / "policies" / "tool-permissions" / "roles.yaml").read_text(encoding="utf-8")
    )
    if not isinstance(loaded, dict):
        message = "roles policy must be a mapping"
        raise ValueError(message)
    return loaded


def assert_tool(role: str, tool: str) -> None:
    loaded = load_roles()
    roles = loaded["roles"]
    if not isinstance(roles, dict) or role not in roles:
        message = f"unknown role: {role}"
        raise PermissionError(message)
    record = roles[role]
    if not isinstance(record, dict):
        message = f"unknown role: {role}"
        raise PermissionError(message)
    tools = record.get("tools", [])
    if not isinstance(tools, list) or tool not in tools:
        message = f"{role} cannot use {tool}"
        raise PermissionError(message)
    if tool == "edit_workspace" and record.get("read_only_code") is True:
        message = f"{role} cannot edit code"
        raise PermissionError(message)


class CodingAgent:
    """Writes files only inside one workspace directory."""

    def __init__(self, root: Path, role: str = "coding") -> None:
        self.root = root.resolve()
        self.role = role
        self.tool_calls = 0

    def write(self, relative: str, content: str) -> None:
        assert_tool(self.role, "edit_workspace")
        target = self._resolve(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self.tool_calls += 1

    def read(self, relative: str) -> str:
        assert_tool(self.role, "read_repo")
        self.tool_calls += 1
        return self._resolve(relative).read_text(encoding="utf-8")

    def _resolve(self, relative: str) -> Path:
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            message = "path escapes the workspace"
            raise PermissionError(message)
        target = (self.root / candidate).resolve()
        if not target.is_relative_to(self.root):
            message = "path escapes the workspace"
            raise PermissionError(message)
        return target
