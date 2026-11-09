"""Workspace policy. Docker is used only when that backend is selected and installed."""

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path


def docker_command(workspace: Path, image: str = "python:3.12-slim") -> list[str]:
    mounted = str(workspace.resolve())
    command = [
        "docker",
        "run",
        "--rm",
        "--user",
        "1000:1000",
        "--memory",
        "512m",
        "--cpus",
        "1",
        "--pids-limit",
        "128",
        "--network",
        "none",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=64m",  # noqa: S108
        "--mount",
        f"type=bind,src={mounted},dst=/workspace",
        "--workdir",
        "/workspace",
        image,
        "python",
        "-m",
        "pytest",
        "-q",
    ]
    rendered = " ".join(command)
    if "docker.sock" in rendered:
        message = "workspace command must not mount the Docker socket"
        raise ValueError(message)
    return command


def write_policy(workspace: Path, backend: str) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    command = " ".join(docker_command(workspace)) if backend == "docker" else "local backend"
    text = (
        "user: 1000\n"
        "network: deny\n"
        "memory: 512m\n"
        "cpus: 1\n"
        "pids: 128\n"
        "docker_socket: false\n"
        "ignore: graphify-out/\n"
        f"backend: {backend}\n"
        f"command: {command}\n"
    )
    (workspace / "WORKSPACE_POLICY.txt").write_text(text, encoding="utf-8")
    ignore = workspace / ".gitignore"
    current = ignore.read_text(encoding="utf-8") if ignore.is_file() else ""
    for line in ("graphify-out/\n", ".scan/\n"):
        if line not in current:
            current += line
    ignore.write_text(current, encoding="utf-8")


def assert_isolation(isolation: str, untrusted: bool) -> None:
    if untrusted and isolation != "microvm":
        message = "untrusted code requires microvm isolation, which this host does not provide"
        raise PermissionError(message)


def destroy_if_expired(workspace: Path, created_at: datetime, retention_hours: int, now: datetime) -> bool:
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    if now - created_at < timedelta(hours=retention_hours):
        return False
    if workspace.exists():
        shutil.rmtree(workspace)
    return True
