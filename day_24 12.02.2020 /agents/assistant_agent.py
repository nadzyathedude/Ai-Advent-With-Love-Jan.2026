"""Unified AI project assistant — combines RAG knowledge retrieval, MCP service
integrations, task management CRUD, and a priority recommendation engine.

All orchestrated via the existing graph engine with intent-based routing.
Zero external AI dependencies — fully deterministic.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.orchestration.graph import END, Graph, GraphState
from core.orchestration.nodes import Node
from core.registry.tool_registry import ToolRegistry

from llm_router import detect_intent
from priority_engine import get_recommendation, prioritize_tasks


AGENT_ID = "assistant_agent"


# ---------------------------------------------------------------------------
# Extended state
# ---------------------------------------------------------------------------


@dataclass
class AssistantState(GraphState):
    """Extended state for the unified assistant pipeline."""
    intent: str = ""
    intent_scores: Dict[str, float] = field(default_factory=dict)
    rag_results: List[Dict[str, Any]] = field(default_factory=list)
    task_result: Dict[str, Any] = field(default_factory=dict)
    task_list: List[Dict[str, Any]] = field(default_factory=list)
    project_status: Dict[str, Any] = field(default_factory=dict)
    priority_results: List[Dict[str, Any]] = field(default_factory=list)
    priority_recommendation: str = ""
    mcp_results: Dict[str, Any] = field(default_factory=dict)
    # Parsed task fields for task_create intent
    parsed_task_title: str = ""
    parsed_task_description: str = ""
    parsed_task_priority: str = "medium"
    parsed_task_effort: str = "medium"
    parsed_task_due_date: str = ""
    parsed_task_tags: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------


class IntentRouterNode(Node):
    """Detects intent and sets the execution route based on keyword scoring."""

    def execute(self, state: GraphState, registry, agent_id: str) -> GraphState:
        if not isinstance(state, AssistantState):
            state.errors.append("IntentRouterNode requires AssistantState")
            return state

        intent, scores = detect_intent(state.question)
        state.intent = intent
        state.intent_scores = scores

        route: List[str] = []

        if intent == "knowledge":
            route.append("rag_retrieve")
        elif intent == "task_create":
            route.append("task_parse")
            route.append("task_create")
        elif intent == "status":
            route.append("status_fetch")
        elif intent == "prioritize":
            route.append("status_fetch")
            route.append("priority_compute")
        elif intent == "combined":
            # Route to all relevant sub-intents
            if "knowledge" in scores:
                route.append("rag_retrieve")
            if "task_create" in scores:
                route.append("task_parse")
                route.append("task_create")
            if "status" in scores or "prioritize" in scores:
                route.append("status_fetch")
            if "prioritize" in scores:
                route.append("priority_compute")

        # Always fetch MCP context for enrichment
        route.append("mcp_context")
        route.append("response_composer")

        state.route = route
        return state


class RAGRetrieveNode(Node):
    """Searches project documentation using BM25."""

    def execute(self, state: GraphState, registry, agent_id: str) -> GraphState:
        if not isinstance(state, AssistantState):
            state.errors.append("RAGRetrieveNode requires AssistantState")
            return state

        if registry is None:
            state.errors.append("No registry available for docs retrieval")
            return state

        result = registry.invoke(
            "docs.search_project_docs", agent_id, query=state.question, top_k=5
        )
        state.tools_used.append("docs.search_project_docs")

        if result.success:
            state.rag_results = result.data
        else:
            state.errors.append(f"docs search failed: {result.error}")

        return state


class TaskParseNode(Node):
    """Parses task creation details from the user's question."""

    PRIORITY_KEYWORDS = {
        "critical": "critical", "urgent": "critical",
        "high": "high", "important": "high",
        "medium": "medium", "normal": "medium",
        "low": "low", "minor": "low",
    }

    EFFORT_KEYWORDS = {
        "tiny": "small", "small": "small", "quick": "small",
        "medium": "medium", "moderate": "medium",
        "large": "large", "big": "large",
        "xlarge": "xlarge", "huge": "xlarge", "massive": "xlarge",
    }

    def execute(self, state: GraphState, registry, agent_id: str) -> GraphState:
        if not isinstance(state, AssistantState):
            state.errors.append("TaskParseNode requires AssistantState")
            return state

        q = state.question
        words = q.lower().split()

        # Extract priority
        for word in words:
            if word in self.PRIORITY_KEYWORDS:
                state.parsed_task_priority = self.PRIORITY_KEYWORDS[word]
                break

        # Extract effort
        for word in words:
            if word in self.EFFORT_KEYWORDS:
                state.parsed_task_effort = self.EFFORT_KEYWORDS[word]
                break

        # Extract title: strip common prefixes
        title = q
        strip_prefixes = [
            "create a ", "create ", "add a ", "add ", "new task ",
            "new ", "task to ", "task ",
        ]
        title_lower = title.lower()
        for prefix in strip_prefixes:
            if title_lower.startswith(prefix):
                title = title[len(prefix):]
                title_lower = title.lower()

        # Strip priority/effort words from the title
        for kw in list(self.PRIORITY_KEYWORDS.keys()) + list(self.EFFORT_KEYWORDS.keys()):
            # Only strip standalone words
            title = " ".join(w for w in title.split() if w.lower() != kw)

        # Strip "priority" and "task" from title
        title = " ".join(w for w in title.split() if w.lower() not in ("priority", "task"))

        state.parsed_task_title = title.strip() or "Untitled task"
        state.parsed_task_description = q  # Original question as description

        return state


