"""Tests for the support memory plugin — persistent customer interaction store."""

import os
import unittest

from plugins.support_memory.tool_support_memory import (
    SupportMemoryDB,
    StoreInteractionTool,
    GetUserHistoryTool,
    SearchPastIssuesTool,
    detect_category,
    extract_summary,
    reset_db,
    SUMMARIZE_THRESHOLD,
    KEEP_RECENT,
)


class TestCategoryDetection(unittest.TestCase):
    """Test automatic issue category detection."""

    def test_detects_auth(self):
        self.assertEqual(detect_category("I cannot login to my account"), "auth")

    def test_detects_billing(self):
        self.assertEqual(detect_category("I need a refund for my subscription"), "billing")

    def test_detects_api(self):
        self.assertEqual(detect_category("I'm hitting the rate limit on the API"), "api")

    def test_detects_performance(self):
        self.assertEqual(detect_category("The dashboard is loading very slow"), "performance")

    def test_detects_integration(self):
        self.assertEqual(detect_category("SSO SAML integration is broken"), "integration")

    def test_defaults_to_general(self):
        self.assertEqual(detect_category("I have a question about your product"), "general")

    def test_mixed_content_picks_strongest(self):
        cat = detect_category("login password authentication failed mfa 2fa")
        self.assertEqual(cat, "auth")


class TestExtractSummary(unittest.TestCase):
    """Test issue summary extraction."""

    def test_basic_summary(self):
        summary = extract_summary("My login is broken", "Please try resetting your password")
        self.assertIn("My login is broken", summary)

    def test_truncates_long_message(self):
        long_msg = "x" * 300
        summary = extract_summary(long_msg, "")
        self.assertIn("...", summary)
        self.assertLessEqual(len(summary), 300)

    def test_includes_resolution_hints(self):
        summary = extract_summary("Problem here", "Try this workaround: restart the service")
        self.assertIn("workaround", summary)

    def test_empty_response(self):
        summary = extract_summary("My issue", "")
        self.assertIn("My issue", summary)


