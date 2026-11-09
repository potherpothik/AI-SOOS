"""Usage ledger. A charge that would cross a budget is refused before it is stored."""

import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.budgets import BudgetLimits
from app.errors import BudgetExceeded
from app.models import UsageRecord


def _id() -> str:
    return str(uuid.uuid4())


def prompt_digest(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _sum(session: Session, project_id: str | None) -> float:
    query = select(UsageRecord)
    if project_id is not None:
        query = query.where(UsageRecord.project_id == project_id)
    rows = session.scalars(query).all()
    return float(sum(row.usd for row in rows))


def charge(
    session: Session,
    limits: BudgetLimits,
    *,
    project_id: str,
    task_id: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    usd: float,
    prompt: str,
    prompt_cache: bool,
    accepted: bool = False,
) -> UsageRecord:
    if input_tokens > limits.input_tokens:
        raise BudgetExceeded("input_tokens")
    if output_tokens > limits.output_tokens:
        raise BudgetExceeded("output_tokens")
    if _sum(session, None) + usd > limits.monthly_usd:
        raise BudgetExceeded("monthly_platform_usd")
    if _sum(session, project_id) + usd > limits.per_project_usd:
        raise BudgetExceeded("per_project_usd")
    digest = prompt_digest(prompt)
    cached = 0
    if prompt_cache:
        previous = session.scalar(select(UsageRecord).where(UsageRecord.prompt_hash == digest))
        if previous is not None:
            cached = input_tokens
    record = UsageRecord(
        id=_id(),
        project_id=project_id,
        task_id=task_id,
        model=model,
        input_tokens=0 if cached else input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached,
        usd=0.0 if cached else usd,
        accepted=accepted,
        prompt_hash=digest,
    )
    session.add(record)
    session.flush()
    return record


def mark_accepted(session: Session, task_id: str) -> None:
    rows = session.scalars(select(UsageRecord).where(UsageRecord.task_id == task_id)).all()
    for row in rows:
        row.accepted = True


def wall_clock_exceeded(started_at: str, limit_minutes: int, now: datetime | None = None) -> bool:
    started = datetime.fromisoformat(started_at)
    current = now or datetime.now(UTC)
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return (current - started).total_seconds() > limit_minutes * 60
