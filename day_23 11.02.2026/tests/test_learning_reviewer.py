"""Tests for the continuous learning reviewer system."""

import os
import unittest
from unittest.mock import MagicMock

from core.orchestration.graph import END
from core.registry.tool_registry import ToolRegistry, ToolResult
from core.registry.permissions import PermissionChecker, PermissionDeniedError

from agents.reviewers.review_state import ReviewFinding, ReviewState
from agents.reviewers.review_orchestrator import build_review_graph, review_pr
from agents.reviewers.review_nodes import (
    LearningContextNode,
    LearningAdjustNode,
    MemoryPersistNode,
)
from agents.reviewers.learning_reviewer import (
    LearningGuidance,
    analyze_history,
    apply_guidance,
)
from plugins.review_memory.tool_review_memory import (
    ReviewMemoryDB,
    StoreReviewRunTool,
    SearchSimilarFindingsTool,
    RecordFeedbackTool,
    GetProjectConventionsTool,
    reset_db,
)


# --- Sample diffs for testing ---

DIFF_WITH_BUGS = """\
diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -10,6 +10,15 @@
 import os

+def process(data=[]):
+    try:
+        result = data[0] / 0
+    except:
+        pass
+    if data == None:
+        return
+    for i in range(len(data)):
+        print(data[i])
"""


