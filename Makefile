.PHONY: setup test lint typecheck security run clean

setup:
	bash scripts/setup.sh

test:
	.venv/bin/python -m pytest

lint:
	.venv/bin/ruff check services scripts alembic

typecheck:
	.venv/bin/mypy

security:
	@command -v .venv/bin/semgrep >/dev/null && .venv/bin/semgrep --config auto --error services/ || echo "semgrep not installed"
	@command -v gitleaks >/dev/null && gitleaks detect --source . --no-banner || echo "gitleaks binary not installed (see docs/operations/security-tools.md)"

run:
	.venv/bin/uvicorn app.main:app --app-dir services/platform-api --reload

clean:
	rm -rf .venv .pytest_cache .mypy_cache .ruff_cache
