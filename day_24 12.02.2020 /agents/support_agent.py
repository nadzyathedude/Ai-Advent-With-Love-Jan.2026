"""Product support agent — answers user questions using FAQ docs, CRM context,
and long-term conversation memory for personalized support."""

from dataclasses import dataclass, field
from typing import Any, Dict, List

from core.orchestration.graph import END, Graph, GraphState
from core.orchestration.nodes import Node
from core.registry.tool_registry import ToolRegistry


AGENT_ID = "support_agent"


@dataclass
class SupportState(GraphState):
    """Extended state for the support agent pipeline."""
    user_id: int = 0
    crm_context: Dict[str, Any] = field(default_factory=dict)
    docs_context: List[Dict[str, Any]] = field(default_factory=list)
    memory_context: Dict[str, Any] = field(default_factory=dict)
    analysis: str = ""


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------


class UserContextNode(Node):
    """Fetches user profile and tickets from CRM, plus searches for similar issues."""

    def execute(self, state: GraphState, registry, agent_id: str) -> GraphState:
        if not isinstance(state, SupportState):
            state.errors.append("UserContextNode requires SupportState")
            return state

        if registry is None:
            state.errors.append("No registry available for CRM lookup")
            return state

        if not state.user_id:
            state.errors.append("No user_id provided")
            return state

        # Get user profile and tickets
        result = registry.invoke(
            "crm.get_user_tickets", agent_id, user_id=state.user_id
        )
        state.tools_used.append("crm.get_user_tickets")

        user_data = {}
        if result.success:
            user_data = result.data
        else:
            state.errors.append(f"crm.get_user_tickets failed: {result.error}")

        # Search for similar issues based on the question
        similar_result = registry.invoke(
            "crm.search_similar_issues", agent_id, query=state.question
        )
        state.tools_used.append("crm.search_similar_issues")

        similar_issues = []
        if similar_result.success:
            similar_issues = similar_result.data
        else:
            state.errors.append(f"crm.search_similar_issues failed: {similar_result.error}")

        state.crm_context = {
            "user": user_data.get("user", {}),
            "tickets": user_data.get("tickets", []),
            "similar_issues": similar_issues,
        }

        return state


class MemoryRetrieveNode(Node):
    """Retrieves user's conversation history and past issues from memory."""

    def execute(self, state: GraphState, registry, agent_id: str) -> GraphState:
        if not isinstance(state, SupportState):
            state.errors.append("MemoryRetrieveNode requires SupportState")
            return state

        if registry is None:
            state.errors.append("No registry available for memory retrieval")
            return state

        if not state.user_id:
            return state

        # Get user history
        history_result = registry.invoke(
            "support_memory.get_user_history",
            agent_id,
            user_id=state.user_id,
            limit=5,
        )
        state.tools_used.append("support_memory.get_user_history")

        history_data = {}
        if history_result.success:
            history_data = history_result.data
        else:
            state.errors.append(f"support_memory.get_user_history failed: {history_result.error}")

        # Search for past issues related to the current question
        search_result = registry.invoke(
            "support_memory.search_past_issues",
            agent_id,
            user_id=state.user_id,
            query=state.question,
            limit=5,
        )
        state.tools_used.append("support_memory.search_past_issues")

        related_past = []
        if search_result.success:
            related_past = search_result.data
        else:
            state.errors.append(f"support_memory.search_past_issues failed: {search_result.error}")

        state.memory_context = {
            "recent_interactions": history_data.get("recent", []),
            "summary": history_data.get("summary"),
            "total_interactions": history_data.get("total_interactions", 0),
            "related_past_issues": related_past,
        }

        return state


class SupportDocsRetrieveNode(Node):
    """Searches FAQ documentation using BM25 for relevant answers."""

    def execute(self, state: GraphState, registry, agent_id: str) -> GraphState:
        if not isinstance(state, SupportState):
            state.errors.append("SupportDocsRetrieveNode requires SupportState")
            return state

        if registry is None:
            state.errors.append("No registry available for docs retrieval")
            return state

        result = registry.invoke(
            "docs.search_project_docs",
            agent_id,
            query=state.question,
            top_k=5,
        )
        state.tools_used.append("docs.search_project_docs")

        if result.success:
            state.docs_context = result.data
        else:
            state.errors.append(f"docs search failed: {result.error}")

        return state


