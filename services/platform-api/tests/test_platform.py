import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from subprocess import CompletedProcess

import pytest
from alembic.config import Config
from app.agent import CodingAgent
from app.budgets import load_budgets
from app.config import Settings
from app.cost import anomaly_task_ids, choose_route, clip_lines, compress_prompt, summarize
from app.db import init_db, make_engine, make_session_factory, session_scope
from app.delivery import build_pr_body, parse_github_repo, pull_request_call
from app.errors import GateBlocked
from app.factory import approve_task, start_task
from app.gates import contract_gaps, failed_checks
from app.ledger import charge
from app.main import create_app
from app.maintenance import merge_request, propose_update
from app.memory import index_workspace, query_memory
from app.models import UsageRecord
from app.paths import repo_root
from app.registry import create_project
from app.review import ReviewFinding, review_diff
from app.runner import visual_check
from app.sbom import generate_sbom
from app.security_runner import ScanFinding, dynamic_scan_allowed, scan_workspace
from app.state import FactoryState, initial_state
from app.teams import effective_policy, perform_deploy, role_can
from app.workflow import route_verify, transition
from app.workspace import assert_isolation, destroy_if_expired, docker_command
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from alembic import command


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'aisoos.db'}",
        model_api_key="",
        model_name="",
        github_token="",
        run_semgrep=False,
        workspace_backend="local",
    )


def _factory(tmp_path: Path) -> tuple[Settings, object]:
    settings = _settings(tmp_path)
    engine = make_engine(settings.database_url)
    init_db(engine)
    return settings, make_session_factory(engine)


def _blank(**overrides: object) -> FactoryState:
    state = initial_state(
        brief="Build a health endpoint.",
        template="api-service",
        mode="template",
        project_id="p",
        task_id="t",
        actor="local",
        workspace="workspace",
        started_at=datetime.now(UTC).isoformat(),
        max_retries=2,
        max_tool_calls=60,
        untrusted=False,
        isolation="local",
    )
    for key, value in overrides.items():
        state[key] = value  # type: ignore[literal-required]
    return state


def test_transition_waits_for_spec_approval() -> None:
    waiting = transition(_blank(status="spec", spec_approved=False))
    moving = transition(_blank(status="spec", spec_approved=True))
    assert waiting["status"] == "spec"
    assert moving["status"] == "approved"


def test_retries_stop_after_the_policy_limit() -> None:
    failed = route_verify(_blank(status="verifying", tests_passed=False, retries=2, max_retries=2))
    repair = route_verify(_blank(status="verifying", tests_passed=False, retries=1, max_retries=2))
    assert failed == "failed"
    assert repair == "repairing"


