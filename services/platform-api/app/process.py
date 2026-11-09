"""Run a local program by absolute path."""

import shutil
import subprocess
import sys
from pathlib import Path


def tool_path(name: str) -> str | None:
    bundled = Path(sys.prefix) / "bin" / name
    if bundled.is_file():
        return str(bundled)
    return shutil.which(name)


def run_tool(
    argv: list[str],
    cwd: Path,
    timeout: int,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    if not argv or not Path(argv[0]).is_absolute():
        message = "command must use an absolute path"
        raise ValueError(message)
    return subprocess.run(  # noqa: S603
        argv,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=env,
    )
