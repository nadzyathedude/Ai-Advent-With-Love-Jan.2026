"""Tests for the unified assistant agent — intent detection, nodes, graph wiring, full pipeline."""

import unittest
from unittest.mock import MagicMock

from core.orchestration.graph import END
from core.registry.tool_registry import ToolResult
from core.registry.permissions import PermissionChecker

from llm_router import detect_intent

from agents.assistant_agent import (
    AssistantState,
    IntentRouterNode,
    RAGRetrieveNode,
    TaskParseNode,
    TaskCreateNode,
    StatusFetchNode,
    PriorityComputeNode,
    MCPContextNode,
    ResponseComposerNode,
    build_assistant_graph,
    assistant_query,
    route_next,
)


# ---------------------------------------------------------------------------
# Intent detection tests
# ---------------------------------------------------------------------------


class TestIntentDetection(unittest.TestCase):
    """Test the keyword-based intent router."""

    def test_knowledge_intent(self):
        intent, _ = detect_intent("What is the project architecture?")
        self.assertIn(intent, ("knowledge", "combined"))

    def test_task_create_intent(self):
        intent, _ = detect_intent("Create a new task to fix the login bug")
        self.assertIn(intent, ("task_create", "combined"))

    def test_status_intent(self):
        intent, _ = detect_intent("Show the current project status")
        self.assertIn(intent, ("status", "combined"))

    def test_prioritize_intent(self):
        intent, _ = detect_intent("What should I focus on next? Show priorities")
        self.assertIn(intent, ("prioritize", "combined"))

    def test_combined_intent(self):
        intent, scores = detect_intent("Show high priority tasks and suggest what to do first")
        self.assertIn(intent, ("prioritize", "combined", "status"))

    def test_default_to_knowledge(self):
        intent, _ = detect_intent("hello world")
        self.assertEqual(intent, "knowledge")

    def test_scores_returned(self):
        _, scores = detect_intent("Create a new task")
        self.assertIsInstance(scores, dict)


# ---------------------------------------------------------------------------
# Node tests
# ---------------------------------------------------------------------------


class TestIntentRouterNode(unittest.TestCase):
    """Test the IntentRouterNode."""

    def test_knowledge_route(self):
        state = AssistantState(question="What is the project architecture?")
        node = IntentRouterNode()
        state = node.execute(state, None, "test")
        self.assertIn("rag_retrieve", state.route)
        self.assertIn("response_composer", state.route)

    def test_task_create_route(self):
        state = AssistantState(question="Create a new task to fix bugs")
        node = IntentRouterNode()
        state = node.execute(state, None, "test")
        self.assertIn("task_parse", state.route)
        self.assertIn("task_create", state.route)
        self.assertIn("response_composer", state.route)

    def test_status_route(self):
        state = AssistantState(question="Show the current project status")
        node = IntentRouterNode()
        state = node.execute(state, None, "test")
        self.assertIn("status_fetch", state.route)

    def test_prioritize_route(self):
        state = AssistantState(question="What should I prioritize next?")
        node = IntentRouterNode()
        state = node.execute(state, None, "test")
        self.assertIn("status_fetch", state.route)
        self.assertIn("priority_compute", state.route)

    def test_mcp_context_always_included(self):
        state = AssistantState(question="hello world")
        node = IntentRouterNode()
        state = node.execute(state, None, "test")
        self.assertIn("mcp_context", state.route)

    def test_wrong_state_type(self):
        from core.orchestration.graph import GraphState
        state = GraphState(question="test")
        node = IntentRouterNode()
        state = node.execute(state, None, "test")
        self.assertIn("requires AssistantState", state.errors[0])


class TestRAGRetrieveNode(unittest.TestCase):
    """Test the RAGRetrieveNode."""

    def _mock_registry(self):
        mock = MagicMock()
        mock.invoke.return_value = ToolResult(success=True, data=[
            {"text": "Architecture info", "source_path": "docs/architecture.md", "score": 2.5},
        ])
        return mock

    def test_retrieves_docs(self):
        state = AssistantState(question="What is the architecture?")
        registry = self._mock_registry()
        node = RAGRetrieveNode()
        state = node.execute(state, registry, "assistant_agent")
        self.assertEqual(len(state.rag_results), 1)
        self.assertIn("docs.search_project_docs", state.tools_used)

    def test_no_registry(self):
        state = AssistantState(question="test")
        node = RAGRetrieveNode()
        state = node.execute(state, None, "test")
        self.assertIn("No registry available", state.errors[0])


