"""Model calls. Nothing is sent unless both the key and the model name are set."""

from typing import Any, cast

import litellm
from sqlalchemy.orm import Session

from app.budgets import BudgetLimits
from app.config import Settings
from app.cost import compress_prompt
from app.errors import MissingSecretError
from app.ledger import charge
from app.state import FactoryState


def complete(session: Session, settings: Settings, limits: BudgetLimits, state: FactoryState) -> str:
    if not settings.model_api_key:
        raise MissingSecretError("AISOOS_MODEL_API_KEY")
    if not settings.model_name:
        raise MissingSecretError("AISOOS_MODEL_NAME")
    prompt = compress_prompt(state["brief"], settings.compress_context)
    response = cast(
        Any,
        litellm.completion(
            model=settings.model_name,
            messages=[{"role": "user", "content": prompt}],
            api_key=settings.model_api_key,
        ),
    )
    text = str(response.choices[0].message.content or "")
    usage = getattr(response, "usage", None)
    input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    charge(
        session,
        limits,
        project_id=state["project_id"],
        task_id=state["task_id"],
        model=settings.model_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        usd=0.0,
        prompt=prompt,
        prompt_cache=settings.prompt_cache,
    )
    return text
