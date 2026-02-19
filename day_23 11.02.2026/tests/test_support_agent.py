"""Tests for the product support agent system with conversation memory."""

import os
import unittest
from unittest.mock import MagicMock

from core.orchestration.graph import END
from core.registry.tool_registry import ToolRegistry, ToolResult
from core.registry.permissions import PermissionChecker, PermissionDeniedError

from agents.support_agent import (
    SupportState,
    UserContextNode,
    MemoryRetrieveNode,
    SupportDocsRetrieveNode,
    ContextMergeNode,
    IssueAnalysisNode,
    SupportAnswerComposerNode,
    MemoryStoreNode,
    build_support_graph,
    support_query,
)
from plugins.crm.tool_crm import (
    CrmDB,
    GetUserTicketsTool,
    GetTicketDetailsTool,
    SearchSimilarIssuesTool,
    reset_db as reset_crm_db,
)


class TestCrmDB(unittest.TestCase):
    """Test the CRM SQLite store."""

    def setUp(self):
        self.db = CrmDB(":memory:")

    def tearDown(self):
        self.db.close()

    def test_sample_data_populated(self):
        """Verify sample users and tickets are inserted."""
        row = self.db._conn.execute("SELECT COUNT(*) FROM users").fetchone()
        self.assertEqual(row[0], 8)
        row = self.db._conn.execute("SELECT COUNT(*) FROM tickets").fetchone()
        self.assertEqual(row[0], 18)
        row = self.db._conn.execute("SELECT COUNT(*) FROM ticket_history").fetchone()
        self.assertGreater(row[0], 0)

    def test_get_user_tickets(self):
        data = self.db.get_user_tickets(1)
        self.assertIn("user", data)
        self.assertIn("tickets", data)
        self.assertEqual(data["user"]["name"], "Alice Johnson")
        self.assertEqual(data["user"]["plan"], "pro")
        self.assertGreater(len(data["tickets"]), 0)

    def test_get_user_tickets_with_status_filter(self):
        data = self.db.get_user_tickets(1, status="open")
        for ticket in data["tickets"]:
            self.assertEqual(ticket["status"], "open")

    def test_get_user_tickets_nonexistent(self):
        data = self.db.get_user_tickets(9999)
        self.assertIn("error", data)

    def test_get_ticket_details(self):
        data = self.db.get_ticket_details(1)
        self.assertEqual(data["subject"], "Cannot log in after password reset")
        self.assertEqual(data["user_name"], "Alice Johnson")
        self.assertIn("history", data)
        self.assertGreater(len(data["history"]), 0)

    def test_get_ticket_details_nonexistent(self):
        data = self.db.get_ticket_details(9999)
        self.assertIn("error", data)

    def test_search_similar_issues(self):
        results = self.db.search_similar_issues("password")
        self.assertGreater(len(results), 0)
        for r in results:
            self.assertIn("password", r["subject"].lower())

    def test_search_similar_issues_with_category(self):
        results = self.db.search_similar_issues("log in", category="login")
        self.assertGreater(len(results), 0)
        for r in results:
            self.assertEqual(r["category"], "login")

    def test_search_similar_issues_no_results(self):
        results = self.db.search_similar_issues("xyznonexistent")
        self.assertEqual(len(results), 0)

    def test_ephemeral_fallback(self):
        db = CrmDB("/nonexistent/path/crm.sqlite")
        self.assertTrue(db.ephemeral)
        data = db.get_user_tickets(1)
        self.assertIn("user", data)
        db.close()