class TestTaskParseNode(unittest.TestCase):
    """Test the TaskParseNode."""

    def test_parses_priority(self):
        state = AssistantState(question="Create a high priority task to fix login bug")
        node = TaskParseNode()
        state = node.execute(state, None, "test")
        self.assertEqual(state.parsed_task_priority, "high")

    def test_parses_critical(self):
        state = AssistantState(question="Create urgent task for server outage")
        node = TaskParseNode()
        state = node.execute(state, None, "test")
        self.assertEqual(state.parsed_task_priority, "critical")

    def test_strips_prefix(self):
        state = AssistantState(question="Create a task to fix the login page")
        node = TaskParseNode()
        state = node.execute(state, None, "test")
        self.assertNotIn("Create a", state.parsed_task_title)
        self.assertIn("fix", state.parsed_task_title.lower())

    def test_default_priority(self):
        state = AssistantState(question="Add a task for documentation")
        node = TaskParseNode()
        state = node.execute(state, None, "test")
        self.assertEqual(state.parsed_task_priority, "medium")

    def test_description_is_original_question(self):
        q = "Create a new task to improve performance"
        state = AssistantState(question=q)
        node = TaskParseNode()
        state = node.execute(state, None, "test")
        self.assertEqual(state.parsed_task_description, q)


class TestTaskCreateNode(unittest.TestCase):
    """Test the TaskCreateNode."""

    def _mock_registry(self):
        mock = MagicMock()
        mock.invoke.return_value = ToolResult(success=True, data={
            "id": 99, "title": "Fix login", "priority": "high",
            "effort": "medium", "status": "todo",
        })
        return mock

    def test_creates_task(self):
        state = AssistantState(question="Create task")
        state.parsed_task_title = "Fix login"
        state.parsed_task_priority = "high"
        registry = self._mock_registry()
        node = TaskCreateNode()
        state = node.execute(state, registry, "assistant_agent")
        self.assertEqual(state.task_result["id"], 99)
        self.assertIn("task.create", state.tools_used)

    def test_no_registry(self):
        state = AssistantState(question="test")
        node = TaskCreateNode()
        state = node.execute(state, None, "test")
        self.assertIn("No registry available", state.errors[0])


class TestStatusFetchNode(unittest.TestCase):
    """Test the StatusFetchNode."""

    def _mock_registry(self):
        mock = MagicMock()

        def mock_invoke(tool_name, agent_id, **kwargs):
            if tool_name == "task.list":
                return ToolResult(success=True, data=[
                    {"id": 1, "title": "Task 1", "status": "todo", "priority": "high"},
                    {"id": 2, "title": "Task 2", "status": "done", "priority": "low"},
                ])
            if tool_name == "task.project_status":
                return ToolResult(success=True, data={
                    "total": 2, "by_status": {"todo": 1, "done": 1},
                    "by_priority": {"high": 1}, "blocked": [], "overdue": [],
                })
            return ToolResult(success=False, error="unknown")

        mock.invoke.side_effect = mock_invoke
        return mock

    def test_fetches_status(self):
        state = AssistantState(question="status")
        registry = self._mock_registry()
        node = StatusFetchNode()
        state = node.execute(state, registry, "assistant_agent")
        self.assertEqual(len(state.task_list), 2)
        self.assertEqual(state.project_status["total"], 2)
        self.assertIn("task.list", state.tools_used)
        self.assertIn("task.project_status", state.tools_used)

    def test_no_registry(self):
        state = AssistantState(question="test")
        node = StatusFetchNode()
        state = node.execute(state, None, "test")
        self.assertIn("No registry available", state.errors[0])


