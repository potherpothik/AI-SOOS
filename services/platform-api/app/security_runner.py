"""Defensive checks. Dynamic scanners do not run without an authorization record."""

import json
from dataclasses import dataclass
from pathlib import Path

from app.paths import repo_root
from app.process import run_tool, tool_path

_PATTERNS = (
    ("eval(", "high", "eval is not allowed"),
    ("exec(", "high", "exec is not allowed"),
    ("BEGIN PRIVATE KEY", "high", "private key material"),
    ("AKIA", "high", "possible cloud access key"),
)


@dataclass(frozen=True)
class ScanFinding:
    source: str
    severity: str
    line: int
    message: str


def pattern_scan(workspace: Path) -> list[ScanFinding]:
    findings: list[ScanFinding] = []
    for path in sorted(workspace.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if path.suffix not in {".py", ".md", ".txt", ".yaml", ".yml", ".html", ".env"}:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for pattern, severity, message in _PATTERNS:
                if pattern in line:
                    findings.append(ScanFinding("pattern", severity, number, f"{path.name}: {message}"))
    return findings


def semgrep_scan(workspace: Path) -> list[ScanFinding]:
    binary = tool_path("semgrep")
    rules = repo_root() / "policies" / "semgrep" / "python.yaml"
    if binary is None or not rules.is_file():
        return []
    completed = run_tool(
        [
            binary,
            "--disable-version-check",
            "--metrics",
            "off",
            "--config",
            str(rules),
            "--json",
            "--quiet",
            str(workspace),
        ],
        workspace,
        timeout=90,
    )
    if not completed.stdout.strip():
        return []
    payload = json.loads(completed.stdout)
    findings: list[ScanFinding] = []
    results = payload.get("results", [])
    if not isinstance(results, list):
        return findings
    for item in results:
        if not isinstance(item, dict):
            continue
        start = item.get("start", {})
        line = int(start.get("line", 1)) if isinstance(start, dict) else 1
        extra = item.get("extra", {})
        message = "semgrep finding"
        severity = "high"
        if isinstance(extra, dict):
            message = str(extra.get("message", message))
            raw = str(extra.get("severity", "ERROR"))
            severity = "high" if raw.upper() in {"ERROR", "HIGH", "CRITICAL"} else "low"
        findings.append(ScanFinding("semgrep", severity, line, message))
    return findings


def scan_workspace(workspace: Path, run_semgrep: bool) -> list[ScanFinding]:
    findings = pattern_scan(workspace)
    if run_semgrep:
        findings.extend(semgrep_scan(workspace))
    return findings


def dynamic_scan_allowed(host: str, signer: str, statement: str, allow_production: bool) -> bool:
    if not host or not signer or host not in statement:
        return False
    if host in {"production", "prod"} and not allow_production:
        return False
    return True
