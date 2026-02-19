"""Tests for the multi-agent PR review system."""

import unittest

from core.orchestration.graph import END
from core.registry.tool_registry import ToolRegistry, ToolResult
from core.registry.permissions import PermissionChecker, PermissionDeniedError

from agents.reviewers.review_state import ReviewFinding, ReviewState
from agents.reviewers.bug_reviewer import analyze_for_bugs
from agents.reviewers.style_reviewer import analyze_style
from agents.reviewers.security_reviewer import analyze_security
from agents.reviewers.performance_reviewer import analyze_performance
from agents.reviewers.review_nodes import (
    PRFetchNode,
    BugReviewNode,
    StyleReviewNode,
    SecurityReviewNode,
    PerformanceReviewNode,
    ReviewMergeNode,
)
from agents.reviewers.review_orchestrator import build_review_graph, review_pr


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

DIFF_WITH_STYLE_ISSUES = """\
diff --git a/utils.py b/utils.py
--- a/utils.py
+++ b/utils.py
@@ -1,3 +1,10 @@
+from os import *
+
+def processData(x):
+    myVar = x + 1
+    # TODO fix this later
+    return myVar
+
"""

DIFF_WITH_SECURITY_ISSUES = """\
diff --git a/server.py b/server.py
--- a/server.py
+++ b/server.py
@@ -1,3 +1,12 @@
+import pickle
+import os
+
+API_KEY = "sk-1234567890abcdef"
+
+def run_cmd(cmd):
+    os.system(cmd)
+    result = eval(user_input)
+    data = pickle.loads(raw_bytes)
+    os.system(f"echo {cmd}")
"""

DIFF_WITH_PERF_ISSUES = """\
diff --git a/data.py b/data.py
--- a/data.py
+++ b/data.py
@@ -1,3 +1,10 @@
+import pandas
+import numpy
+
+def load():
+    f = open("big.txt")
+    lines = f.readlines()
+    for x in list(lines):
+        for y in list(lines):
+            pass
"""

CLEAN_DIFF = """\
diff --git a/clean.py b/clean.py
--- a/clean.py
+++ b/clean.py
@@ -1,3 +1,5 @@
+def add(a, b):
+    return a + b
"""


class TestBugReviewer(unittest.TestCase):
    """Test bug pattern detection."""

    def test_detects_bare_except(self):
        findings = analyze_for_bugs(DIFF_WITH_BUGS)
        messages = [f.message for f in findings]
        self.assertTrue(any("Bare except" in m for m in messages))

    def test_detects_mutable_default(self):
        findings = analyze_for_bugs(DIFF_WITH_BUGS)
        messages = [f.message for f in findings]
        self.assertTrue(any("Mutable default" in m for m in messages))

    def test_detects_none_comparison(self):
        findings = analyze_for_bugs(DIFF_WITH_BUGS)
        messages = [f.message for f in findings]
        self.assertTrue(any("None" in m and "==" in m for m in messages))

    def test_detects_range_len(self):
        findings = analyze_for_bugs(DIFF_WITH_BUGS)
        messages = [f.message for f in findings]
        self.assertTrue(any("range(len" in m for m in messages))

    def test_clean_diff_no_bugs(self):
        findings = analyze_for_bugs(CLEAN_DIFF)
        self.assertEqual(len(findings), 0)

    def test_finding_fields(self):
        findings = analyze_for_bugs(DIFF_WITH_BUGS)
        for f in findings:
            self.assertEqual(f.category, "bug")
            self.assertIn(f.severity, ("low", "medium", "high"))
            self.assertIsInstance(f.message, str)
            self.assertIsInstance(f.suggestion, str)


class TestStyleReviewer(unittest.TestCase):
    """Test style rule checking."""

    def test_detects_wildcard_import(self):
        findings = analyze_style(DIFF_WITH_STYLE_ISSUES)
        messages = [f.message for f in findings]
        self.assertTrue(any("Wildcard import" in m for m in messages))

    def test_detects_mixed_case_function(self):
        findings = analyze_style(DIFF_WITH_STYLE_ISSUES)
        messages = [f.message for f in findings]
        self.assertTrue(any("mixedCase" in m for m in messages))

    def test_detects_todo_comment(self):
        findings = analyze_style(DIFF_WITH_STYLE_ISSUES)
        messages = [f.message for f in findings]
        self.assertTrue(any("TODO" in m for m in messages))

    def test_clean_diff_minimal_findings(self):
        findings = analyze_style(CLEAN_DIFF)
        # Clean diff may have missing docstring finding
        high_findings = [f for f in findings if f.severity == "high"]
        self.assertEqual(len(high_findings), 0)

    def test_docs_context_integration(self):
        docs = [{"text": "Use snake_case for all function names", "source_path": "docs/style.md", "score": 1.0}]
        findings = analyze_style(DIFF_WITH_STYLE_ISSUES, docs)
        messages = [f.message for f in findings]
        self.assertTrue(any("convention" in m.lower() or "mixedCase" in m for m in messages))