class TestSupportMemoryDB(unittest.TestCase):
    """Test the support memory SQLite store."""

    def setUp(self):
        self.db = SupportMemoryDB(":memory:")

    def tearDown(self):
        self.db.close()

    def test_store_and_retrieve(self):
        iid = self.db.store_interaction(
            user_id=1,
            user_message="My login is broken",
            assistant_response="Try resetting your password",
        )
        self.assertIsInstance(iid, int)
        self.assertGreater(iid, 0)

        history = self.db.get_user_history(1)
        self.assertEqual(history["total_interactions"], 1)
        self.assertEqual(len(history["recent"]), 1)
        self.assertEqual(history["recent"][0]["user_message"], "My login is broken")

    def test_auto_category_detection(self):
        self.db.store_interaction(
            user_id=1,
            user_message="I need a refund for double charge",
            assistant_response="Let me check your billing",
        )
        history = self.db.get_user_history(1)
        self.assertEqual(history["recent"][0]["category"], "billing")

    def test_auto_summary_extraction(self):
        self.db.store_interaction(
            user_id=1,
            user_message="API rate limit exceeded",
            assistant_response="Try reducing request frequency",
        )
        history = self.db.get_user_history(1)
        self.assertIn("API rate limit", history["recent"][0]["issue_summary"])

    def test_explicit_category(self):
        self.db.store_interaction(
            user_id=1,
            user_message="Something happened",
            category="billing",
        )
        history = self.db.get_user_history(1)
        self.assertEqual(history["recent"][0]["category"], "billing")

    def test_explicit_summary(self):
        self.db.store_interaction(
            user_id=1,
            user_message="Something happened",
            issue_summary="Custom summary",
        )
        history = self.db.get_user_history(1)
        self.assertEqual(history["recent"][0]["issue_summary"], "Custom summary")

    def test_multiple_users_isolated(self):
        self.db.store_interaction(user_id=1, user_message="User 1 issue")
        self.db.store_interaction(user_id=2, user_message="User 2 issue")

        h1 = self.db.get_user_history(1)
        h2 = self.db.get_user_history(2)
        self.assertEqual(h1["total_interactions"], 1)
        self.assertEqual(h2["total_interactions"], 1)
        self.assertNotEqual(
            h1["recent"][0]["user_message"],
            h2["recent"][0]["user_message"],
        )

    def test_search_past_issues(self):
        self.db.store_interaction(user_id=1, user_message="Login broken")
        self.db.store_interaction(user_id=1, user_message="Billing question")
        self.db.store_interaction(user_id=1, user_message="Login fails again")

        results = self.db.search_past_issues(1, "login")
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertIn("login", r["user_message"].lower())

    def test_search_no_results(self):
        self.db.store_interaction(user_id=1, user_message="Hello")
        results = self.db.search_past_issues(1, "xyznonexistent")
        self.assertEqual(len(results), 0)

    def test_search_other_user_isolated(self):
        self.db.store_interaction(user_id=1, user_message="Login broken")
        self.db.store_interaction(user_id=2, user_message="Login broken too")

        results = self.db.search_past_issues(1, "login")
        self.assertEqual(len(results), 1)
        # Should not return user 2's data

    def test_delete_user_history(self):
        self.db.store_interaction(user_id=1, user_message="Issue 1")
        self.db.store_interaction(user_id=1, user_message="Issue 2")
        count = self.db.delete_user_history(1)
        self.assertEqual(count, 2)

        history = self.db.get_user_history(1)
        self.assertEqual(history["total_interactions"], 0)
        self.assertEqual(len(history["recent"]), 0)

    def test_delete_preserves_other_users(self):
        self.db.store_interaction(user_id=1, user_message="Issue 1")
        self.db.store_interaction(user_id=2, user_message="Issue 2")
        self.db.delete_user_history(1)

        h2 = self.db.get_user_history(2)
        self.assertEqual(h2["total_interactions"], 1)

    def test_empty_history(self):
        history = self.db.get_user_history(999)
        self.assertEqual(history["total_interactions"], 0)
        self.assertEqual(len(history["recent"]), 0)
        self.assertIsNone(history["summary"])

    def test_history_limit(self):
        for i in range(15):
            self.db.store_interaction(user_id=1, user_message=f"Issue {i}")

        history = self.db.get_user_history(1, limit=5)
        self.assertEqual(len(history["recent"]), 5)

    def test_conversation_id_auto_generated(self):
        iid = self.db.store_interaction(user_id=1, user_message="test")
        history = self.db.get_user_history(1)
        conv_id = history["recent"][0]["conversation_id"]
        self.assertIsInstance(conv_id, str)
        self.assertGreater(len(conv_id), 0)

    def test_conversation_id_explicit(self):
        self.db.store_interaction(
            user_id=1, user_message="test", conversation_id="conv-42"
        )
        history = self.db.get_user_history(1)
        self.assertEqual(history["recent"][0]["conversation_id"], "conv-42")

    def test_message_capping(self):
        long_msg = "x" * 10000
        self.db.store_interaction(user_id=1, user_message=long_msg)
        history = self.db.get_user_history(1)
        self.assertLessEqual(len(history["recent"][0]["user_message"]), 5000)

    def test_ephemeral_fallback(self):
        db = SupportMemoryDB("/nonexistent/path/memory.sqlite")
        self.assertTrue(db.ephemeral)
        iid = db.store_interaction(user_id=1, user_message="test")
        self.assertGreater(iid, 0)
        db.close()


class TestSummarization(unittest.TestCase):
    """Test automatic summarization of old interactions."""

    def setUp(self):
        self.db = SupportMemoryDB(":memory:")

    def tearDown(self):
        self.db.close()

    def test_no_summarization_below_threshold(self):
        for i in range(SUMMARIZE_THRESHOLD - 1):
            self.db.store_interaction(user_id=1, user_message=f"Issue {i}")

        history = self.db.get_user_history(1)
        self.assertIsNone(history["summary"])

    def test_summarization_at_threshold(self):
        """When interactions exceed threshold, old ones are summarized and deleted."""
        for i in range(SUMMARIZE_THRESHOLD + 1):
            self.db.store_interaction(
                user_id=1,
                user_message=f"Login issue #{i}",
                category="auth",
            )

        history = self.db.get_user_history(1)
        # Should have a summary now
        self.assertIsNotNone(history["summary"])
        self.assertIn("past support interactions", history["summary"]["summary"])
        # Should keep only KEEP_RECENT raw interactions
        self.assertEqual(len(history["recent"]), KEEP_RECENT)

    def test_summary_tracks_recurring_issues(self):
        # Create enough auth + billing interactions to trigger summary
        for i in range(15):
            self.db.store_interaction(
                user_id=1, user_message=f"Login issue {i}", category="auth"
            )
        for i in range(8):
            self.db.store_interaction(
                user_id=1, user_message=f"Billing issue {i}", category="billing"
            )

        history = self.db.get_user_history(1)
        self.assertIsNotNone(history["summary"])
        recurring = history["summary"]["recurring_issues"]
        categories = [r["category"] for r in recurring]
        self.assertIn("auth", categories)

    def test_summary_preserves_key_facts(self):
        for i in range(SUMMARIZE_THRESHOLD + 1):
            self.db.store_interaction(
                user_id=1,
                user_message=f"Issue about topic {i}",
                issue_summary=f"Summary {i}",
            )

        history = self.db.get_user_history(1)
        self.assertIsNotNone(history["summary"])
        key_facts = history["summary"]["key_facts"]
        self.assertGreater(len(key_facts), 0)

    def test_summarization_isolated_per_user(self):
        """Summarization for user 1 shouldn't affect user 2."""
        for i in range(SUMMARIZE_THRESHOLD + 1):
            self.db.store_interaction(user_id=1, user_message=f"U1 issue {i}")
        self.db.store_interaction(user_id=2, user_message="U2 issue")

        h1 = self.db.get_user_history(1)
        h2 = self.db.get_user_history(2)

        self.assertIsNotNone(h1["summary"])
        self.assertIsNone(h2["summary"])
        self.assertEqual(h2["total_interactions"], 1)