class TestReviewMemoryDB(unittest.TestCase):
    """Test the SQLite memory store."""

    def setUp(self):
        self.db = ReviewMemoryDB(":memory:")

    def tearDown(self):
        self.db.close()

    def test_store_and_retrieve_run(self):
        run_id = self.db.store_run(
            pr_id="repo#1",
            base_branch="main",
            files=["app.py", "lib.py"],
            risk_level="medium",
            report="# Report\nSome findings...",
            findings=[
                {"category": "bug", "severity": "high", "file_path": "app.py",
                 "line": 10, "message": "Bare except", "suggestion": "Use Exception"},
                {"category": "style", "severity": "low", "file_path": "lib.py",
                 "line": 5, "message": "Trailing whitespace", "suggestion": "Remove it"},
            ],
        )
        self.assertIsInstance(run_id, int)
        self.assertGreater(run_id, 0)

        # Search by file path
        results = self.db.search_findings(file_path="app.py")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["message"], "Bare except")

        # Search by category
        results = self.db.search_findings(category="style")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["message"], "Trailing whitespace")

    def test_search_by_keyword(self):
        self.db.store_run(
            pr_id="repo#2", base_branch="main", files=["x.py"],
            risk_level="low", report="", findings=[
                {"category": "bug", "severity": "high", "message": "eval() is dangerous",
                 "file_path": "x.py", "suggestion": "Remove eval"},
            ],
        )
        results = self.db.search_findings(keyword="eval")
        self.assertEqual(len(results), 1)

    def test_record_feedback(self):
        run_id = self.db.store_run(
            pr_id="repo#3", base_branch="main", files=["a.py"],
            risk_level="low", report="", findings=[
                {"category": "style", "severity": "low", "message": "TODO comment",
                 "file_path": "a.py", "suggestion": "Remove TODO"},
            ],
        )
        # Get the finding ID
        findings = self.db.search_findings(keyword="TODO")
        self.assertEqual(len(findings), 1)
        fid = findings[0]["id"]

        # Record feedback
        ok = self.db.record_feedback(fid, "rejected", comment="Not relevant in tests")
        self.assertTrue(ok)

        # Verify label updated
        findings = self.db.search_findings(label="rejected")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["label"], "rejected")

    def test_record_feedback_nonexistent(self):
        ok = self.db.record_feedback(9999, "accepted")
        self.assertFalse(ok)

    def test_false_positive_patterns(self):
        # Store two runs with the same finding rejected
        for pr_num in range(3):
            run_id = self.db.store_run(
                pr_id=f"repo#{pr_num}", base_branch="main", files=["a.py"],
                risk_level="low", report="", findings=[
                    {"category": "style", "severity": "low", "message": "Trailing whitespace",
                     "file_path": "a.py", "suggestion": "Remove it"},
                ],
            )
            findings = self.db.search_findings(keyword="Trailing whitespace")
            # Reject each finding
            for f in findings:
                if f.get("label") == "pending":
                    self.db.record_feedback(f["id"], "rejected")

        fps = self.db.get_false_positive_patterns(min_rejected=2)
        self.assertGreater(len(fps), 0)
        self.assertEqual(fps[0]["message"], "Trailing whitespace")

    def test_high_value_patterns(self):
        for pr_num in range(3):
            run_id = self.db.store_run(
                pr_id=f"repo#{pr_num}", base_branch="main", files=["a.py"],
                risk_level="high", report="", findings=[
                    {"category": "security", "severity": "high", "message": "eval() detected",
                     "file_path": "a.py", "suggestion": "Remove eval"},
                ],
            )
            findings = self.db.search_findings(keyword="eval")
            for f in findings:
                if f.get("label") == "pending":
                    self.db.record_feedback(f["id"], "accepted")

        hvs = self.db.get_high_value_patterns(min_accepted=2)
        self.assertGreater(len(hvs), 0)
        self.assertEqual(hvs[0]["message"], "eval() detected")

    def test_conventions(self):
        cid = self.db.store_convention("prefer snake_case", "inferred", 0.8)
        self.assertIsInstance(cid, int)

        convs = self.db.get_conventions(min_confidence=0.5)
        self.assertEqual(len(convs), 1)
        self.assertEqual(convs[0]["pattern"], "prefer snake_case")

        # Below threshold
        convs = self.db.get_conventions(min_confidence=0.9)
        self.assertEqual(len(convs), 0)

    def test_finding_stats(self):
        self.db.store_run(
            pr_id="repo#10", base_branch="main", files=["a.py"],
            risk_level="low", report="", findings=[
                {"category": "bug", "severity": "high", "message": "Bare except",
                 "file_path": "a.py", "suggestion": "Fix"},
                {"category": "bug", "severity": "high", "message": "Bare except",
                 "file_path": "b.py", "suggestion": "Fix"},
            ],
        )
        stats = self.db.get_finding_stats(category="bug")
        self.assertGreater(len(stats), 0)
        self.assertEqual(stats[0]["message"], "Bare except")
        self.assertEqual(stats[0]["total_count"], 2)

    def test_ephemeral_fallback(self):
        db = ReviewMemoryDB("/nonexistent/path/db.sqlite")
        self.assertTrue(db.ephemeral)
        # Should still work with in-memory DB
        run_id = db.store_run(
            pr_id="test", base_branch="main", files=[], risk_level="none",
            report="", findings=[],
        )
        self.assertGreater(run_id, 0)
        db.close()

    def test_report_capping(self):
        long_report = "x" * 100_000
        run_id = self.db.store_run(
            pr_id="repo#big", base_branch="main", files=[], risk_level="low",
            report=long_report, findings=[],
        )
        # Verify it was stored (capped internally)
        self.assertGreater(run_id, 0)


