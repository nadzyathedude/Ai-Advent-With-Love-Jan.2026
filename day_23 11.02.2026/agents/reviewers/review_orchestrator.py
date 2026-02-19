"""Review orchestrator — builds the review graph and provides the review_pr() entry point."""

from core.orchestration.graph import END, Graph
from core.registry.tool_registry import ToolRegistry

from .review_nodes import (
    PRFetchNode,
    DocsContextNode,
    BugReviewNode,
    StyleReviewNode,
    SecurityReviewNode,
    PerformanceReviewNode,
    ReviewMergeNode,
    LearningContextNode,
    LearningAdjustNode,
    MemoryPersistNode,
)
from .review_state import ReviewState


# Agent IDs and their required permissions for reference / CI config
REVIEWER_AGENTS = {
    "bug_reviewer": ["pr:read"],
    "style_reviewer": ["pr:read", "docs:read"],
    "security_reviewer": ["pr:read"],
    "performance_reviewer": ["pr:read"],
    "learning_reviewer": ["review_memory:read"],
    "review_orchestrator": ["pr:read", "docs:read", "review_memory:read", "review_memory:write"],
}


def build_review_graph() -> Graph:
    """Construct the PR review pipeline graph with continuous learning.

    Wiring:
        pr_fetch -> learning_context -> docs_context -> bug_review -> style_review
          -> security_review -> performance_review -> review_merge
          -> learning_adjust -> memory_persist -> END
    """
    graph = Graph()

    graph.add_node("pr_fetch", PRFetchNode())
    graph.add_node("learning_context", LearningContextNode())
    graph.add_node("docs_context", DocsContextNode())
    graph.add_node("bug_review", BugReviewNode())
    graph.add_node("style_review", StyleReviewNode())
    graph.add_node("security_review", SecurityReviewNode())
    graph.add_node("performance_review", PerformanceReviewNode())
    graph.add_node("review_merge", ReviewMergeNode())
    graph.add_node("learning_adjust", LearningAdjustNode())
    graph.add_node("memory_persist", MemoryPersistNode())

    graph.set_entry_point("pr_fetch")
    graph.add_edge("pr_fetch", "learning_context")
    graph.add_edge("learning_context", "docs_context")
    graph.add_edge("docs_context", "bug_review")
    graph.add_edge("bug_review", "style_review")
    graph.add_edge("style_review", "security_review")
    graph.add_edge("security_review", "performance_review")
    graph.add_edge("performance_review", "review_merge")
    graph.add_edge("review_merge", "learning_adjust")
    graph.add_edge("learning_adjust", "memory_persist")
    graph.add_edge("memory_persist", END)

    return graph


def review_pr(
    base_branch: str = "main",
    registry: ToolRegistry = None,
    debug: bool = False,
    pr_id: str = "",
) -> str:
    """Run the full PR review pipeline and return the formatted report."""
    graph = build_review_graph()
    state = ReviewState(base_branch=base_branch, pr_id=pr_id)

    # Use review_orchestrator agent_id — has broadest permissions
    state = graph.run(state, registry=registry, agent_id="review_orchestrator")

    if debug:
        lines = [
            f"[DEBUG] Nodes executed: {state.nodes_executed}",
            f"[DEBUG] Tools used: {state.tools_used}",
            f"[DEBUG] Errors: {state.errors}",
            f"[DEBUG] Findings: {len(state.findings)}",
            f"[DEBUG] Risk level: {state.risk_level}",
            f"[DEBUG] Learning: {state.learning_summary}",
            "",
        ]
        return "\n".join(lines) + state.review_report

    return state.review_report