class TestSupportMemoryTools(unittest.TestCase):
    """Test the plugin tool classes directly."""

    def setUp(self):
        reset_db()
        os.environ["SUPPORT_MEMORY_DB"] = ":memory:"

    def tearDown(self):
        reset_db()
        os.environ.pop("SUPPORT_MEMORY_DB", None)

    def test_store_interaction_tool_properties(self):
        tool = StoreInteractionTool()
        self.assertEqual(tool.name, "support_memory.store_interaction")
        self.assertEqual(tool.required_permissions, ["support_memory:write"])

    def test_store_interaction_tool_execute(self):
        tool = StoreInteractionTool()
        result = tool.execute(
            user_id=1,
            user_message="My login is broken",
            assistant_response="Try resetting your password",
        )
        self.assertTrue(result.success)
        self.assertIn("interaction_id", result.data)

    def test_store_interaction_missing_user_id(self):
        tool = StoreInteractionTool()
        result = tool.execute(user_message="test")
        self.assertFalse(result.success)
        self.assertIn("user_id", result.error)

    def test_store_interaction_missing_message(self):
        tool = StoreInteractionTool()
        result = tool.execute(user_id=1)
        self.assertFalse(result.success)
        self.assertIn("user_message", result.error)

    def test_get_user_history_tool_properties(self):
        tool = GetUserHistoryTool()
        self.assertEqual(tool.name, "support_memory.get_user_history")
        self.assertEqual(tool.required_permissions, ["support_memory:read"])

    def test_get_user_history_tool_execute(self):
        # Store first
        store = StoreInteractionTool()
        store.execute(user_id=1, user_message="Test issue")

        tool = GetUserHistoryTool()
        result = tool.execute(user_id=1)
        self.assertTrue(result.success)
        self.assertIn("recent", result.data)
        self.assertEqual(len(result.data["recent"]), 1)

    def test_get_user_history_missing_user_id(self):
        tool = GetUserHistoryTool()
        result = tool.execute()
        self.assertFalse(result.success)
        self.assertIn("user_id", result.error)

    def test_search_past_issues_tool_properties(self):
        tool = SearchPastIssuesTool()
        self.assertEqual(tool.name, "support_memory.search_past_issues")
        self.assertEqual(tool.required_permissions, ["support_memory:read"])

    def test_search_past_issues_tool_execute(self):
        store = StoreInteractionTool()
        store.execute(user_id=1, user_message="Login broken")
        store.execute(user_id=1, user_message="Billing question")

        tool = SearchPastIssuesTool()
        result = tool.execute(user_id=1, query="login")
        self.assertTrue(result.success)
        self.assertEqual(len(result.data), 1)

    def test_search_past_issues_missing_user_id(self):
        tool = SearchPastIssuesTool()
        result = tool.execute(query="test")
        self.assertFalse(result.success)
        self.assertIn("user_id", result.error)

    def test_search_past_issues_missing_query(self):
        tool = SearchPastIssuesTool()
        result = tool.execute(user_id=1)
        self.assertFalse(result.success)
        self.assertIn("query", result.error)


if __name__ == "__main__":
    unittest.main()