class TestPriorityComputeNode(unittest.TestCase):
    """Test the PriorityComputeNode."""

    def test_computes_priority(self):
        state = AssistantState(question="priorities")
        state.task_list = [
            {"id": 1, "title": "Urgent", "status": "todo", "priority": "critical",
             "effort": "small", "due_date": None, "depends_on": []},
            {"id": 2, "title": "Low", "status": "todo", "priority": "low",
             "effort": "large", "due_date": None, "depends_on": []},
        ]
        node = PriorityComputeNode()
        state = node.execute(state, None, "test")
        self.assertGreater(len(state.priority_results), 0)
        self.assertIn("Priority Recommendations", state.priority_recommendation)

    def test_empty_task_list(self):
        state = AssistantState(question="priorities")
        state.task_list = []
        node = PriorityComputeNode()
        state = node.execute(state, None, "test")
        self.assertIn("No tasks", state.priority_recommendation)


class TestMCPContextNode(unittest.TestCase):
    """Test the MCPContextNode."""

    def _mock_registry(self):
        mock = MagicMock()

        def mock_invoke(tool_name, agent_id, **kwargs):
            if tool_name == "mcp.call_service" and kwargs.get("service") == "notifications":
                return ToolResult(success=True, data={
                    "count": 2, "items": [
                        {"type": "pr_review", "message": "PR approved", "age": "1h"},
                    ],
                })
            if tool_name == "mcp.call_service" and kwargs.get("service") == "metrics":
                return ToolResult(success=True, data={
                    "commits": 10, "prs_merged": 3, "issues_closed": 5,
                })
            return ToolResult(success=False, error="unknown")

        mock.invoke.side_effect = mock_invoke
        return mock

    def test_fetches_mcp(self):
        state = AssistantState(question="test")
        registry = self._mock_registry()
        node = MCPContextNode()
        state = node.execute(state, registry, "assistant_agent")
        self.assertIn("notifications", state.mcp_results)
        self.assertIn("metrics", state.mcp_results)

    def test_no_registry(self):
        state = AssistantState(question="test")
        node = MCPContextNode()
        state = node.execute(state, None, "test")
        self.assertEqual(state.mcp_results, {})


class TestResponseComposerNode(unittest.TestCase):
    """Test the ResponseComposerNode."""

    def test_composes_knowledge_response(self):
        state = AssistantState(question="architecture", intent="knowledge")
        state.rag_results = [
            {"text": "Architecture info", "source_path": "docs/arch.md", "score": 2.5},
        ]
        state.mcp_results = {}
        node = ResponseComposerNode()
        state = node.execute(state, None, "test")
        self.assertIn("Assistant Response", state.final_answer)
        self.assertIn("Documentation", state.final_answer)
        self.assertIn("Architecture info", state.final_answer)

    def test_composes_task_creation_response(self):
        state = AssistantState(question="create task", intent="task_create")
        state.task_result = {"id": 1, "title": "Test", "priority": "high",
                             "effort": "small", "status": "todo"}
        state.mcp_results = {}
        node = ResponseComposerNode()
        state = node.execute(state, None, "test")
        self.assertIn("Task Created", state.final_answer)
        self.assertIn("Test", state.final_answer)

    def test_composes_status_response(self):
        state = AssistantState(question="status", intent="status")
        state.project_status = {
            "total": 5, "by_status": {"todo": 3, "done": 2},
            "by_priority": {"high": 2, "medium": 1},
            "blocked": [], "overdue": [],
        }
        state.mcp_results = {}
        node = ResponseComposerNode()
        state = node.execute(state, None, "test")
        self.assertIn("Project Status", state.final_answer)
        self.assertIn("5", state.final_answer)

    def test_includes_errors(self):
        state = AssistantState(question="test", intent="knowledge")
        state.errors = ["Something failed"]
        state.mcp_results = {}
        node = ResponseComposerNode()
        state = node.execute(state, None, "test")
        self.assertIn("Errors", state.final_answer)
        self.assertIn("Something failed", state.final_answer)


# ---------------------------------------------------------------------------
# Graph structure tests
# ---------------------------------------------------------------------------


