"""LangGraph transitions. Side effects stay outside the graph."""

from typing import Any, cast

from langgraph.graph import END, StateGraph

from app.state import FactoryState

_HOLD = "hold"


def _identity(state: FactoryState) -> FactoryState:
    return state


def _set_status(name: str) -> Any:
    def node(state: FactoryState) -> FactoryState:
        updated = cast(FactoryState, dict(state))
        updated["status"] = name
        return updated

    return node


def route_verify(state: FactoryState) -> str:
    if state["tests_passed"]:
        return "reviewing"
    if state["retries"] >= state["max_retries"]:
        return "failed"
    return "repairing"


def route_review(state: FactoryState) -> str:
    if state["rewrite"]:
        return "repairing"
    return "scanning"


def route_scan(state: FactoryState) -> str:
    if state["rewrite"]:
        return "repairing"
    return "awaiting_approval"


def transition(state: FactoryState) -> FactoryState:
    status = state["status"]
    graph: StateGraph[FactoryState] = StateGraph(FactoryState)
    graph.add_node(status, cast(Any, _identity))
    graph.set_entry_point(status)

    def destination(name: str) -> None:
        graph.add_node(name, cast(Any, _set_status(name)))
        graph.add_edge(name, END)

    if status == "brief":
        destination("spec")
        graph.add_edge("brief", "spec")
    elif status == "spec":
        destination("approved")
        graph.add_conditional_edges(
            "spec",
            lambda current: "approved" if current["spec_approved"] else _HOLD,
            {"approved": "approved", _HOLD: END},
        )
    elif status == "approved":
        destination("workspace")
        graph.add_edge("approved", "workspace")
    elif status == "workspace":
        destination("coding")
        graph.add_edge("workspace", "coding")
    elif status == "coding":
        destination("verifying")
        graph.add_edge("coding", "verifying")
    elif status == "verifying":
        for name in ("reviewing", "repairing", "failed"):
            destination(name)
        graph.add_conditional_edges(
            "verifying",
            route_verify,
            {"reviewing": "reviewing", "repairing": "repairing", "failed": "failed"},
        )
    elif status == "repairing":
        destination("coding")
        graph.add_edge("repairing", "coding")
    elif status == "reviewing":
        for name in ("scanning", "repairing"):
            destination(name)
        graph.add_conditional_edges(
            "reviewing",
            route_review,
            {"scanning": "scanning", "repairing": "repairing"},
        )
    elif status == "scanning":
        for name in ("awaiting_approval", "repairing"):
            destination(name)
        graph.add_conditional_edges(
            "scanning",
            route_scan,
            {"awaiting_approval": "awaiting_approval", "repairing": "repairing"},
        )
    elif status == "awaiting_approval":
        destination("delivered")
        graph.add_conditional_edges(
            "awaiting_approval",
            lambda current: "delivered" if current["delivery_approved"] else _HOLD,
            {"delivered": "delivered", _HOLD: END},
        )
    elif status in {"delivered", "failed"}:
        graph.add_edge(status, END)
    else:
        message = f"unknown status: {status}"
        raise ValueError(message)

    compiled = graph.compile()
    return cast(FactoryState, compiled.invoke(state))
