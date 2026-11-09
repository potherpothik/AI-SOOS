"""Turn a brief into the documents later checks use."""

from pathlib import Path

from app.paths import repo_root


def generate_documents(brief: str, template: str) -> dict[str, str]:
    checklist = (repo_root() / "policies" / "asvs" / "checklist.yaml").read_text(encoding="utf-8")
    requirements = (
        f"# Requirements\n\n{brief.strip()}\n\n## Template\n\n{template}\n\n"
        "The human accepts this scope before any code is written.\n"
    )
    acceptance = (
        "# Acceptance criteria\n\n"
        "- The selected template is present in the workspace.\n"
        "- The workspace tests pass.\n"
        "- An independent review cites any finding to a line.\n"
        "- Security checks record evidence.\n"
        "- A human approves delivery before merge.\n"
    )
    threat = (
        "# Threat model\n\n"
        f"System: generated {template} from the project brief.\n\n"
        "## Assets\n\n- Source in the task workspace\n- Model credentials, which stay outside the workspace\n\n"
        "## Boundaries\n\n- The coding agent writes only inside the workspace.\n"
        "- Dynamic scans run only against a host named in an authorization record.\n\n"
        f"## Brief\n\n{brief.strip()}\n"
    )
    design = f"# Design\n\nTemplate `{template}` is the first implementation of the accepted brief.\n"
    return {
        "REQUIREMENTS.md": requirements,
        "ACCEPTANCE_CRITERIA.md": acceptance,
        "THREAT_MODEL.md": threat,
        "DESIGN.md": design,
        "ASVS_CHECKLIST.yaml": checklist,
    }


def write_documents(workspace: Path, documents: dict[str, str]) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    for name, body in documents.items():
        (workspace / name).write_text(body, encoding="utf-8")
