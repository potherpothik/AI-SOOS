# AI-SOOS

AI-SOOS is a control plane for a software factory. A brief goes in. The system writes a specification, waits for a person to accept it, builds a code graph of the workspace, implements the change, runs tests and security checks, and prepares a pull request. Merge and production deploy stay manual. A build does not read a skill file.

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

`GET /health` and `POST /projects/{id}/generate` run with a blank `AISOOS_MODEL_API_KEY`. A blank key copies a template from this repository and does not call a model, including a request that says `"mode": "model"`. When both `AISOOS_MODEL_API_KEY` and `AISOOS_MODEL_NAME` are set, the model receives a Graphify query for the brief and its reply is written into the workspace as files. A high scan or review finding is sent back to that model until the retry cap. With a blank key the template stays, and delivery stays blocked until a person approves an exception. Opening a GitHub pull request returns `AISOOS_GITHUB_TOKEN` when that variable is empty.

`GET /projects/{id}/cost` reports cost and tokens for each accepted task, including the full workspace size and the smaller graph-query size.

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
| `AISOOS_MODEL_API_KEY` | Leave blank. Generation does not ask for it. Set it, with `AISOOS_MODEL_NAME`, only when the factory should call a model. |
| `AISOOS_MODEL_NAME` | Leave blank. The model name passed to LiteLLM when the key is set. |
| `AISOOS_GITHUB_TOKEN` | Required only when the platform opens a pull request. |
| `AISOOS_WORKSPACE_BACKEND` | `local` or `docker`. Docker runs the task container with no network and without the Docker socket. |

`policies/model-budgets/budgets.yaml` records usage figures for the cost report. Those figures do not stop a task. Tool permissions live in `policies/tool-permissions/roles.yaml`.

## Security tools

Semgrep is installed with the Python package and runs on every workspace. Gitleaks and Trivy run when their binaries are present. Install them with `AISOOS_INSTALL_SECURITY_TOOLS=1 bash scripts/install-security-tools.sh`. A missing binary is recorded as a note and the task continues. Pinned releases and the checksum check are in `docs/operations/security-tools.md`.

## What a generated project can be

Templates in `templates/` cover an API service, a marketing site, a SaaS service, and a small agent with a tool allowlist. The first run uses one coding role. Frontend, backend, database, and QA roles are limited by the same policy file.

## License

See `LICENSE` and `THIRD_PARTY_NOTICES.md`.