class ContextMergeNode(Node):
    """Combines CRM context, docs context, and memory context into an analysis string."""

    def execute(self, state: GraphState, registry, agent_id: str) -> GraphState:
        if not isinstance(state, SupportState):
            state.errors.append("ContextMergeNode requires SupportState")
            return state

        lines = []

        # Analyze user context
        user = state.crm_context.get("user", {})
        tickets = state.crm_context.get("tickets", [])

        if user:
            plan = user.get("plan", "unknown")
            lines.append(f"User is on the {plan} plan.")
            open_tickets = [t for t in tickets if t.get("status") == "open"]
            in_progress = [t for t in tickets if t.get("status") == "in_progress"]
            if open_tickets:
                lines.append(f"User has {len(open_tickets)} open ticket(s).")
            if in_progress:
                lines.append(f"User has {len(in_progress)} in-progress ticket(s).")

            # Check if the question relates to an existing ticket
            for t in tickets:
                subject_lower = t.get("subject", "").lower()
                question_lower = state.question.lower()
                question_words = set(question_lower.split())
                subject_words = set(subject_lower.split())
                overlap = question_words & subject_words - {"my", "the", "a", "is", "to", "how", "do", "i", "does", "why"}
                if len(overlap) >= 2:
                    lines.append(
                        f"Possibly related to ticket #{t['id']}: \"{t['subject']}\" "
                        f"(status: {t['status']}, priority: {t['priority']})"
                    )

        # Analyze memory context
        total = state.memory_context.get("total_interactions", 0)
        if total > 0:
            lines.append(f"User has {total} previous support interaction(s) on record.")

            # Check summary for recurring issues
            summary_data = state.memory_context.get("summary")
            if summary_data:
                recurring = summary_data.get("recurring_issues", [])
                if recurring:
                    cats = ", ".join(f"{r['category']} ({r['count']}x)" for r in recurring[:3])
                    lines.append(f"Recurring issue categories: {cats}.")

            # Check related past issues
            related = state.memory_context.get("related_past_issues", [])
            if related:
                lines.append(f"Found {len(related)} related past interaction(s):")
                for past in related[:3]:
                    issue = past.get("issue_summary", past.get("user_message", ""))[:100]
                    status = past.get("resolution_status", "unknown")
                    lines.append(f"  - \"{issue}\" (status: {status})")

            # Check recent interactions for context
            recent = state.memory_context.get("recent_interactions", [])
            if recent:
                last = recent[0]
                last_cat = last.get("category", "general")
                last_msg = last.get("user_message", "")[:80]
                lines.append(f"Last interaction was about {last_cat}: \"{last_msg}\"")
        else:
            lines.append("This is the user's first support interaction.")

        # Analyze docs relevance
        if state.docs_context:
            top_doc = state.docs_context[0]
            if top_doc.get("score", 0) > 0:
                lines.append(
                    f"Found {len(state.docs_context)} relevant documentation section(s) "
                    f"(top score: {top_doc['score']})."
                )
            else:
                lines.append("No highly relevant documentation found for this query.")
        else:
            lines.append("No documentation results available.")

        # Check similar issues from CRM
        similar = state.crm_context.get("similar_issues", [])
        if similar:
            resolved = [s for s in similar if s.get("status") == "resolved"]
            lines.append(
                f"Found {len(similar)} similar issue(s) in CRM"
                + (f", {len(resolved)} resolved." if resolved else ".")
            )

        state.analysis = "\n".join(lines) if lines else "No analysis available."
        return state