class TaskCreateNode(Node):
    """Creates a task using the parsed fields."""

    def execute(self, state: GraphState, registry, agent_id: str) -> GraphState:
        if not isinstance(state, AssistantState):
            state.errors.append("TaskCreateNode requires AssistantState")
            return state

        if registry is None:
            state.errors.append("No registry available for task creation")
            return state

        result = registry.invoke(
            "task.create", agent_id,
            title=state.parsed_task_title,
            description=state.parsed_task_description,
            priority=state.parsed_task_priority,
            effort=state.parsed_task_effort,
            due_date=state.parsed_task_due_date,
            tags=state.parsed_task_tags,
        )
        state.tools_used.append("task.create")

        if result.success:
            state.task_result = result.data
        else:
            state.errors.append(f"task creation failed: {result.error}")

        return state


class StatusFetchNode(Node):
    """Fetches task list and project status."""

    def execute(self, state: GraphState, registry, agent_id: str) -> GraphState:
        if not isinstance(state, AssistantState):
            state.errors.append("StatusFetchNode requires AssistantState")
            return state

        if registry is None:
            state.errors.append("No registry available for status fetch")
            return state

        # Get all tasks
        list_result = registry.invoke("task.list", agent_id, limit=50)
        state.tools_used.append("task.list")

        if list_result.success:
            state.task_list = list_result.data
        else:
            state.errors.append(f"task list failed: {list_result.error}")

        # Get project status
        status_result = registry.invoke("task.project_status", agent_id)
        state.tools_used.append("task.project_status")

        if status_result.success:
            state.project_status = status_result.data
        else:
            state.errors.append(f"project status failed: {status_result.error}")

        return state


class PriorityComputeNode(Node):
    """Computes priority scores and recommendation from the task list."""

    def execute(self, state: GraphState, registry, agent_id: str) -> GraphState:
        if not isinstance(state, AssistantState):
            state.errors.append("PriorityComputeNode requires AssistantState")
            return state

        if not state.task_list:
            state.priority_recommendation = "No tasks available to prioritize."
            return state

        scored = prioritize_tasks(state.task_list)
        state.priority_results = scored
        state.priority_recommendation = get_recommendation(scored)

        return state


class MCPContextNode(Node):
    """Fetches contextual data from MCP services (notifications, metrics)."""

    def execute(self, state: GraphState, registry, agent_id: str) -> GraphState:
        if not isinstance(state, AssistantState):
            state.errors.append("MCPContextNode requires AssistantState")
            return state

        if registry is None:
            return state

        mcp_data = {}

        # Get unread notifications
        notif_result = registry.invoke(
            "mcp.call_service", agent_id,
            service="notifications", action="unread", params={},
        )
        state.tools_used.append("mcp.call_service")
        if notif_result.success:
            mcp_data["notifications"] = notif_result.data

        # Get development metrics
        metrics_result = registry.invoke(
            "mcp.call_service", agent_id,
            service="metrics", action="summary", params={},
        )
        state.tools_used.append("mcp.call_service")
        if metrics_result.success:
            mcp_data["metrics"] = metrics_result.data

        state.mcp_results = mcp_data
        return state