class TestCrmTools(unittest.TestCase):
    """Test CRM tool classes directly."""

    def setUp(self):
        reset_crm_db()
        os.environ["CRM_DB"] = ":memory:"

    def tearDown(self):
        reset_crm_db()
        os.environ.pop("CRM_DB", None)

    def test_get_user_tickets_tool_properties(self):
        tool = GetUserTicketsTool()
        self.assertEqual(tool.name, "crm.get_user_tickets")
        self.assertEqual(tool.required_permissions, ["crm:read"])
        self.assertIn("user", tool.description.lower())

    def test_get_user_tickets_tool_execute(self):
        tool = GetUserTicketsTool()
        result = tool.execute(user_id=1)
        self.assertTrue(result.success)
        self.assertIn("user", result.data)
        self.assertIn("tickets", result.data)

    def test_get_user_tickets_tool_missing_user_id(self):
        tool = GetUserTicketsTool()
        result = tool.execute()
        self.assertFalse(result.success)
        self.assertIn("user_id", result.error)

    def test_get_user_tickets_tool_nonexistent_user(self):
        tool = GetUserTicketsTool()
        result = tool.execute(user_id=9999)
        self.assertFalse(result.success)
        self.assertIn("not found", result.error)

    def test_get_ticket_details_tool_properties(self):
        tool = GetTicketDetailsTool()
        self.assertEqual(tool.name, "crm.get_ticket_details")
        self.assertEqual(tool.required_permissions, ["crm:read"])

    def test_get_ticket_details_tool_execute(self):
        tool = GetTicketDetailsTool()
        result = tool.execute(ticket_id=1)
        self.assertTrue(result.success)
        self.assertIn("subject", result.data)
        self.assertIn("history", result.data)

    def test_get_ticket_details_tool_missing_id(self):
        tool = GetTicketDetailsTool()
        result = tool.execute()
        self.assertFalse(result.success)
        self.assertIn("ticket_id", result.error)

    def test_search_similar_issues_tool_properties(self):
        tool = SearchSimilarIssuesTool()
        self.assertEqual(tool.name, "crm.search_similar_issues")
        self.assertEqual(tool.required_permissions, ["crm:read"])

    def test_search_similar_issues_tool_execute(self):
        tool = SearchSimilarIssuesTool()
        result = tool.execute(query="password")
        self.assertTrue(result.success)
        self.assertGreater(len(result.data), 0)

    def test_search_similar_issues_tool_missing_query(self):
        tool = SearchSimilarIssuesTool()
        result = tool.execute()
        self.assertFalse(result.success)
        self.assertIn("query", result.error)


