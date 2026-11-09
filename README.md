# AI-SOOS — AI Software Orchestration Operating System

A controlled software factory. A project brief goes in; a specification, a plan, an implementation in an isolated workspace, verification, and a reviewed pull request come out.

## Start here

1. Read `AGENTS.md` (instructions for all coding agents) and `rules/` (binding constraints).
2. Read `docs/architecture/` for the design (the architecture document is provided separately).
3. Set up the environment:

```bash
bash scripts/setup.sh
make test
```

4. Optional: clone reference repositories for study (read-only, never built or run):

```bash
bash scripts/fetch-reference-repos.sh
```

## What is installed, and what is not

`vendor/manifest.yaml` classifies all 75 supplied repositories. In short:

- **Installed into the project:** Semgrep (SAST), LiteLLM and LangGraph (gateway and orchestration libraries), Playwright (browser tests), FastAPI, SQLAlchemy, and the test tooling. Also `headroom-ai`, `graphifyy`, and `specify-cli`, verified against their listed repositories.
- **Cloned for study only:** architecture, agent-workflow, and design references. These are not built or executed.
- **Excluded:** offensive security tools (exploitation, fuzzing, reconnaissance against third parties), reverse-engineering tools, prompt collections intended to reduce model restrictions, outreach automation, and forks or packages that do not match the listed repository. Reasons are in the manifest.

Binary security tools (Gitleaks, Trivy, ZAP, Nuclei, testssl.sh) are installed later as pinned releases; see `docs/operations/security-tools.md` (to be written when the runner is built).

## Layout

See `AGENTS.md` for the repository map.
