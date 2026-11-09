"""Repository-relative paths. Install never reads outside the clone."""

from pathlib import Path


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    message = "pyproject.toml not found"
    raise FileNotFoundError(message)
