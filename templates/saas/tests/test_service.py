from service import health, plan_name


def test_health() -> None:
    assert health()["product"] == "saas"


def test_plan_is_local() -> None:
    assert plan_name() == "local"