class TestSupportNodes(unittest.TestCase):
    """Test individual support agent graph nodes."""

    def _mock_registry(self):
        mock = MagicMock()

        def mock_invoke(tool_name, agent_id, **kwargs):
            if tool_name == "crm.get_user_tickets":
                return ToolResult(success=True, data={
                    "user": {"id": 1, "name": "Alice", "email": "alice@test.com", "plan": "pro"},
                    "tickets": [
                        {"id": 1, "subject": "Login fails after reset", "status": "open",
                         "priority": "high", "category": "login"},
                        {"id": 2, "subject": "Dashboard slow", "status": "resolved",
                         "priority": "medium", "category": "performance"},
                    ],
                })
            if tool_name == "crm.search_similar_issues":
                return ToolResult(success=True, data=[
                    {"id": 8, "subject": "MFA setup fails", "status": "open",
                     "priority": "medium", "category": "login", "user_name": "Dave"},
                ])
            if tool_name == "docs.search_project_docs":
                return ToolResult(success=True, data=[
                    {"text": "To reset your password, click Forgot Password.",
                     "source_path": "project/faq/general.md", "score": 2.5},
                    {"text": "Login issues can be caused by MFA problems.",
                     "source_path": "project/faq/troubleshooting.md", "score": 1.8},
                ])
            if tool_name == "support_memory.get_user_history":
                return ToolResult(success=True, data={
                    "user_id": 1,
                    "total_interactions": 3,
                    "recent": [
                        {"id": 10, "user_message": "Password reset not working",
                         "category": "auth", "resolution_status": "resolved",
                         "issue_summary": "Issue: Password reset not working"},
                        {"id": 9, "user_message": "Dashboard slow",
                         "category": "performance", "resolution_status": "resolved",
                         "issue_summary": "Issue: Dashboard slow"},
                    ],
                    "summary": None,
                })
            if tool_name == "support_memory.search_past_issues":
                return ToolResult(success=True, data=[
                    {"id": 10, "user_message": "Password reset not working",
                     "issue_summary": "Issue: Password reset not working",
                     "category": "auth", "resolution_status": "resolved"},
                ])
            if tool_name == "support_memory.store_interaction":
                return ToolResult(success=True, data={"interaction_id": 11, "ephemeral": False})
            return ToolResult(success=False, error="unknown tool")

        mock.invoke.side_effect = mock_invoke
        return mock

    def test_user_context_node(self):
        state = SupportState(user_id=1, question="Why does my login fail?")
        registry = self._mock_registry()
        node = UserContextNode()
        state = node.execute(state, registry, "support_agent")

        self.assertIn("user", state.crm_context)
        self.assertEqual(state.crm_context["user"]["name"], "Alice")
        self.assertGreater(len(state.crm_context["tickets"]), 0)
        self.assertIn("crm.get_user_tickets", state.tools_used)

    def test_user_context_node_no_registry(self):
        state = SupportState(user_id=1, question="test")
        node = UserContextNode()
        state = node.execute(state, None, "test")
        self.assertIn("No registry available", state.errors[0])

    def test_user_context_node_no_user_id(self):
        state = SupportState(question="test")
        registry = self._mock_registry()
        node = UserContextNode()
        state = node.execute(state, registry, "test")
        self.assertIn("No user_id provided", state.errors[0])

    def test_user_context_node_wrong_state(self):
        from core.orchestration.graph import GraphState
        state = GraphState(question="test")
        node = UserContextNode()
        state = node.execute(state, None, "test")
        self.assertIn("requires SupportState", state.errors[0])

    def test_memory_retrieve_node(self):
        state = SupportState(user_id=1, question="login fails")
        registry = self._mock_registry()
        node = MemoryRetrieveNode()
        state = node.execute(state, registry, "support_agent")

        self.assertEqual(state.memory_context["total_interactions"], 3)
        self.assertEqual(len(state.memory_context["recent_interactions"]), 2)
        self.assertEqual(len(state.memory_context["related_past_issues"]), 1)
        self.assertIn("support_memory.get_user_history", state.tools_used)
        self.assertIn("support_memory.search_past_issues", state.tools_used)

    def test_memory_retrieve_node_no_registry(self):
        state = SupportState(user_id=1, question="test")
        node = MemoryRetrieveNode()
        state = node.execute(state, None, "test")
        self.assertIn("No registry available", state.errors[0])

    def test_memory_retrieve_node_no_user_id(self):
        state = SupportState(question="test")
        registry = self._mock_registry()
        node = MemoryRetrieveNode()
        state = node.execute(state, registry, "test")
        # Should return without error, just skip
        self.assertEqual(state.memory_context, {})

    def test_docs_retrieve_node(self):
        state = SupportState(user_id=1, question="How to reset password?")
        registry = self._mock_registry()
        node = SupportDocsRetrieveNode()
        state = node.execute(state, registry, "support_agent")

        self.assertEqual(len(state.docs_context), 2)
        self.assertIn("docs.search_project_docs", state.tools_used)

    def test_docs_retrieve_node_no_registry(self):
        state = SupportState(question="test")
        node = SupportDocsRetrieveNode()
        state = node.execute(state, None, "test")
        self.assertIn("No registry available", state.errors[0])

    def test_context_merge_node(self):
        state = SupportState(user_id=1, question="login fails")
        state.crm_context = {
            "user": {"name": "Alice", "plan": "pro"},
            "tickets": [
                {"id": 1, "subject": "Login fails after reset", "status": "open",
                 "priority": "high", "category": "login"},
            ],
            "similar_issues": [
                {"id": 8, "subject": "MFA setup fails", "status": "open"},
            ],
        }
        state.memory_context = {
            "recent_interactions": [
                {"user_message": "Password issue", "category": "auth",
                 "resolution_status": "resolved"},
            ],
            "summary": None,
            "total_interactions": 2,
            "related_past_issues": [
                {"user_message": "Login broken", "issue_summary": "Issue: Login broken",
                 "category": "auth", "resolution_status": "resolved"},
            ],
        }
        state.docs_context = [
            {"text": "Password reset info", "source_path": "faq/general.md", "score": 2.0},
        ]

        node = ContextMergeNode()
        state = node.execute(state, None, "test")

        self.assertIn("pro plan", state.analysis)
        self.assertIn("1 open ticket", state.analysis)
        self.assertIn("2 previous support interaction", state.analysis)
        self.assertIn("1 related past interaction", state.analysis)
        self.assertIn("documentation", state.analysis.lower())

    def test_context_merge_node_first_interaction(self):
        state = SupportState(user_id=1, question="test")
        state.crm_context = {"user": {"name": "Alice", "plan": "free"}, "tickets": [], "similar_issues": []}
        state.memory_context = {
            "recent_interactions": [], "summary": None,
            "total_interactions": 0, "related_past_issues": [],
        }
        state.docs_context = []

        node = ContextMergeNode()
        state = node.execute(state, None, "test")

        self.assertIn("first support interaction", state.analysis)

    def test_context_merge_node_with_recurring_issues(self):
        state = SupportState(user_id=1, question="test")
        state.crm_context = {"user": {"name": "Alice", "plan": "pro"}, "tickets": [], "similar_issues": []}
        state.memory_context = {
            "recent_interactions": [{"user_message": "test", "category": "auth", "resolution_status": "resolved"}],
            "summary": {
                "summary": "User has 15 past interactions.",
                "recurring_issues": [{"category": "auth", "count": 8}, {"category": "billing", "count": 3}],
                "key_facts": [],
            },
            "total_interactions": 15,
            "related_past_issues": [],
        }
        state.docs_context = []

        node = ContextMergeNode()
        state = node.execute(state, None, "test")

        self.assertIn("auth (8x)", state.analysis)

    def test_issue_analysis_is_context_merge_alias(self):
        """IssueAnalysisNode should be an alias for ContextMergeNode."""
        self.assertIs(IssueAnalysisNode, ContextMergeNode)

    def test_answer_composer_node(self):
        state = SupportState(user_id=1, question="login fails")
        state.crm_context = {
            "user": {"name": "Alice", "email": "alice@test.com", "plan": "pro"},
            "tickets": [],
            "similar_issues": [
                {"id": 8, "subject": "MFA setup fails", "status": "open",
                 "priority": "medium", "category": "login"},
            ],
        }
        state.memory_context = {
            "recent_interactions": [],
            "summary": None,
            "total_interactions": 3,
            "related_past_issues": [
                {"user_message": "Login broken", "issue_summary": "Issue: Login broken",
                 "category": "auth", "resolution_status": "resolved"},
            ],
        }
        state.docs_context = [
            {"text": "Reset your password from the login page.", "source_path": "faq/general.md", "score": 2.0},
        ]
        state.analysis = "User is on the pro plan."

        node = SupportAnswerComposerNode()
        state = node.execute(state, None, "test")

        self.assertIn("# Support Response", state.final_answer)
        self.assertIn("Alice", state.final_answer)
        self.assertIn("pro", state.final_answer)
        self.assertIn("Past Interactions", state.final_answer)
        self.assertIn("Conversation History", state.final_answer)
        self.assertIn("Analysis", state.final_answer)
        self.assertIn("Documentation", state.final_answer)
        self.assertIn("Similar Issues", state.final_answer)

    def test_answer_composer_with_errors(self):
        state = SupportState(user_id=1, question="test")
        state.crm_context = {"user": {}, "tickets": [], "similar_issues": []}
        state.memory_context = {
            "recent_interactions": [], "summary": None,
            "total_interactions": 0, "related_past_issues": [],
        }
        state.docs_context = []
        state.analysis = ""
        state.errors = ["CRM lookup failed"]

        node = SupportAnswerComposerNode()
        state = node.execute(state, None, "test")

        self.assertIn("Errors", state.final_answer)
        self.assertIn("CRM lookup failed", state.final_answer)

    def test_memory_store_node(self):
        state = SupportState(user_id=1, question="login fails")
        state.final_answer = "# Support Response\nHere is your answer."
        registry = self._mock_registry()

        node = MemoryStoreNode()
        state = node.execute(state, registry, "support_agent")

        self.assertIn("support_memory.store_interaction", state.tools_used)

    def test_memory_store_node_no_registry(self):
        state = SupportState(user_id=1, question="test")
        node = MemoryStoreNode()
        state = node.execute(state, None, "test")
        self.assertNotIn("support_memory.store_interaction", state.tools_used)

    def test_memory_store_node_no_user_id(self):
        state = SupportState(question="test")
        registry = self._mock_registry()
        node = MemoryStoreNode()
        state = node.execute(state, registry, "test")
        self.assertNotIn("support_memory.store_interaction", state.tools_used)