class SupportAnswerComposerNode(Node):
    """Composes the final support answer from all gathered context."""

    def execute(self, state: GraphState, registry, agent_id: str) -> GraphState:
        if not isinstance(state, SupportState):
            state.errors.append("SupportAnswerComposerNode requires SupportState")
            return state

        sections = []

        # Header
        sections.append("# Support Response")
        sections.append("")

        # User Info
        user = state.crm_context.get("user", {})
        if user:
            sections.append("## User Info")
            sections.append(f"- **Name:** {user.get('name', 'Unknown')}")
            sections.append(f"- **Email:** {user.get('email', 'Unknown')}")
            sections.append(f"- **Plan:** {user.get('plan', 'Unknown')}")
            total = state.memory_context.get("total_interactions", 0)
            if total > 0:
                sections.append(f"- **Past Interactions:** {total}")
            sections.append("")

        # Conversation History Context
        related = state.memory_context.get("related_past_issues", [])
        recent = state.memory_context.get("recent_interactions", [])
        summary_data = state.memory_context.get("summary")

        if related or recent or summary_data:
            sections.append("## Conversation History")
            if summary_data and summary_data.get("summary"):
                sections.append(f"**Summary:** {summary_data['summary']}")
                sections.append("")
            if related:
                sections.append("**Related Past Issues:**")
                for past in related[:5]:
                    issue = past.get("issue_summary", past.get("user_message", ""))[:150]
                    status = past.get("resolution_status", "unknown")
                    cat = past.get("category", "general")
                    sections.append(f"- [{status.upper()}] ({cat}) {issue}")
                sections.append("")
            if recent and not related:
                sections.append("**Recent Interactions:**")
                for past in recent[:3]:
                    msg = past.get("user_message", "")[:100]
                    cat = past.get("category", "general")
                    sections.append(f"- ({cat}) {msg}")
                sections.append("")

        # Analysis
        if state.analysis:
            sections.append("## Analysis")
            sections.append(state.analysis)
            sections.append("")

        # Documentation
        if state.docs_context:
            sections.append("## Relevant Documentation")
            for i, doc in enumerate(state.docs_context, 1):
                score = doc.get("score", 0)
                if score <= 0:
                    continue
                source = doc.get("source_path", "unknown")
                text = doc.get("text", "")
                preview = text[:400] + "..." if len(text) > 400 else text
                sections.append(f"### {i}. [{source}] (score: {score})")
                sections.append(preview)
                sections.append("")

        # Similar Issues
        similar = state.crm_context.get("similar_issues", [])
        if similar:
            sections.append("## Similar Issues")
            for issue in similar[:5]:
                status_badge = f"[{issue['status'].upper()}]"
                sections.append(
                    f"- {status_badge} Ticket #{issue['id']}: {issue['subject']} "
                    f"(priority: {issue['priority']}, category: {issue['category']})"
                )
            sections.append("")

        # Errors
        if state.errors:
            sections.append("## Errors")
            for err in state.errors:
                sections.append(f"- {err}")
            sections.append("")

        state.final_answer = "\n".join(sections)
        return state


class MemoryStoreNode(Node):
    """Persists the current interaction to the conversation memory."""

    def execute(self, state: GraphState, registry, agent_id: str) -> GraphState:
        if not isinstance(state, SupportState):
            state.errors.append("MemoryStoreNode requires SupportState")
            return state

        if registry is None:
            return state

        if not state.user_id or not state.question:
            return state

        result = registry.invoke(
            "support_memory.store_interaction",
            agent_id,
            user_id=state.user_id,
            user_message=state.question,
            assistant_response=state.final_answer,
            issue_summary="",  # auto-detected
            category="",  # auto-detected
        )
        state.tools_used.append("support_memory.store_interaction")

        if not result.success:
            state.errors.append(f"Memory store failed: {result.error}")

        return state


# ---------------------------------------------------------------------------
# Backward-compatible alias
# ---------------------------------------------------------------------------

# IssueAnalysisNode is replaced by ContextMergeNode but kept as alias
IssueAnalysisNode = ContextMergeNode


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_support_graph() -> Graph:
    """Construct the support agent pipeline graph with conversation memory.

    Wiring:
        user_context -> memory_retrieve -> docs_retrieve -> context_merge
          -> answer_composer -> memory_store -> END
    """
    graph = Graph()

    graph.add_node("user_context", UserContextNode())
    graph.add_node("memory_retrieve", MemoryRetrieveNode())
    graph.add_node("docs_retrieve", SupportDocsRetrieveNode())
    graph.add_node("context_merge", ContextMergeNode())
    graph.add_node("answer_composer", SupportAnswerComposerNode())
    graph.add_node("memory_store", MemoryStoreNode())

    graph.set_entry_point("user_context")
    graph.add_edge("user_context", "memory_retrieve")
    graph.add_edge("memory_retrieve", "docs_retrieve")
    graph.add_edge("docs_retrieve", "context_merge")
    graph.add_edge("context_merge", "answer_composer")
    graph.add_edge("answer_composer", "memory_store")
    graph.add_edge("memory_store", END)

    return graph


def support_query(
    user_id: int,
    question: str,
    registry: ToolRegistry = None,
    debug: bool = False,
) -> str:
    """Run the support agent pipeline and return the formatted response."""
    graph = build_support_graph()
    state = SupportState(user_id=user_id, question=question)

    state = graph.run(state, registry=registry, agent_id=AGENT_ID)

    if debug:
        lines = [
            f"[DEBUG] Nodes executed: {state.nodes_executed}",
            f"[DEBUG] Tools used: {state.tools_used}",
            f"[DEBUG] Errors: {state.errors}",
            f"[DEBUG] CRM user: {state.crm_context.get('user', {}).get('name', 'N/A')}",
            f"[DEBUG] Docs results: {len(state.docs_context)}",
            f"[DEBUG] Memory interactions: {state.memory_context.get('total_interactions', 0)}",
            f"[DEBUG] Analysis: {state.analysis[:200]}",
            "",
        ]
        return "\n".join(lines) + state.final_answer

    return state.final_answer