class TestToolImplementations(unittest.TestCase):
    """Test the plugin tool classes directly."""

    def setUp(self):
        # Reset singleton and use in-memory DB
        reset_db()
        os.environ["REVIEW_MEMORY_DB"] = ":memory:"

    def tearDown(self):
        reset_db()
        os.environ.pop("REVIEW_MEMORY_DB", None)

    def test_store_review_run_tool(self):
        tool = StoreReviewRunTool()
        self.assertEqual(tool.name, "review_memory.store_review_run")
        self.assertEqual(tool.required_permissions, ["review_memory:write"])

        result = tool.execute(
            pr_id="repo#1",
            base_branch="main",
            files=["a.py"],
            risk_level="low",
            report="test report",
            findings=[{"category": "bug", "severity": "low", "message": "test", "file_path": "a.py"}],
        )
        self.assertTrue(result.success)
        self.assertIn("run_id", result.data)

    def test_store_review_run_missing_pr_id(self):
        tool = StoreReviewRunTool()
        result = tool.execute()
        self.assertFalse(result.success)
        self.assertIn("pr_id", result.error)

    def test_search_similar_findings_tool(self):
        # Store first
        store = StoreReviewRunTool()
        store.execute(
            pr_id="repo#1", base_branch="main", files=["app.py"],
            risk_level="low", report="",
            findings=[{"category": "bug", "severity": "high", "message": "Bare except",
                        "file_path": "app.py", "suggestion": "Fix"}],
        )

        search = SearchSimilarFindingsTool()
        self.assertEqual(search.name, "review_memory.search_similar_findings")
        self.assertEqual(search.required_permissions, ["review_memory:read"])

        result = search.execute(category="bug")
        self.assertTrue(result.success)
        self.assertEqual(len(result.data), 1)

    def test_record_feedback_tool(self):
        store = StoreReviewRunTool()
        store.execute(
            pr_id="repo#1", base_branch="main", files=["a.py"],
            risk_level="low", report="",
            findings=[{"category": "bug", "severity": "low", "message": "test",
                        "file_path": "a.py", "suggestion": "fix"}],
        )
        # Find the finding
        search = SearchSimilarFindingsTool()
        result = search.execute(keyword="test")
        fid = result.data[0]["id"]

        fb = RecordFeedbackTool()
        self.assertEqual(fb.name, "review_memory.record_feedback")
        self.assertEqual(fb.required_permissions, ["review_memory:write"])

        result = fb.execute(finding_id=fid, label="accepted")
        self.assertTrue(result.success)

    def test_record_feedback_invalid_label(self):
        fb = RecordFeedbackTool()
        result = fb.execute(finding_id=1, label="invalid")
        self.assertFalse(result.success)
        self.assertIn("Invalid label", result.error)

    def test_record_feedback_missing_id(self):
        fb = RecordFeedbackTool()
        result = fb.execute(label="accepted")
        self.assertFalse(result.success)
        self.assertIn("finding_id", result.error)

    def test_get_conventions_tool(self):
        tool = GetProjectConventionsTool()
        self.assertEqual(tool.name, "review_memory.get_project_conventions")
        self.assertEqual(tool.required_permissions, ["review_memory:read"])

        result = tool.execute()
        self.assertTrue(result.success)
        self.assertIn("conventions", result.data)
        self.assertIn("false_positive_patterns", result.data)
        self.assertIn("high_value_patterns", result.data)


class TestLearningReviewer(unittest.TestCase):
    """Test the learning reviewer analysis logic."""

    def test_analyze_empty_history(self):
        guidance = analyze_history([], [], [], [])
        self.assertEqual(len(guidance.deprioritize), 0)
        self.assertEqual(len(guidance.boost), 0)
        self.assertEqual(len(guidance.conventions), 0)
        self.assertIn("No historical", guidance.summary)

    def test_deprioritize_false_positives(self):
        fps = [{"message": "Trailing whitespace", "category": "style", "rejected_count": 5}]
        guidance = analyze_history([], fps, [], [])
        self.assertEqual(len(guidance.deprioritize), 1)
        self.assertEqual(guidance.deprioritize[0]["message"], "Trailing whitespace")

    def test_boost_high_value(self):
        hvs = [{"message": "eval() detected", "category": "security", "confirmed_count": 3}]
        guidance = analyze_history([], [], hvs, [])
        self.assertEqual(len(guidance.boost), 1)
        self.assertEqual(guidance.boost[0]["message"], "eval() detected")

    def test_conventions_applied(self):
        convs = [
            {"pattern": "prefer snake_case", "confidence": 0.8},
            {"pattern": "low confidence rule", "confidence": 0.1},
        ]
        guidance = analyze_history([], [], [], convs)
        self.assertEqual(len(guidance.conventions), 1)
        self.assertEqual(guidance.conventions[0], "prefer snake_case")

    def test_similar_findings_analysis(self):
        # Simulate a message that was rejected 3 out of 4 times
        similar = [
            {"message": "TODO comment", "label": "rejected"},
            {"message": "TODO comment", "label": "rejected"},
            {"message": "TODO comment", "label": "rejected"},
            {"message": "TODO comment", "label": "accepted"},
        ]
        guidance = analyze_history(similar, [], [], [])
        self.assertEqual(len(guidance.deprioritize), 1)
        self.assertIn("TODO comment", guidance.deprioritize[0]["message"])

    def test_similar_findings_boost(self):
        similar = [
            {"message": "Bare except", "label": "accepted"},
            {"message": "Bare except", "label": "fixed"},
            {"message": "Bare except", "label": "accepted"},
        ]
        guidance = analyze_history(similar, [], [], [])
        self.assertEqual(len(guidance.boost), 1)
        self.assertIn("Bare except", guidance.boost[0]["message"])

    def test_summary_format(self):
        fps = [{"message": "X", "category": "style", "rejected_count": 3}]
        hvs = [{"message": "Y", "category": "bug", "confirmed_count": 2}]
        convs = [{"pattern": "Z", "confidence": 0.9}]
        guidance = analyze_history([], fps, hvs, convs)
        self.assertIn("deprioritized", guidance.summary)
        self.assertIn("boosted", guidance.summary)
        self.assertIn("convention", guidance.summary)


