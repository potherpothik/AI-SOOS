"""Durable workflow state. The graph is the only place status changes."""

from typing import TypedDict


class FactoryState(TypedDict):
    status: str
    spec_approved: bool
    delivery_approved: bool
    tests_passed: bool
    review_ok: bool
    scan_ok: bool
    rewrite: bool
    retries: int
    max_retries: int
    tool_calls: int
    max_tool_calls: int
    brief: str
    template: str
    mode: str
    workspace: str
    branch: str
    missing: str
    pr_body: str
    project_id: str
    task_id: str
    actor: str
    started_at: str
    blockers: list[str]
    test_output: str
    visual: str
    untrusted: bool
    isolation: str


def initial_state(
    *,
    brief: str,
    template: str,
    mode: str,
    project_id: str,
    task_id: str,
    actor: str,
    workspace: str,
    started_at: str,
    max_retries: int,
    max_tool_calls: int,
    untrusted: bool,
    isolation: str,
) -> FactoryState:
    return FactoryState(
        status="brief",
        spec_approved=False,
        delivery_approved=False,
        tests_passed=False,
        review_ok=False,
        scan_ok=False,
        rewrite=False,
        retries=0,
        max_retries=max_retries,
        tool_calls=0,
        max_tool_calls=max_tool_calls,
        brief=brief,
        template=template,
        mode=mode,
        workspace=workspace,
        branch=f"aisoos/{task_id}",
        missing="",
        pr_body="",
        project_id=project_id,
        task_id=task_id,
        actor=actor,
        started_at=started_at,
        blockers=[],
        test_output="",
        visual="not_applicable",
        untrusted=untrusted,
        isolation=isolation,
    )
