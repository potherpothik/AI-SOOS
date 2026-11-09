"""Tool allowlist for a generated agent. Unknown tools are refused."""

ALLOWED = frozenset({"read", "draft"})


def use_tool(name: str) -> str:
    if name not in ALLOWED:
        message = name
        raise PermissionError(message)
    return name
