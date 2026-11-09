"""Generated SaaS service."""


def health() -> dict[str, str]:
    return {"status": "ok", "product": "saas"}


def plan_name() -> str:
    return "local"
