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
        if not path.is_file() or {"__pycache__", "graphify-out", ".git", ".scan"}.intersection(path.parts):
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
            "--exclude",
            "graphify-out",
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


def security_binary(name: str) -> str | None:
    bundled = repo_root() / ".tools" / name
    if bundled.is_file():
        return str(bundled)
    return tool_path(name)


def _missing(name: str) -> ScanFinding:
    return ScanFinding(name, "low", 0, f"{name} is not installed")


def gitleaks_scan(workspace: Path) -> list[ScanFinding]:
    binary = security_binary("gitleaks")
    if binary is None:
        return [_missing("gitleaks")]
    report = workspace / ".scan" / "gitleaks.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    completed = run_tool(
        [
            binary,
            "detect",
            "--source",
            str(workspace),
            "--no-git",
            "--report-format",
            "json",
            "--report-path",
            str(report),
            "--exit-code",
            "0",
        ],
        workspace,
        timeout=60,
    )
    del completed
    if not report.is_file() or not report.read_text(encoding="utf-8").strip():
        return [ScanFinding("gitleaks", "low", 0, "gitleaks produced no report")]
    try:
        payload = json.loads(report.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return [ScanFinding("gitleaks", "low", 0, "gitleaks produced no report")]
    if not isinstance(payload, list):
        return [ScanFinding("gitleaks", "low", 0, "gitleaks produced no report")]
    findings: list[ScanFinding] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        findings.append(
            ScanFinding(
                "gitleaks",
                "high",
                int(item.get("StartLine", 1) or 1),
                str(item.get("Description", "secret")),
            )
        )
    return findings


def trivy_scan(workspace: Path) -> list[ScanFinding]:
    binary = security_binary("trivy")
    if binary is None:
        return [_missing("trivy")]
    completed = run_tool(
        [binary, "fs", "--scanners", "vuln", "--format", "json", "--quiet", str(workspace)],
        workspace,
        timeout=90,
    )
    if not completed.stdout.strip():
        return [ScanFinding("trivy", "low", 0, "trivy produced no report")]
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return [ScanFinding("trivy", "low", 0, "trivy produced no report")]
    findings: list[ScanFinding] = []
    results = payload.get("Results", []) if isinstance(payload, dict) else []
    if not isinstance(results, list):
        return findings
    for result in results:
        if not isinstance(result, dict):
            continue
        vulnerabilities = result.get("Vulnerabilities", [])
        if not isinstance(vulnerabilities, list):
            continue
        for item in vulnerabilities:
            if not isinstance(item, dict):
                continue
            severity = str(item.get("Severity", "LOW")).upper()
            rank = "high" if severity in {"HIGH", "CRITICAL"} else "low"
            label = str(item.get("VulnerabilityID", "vulnerability"))
            findings.append(ScanFinding("trivy", rank, 1, label))
    return findings


def scan_workspace(workspace: Path, run_semgrep: bool) -> list[ScanFinding]:
    findings = pattern_scan(workspace)
    if run_semgrep:
        findings.extend(semgrep_scan(workspace))
    findings.extend(gitleaks_scan(workspace))
    findings.extend(trivy_scan(workspace))
    return findings


def dynamic_scan_allowed(host: str, signer: str, statement: str, allow_production: bool) -> bool:
    if not host or not signer or host not in statement:
        return False
    if host in {"production", "prod"} and not allow_production:
        return False
    return True
