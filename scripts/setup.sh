#!/usr/bin/env bash
# Create the development environment for AI-SOOS.
# Installs only the packages classified "install" in vendor/manifest.yaml, plus the project's own dependencies.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Checking Python"
python3 -c 'import sys; assert sys.version_info >= (3, 12), "Python 3.12+ required"'

echo "==> Creating virtual environment (.venv)"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --quiet --upgrade pip

echo "==> Installing project dependencies (runtime, dev, security)"
python -m pip install --quiet -e ".[dev,security]"

echo "==> Installing reviewed knowledge and context tools (from vendor/manifest.yaml, disposition=install)"
python -m pip install --quiet "headroom-ai" "graphifyy" "specify-cli"

echo "==> Installing Playwright browser (for visual QA)"
python -m playwright install chromium || echo "WARN: Playwright browser install failed; visual QA will not run until fixed."

echo "==> Preparing configuration"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "    created .env from .env.example (edit before running services)"
fi

echo "==> Verifying"
python -m pytest -q || { echo "Tests failed"; exit 1; }

echo
echo "Setup complete. Activate with: source .venv/bin/activate"
echo "Binary security tools (gitleaks, trivy, zaproxy, nuclei, testssl.sh) are NOT installed here."
echo "Install them with a pinned release after review: see docs/operations/security-tools.md"