class TestAssistantGraph(unittest.TestCase):
    """Test the assistant graph structure."""

    def test_entry_point(self):
        graph = build_assistant_graph()
        self.assertEqual(graph._entry_point, "intent_router")

    def test_all_nodes_registered(self):
        graph = build_assistant_graph()
        expected = [
            "intent_router", "rag_retrieve", "task_parse", "task_create",
            "status_fetch", "priority_compute", "mcp_context", "response_composer",
        ]
        for name in expected:
            self.assertIn(name, graph._nodes)

    def test_response_composer_leads_to_end(self):
        graph = build_assistant_graph()
        self.assertEqual(graph._edges["response_composer"], END)

    def test_conditional_edges_set(self):
        graph = build_assistant_graph()
        for name in ["intent_router", "rag_retrieve", "task_parse",
                      "task_create", "status_fetch", "priority_compute", "mcp_context"]:
            self.assertIn(name, graph._conditional_edges)


class TestRouteNext(unittest.TestCase):
    """Test the route_next function."""

    def test_picks_first_unexecuted(self):
        state = AssistantState(question="test")
        state.route = ["rag_retrieve", "mcp_context", "response_composer"]
        state.nodes_executed = ["intent_router"]
        result = route_next(state)
        self.assertEqual(result, "rag_retrieve")

    def test_skips_executed(self):
        state = AssistantState(question="test")
        state.route = ["rag_retrieve", "mcp_context", "response_composer"]
        state.nodes_executed = ["intent_router", "rag_retrieve"]
        result = route_next(state)
        self.assertEqual(result, "mcp_context")

    def test_returns_end_when_done(self):
        state = AssistantState(question="test")
        state.route = ["rag_retrieve"]
        state.nodes_executed = ["intent_router", "rag_retrieve"]
        result = route_next(state)
        self.assertEqual(result, END)


# ---------------------------------------------------------------------------
# Full pipeline tests
# ---------------------------------------------------------------------------


