"""Usage ledger. Charges are stored. Budget figures do not refuse a charge."""

import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.budgets import BudgetLimits
from app.models import UsageRecord


def _id() -> str:
    return str(uuid.uuid4())


def prompt_digest(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


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
    del limits
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