def test_blank_model_key_generates_from_the_template(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    application = create_app(settings)
    application.state.workspace_root = tmp_path / "work"
    client = TestClient(application)
    created = client.post(
        "/projects",
        json={"organization": "local", "name": "demo", "owner": "ada", "actor_role": "owner"},
    )
    assert created.status_code == 200
    response = client.post(
        f"/projects/{created.json()['id']}/generate",
        json={"brief": "Build a health endpoint.", "mode": "model"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "spec"
    assert body["missing"] == ""


def test_template_run_reaches_an_approved_pull_request(tmp_path: Path) -> None:
    settings, factory = _factory(tmp_path)
    with session_scope(factory) as session:
        assert isinstance(session, Session)
        project = create_project(
            session,
            organization="local",
            name="demo",
            owner="ada",
            actor_role="owner",
            repository_url="https://github.com/example/demo.git",
        )
        task = start_task(
            session,
            settings,
            project_id=project.id,
            brief="Build a health endpoint.",
            template="api-service",
            mode="template",
            actor="ada",
            actor_role="owner",
            idempotency_key="same-task",
            workspace_root=tmp_path / "work",
        )
        assert task.status == "spec"
        again = start_task(
            session,
            settings,
            project_id=project.id,
            brief="Build a health endpoint.",
            template="api-service",
            mode="template",
            actor="ada",
            actor_role="owner",
            idempotency_key="same-task",
            workspace_root=tmp_path / "work",
        )
        assert again.id == task.id
        approved = approve_task(
            session,
            settings,
            task_id=task.id,
            kind="spec",
            approver="ada",
            approver_role="owner",
            workspace_root=tmp_path / "work",
        )
        loaded = json.loads(approved.state_json)
        assert approved.status == "awaiting_approval"
        assert loaded["missing"] == "AISOOS_GITHUB_TOKEN"
        delivered = approve_task(
            session,
            settings,
            task_id=task.id,
            kind="delivery",
            approver="ada",
            approver_role="owner",
            workspace_root=tmp_path / "work",
        )
        assert delivered.status == "delivered"
        hits = query_memory(session, project.id, "where is health implemented")
        assert any(item.symbol == "health" for item in hits)
        rows = list(session.scalars(select(UsageRecord)).all())
        summary = summarize(rows)
        assert summary["accepted_tasks"] == 1
        assert summary["cost_per_accepted_task"] == 0.0


def test_viewer_cannot_create_a_project(tmp_path: Path) -> None:
    _settings_obj, factory = _factory(tmp_path)
    with session_scope(factory) as session:
        with pytest.raises(PermissionError):
            create_project(session, organization="local", name="demo", owner="ada", actor_role="viewer")


def test_coding_agent_stays_inside_the_workspace(tmp_path: Path) -> None:
    agent = CodingAgent(tmp_path)
    agent.write("service.py", "x = 1\n")
    assert (tmp_path / "service.py").is_file()
    with pytest.raises(PermissionError):
        agent.write("../outside.py", "nope")


def test_docker_command_is_closed() -> None:
    command = docker_command(Path("aisoos-workspace"))
    rendered = " ".join(command)
    assert "--network" in command and "none" in command
    assert "docker.sock" not in rendered
    assert "--user" in command


def test_untrusted_code_is_refused_without_a_microvm() -> None:
    with pytest.raises(PermissionError):
        assert_isolation("local", True)


def test_charge_is_stored_without_a_budget_cap(tmp_path: Path) -> None:
    _settings_obj, factory = _factory(tmp_path)
    limits = load_budgets()
    with session_scope(factory) as session:
        project = create_project(session, organization="local", name="demo", owner="ada", actor_role="owner")
        record = charge(
            session,
            limits,
            project_id=project.id,
            task_id="t",
            model="test",
            input_tokens=limits.input_tokens + 1,
            output_tokens=1,
            usd=1000.0,
            prompt="hello",
            prompt_cache=False,
        )
        assert record.input_tokens == limits.input_tokens + 1
        assert record.usd == 1000.0


def test_release_gate_and_contract() -> None:
    blocked = failed_checks({"tests": False, "review": True, "scan": True}, ["tests", "review", "scan"], False)
    assert blocked == ["tests"]
    assert failed_checks({"tests": False}, ["tests"], True) == []
    spec = (repo_root() / "templates" / "api-service" / "API_SPEC.yaml").read_text(encoding="utf-8")
    source = (repo_root() / "templates" / "api-service" / "service.py").read_text(encoding="utf-8")
    assert contract_gaps(spec, source) == []
    assert contract_gaps(spec, "def other():\n    return None\n") == ["health"]


def test_dynamic_scan_requires_an_authorization_record() -> None:
    assert dynamic_scan_allowed("staging.example", "ada", "scan staging.example", False) is True
    assert dynamic_scan_allowed("production", "ada", "scan production", False) is False
    assert dynamic_scan_allowed("staging.example", "", "scan staging.example", False) is False


def test_scanner_reports_eval(tmp_path: Path) -> None:
    sample = "def run():\n    return eval('1')\n"
    (tmp_path / "bad.py").write_text(sample, encoding="utf-8")
    findings = scan_workspace(tmp_path, True)
    assert any(item.severity == "high" for item in findings)


def test_maintenance_proposal_is_not_merged(tmp_path: Path) -> None:
    _settings_obj, factory = _factory(tmp_path)
    with session_scope(factory) as session:
        project = create_project(session, organization="local", name="demo", owner="ada", actor_role="owner")
        proposal = propose_update(
            session,
            project_id=project.id,
            package="demo",
            from_version="1",
            to_version="2",
            actor="ada",
        )
        assert proposal.status == "proposed"
        with pytest.raises(PermissionError):
            merge_request(proposal)


def test_project_policy_cannot_enable_deploy() -> None:
    policy = effective_policy('{"deploy": true, "network": "registry.example"}')
    assert policy["deploy"] is False
    assert role_can("owner", "deploy") is False
    with pytest.raises(PermissionError):
        perform_deploy()


def test_cheapest_successful_route_is_selected() -> None:
    chosen = choose_route(
        [
            {"model": "big", "usd": 1.5, "success": True},
            {"model": "small", "usd": 0.2, "success": True},
            {"model": "broken", "usd": 0.01, "success": False},
        ]
    )
    assert chosen == "small"


def test_compression_is_off_by_default() -> None:
    text = "\n".join(f"line {number}" for number in range(10))
    assert compress_prompt(text, False) == text
    assert "omitted" in clip_lines("\n".join(str(number) for number in range(50)), max_lines=4)


def test_workspace_is_removed_after_retention(tmp_path: Path) -> None:
    workspace = tmp_path / "gone"
    workspace.mkdir()
    created = datetime.now(UTC) - timedelta(hours=48)
    assert destroy_if_expired(workspace, created, 24, datetime.now(UTC)) is True
    assert workspace.exists() is False


def test_pull_request_body_keeps_the_token_out() -> None:
    body = build_pr_body(
        summary="health",
        files=["service.py"],
        tests="passed",
        scans="clean",
        cost_usd=0,
        limitations="manual merge",
    )
    owner, name = parse_github_repo("https://github.com/example/demo.git")
    request = pull_request_call("https://github.com/example/demo.git", "aisoos/1", "title", body)
    assert owner == "example" and name == "demo"
    assert "service.py" in body
    assert "secret-token" not in json.dumps(request.body)


def test_visual_check_reports_a_result(tmp_path: Path) -> None:
    page = tmp_path / "index.html"
    page.write_text("<html><head><title>AI-SOOS site</title></head></html>", encoding="utf-8")
    result = visual_check(page)
    assert result.status in {"passed", "skipped", "failed"}


def test_readme_does_not_depend_on_local_files() -> None:
    readme = (repo_root() / "README.md").read_text(encoding="utf-8")
    example = (repo_root() / ".env.example").read_text(encoding="utf-8")
    assert "AGENTS.md" not in readme
    assert "Clone-Repositories" not in readme
    assert "AISOOS_MODEL_API_KEY" in example
    assert "AISOOS_GITHUB_TOKEN" in example
    assert (repo_root() / "LICENSE").is_file()
    assert (repo_root() / "requirements.lock").is_file()
    assert (repo_root() / ".github" / "workflows" / "ci.yml").is_file()


def test_failed_repairs_stop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.effects.run_tests", lambda _workspace: (False, "failed on purpose"))
    settings, factory = _factory(tmp_path)
    with session_scope(factory) as session:
        project = create_project(session, organization="local", name="demo", owner="ada", actor_role="owner")
        task = start_task(
            session,
            settings,
            project_id=project.id,
            brief="Build a health endpoint.",
            template="api-service",
            mode="template",
            actor="ada",
            actor_role="owner",
            idempotency_key=None,
            workspace_root=tmp_path / "work",
        )
        finished = approve_task(
            session,
            settings,
            task_id=task.id,
            kind="spec",
            approver="ada",
            approver_role="owner",
            workspace_root=tmp_path / "work",
        )
        assert finished.status == "failed"


def test_coding_role_cannot_approve(tmp_path: Path) -> None:
    settings, factory = _factory(tmp_path)
    with session_scope(factory) as session:
        project = create_project(session, organization="local", name="demo", owner="ada", actor_role="owner")
        task = start_task(
            session,
            settings,
            project_id=project.id,
            brief="Build a health endpoint.",
            template="api-service",
            mode="template",
            actor="ada",
            actor_role="owner",
            idempotency_key=None,
            workspace_root=tmp_path / "work",
        )
        with pytest.raises(PermissionError):
            approve_task(
                session,
                settings,
                task_id=task.id,
                kind="spec",
                approver="coder",
                approver_role="coding",
                workspace_root=tmp_path / "work",
            )


def test_high_review_finding_blocks_delivery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.effects.review_diff",
        lambda _diff: [ReviewFinding(1, "high", "eval is not allowed")],
    )
    settings, factory = _factory(tmp_path)
    with session_scope(factory) as session:
        project = create_project(session, organization="local", name="demo", owner="ada", actor_role="owner")
        task = start_task(
            session,
            settings,
            project_id=project.id,
            brief="Build a health endpoint.",
            template="api-service",
            mode="template",
            actor="ada",
            actor_role="owner",
            idempotency_key=None,
            workspace_root=tmp_path / "work",
        )
        waiting = approve_task(
            session,
            settings,
            task_id=task.id,
            kind="spec",
            approver="ada",
            approver_role="owner",
            workspace_root=tmp_path / "work",
        )
        with pytest.raises(GateBlocked):
            approve_task(
                session,
                settings,
                task_id=waiting.id,
                kind="delivery",
                approver="ada",
                approver_role="owner",
                workspace_root=tmp_path / "work",
            )


def test_sbom_has_a_sha256_digest() -> None:
    document = generate_sbom()
    digest = document["digest"]
    assert document["bomFormat"] == "CycloneDX"
    assert isinstance(digest, dict)
    assert digest["algorithm"] == "sha256"
    assert isinstance(digest["value"], str) and len(digest["value"]) == 64


def test_schema_migration_upgrades_and_rolls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = tmp_path / "migrated.db"
    monkeypatch.setenv("AISOOS_DATABASE_URL", f"sqlite+pysqlite:///{database}")
    config = Config(str(repo_root() / "alembic.ini"))
    command.upgrade(config, "head")
    assert database.is_file()
    command.downgrade(config, "base")


def test_spend_anomaly_is_three_times_the_median() -> None:
    def row(identifier: str, task_id: str, usd: float) -> UsageRecord:
        return UsageRecord(
            id=identifier,
            project_id="p",
            task_id=task_id,
            model="m",
            input_tokens=1,
            output_tokens=1,
            cached_tokens=0,
            usd=usd,
            accepted=True,
            prompt_hash=identifier,
        )

    flagged = anomaly_task_ids([row("1", "low", 1.0), row("2", "mid", 1.0), row("3", "high", 10.0)])
    assert flagged == ["high"]


def test_scan_returns_to_repair_only_while_a_rewrite_is_requested() -> None:
    repair = transition(_blank(status="scanning", rewrite=True, retries=0, max_retries=2))
    onward = transition(_blank(status="scanning", rewrite=False, retries=2, max_retries=2))
    assert repair["status"] == "repairing"
    assert onward["status"] == "awaiting_approval"


def test_large_diff_is_a_note() -> None:
    long_diff = "\n".join(f"+line {number}" for number in range(121))
    noted = review_diff(long_diff)
    assert any(item.severity == "low" and item.message == "large diff" for item in noted)
    assert review_diff("+ok\n") == []


def test_missing_security_binaries_are_notes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.security_runner.security_binary", lambda _name: None)
    findings = scan_workspace(tmp_path, False)
    notes = {item.source: item.severity for item in findings}
    assert notes["gitleaks"] == "low"
    assert notes["trivy"] == "low"


def test_factory_source_does_not_read_a_skill_file() -> None:
    app = repo_root() / "services" / "platform-api" / "app"
    text = "\n".join(path.read_text(encoding="utf-8") for path in sorted(app.rglob("*.py")))
    assert "SKILL.md" not in text
    assert "graphify install" not in text
    assert "specify init" not in text


def test_memory_reindexes_the_project(tmp_path: Path) -> None:
    _settings_obj, factory = _factory(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "service.py").write_text("def health():\n    return {}\n", encoding="utf-8")
    with session_scope(factory) as session:
        project = create_project(session, organization="local", name="demo", owner="ada", actor_role="owner")
        index_workspace(session, project.id, workspace)
        (workspace / "service.py").write_text("def status():\n    return {}\n", encoding="utf-8")
        index_workspace(session, project.id, workspace)
        symbols = {item.symbol for item in query_memory(session, project.id, "status health")}
        assert "status" in symbols
        assert "health" not in symbols


def test_model_sees_the_graph_query_and_repairs_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompts: list[str] = []
    scans = {"n": 0}

    def fake_tool(name: str) -> str | None:
        if name == "graphify":
            return "/usr/bin/graphify"
        return None

    def fake_run(argv: list[str], cwd: Path, timeout: int, env: dict[str, str] | None = None) -> CompletedProcess[str]:
        del timeout, env
        if argv[1] == "extract":
            out = Path(cwd) / "graphify-out"
            out.mkdir(parents=True, exist_ok=True)
            (out / "graph.json").write_text("{}", encoding="utf-8")
            return CompletedProcess(argv, 0, stdout="extracted", stderr="")
        if argv[1] == "query":
            return CompletedProcess(argv, 0, stdout="GRAPH_QUERY health", stderr="")
        if argv[1] == "god-nodes":
            return CompletedProcess(argv, 0, stdout='[{"label": "health"}]', stderr="")
        return CompletedProcess(argv, 0, stdout="", stderr="")

    def fake_completion(**kwargs: object) -> object:
        messages = kwargs["messages"]
        assert isinstance(messages, list)
        prompt = str(messages[0]["content"])
        prompts.append(prompt)
        content = json.dumps({"service.py": "def health():\n    return {'status': 'ok'}\n"})
        message = type("Message", (), {"content": content})()
        choice = type("Choice", (), {"message": message})()
        usage = type("Usage", (), {"prompt_tokens": 12, "completion_tokens": 4})()
        return type("Response", (), {"choices": [choice], "usage": usage})()

    def fake_scan(workspace: Path, run_semgrep: bool) -> list[ScanFinding]:
        del workspace, run_semgrep
        scans["n"] += 1
        if scans["n"] == 1:
            return [ScanFinding("semgrep", "high", 1, "eval is not allowed in generated code")]
        return []

    monkeypatch.setattr("app.context.tool_path", fake_tool)
    monkeypatch.setattr("app.context.run_tool", fake_run)
    monkeypatch.setattr("app.context.compress_prompt", lambda text, enabled, compressor=None: text)
    monkeypatch.setattr("app.gateway.litellm.completion", fake_completion)
    monkeypatch.setattr("app.effects.scan_workspace", fake_scan)
    monkeypatch.setattr("app.effects.run_tests", lambda _workspace: (True, "passed"))

    settings = Settings(
        environment="test",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'aisoos.db'}",
        model_api_key="test-key",
        model_name="test-model",
        github_token="",
        run_semgrep=False,
        workspace_backend="local",
    )
    _ignored, factory = _factory(tmp_path)
    with session_scope(factory) as session:
        project = create_project(session, organization="local", name="demo", owner="ada", actor_role="owner")
        task = start_task(
            session,
            settings,
            project_id=project.id,
            brief="Build a health endpoint.",
            template="api-service",
            mode="model",
            actor="ada",
            actor_role="owner",
            idempotency_key=None,
            workspace_root=tmp_path / "work",
        )
        finished = approve_task(
            session,
            settings,
            task_id=task.id,
            kind="spec",
            approver="ada",
            approver_role="owner",
            workspace_root=tmp_path / "work",
        )
        loaded = json.loads(finished.state_json)
        assert finished.status == "awaiting_approval"
        assert loaded["retries"] == 1
        assert loaded["missing"] == "AISOOS_GITHUB_TOKEN"
        assert len(prompts) == 2
        assert "GRAPH_QUERY health" in prompts[0]
        assert "eval is not allowed in generated code" in prompts[1]
        workspace = tmp_path / "work" / task.id
        assert "health" in (workspace / "DESIGN.md").read_text(encoding="utf-8")
        models = {row.model for row in session.scalars(select(UsageRecord)).all()}
        assert "context-full" in models
        assert "graphify-query" in models

