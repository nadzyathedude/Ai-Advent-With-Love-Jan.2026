"""Concrete graph nodes: router, docs retrieval, git context, answer composer."""

from abc import ABC, abstractmethod
from typing import List

from .graph import END, GraphState


class Node(ABC):
    """Base class for graph nodes."""

    @abstractmethod
    def execute(self, state: GraphState, registry, agent_id: str) -> GraphState:
        """Process state and return updated state."""


def route_next(state: GraphState) -> str:
    """Pick the first node in state.route not yet executed. If none remain, go to END."""
    for node_name in state.route:
        if node_name not in state.nodes_executed:
            return node_name
    return END


class RouterNode(Node):
    """Analyzes the question and sets the execution route based on keywords."""

    GIT_KEYWORDS = {"branch", "git", "commit", "merge", "repo", "repository"}
    DOCS_KEYWORDS = {"architecture", "doc", "docs", "documentation", "design",
                     "structure", "project", "how", "what", "explain", "overview"}

    def execute(self, state: GraphState, registry, agent_id: str) -> GraphState:
        words = set(state.question.lower().split())
        route: List[str] = []

        wants_git = bool(words & self.GIT_KEYWORDS)
        wants_docs = bool(words & self.DOCS_KEYWORDS)

        if wants_git:
            route.append("git_context")
        if wants_docs:
            route.append("docs_retrieve")

        # If nothing matched, default to docs search
        if not route:
            route.append("docs_retrieve")

        route.append("answer_composer")
        state.route = route
        return state


class DocsRetrieveNode(Node):
    """Calls the docs search tool and stores results in state."""

    def execute(self, state: GraphState, registry, agent_id: str) -> GraphState:
        if registry is None:
            state.errors.append("No registry available for docs retrieval")
            return state
        result = registry.invoke(
            "docs.search_project_docs",
            agent_id,
            query=state.question,
            top_k=3,
        )
        state.tools_used.append("docs.search_project_docs")
        if result.success:
            state.retrieved_docs = result.data
        else:
            state.errors.append(f"docs search failed: {result.error}")
        return state


class GitContextNode(Node):
    """Calls the git branch tool and stores the result in state."""

    def execute(self, state: GraphState, registry, agent_id: str) -> GraphState:
        if registry is None:
            state.errors.append("No registry available for git context")
            return state
        result = registry.invoke("git.current_branch", agent_id)
        state.tools_used.append("git.current_branch")
        if result.success:
            state.git_branch = result.data
        else:
            state.errors.append(f"git branch failed: {result.error}")
        return state


class AnswerComposerNode(Node):
    """Composes a final answer from the collected state."""

    def execute(self, state: GraphState, registry, agent_id: str) -> GraphState:
        sections = []

        if state.git_branch:
            sections.append(f"**Git Branch:** {state.git_branch}")

        if state.retrieved_docs:
            sections.append("**Relevant Documentation:**")
            for i, doc in enumerate(state.retrieved_docs, 1):
                score = doc.get("score", 0)
                source = doc.get("source_path", "unknown")
                text = doc.get("text", "")
                # Truncate long chunks for display
                preview = text[:300] + "..." if len(text) > 300 else text
                sections.append(f"\n{i}. [{source}] (score: {score})\n   {preview}")

        if state.errors:
            sections.append("\n**Errors:**")
            for err in state.errors:
                sections.append(f"  - {err}")

        if not sections:
            sections.append("No relevant information found for your question.")

        state.final_answer = "\n".join(sections)
        return state
