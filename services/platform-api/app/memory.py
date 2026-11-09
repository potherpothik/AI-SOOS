"""File and symbol index for the next task. Entries keep a commit id."""

import re
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MemoryEntry
from app.process import run_tool, tool_path

_SYMBOL = re.compile(r"^(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)


def git_head(workspace: Path) -> str:
    git = tool_path("git")
    if git is None:
        return "uncommitted"
    completed = run_tool([git, "rev-parse", "HEAD"], workspace, timeout=10)
    if completed.returncode != 0:
        return "uncommitted"
    return completed.stdout.strip() or "uncommitted"


def index_workspace(session: Session, project_id: str, workspace: Path) -> list[MemoryEntry]:
    commit = git_head(workspace)
    entries: list[MemoryEntry] = []
    for path in sorted(workspace.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix not in {".py", ".md"}:
            continue
        text = path.read_text(encoding="utf-8")
        symbols = _SYMBOL.findall(text) or [path.stem]
        relative = str(path.relative_to(workspace))
        for symbol in symbols:
            entry = MemoryEntry(
                id=str(uuid.uuid4()),
                project_id=project_id,
                path=relative,
                symbol=symbol,
                commit_id=commit,
            )
            session.add(entry)
            entries.append(entry)
    session.flush()
    return entries


def query_memory(session: Session, project_id: str, question: str) -> list[MemoryEntry]:
    rows = session.scalars(select(MemoryEntry).where(MemoryEntry.project_id == project_id)).all()
    needles = {part.lower() for part in re.split(r"[^A-Za-z0-9_]+", question) if len(part) > 2}
    ranked = [
        row
        for row in rows
        if row.symbol.lower() in needles or any(part in row.path.lower() for part in needles)
    ]
    return ranked