class TestApplyGuidance(unittest.TestCase):
    """Test severity adjustments from learning guidance."""

    def test_deprioritize_downgrades_severity(self):
        findings = [
            ReviewFinding("style", "high", "a.py", 1, "Trailing whitespace", "Remove"),
            ReviewFinding("bug", "high", "a.py", 2, "Bare except", "Fix"),
        ]
        guidance = LearningGuidance(
            deprioritize=[{"message": "Trailing whitespace", "category": "style", "reason": "FP"}],
        )
        adjusted = apply_guidance(findings, guidance)
        self.assertEqual(adjusted[0].severity, "medium")  # downgraded
        self.assertIn("[deprioritized by learning]", adjusted[0].suggestion)
        self.assertEqual(adjusted[1].severity, "high")  # unchanged

    def test_boost_upgrades_severity(self):
        findings = [
            ReviewFinding("security", "low", "a.py", 1, "eval() detected", "Remove"),
        ]
        guidance = LearningGuidance(
            boost=[{"message": "eval() detected", "category": "security", "reason": "confirmed"}],
        )
        adjusted = apply_guidance(findings, guidance)
        self.assertEqual(adjusted[0].severity, "medium")  # upgraded
        self.assertIn("[boosted by learning]", adjusted[0].suggestion)

    def test_no_change_for_unmatched(self):
        findings = [ReviewFinding("bug", "medium", "a.py", 1, "Some issue", "Fix")]
        guidance = LearningGuidance()
        adjusted = apply_guidance(findings, guidance)
        self.assertEqual(adjusted[0].severity, "medium")
        self.assertEqual(adjusted[0].suggestion, "Fix")

    def test_high_stays_high_on_boost(self):
        findings = [ReviewFinding("bug", "high", "a.py", 1, "Critical", "Fix")]
        guidance = LearningGuidance(
            boost=[{"message": "Critical", "category": "bug", "reason": "test"}],
        )
        adjusted = apply_guidance(findings, guidance)
        self.assertEqual(adjusted[0].severity, "high")  # can't go higher

    def test_low_stays_low_on_deprioritize(self):
        findings = [ReviewFinding("style", "low", "a.py", 1, "Minor", "Fix")]
        guidance = LearningGuidance(
            deprioritize=[{"message": "Minor", "category": "style", "reason": "test"}],
        )
        adjusted = apply_guidance(findings, guidance)
        self.assertEqual(adjusted[0].severity, "low")  # can't go lower