class ResponseComposerNode(Node):
    """Composes the final response from all gathered context."""

    def execute(self, state: GraphState, registry, agent_id: str) -> GraphState:
        if not isinstance(state, AssistantState):
            state.errors.append("ResponseComposerNode requires AssistantState")
            return state

        sections = []
        sections.append("# Assistant Response")
        sections.append("")

        # Intent info
        intent_label = state.intent.replace("_", " ").title()
        sections.append(f"**Intent:** {intent_label}")
        sections.append("")

        # Knowledge / RAG results
        if state.rag_results:
            sections.append("## Relevant Documentation")
            for i, doc in enumerate(state.rag_results, 1):
                score = doc.get("score", 0)
                if score <= 0:
                    continue
                source = doc.get("source_path", "unknown")
                text = doc.get("text", "")
                preview = text[:400] + "..." if len(text) > 400 else text
                sections.append(f"### {i}. [{source}] (score: {score})")
                sections.append(preview)
                sections.append("")

        # Task creation result
        if state.task_result:
            task = state.task_result
            sections.append("## Task Created")
            sections.append(f"- **ID:** {task.get('id')}")
            sections.append(f"- **Title:** {task.get('title')}")
            sections.append(f"- **Priority:** {task.get('priority')}")
            sections.append(f"- **Effort:** {task.get('effort')}")
            sections.append(f"- **Status:** {task.get('status')}")
            if task.get("due_date"):
                sections.append(f"- **Due:** {task['due_date']}")
            sections.append("")

        # Project status
        if state.project_status:
            ps = state.project_status
            sections.append("## Project Status")
            sections.append(f"- **Total tasks:** {ps.get('total', 0)}")
            by_status = ps.get("by_status", {})
            if by_status:
                status_parts = [f"{k}: {v}" for k, v in sorted(by_status.items())]
                sections.append(f"- **By status:** {', '.join(status_parts)}")
            by_prio = ps.get("by_priority", {})
            if by_prio:
                prio_parts = [f"{k}: {v}" for k, v in sorted(by_prio.items())]
                sections.append(f"- **By priority (active):** {', '.join(prio_parts)}")
            blocked = ps.get("blocked", [])
            if blocked:
                sections.append(f"- **Blocked:** {len(blocked)} task(s)")
                for b in blocked:
                    sections.append(f"  - #{b['id']} {b['title']}: {b['blocked_by']}")
            overdue = ps.get("overdue", [])
            if overdue:
                sections.append(f"- **Overdue:** {len(overdue)} task(s)")
                for o in overdue:
                    sections.append(f"  - #{o['id']} {o['title']} (due: {o['due_date']})")
            sections.append("")

        # Priority recommendations
        if state.priority_recommendation:
            sections.append(state.priority_recommendation)
            sections.append("")

        # MCP context
        notifs = state.mcp_results.get("notifications")
        metrics = state.mcp_results.get("metrics")
        if notifs or metrics:
            sections.append("## Context")
            if notifs:
                count = notifs.get("count", 0)
                sections.append(f"- **Notifications:** {count} unread")
                for item in notifs.get("items", [])[:3]:
                    sections.append(f"  - [{item['type']}] {item['message']} ({item['age']})")
            if metrics:
                sections.append(
                    f"- **Week metrics:** {metrics.get('commits', 0)} commits, "
                    f"{metrics.get('prs_merged', 0)} PRs merged, "
                    f"{metrics.get('issues_closed', 0)} issues closed"
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


# ---------------------------------------------------------------------------
# Conditional routing
# ---------------------------------------------------------------------------


def route_next(state: GraphState) -> str:
    """Pick the first node in state.route not yet executed."""
    for node_name in state.route:
        if node_name not in state.nodes_executed:
            return node_name
    return END


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_assistant_graph() -> Graph:
    """Construct the assistant agent graph with intent-based conditional routing.

    Wiring:
        intent_router -> conditional -> [rag_retrieve, task_parse, task_create,
                                         status_fetch, priority_compute, mcp_context]
                                      -> response_composer -> END
    """
    graph = Graph()

    graph.add_node("intent_router", IntentRouterNode())
    graph.add_node("rag_retrieve", RAGRetrieveNode())
    graph.add_node("task_parse", TaskParseNode())
    graph.add_node("task_create", TaskCreateNode())
    graph.add_node("status_fetch", StatusFetchNode())
    graph.add_node("priority_compute", PriorityComputeNode())
    graph.add_node("mcp_context", MCPContextNode())
    graph.add_node("response_composer", ResponseComposerNode())

    graph.set_entry_point("intent_router")

    # All nodes use conditional routing except response_composer
    graph.add_conditional_edges("intent_router", route_next)
    graph.add_conditional_edges("rag_retrieve", route_next)
    graph.add_conditional_edges("task_parse", route_next)
    graph.add_conditional_edges("task_create", route_next)
    graph.add_conditional_edges("status_fetch", route_next)
    graph.add_conditional_edges("priority_compute", route_next)
    graph.add_conditional_edges("mcp_context", route_next)
    graph.add_edge("response_composer", END)

    return graph


def assistant_query(
    question: str,
    registry: ToolRegistry = None,
    debug: bool = False,
) -> str:
    """Run the assistant pipeline and return the formatted response."""
    graph = build_assistant_graph()
    state = AssistantState(question=question)

    state = graph.run(state, registry=registry, agent_id=AGENT_ID)

    if debug:
        lines = [
            f"[DEBUG] Intent: {state.intent}",
            f"[DEBUG] Intent scores: {state.intent_scores}",
            f"[DEBUG] Nodes executed: {state.nodes_executed}",
            f"[DEBUG] Tools used: {state.tools_used}",
            f"[DEBUG] Route: {state.route}",
            f"[DEBUG] Errors: {state.errors}",
            "",
        ]
        return "\n".join(lines) + state.final_answer

    return state.final_answer
