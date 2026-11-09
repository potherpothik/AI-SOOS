#!/usr/bin/env bash
# Start the local services defined in the repository. Docker is not installed by this script.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed. The application itself installs with: bash scripts/setup.sh"
  echo "After Docker is installed, run: docker compose -f infra/compose/docker-compose.yml up -d"
  exit 0
fi
docker compose -f "$ROOT/infra/compose/docker-compose.yml" up -d