class TestLearningNodes(unittest.TestCase):
    """Test the three learning graph nodes."""

    def _mock_registry(self):
        mock = MagicMock()

        def mock_invoke(tool_name, agent_id, **kwargs):
            if tool_name == "review_memory.search_similar_findings":
                return ToolResult(success=True, data=[])
            if tool_name == "review_memory.get_project_conventions":
                return ToolResult(success=True, data={
                    "conventions": [],
                    "false_positive_patterns": [],
                    "high_value_patterns": [],
                })
            if tool_name == "review_memory.store_review_run":
                return ToolResult(success=True, data={"run_id": 1, "ephemeral": True})
            return ToolResult(success=False, error="unknown")

        mock.invoke.side_effect = mock_invoke
        return mock

    def test_learning_context_node(self):
        state = ReviewState()
        state.pr_files = ["app.py"]
        registry = self._mock_registry()

        node = LearningContextNode()
        state = node.execute(state, registry, "review_orchestrator")

        self.assertIn("similar_findings", state.learning_context)
        self.assertIn("false_positive_patterns", state.learning_context)

    def test_learning_context_node_no_registry(self):
        state = ReviewState()
        node = LearningContextNode()
        state = node.execute(state, None, "test")
        self.assertEqual(state.learning_context, {})

    def test_learning_adjust_node_no_context(self):
        state = ReviewState()
        state.findings = [ReviewFinding("bug", "high", "a.py", 1, "Test", "Fix")]
        node = LearningAdjustNode()
        state = node.execute(state, None, "test")
        # No learning context — findings unchanged
        self.assertEqual(len(state.findings), 1)
        self.assertEqual(state.findings[0].severity, "high")

    def test_learning_adjust_node_with_context(self):
        state = ReviewState()
        state.findings = [
            ReviewFinding("style", "medium", "a.py", 1, "TODO comment", "Remove"),
        ]
        state.learning_context = {
            "similar_findings": [],
            "false_positive_patterns": [
                {"message": "TODO comment", "category": "style", "rejected_count": 5},
            ],
            "high_value_patterns": [],
            "conventions": [],
        }
        state.review_report = "# Report\n"

        node = LearningAdjustNode()
        state = node.execute(state, None, "test")
        self.assertEqual(state.findings[0].severity, "low")  # downgraded
        self.assertIn("deprioritized", state.learning_summary)

    def test_memory_persist_node(self):
        state = ReviewState()
        state.pr_id = "repo#42"
        state.base_branch = "main"
        state.pr_files = ["a.py"]
        state.risk_level = "low"
        state.review_report = "# Report"
        state.findings = [
            ReviewFinding("bug", "high", "a.py", 1, "Test", "Fix"),
        ]
        registry = self._mock_registry()

        node = MemoryPersistNode()
        state = node.execute(state, registry, "review_orchestrator")
        self.assertIn("review_memory.store_review_run", state.tools_used)

    def test_memory_persist_node_no_registry(self):
        state = ReviewState()
        node = MemoryPersistNode()
        state = node.execute(state, None, "test")
        self.assertNotIn("review_memory.store_review_run", state.tools_used)


