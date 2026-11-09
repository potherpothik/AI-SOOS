#!/usr/bin/env bash
# Install AI-SOOS from a clone of this repository.
# Uses requirements.lock when it is present so two machines resolve the same versions.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Checking Python"
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else "Python 3.12+ required")'

echo "==> Creating virtual environment (.venv)"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --quiet --upgrade pip

if [ -f requirements.lock ]; then
  echo "==> Installing locked dependencies"
  python -m pip install --quiet --no-deps -r requirements.lock
  python -m pip install --quiet --no-deps -e .
else
  echo "==> Installing project dependencies (runtime, dev, security)"
  python -m pip install --quiet -e ".[dev,security]"
  echo "==> Installing reviewed knowledge and context tools"
  python -m pip install --quiet "headroom-ai" "graphifyy" "specify-cli"
fi

if [ "${AISOOS_SKIP_BROWSER:-}" = "1" ]; then
  echo "==> Skipping Playwright browser install"
else
  echo "==> Installing Playwright browser (for visual QA)"
  python -m playwright install chromium || echo "WARN: Playwright browser install failed; visual checks are skipped until it is installed."
fi

echo "==> Preparing configuration"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "    created .env from .env.example"
fi

echo "==> Verifying"
python -m pytest -q || { echo "Tests failed"; exit 1; }

echo
echo "Setup complete. Activate with: source .venv/bin/activate"
echo "Start local Postgres, Redis, and MinIO when Docker is installed:"
echo "    docker compose -f infra/compose/docker-compose.yml up -d"
echo "Run the API: make run"
echo "Health check: curl -s http://127.0.0.1:8000/health"
echo "Gitleaks and Trivy are not installed. See docs/operations/security-tools.md"
