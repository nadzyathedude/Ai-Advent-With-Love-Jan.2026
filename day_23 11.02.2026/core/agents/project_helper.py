"""Project helper agent — wires the graph with nodes and edges."""

from core.orchestration.graph import Graph
from core.orchestration.nodes import (
    AnswerComposerNode,
    DocsRetrieveNode,
    GitContextNode,
    RouterNode,
    route_next,
)
from core.registry.tool_registry import ToolRegistry


AGENT_ID = "project_helper"


def build_graph() -> Graph:
    """Construct the project helper graph.

    Wiring:
        router -> conditional -> git_context/docs_retrieve
                              -> answer_composer -> END
    """
    graph = Graph()

    graph.add_node("router", RouterNode())
    graph.add_node("git_context", GitContextNode())
    graph.add_node("docs_retrieve", DocsRetrieveNode())
    graph.add_node("answer_composer", AnswerComposerNode())

    graph.set_entry_point("router")
    graph.add_conditional_edges("router", route_next)
    graph.add_conditional_edges("git_context", route_next)
    graph.add_conditional_edges("docs_retrieve", route_next)
    graph.add_edge("answer_composer", "__end__")

    return graph


def ask(question: str, registry: ToolRegistry, debug: bool = False) -> str:
    """Run the project helper agent on a question."""
    from core.orchestration.graph import GraphState

    graph = build_graph()
    state = GraphState(question=question)
    state = graph.run(state, registry=registry, agent_id=AGENT_ID)

    if debug:
        lines = [
            f"[DEBUG] Nodes executed: {state.nodes_executed}",
            f"[DEBUG] Tools used: {state.tools_used}",
            f"[DEBUG] Route: {state.route}",
            f"[DEBUG] Errors: {state.errors}",
            "",
        ]
        return "\n".join(lines) + state.final_answer

    return state.final_answer