class TestUpdatedGraph(unittest.TestCase):
    """Test the updated graph structure with learning nodes."""

    def test_graph_includes_learning_nodes(self):
        graph = build_review_graph()
        self.assertIn("learning_context", graph._nodes)
        self.assertIn("learning_adjust", graph._nodes)
        self.assertIn("memory_persist", graph._nodes)

    def test_graph_wiring(self):
        graph = build_review_graph()
        self.assertEqual(graph._edges["pr_fetch"], "learning_context")
        self.assertEqual(graph._edges["learning_context"], "docs_context")
        self.assertEqual(graph._edges["review_merge"], "learning_adjust")
        self.assertEqual(graph._edges["learning_adjust"], "memory_persist")
        self.assertEqual(graph._edges["memory_persist"], END)

    def test_full_pipeline_with_learning(self):
        """Run the full 10-node pipeline with a mock registry."""
        mock = MagicMock()

        def mock_invoke(tool_name, agent_id, **kwargs):
            if tool_name == "pr.get_diff":
                return ToolResult(success=True, data=DIFF_WITH_BUGS)
            if tool_name == "docs.search_project_docs":
                return ToolResult(success=True, data=[])
            if tool_name == "review_memory.search_similar_findings":
                return ToolResult(success=True, data=[])
            if tool_name == "review_memory.get_project_conventions":
                return ToolResult(success=True, data={
                    "conventions": [],
                    "false_positive_patterns": [],
                    "high_value_patterns": [],
                })
            if tool_name == "review_memory.store_review_run":
                return ToolResult(success=True, data={"run_id": 1})
            return ToolResult(success=False, error="unknown")

        mock.invoke.side_effect = mock_invoke

        graph = build_review_graph()
        state = ReviewState(base_branch="main", pr_id="test#1")
        state = graph.run(state, registry=mock, agent_id="review_orchestrator")

        expected = [
            "pr_fetch", "learning_context", "docs_context",
            "bug_review", "style_review", "security_review",
            "performance_review", "review_merge",
            "learning_adjust", "memory_persist",
        ]
        self.assertEqual(state.nodes_executed, expected)
        self.assertGreater(len(state.findings), 0)
        self.assertIn("PR Review Report", state.review_report)

    def test_pipeline_with_learning_signals(self):
        """Test that learning signals actually affect the output."""
        mock = MagicMock()

        def mock_invoke(tool_name, agent_id, **kwargs):
            if tool_name == "pr.get_diff":
                return ToolResult(success=True, data=DIFF_WITH_BUGS)
            if tool_name == "docs.search_project_docs":
                return ToolResult(success=True, data=[])
            if tool_name == "review_memory.search_similar_findings":
                return ToolResult(success=True, data=[])
            if tool_name == "review_memory.get_project_conventions":
                return ToolResult(success=True, data={
                    "conventions": [{"pattern": "prefer snake_case", "confidence": 0.9}],
                    "false_positive_patterns": [
                        {"message": "Bare except clause catches all exceptions including KeyboardInterrupt and SystemExit",
                         "category": "bug", "rejected_count": 5},
                    ],
                    "high_value_patterns": [],
                })
            if tool_name == "review_memory.store_review_run":
                return ToolResult(success=True, data={"run_id": 1})
            return ToolResult(success=False, error="unknown")

        mock.invoke.side_effect = mock_invoke

        graph = build_review_graph()
        state = ReviewState(base_branch="main", pr_id="test#2")
        state = graph.run(state, registry=mock, agent_id="review_orchestrator")

        # The bare except finding should be deprioritized
        bare_except = [f for f in state.findings if "Bare except" in f.message]
        self.assertEqual(len(bare_except), 1)
        # It was HIGH, should now be MEDIUM (deprioritized)
        self.assertEqual(bare_except[0].severity, "medium")
        self.assertIn("[deprioritized by learning]", bare_except[0].suggestion)
        # Convention should appear in report
        self.assertIn("snake_case", state.review_report)
        self.assertIn("deprioritized", state.learning_summary)


class TestPermissions(unittest.TestCase):
    """Test that learning-related permissions are configured correctly."""

    def test_learning_reviewer_has_read(self):
        checker = PermissionChecker()
        self.assertTrue(checker.check("learning_reviewer", ["review_memory:read"]))

    def test_learning_reviewer_cannot_write(self):
        checker = PermissionChecker()
        self.assertFalse(checker.check("learning_reviewer", ["review_memory:write"]))

    def test_orchestrator_has_all_permissions(self):
        checker = PermissionChecker()
        self.assertTrue(checker.check("review_orchestrator", [
            "pr:read", "docs:read", "review_memory:read", "review_memory:write",
        ]))

    def test_bug_reviewer_cannot_access_memory(self):
        checker = PermissionChecker()
        self.assertFalse(checker.check("bug_reviewer", ["review_memory:read"]))

    def test_write_permission_enforced(self):
        checker = PermissionChecker()
        with self.assertRaises(PermissionDeniedError):
            checker.enforce("learning_reviewer", ["review_memory:write"])


if __name__ == "__main__":
    unittest.main()