class TestAssistantPipeline(unittest.TestCase):
    """Test the full assistant pipeline."""

    def _make_mock(self):
        mock = MagicMock()

        def mock_invoke(tool_name, agent_id, **kwargs):
            if tool_name == "docs.search_project_docs":
                return ToolResult(success=True, data=[
                    {"text": "Architecture docs", "source_path": "docs/arch.md", "score": 2.0},
                ])
            if tool_name == "task.create":
                return ToolResult(success=True, data={
                    "id": 99, "title": kwargs.get("title", ""),
                    "priority": kwargs.get("priority", "medium"),
                    "effort": kwargs.get("effort", "medium"), "status": "todo",
                })
            if tool_name == "task.list":
                return ToolResult(success=True, data=[
                    {"id": 1, "title": "Task 1", "status": "todo",
                     "priority": "critical", "effort": "small",
                     "due_date": None, "depends_on": []},
                ])
            if tool_name == "task.project_status":
                return ToolResult(success=True, data={
                    "total": 1, "by_status": {"todo": 1},
                    "by_priority": {"critical": 1},
                    "blocked": [], "overdue": [],
                })
            if tool_name == "mcp.call_service":
                service = kwargs.get("service", "")
                if service == "notifications":
                    return ToolResult(success=True, data={
                        "count": 1, "items": [
                            {"type": "ci", "message": "Build passed", "age": "1h"},
                        ],
                    })
                if service == "metrics":
                    return ToolResult(success=True, data={
                        "commits": 10, "prs_merged": 2, "issues_closed": 3,
                    })
            return ToolResult(success=False, error="unknown")

        mock.invoke.side_effect = mock_invoke
        return mock

    def test_knowledge_pipeline(self):
        mock = self._make_mock()
        graph = build_assistant_graph()
        state = AssistantState(question="What is the project architecture?")
        state = graph.run(state, registry=mock, agent_id="assistant_agent")

        self.assertIn("intent_router", state.nodes_executed)
        self.assertIn("rag_retrieve", state.nodes_executed)
        self.assertIn("response_composer", state.nodes_executed)
        self.assertIn("Assistant Response", state.final_answer)
        self.assertIn("Documentation", state.final_answer)

    def test_task_create_pipeline(self):
        mock = self._make_mock()
        graph = build_assistant_graph()
        state = AssistantState(question="Create a high priority task to fix login bug")
        state = graph.run(state, registry=mock, agent_id="assistant_agent")

        self.assertIn("task_parse", state.nodes_executed)
        self.assertIn("task_create", state.nodes_executed)
        self.assertIn("response_composer", state.nodes_executed)
        self.assertIn("Task Created", state.final_answer)

    def test_status_pipeline(self):
        mock = self._make_mock()
        graph = build_assistant_graph()
        state = AssistantState(question="Show the current project status report")
        state = graph.run(state, registry=mock, agent_id="assistant_agent")

        self.assertIn("status_fetch", state.nodes_executed)
        self.assertIn("response_composer", state.nodes_executed)
        self.assertIn("Project Status", state.final_answer)

    def test_prioritize_pipeline(self):
        mock = self._make_mock()
        graph = build_assistant_graph()
        state = AssistantState(question="What should I prioritize next?")
        state = graph.run(state, registry=mock, agent_id="assistant_agent")

        self.assertIn("status_fetch", state.nodes_executed)
        self.assertIn("priority_compute", state.nodes_executed)
        self.assertIn("response_composer", state.nodes_executed)
        self.assertIn("Priority Recommendations", state.final_answer)

    def test_mcp_context_always_runs(self):
        mock = self._make_mock()
        graph = build_assistant_graph()
        state = AssistantState(question="What is the architecture?")
        state = graph.run(state, registry=mock, agent_id="assistant_agent")
        self.assertIn("mcp_context", state.nodes_executed)

    def test_assistant_query_entry_point(self):
        mock = self._make_mock()
        result = assistant_query("What is the architecture?", registry=mock)
        self.assertIn("Assistant Response", result)

    def test_assistant_query_debug_mode(self):
        mock = self._make_mock()
        result = assistant_query("status", registry=mock, debug=True)
        self.assertIn("[DEBUG]", result)
        self.assertIn("Intent:", result)
        self.assertIn("Nodes executed", result)

    def test_pipeline_handles_errors(self):
        mock = MagicMock()
        mock.invoke.return_value = ToolResult(success=False, error="service down")

        graph = build_assistant_graph()
        state = AssistantState(question="What is the architecture?")
        state = graph.run(state, registry=mock, agent_id="assistant_agent")

        self.assertIn("response_composer", state.nodes_executed)
        self.assertIn("Assistant Response", state.final_answer)
        self.assertTrue(len(state.errors) > 0)


# ---------------------------------------------------------------------------
# Permission tests
# ---------------------------------------------------------------------------


class TestAssistantPermissions(unittest.TestCase):
    """Test that assistant agent has correct permissions configured."""

    def test_has_docs_read(self):
        checker = PermissionChecker()
        self.assertTrue(checker.check("assistant_agent", ["docs:read"]))

    def test_has_task_read(self):
        checker = PermissionChecker()
        self.assertTrue(checker.check("assistant_agent", ["task:read"]))

    def test_has_task_write(self):
        checker = PermissionChecker()
        self.assertTrue(checker.check("assistant_agent", ["task:write"]))

    def test_has_mcp_read(self):
        checker = PermissionChecker()
        self.assertTrue(checker.check("assistant_agent", ["mcp:read"]))

    def test_has_all_permissions(self):
        checker = PermissionChecker()
        self.assertTrue(checker.check("assistant_agent", [
            "docs:read", "task:read", "task:write", "mcp:read",
        ]))

    def test_cannot_access_crm(self):
        checker = PermissionChecker()
        self.assertFalse(checker.check("assistant_agent", ["crm:read"]))

    def test_cannot_access_pr(self):
        checker = PermissionChecker()
        self.assertFalse(checker.check("assistant_agent", ["pr:read"]))

    def test_cannot_access_support_memory(self):
        checker = PermissionChecker()
        self.assertFalse(checker.check("assistant_agent", ["support_memory:read"]))


if __name__ == "__main__":
    unittest.main()
