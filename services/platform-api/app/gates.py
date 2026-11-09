"""Release checks. A failed check stops delivery until an exception is in force."""

from datetime import UTC, datetime
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from app.paths import repo_root


def required_checks(path: Path | None = None) -> list[str]:
    policy = path or (repo_root() / "policies" / "release-gates" / "gates.yaml")
    loaded = yaml.safe_load(policy.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        return []
    checks = loaded.get("required", [])
    if not isinstance(checks, list):
        return []
    return [str(item) for item in checks]


def failed_checks(results: dict[str, bool], names: list[str], exception_valid: bool) -> list[str]:
    if exception_valid:
        return []
    return [name for name in names if not results.get(name, False)]


def exception_is_valid(approver: str, finding_id: str, reason: str, expires_at: datetime, now: datetime) -> bool:
    current = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    expiry = expires_at if expires_at.tzinfo is not None else expires_at.replace(tzinfo=UTC)
    return bool(approver and finding_id and reason and expiry > current)


def contract_gaps(spec_text: str, source_text: str) -> list[str]:
    loaded = yaml.safe_load(spec_text)
    if not isinstance(loaded, dict):
        return ["spec"]
    paths = loaded.get("paths", {})
    if not isinstance(paths, dict):
        return ["paths"]
    missing: list[str] = []
    for operations in paths.values():
        if not isinstance(operations, dict):
            continue
        for operation in operations.values():
            if not isinstance(operation, dict):
                continue
            operation_id = operation.get("operationId")
            if isinstance(operation_id, str) and f"def {operation_id}" not in source_text:
                missing.append(operation_id)
    return missing