class TestSecurityReviewer(unittest.TestCase):
    """Test security pattern scanning."""

    def test_detects_eval(self):
        findings = analyze_security(DIFF_WITH_SECURITY_ISSUES)
        messages = [f.message for f in findings]
        self.assertTrue(any("eval()" in m for m in messages))

    def test_detects_os_system(self):
        findings = analyze_security(DIFF_WITH_SECURITY_ISSUES)
        messages = [f.message for f in findings]
        self.assertTrue(any("os.system" in m for m in messages))

    def test_detects_hardcoded_secret(self):
        findings = analyze_security(DIFF_WITH_SECURITY_ISSUES)
        messages = [f.message for f in findings]
        self.assertTrue(any("secret" in m.lower() or "credential" in m.lower() or "hardcoded" in m.lower() for m in messages))

    def test_detects_pickle(self):
        findings = analyze_security(DIFF_WITH_SECURITY_ISSUES)
        messages = [f.message for f in findings]
        self.assertTrue(any("pickle" in m for m in messages))

    def test_clean_diff_no_security_issues(self):
        findings = analyze_security(CLEAN_DIFF)
        self.assertEqual(len(findings), 0)

    def test_all_high_severity(self):
        findings = analyze_security(DIFF_WITH_SECURITY_ISSUES)
        # Most security findings should be high severity
        high = [f for f in findings if f.severity == "high"]
        self.assertGreater(len(high), 0)


class TestPerformanceReviewer(unittest.TestCase):
    """Test performance anti-pattern detection."""

    def test_detects_heavy_imports(self):
        findings = analyze_performance(DIFF_WITH_PERF_ISSUES)
        messages = [f.message for f in findings]
        self.assertTrue(any("pandas" in m or "numpy" in m or "heavy module" in m for m in messages))

    def test_detects_readlines(self):
        findings = analyze_performance(DIFF_WITH_PERF_ISSUES)
        messages = [f.message for f in findings]
        self.assertTrue(any("readlines" in m for m in messages))

    def test_detects_in_list(self):
        findings = analyze_performance(DIFF_WITH_PERF_ISSUES)
        messages = [f.message for f in findings]
        self.assertTrue(any("in list" in m for m in messages))

    def test_clean_diff_no_perf_issues(self):
        findings = analyze_performance(CLEAN_DIFF)
        self.assertEqual(len(findings), 0)


class TestReviewMergeNode(unittest.TestCase):
    """Test deduplication, risk calculation, and report formatting."""

    def test_deduplication(self):
        state = ReviewState()
        dup = ReviewFinding("bug", "high", "app.py", 10, "Bare except", "Fix it")
        state.findings = [dup, dup, dup]

        node = ReviewMergeNode()
        state = node.execute(state, None, "test")
        self.assertEqual(len(state.findings), 1)

    def test_risk_level_high(self):
        state = ReviewState()
        state.findings = [
            ReviewFinding("bug", "high", "a.py", 1, "Bug 1", "Fix"),
            ReviewFinding("bug", "high", "a.py", 2, "Bug 2", "Fix"),
            ReviewFinding("bug", "high", "a.py", 3, "Bug 3", "Fix"),
        ]
        node = ReviewMergeNode()
        state = node.execute(state, None, "test")
        self.assertEqual(state.risk_level, "high")

    def test_risk_level_medium(self):
        state = ReviewState()
        state.findings = [
            ReviewFinding("bug", "high", "a.py", 1, "Bug 1", "Fix"),
            ReviewFinding("style", "medium", "a.py", 2, "Style 1", "Fix"),
        ]
        node = ReviewMergeNode()
        state = node.execute(state, None, "test")
        self.assertEqual(state.risk_level, "medium")

    def test_risk_level_low(self):
        state = ReviewState()
        state.findings = [
            ReviewFinding("style", "low", "a.py", 1, "Minor", "Fix"),
        ]
        node = ReviewMergeNode()
        state = node.execute(state, None, "test")
        self.assertEqual(state.risk_level, "low")

    def test_risk_level_none(self):
        state = ReviewState()
        state.findings = []
        node = ReviewMergeNode()
        state = node.execute(state, None, "test")
        self.assertEqual(state.risk_level, "none")
        self.assertIn("LGTM", state.review_report)

    def test_report_formatting(self):
        state = ReviewState()
        state.pr_files = ["app.py"]
        state.findings = [
            ReviewFinding("bug", "high", "app.py", 10, "Bare except", "Use Exception"),
            ReviewFinding("security", "high", "app.py", 15, "eval() used", "Remove eval"),
        ]
        node = ReviewMergeNode()
        state = node.execute(state, None, "test")
        self.assertIn("# PR Review Report", state.review_report)
        self.assertIn("HIGH", state.review_report)
        self.assertIn("Bug", state.review_report)
        self.assertIn("Security", state.review_report)

    def test_severity_sorting(self):
        state = ReviewState()
        state.findings = [
            ReviewFinding("style", "low", "a.py", 1, "Low issue", "Fix"),
            ReviewFinding("bug", "high", "a.py", 2, "High issue", "Fix"),
            ReviewFinding("style", "medium", "a.py", 3, "Medium issue", "Fix"),
        ]
        node = ReviewMergeNode()
        state = node.execute(state, None, "test")
        self.assertEqual(state.findings[0].severity, "high")


