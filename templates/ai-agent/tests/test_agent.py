import pytest

from agent import use_tool


def test_declared_tool_is_allowed() -> None:
    assert use_tool("read") == "read"


def test_unknown_tool_is_refused() -> None:
    with pytest.raises(PermissionError):
        use_tool("deploy")
