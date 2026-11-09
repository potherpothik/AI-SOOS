"""Read-only review. Findings cite a line and this function does not write."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewFinding:
    line: int
    severity: str
    message: str


_PATTERNS = (
    ("eval(", "high", "eval is not allowed in generated code"),
    ("exec(", "high", "exec is not allowed in generated code"),
    ("BEGIN PRIVATE KEY", "high", "a private key was added"),
)


def review_diff(diff: str) -> list[ReviewFinding]:
    findings: list[ReviewFinding] = []
    added = 0
    for line_number, line in enumerate(diff.splitlines(), start=1):
        if not line.startswith("+") or line.startswith("+++"):
            continue
        added += 1
        for pattern, severity, message in _PATTERNS:
            if pattern in line:
                findings.append(ReviewFinding(line_number, severity, message))
    if added > 120:
        findings.append(ReviewFinding(1, "low", "large diff"))
    return findings
