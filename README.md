# AI-SOOS

AI-SOOS is a control plane for a software factory. A brief goes in. The system writes a specification, waits for a person to accept it, implements the change in an isolated workspace, runs tests and security checks, and prepares a pull request. Merge and production deploy stay manual.

## Prerequisites

- Git
- Python 3.12 or newer
- Docker Compose, only if you want local Postgres, Redis, and MinIO

A model API key and a GitHub token are optional. The health check works without them.

## Install

```bash
git clone https://github.com/potherpothik/AI-SOOS.git
cd AI-SOOS
cp .env.example .env
bash scripts/setup.sh
```

`scripts/setup.sh` is the install command. It refuses to run on Python older than 3.12, creates `.venv`, installs the locked dependencies from `requirements.lock`, copies `.env` when it is missing, and runs the tests.

Activate the environment after install:

```bash
source .venv/bin/activate
```

## Run

```bash
make run
```

The API listens on `http://127.0.0.1:8000`. Check it:

```bash
curl -s http://127.0.0.1:8000/health
```

`GET /health` answers with no model key and no GitHub token. `POST /projects/{id}/generate` with `"mode": "model"` returns `{"missing": "AISOOS_MODEL_API_KEY"}` until that variable is set in `.env`. Opening a GitHub pull request returns `AISOOS_GITHUB_TOKEN` the same way. `"mode": "template"` builds from a template in this repository and does not call a model.

## Local services

Postgres, Redis, and MinIO are declared in `infra/compose/docker-compose.yml`. The database password in that file is for a machine-local database. Change it before any shared or public deploy.

```bash
bash scripts/compose-up.sh
```

If Docker is not installed, that command prints the install path and does not try to install Docker.

## Tests

```bash
make test
make lint
make typecheck
```

## Configuration

Every variable is listed in `.env.example`.

| Variable | Purpose |
|---|---|
| `AISOOS_DATABASE_URL` | Control-plane database. The default is local Postgres. |
| `AISOOS_MODEL_API_KEY` | Required only when generation uses a model. |
| `AISOOS_MODEL_NAME` | Model name passed to LiteLLM. |
| `AISOOS_GITHUB_TOKEN` | Required only when the platform opens a pull request. |
| `AISOOS_WORKSPACE_BACKEND` | `local` or `docker`. Docker runs the task container with no network and without the Docker socket. |

Budgets live in `policies/model-budgets/budgets.yaml`. Tool permissions live in `policies/tool-permissions/roles.yaml`.

## Security tools

Semgrep is installed with the Python package. Gitleaks and Trivy are not part of the default install. Their pinned releases and the checksum check are in `docs/operations/security-tools.md`.

## What a generated project can be

Templates in `templates/` cover an API service, a marketing site, a SaaS service, and a small agent with a tool allowlist. The first run uses one coding role. Frontend, backend, database, and QA roles are limited by the same policy file.

## License

See `LICENSE` and `THIRD_PARTY_NOTICES.md`.