class TestSupportGraph(unittest.TestCase):
    """Test the support graph structure and full pipeline."""

    def test_graph_structure(self):
        graph = build_support_graph()
        self.assertIsNotNone(graph._entry_point)
        self.assertEqual(graph._entry_point, "user_context")

    def test_all_nodes_registered(self):
        graph = build_support_graph()
        expected = [
            "user_context", "memory_retrieve", "docs_retrieve",
            "context_merge", "answer_composer", "memory_store",
        ]
        for name in expected:
            self.assertIn(name, graph._nodes)

    def test_edge_wiring(self):
        graph = build_support_graph()
        self.assertEqual(graph._edges["user_context"], "memory_retrieve")
        self.assertEqual(graph._edges["memory_retrieve"], "docs_retrieve")
        self.assertEqual(graph._edges["docs_retrieve"], "context_merge")
        self.assertEqual(graph._edges["context_merge"], "answer_composer")
        self.assertEqual(graph._edges["answer_composer"], "memory_store")
        self.assertEqual(graph._edges["memory_store"], END)

    def _make_full_mock(self):
        mock = MagicMock()

        def mock_invoke(tool_name, agent_id, **kwargs):
            if tool_name == "crm.get_user_tickets":
                return ToolResult(success=True, data={
                    "user": {"id": 1, "name": "Alice", "email": "a@t.com", "plan": "pro"},
                    "tickets": [
                        {"id": 1, "subject": "Login fails after reset", "status": "open",
                         "priority": "high", "category": "login"},
                    ],
                })
            if tool_name == "crm.search_similar_issues":
                return ToolResult(success=True, data=[
                    {"id": 8, "subject": "MFA setup fails", "status": "open",
                     "priority": "medium", "category": "login", "user_name": "Dave"},
                ])
            if tool_name == "support_memory.get_user_history":
                return ToolResult(success=True, data={
                    "user_id": 1, "total_interactions": 2,
                    "recent": [
                        {"id": 5, "user_message": "Login broken yesterday",
                         "category": "auth", "resolution_status": "resolved",
                         "issue_summary": "Issue: Login broken yesterday"},
                    ],
                    "summary": None,
                })
            if tool_name == "support_memory.search_past_issues":
                return ToolResult(success=True, data=[
                    {"id": 5, "user_message": "Login broken yesterday",
                     "issue_summary": "Issue: Login broken yesterday",
                     "category": "auth", "resolution_status": "resolved"},
                ])
            if tool_name == "docs.search_project_docs":
                return ToolResult(success=True, data=[
                    {"text": "Reset your password from the login page.",
                     "source_path": "project/faq/general.md", "score": 2.5},
                ])
            if tool_name == "support_memory.store_interaction":
                return ToolResult(success=True, data={"interaction_id": 6, "ephemeral": False})
            return ToolResult(success=False, error="unknown")

        mock.invoke.side_effect = mock_invoke
        return mock

    def test_full_pipeline(self):
        """Run the full 6-node pipeline with a mock registry."""
        mock = self._make_full_mock()

        graph = build_support_graph()
        state = SupportState(user_id=1, question="Why does my login fail?")
        state = graph.run(state, registry=mock, agent_id="support_agent")

        expected = [
            "user_context", "memory_retrieve", "docs_retrieve",
            "context_merge", "answer_composer", "memory_store",
        ]
        self.assertEqual(state.nodes_executed, expected)
        self.assertIn("Support Response", state.final_answer)
        self.assertIn("Alice", state.final_answer)
        self.assertIn("Conversation History", state.final_answer)
        self.assertIn("support_memory.store_interaction", state.tools_used)

    def test_pipeline_with_crm_failure(self):
        """Pipeline should handle CRM failures gracefully."""
        mock = MagicMock()

        def mock_invoke(tool_name, agent_id, **kwargs):
            if tool_name == "crm.get_user_tickets":
                return ToolResult(success=False, error="User 999 not found")
            if tool_name == "crm.search_similar_issues":
                return ToolResult(success=True, data=[])
            if tool_name == "support_memory.get_user_history":
                return ToolResult(success=True, data={
                    "user_id": 999, "total_interactions": 0,
                    "recent": [], "summary": None,
                })
            if tool_name == "support_memory.search_past_issues":
                return ToolResult(success=True, data=[])
            if tool_name == "docs.search_project_docs":
                return ToolResult(success=True, data=[])
            if tool_name == "support_memory.store_interaction":
                return ToolResult(success=True, data={"interaction_id": 1})
            return ToolResult(success=False, error="unknown")

        mock.invoke.side_effect = mock_invoke

        graph = build_support_graph()
        state = SupportState(user_id=999, question="help")
        state = graph.run(state, registry=mock, agent_id="support_agent")

        self.assertEqual(len(state.nodes_executed), 6)
        self.assertIn("Support Response", state.final_answer)
        self.assertTrue(any("failed" in e for e in state.errors))

    def test_pipeline_memory_shows_in_response(self):
        """Verify memory context appears in the final response."""
        mock = self._make_full_mock()

        graph = build_support_graph()
        state = SupportState(user_id=1, question="Why does my login fail again?")
        state = graph.run(state, registry=mock, agent_id="support_agent")

        # Memory context should be visible
        self.assertIn("2 previous support interaction", state.analysis)
        self.assertIn("Conversation History", state.final_answer)

    def test_support_query_entry_point(self):
        """Test the support_query() convenience function."""
        mock = self._make_full_mock()
        result = support_query(user_id=1, question="test", registry=mock)
        self.assertIn("Support Response", result)

    def test_support_query_debug_mode(self):
        """Test debug output includes memory info."""
        mock = self._make_full_mock()
        result = support_query(user_id=1, question="test", registry=mock, debug=True)
        self.assertIn("[DEBUG]", result)
        self.assertIn("Nodes executed", result)
        self.assertIn("Memory interactions", result)
        self.assertIn("Support Response", result)


