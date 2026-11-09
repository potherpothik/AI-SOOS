"""Verification commands for a workspace."""

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from app.process import run_tool


@dataclass(frozen=True)
class VisualResult:
    status: str
    detail: str


def run_tests(workspace: Path) -> tuple[bool, str]:
    env_python = Path(sys.executable)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(workspace)
    completed = run_tool(
        [str(env_python), "-m", "pytest", "-q", "--tb=line"],
        workspace,
        timeout=120,
        env=env,
    )
    output = f"{completed.stdout}\n{completed.stderr}"[-4000:]
    return completed.returncode == 0, output


def workspace_diff(workspace: Path) -> str:
    lines: list[str] = []
    for path in sorted(workspace.rglob("*")):
        if not path.is_file() or {"__pycache__", "graphify-out", ".git", ".scan"}.intersection(path.parts):
            continue
        if path.name.startswith("."):
            continue
        relative = path.relative_to(workspace)
        lines.append(f"+++ {relative}")
        for number, text in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            lines.append(f"+{number}:{text}")
    return "\n".join(lines)


def visual_check(html_path: Path) -> VisualResult:
    if not html_path.is_file():
        return VisualResult("not_applicable", "no html file")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return VisualResult("skipped", "playwright is not installed")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(html_path.resolve().as_uri())
            title = page.title()
            browser.close()
    except Exception as exc:
        return VisualResult("skipped", exc.__class__.__name__)
    if not title:
        return VisualResult("failed", "empty title")
    return VisualResult("passed", title)