class TestReviewGraph(unittest.TestCase):
    """Test the graph structure and wiring."""

    def test_graph_structure(self):
        graph = build_review_graph()
        self.assertIsNotNone(graph._entry_point)
        self.assertEqual(graph._entry_point, "pr_fetch")
        self.assertIn("memory_persist", graph._edges)
        self.assertEqual(graph._edges["memory_persist"], END)

    def test_all_nodes_registered(self):
        graph = build_review_graph()
        expected_nodes = [
            "pr_fetch", "learning_context", "docs_context", "bug_review",
            "style_review", "security_review", "performance_review",
            "review_merge", "learning_adjust", "memory_persist",
        ]
        for name in expected_nodes:
            self.assertIn(name, graph._nodes)


class TestPermissionEnforcement(unittest.TestCase):
    """Test that reviewer agents have correct permissions."""

    def test_bug_reviewer_permissions(self):
        checker = PermissionChecker()
        self.assertTrue(checker.check("bug_reviewer", ["pr:read"]))

    def test_style_reviewer_permissions(self):
        checker = PermissionChecker()
        self.assertTrue(checker.check("style_reviewer", ["pr:read", "docs:read"]))

    def test_bug_reviewer_cannot_access_docs(self):
        checker = PermissionChecker()
        self.assertFalse(checker.check("bug_reviewer", ["docs:read"]))

    def test_bug_reviewer_docs_enforce_raises(self):
        checker = PermissionChecker()
        with self.assertRaises(PermissionDeniedError):
            checker.enforce("bug_reviewer", ["docs:read"])

    def test_security_reviewer_permissions(self):
        checker = PermissionChecker()
        self.assertTrue(checker.check("security_reviewer", ["pr:read"]))

    def test_performance_reviewer_permissions(self):
        checker = PermissionChecker()
        self.assertTrue(checker.check("performance_reviewer", ["pr:read"]))


class TestFullPipeline(unittest.TestCase):
    """Integration test: run review pipeline with a mock diff."""

    def test_pipeline_with_real_plugins(self):
        """Run the full pipeline against the current repo."""
        from core.registry.plugin_loader import PluginLoader

        checker = PermissionChecker()
        registry = ToolRegistry(permission_checker=checker)
        loader = PluginLoader()
        loader.load_tools(registry)

        # Verify pr tools are registered
        self.assertIsNotNone(registry.get("pr.get_diff"))
        self.assertIsNotNone(registry.get("pr.get_file_content"))

        # Run review (may produce empty diff if on main)
        report = review_pr(base_branch="HEAD", registry=registry)
        self.assertIn("PR Review Report", report)

    def test_pipeline_node_execution_order(self):
        """Verify all nodes execute in order with a mock registry."""
        from unittest.mock import MagicMock

        mock_registry = MagicMock()

        def mock_invoke(tool_name, agent_id, **kwargs):
            if tool_name == "pr.get_diff":
                return ToolResult(success=True, data=DIFF_WITH_BUGS)
            if tool_name == "docs.search_project_docs":
                return ToolResult(success=True, data=[])
            if tool_name == "review_memory.search_similar_findings":
                return ToolResult(success=True, data=[])
            if tool_name == "review_memory.get_project_conventions":
                return ToolResult(success=True, data={
                    "conventions": [], "false_positive_patterns": [], "high_value_patterns": [],
                })
            if tool_name == "review_memory.store_review_run":
                return ToolResult(success=True, data={"run_id": 1})
            return ToolResult(success=False, error="unknown tool")

        mock_registry.invoke.side_effect = mock_invoke

        graph = build_review_graph()
        state = ReviewState(base_branch="main")
        state = graph.run(state, registry=mock_registry, agent_id="review_orchestrator")

        expected = [
            "pr_fetch", "learning_context", "docs_context", "bug_review",
            "style_review", "security_review", "performance_review",
            "review_merge", "learning_adjust", "memory_persist",
        ]
        self.assertEqual(state.nodes_executed, expected)
        self.assertGreater(len(state.findings), 0)
        self.assertIn("PR Review Report", state.review_report)


if __name__ == "__main__":
    unittest.main()
