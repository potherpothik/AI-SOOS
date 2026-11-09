"""Failures the API can explain without leaking secrets."""


class MissingSecretError(Exception):
    """A required configuration value is empty."""

    def __init__(self, variable: str) -> None:
        self.variable = variable
        super().__init__(variable)


class BudgetExceeded(Exception):
    """A hard budget in the policy file was reached."""

    def __init__(self, limit: str) -> None:
        self.limit = limit
        super().__init__(limit)


class GateBlocked(Exception):
    """A release check failed and no valid exception covers it."""

    def __init__(self, check: str) -> None:
        self.check = check
        super().__init__(check)