class TestSupportPermissions(unittest.TestCase):
    """Test that support agent has correct permissions configured."""

    def test_support_agent_has_docs_read(self):
        checker = PermissionChecker()
        self.assertTrue(checker.check("support_agent", ["docs:read"]))

    def test_support_agent_has_crm_read(self):
        checker = PermissionChecker()
        self.assertTrue(checker.check("support_agent", ["crm:read"]))

    def test_support_agent_has_memory_read(self):
        checker = PermissionChecker()
        self.assertTrue(checker.check("support_agent", ["support_memory:read"]))

    def test_support_agent_has_memory_write(self):
        checker = PermissionChecker()
        self.assertTrue(checker.check("support_agent", ["support_memory:write"]))

    def test_support_agent_has_all_permissions(self):
        checker = PermissionChecker()
        self.assertTrue(checker.check("support_agent", [
            "docs:read", "crm:read", "support_memory:read", "support_memory:write",
        ]))

    def test_support_agent_cannot_access_pr_read(self):
        checker = PermissionChecker()
        self.assertFalse(checker.check("support_agent", ["pr:read"]))

    def test_support_agent_cannot_access_review_memory(self):
        checker = PermissionChecker()
        self.assertFalse(checker.check("support_agent", ["review_memory:read"]))

    def test_support_agent_pr_enforce_raises(self):
        checker = PermissionChecker()
        with self.assertRaises(PermissionDeniedError):
            checker.enforce("support_agent", ["pr:read"])

    def test_bug_reviewer_cannot_access_crm(self):
        checker = PermissionChecker()
        self.assertFalse(checker.check("bug_reviewer", ["crm:read"]))

    def test_bug_reviewer_cannot_access_support_memory(self):
        checker = PermissionChecker()
        self.assertFalse(checker.check("bug_reviewer", ["support_memory:read"]))

    def test_review_orchestrator_cannot_access_support_memory(self):
        checker = PermissionChecker()
        self.assertFalse(checker.check("review_orchestrator", ["support_memory:read"]))


if __name__ == "__main__":
    unittest.main()
