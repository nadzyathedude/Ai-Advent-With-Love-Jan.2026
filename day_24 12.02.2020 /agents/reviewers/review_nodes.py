"""Graph nodes for the multi-agent PR review pipeline."""

import re
from typing import Any, Dict, List

from core.orchestration.graph import GraphState
from core.orchestration.nodes import Node

from . import bug_reviewer, style_reviewer, security_reviewer, performance_reviewer
from . import learning_reviewer
from .review_state import ReviewFinding, ReviewState


class PRFetchNode(Node):
    """Fetches the PR diff via the pr.get_diff tool and extracts changed file list."""

    def execute(self, state: GraphState, registry, agent_id: str) -> GraphState:
        if not isinstance(state, ReviewState):
            state.errors.append("PRFetchNode requires ReviewState")
            return state

        if registry is None:
            state.errors.append("No registry available for PR fetch")
            return state

        result = registry.invoke(
            "pr.get_diff", agent_id, base_branch=state.base_branch
        )
        state.tools_used.append("pr.get_diff")

        if result.success:
            state.pr_diff = result.data
            # Extract changed file paths from diff headers
            state.pr_files = re.findall(r"^\+\+\+ b/(.+)$", result.data, re.MULTILINE)
        else:
            state.errors.append(f"pr.get_diff failed: {result.error}")

        return state


class DocsContextNode(Node):
    """Fetches style documentation via docs.search_project_docs."""

    def execute(self, state: GraphState, registry, agent_id: str) -> GraphState:
        if registry is None:
            state.errors.append("No registry available for docs context")
            return state

        result = registry.invoke(
            "docs.search_project_docs",
            agent_id,
            query="code style conventions naming",
            top_k=3,
        )
        state.tools_used.append("docs.search_project_docs")

        if result.success:
            state.retrieved_docs = result.data
        else:
            state.errors.append(f"docs search failed: {result.error}")

        return state


class BugReviewNode(Node):
    """Runs bug pattern detection on the PR diff."""

    def execute(self, state: GraphState, registry, agent_id: str) -> GraphState:
        if not isinstance(state, ReviewState):
            state.errors.append("BugReviewNode requires ReviewState")
            return state

        if not state.pr_diff:
            return state

        findings = bug_reviewer.analyze_for_bugs(state.pr_diff)
        state.findings.extend(findings)
        return state


class StyleReviewNode(Node):
    """Runs style rule checking on the PR diff with docs context."""

    def execute(self, state: GraphState, registry, agent_id: str) -> GraphState:
        if not isinstance(state, ReviewState):
            state.errors.append("StyleReviewNode requires ReviewState")
            return state

        if not state.pr_diff:
            return state

        docs_context = getattr(state, "retrieved_docs", [])
        findings = style_reviewer.analyze_style(state.pr_diff, docs_context)
        state.findings.extend(findings)
        return state


class SecurityReviewNode(Node):
    """Runs security pattern scanning on the PR diff."""

    def execute(self, state: GraphState, registry, agent_id: str) -> GraphState:
        if not isinstance(state, ReviewState):
            state.errors.append("SecurityReviewNode requires ReviewState")
            return state

        if not state.pr_diff:
            return state

        findings = security_reviewer.analyze_security(state.pr_diff)
        state.findings.extend(findings)
        return state


class PerformanceReviewNode(Node):
    """Runs performance anti-pattern detection on the PR diff."""

    def execute(self, state: GraphState, registry, agent_id: str) -> GraphState:
        if not isinstance(state, ReviewState):
            state.errors.append("PerformanceReviewNode requires ReviewState")
            return state

        if not state.pr_diff:
            return state

        findings = performance_reviewer.analyze_performance(state.pr_diff)
        state.findings.extend(findings)
        return state


class ReviewMergeNode(Node):
    """Deduplicates findings, computes risk level, and formats the final report."""

    SEVERITY_ORDER = {"high": 3, "medium": 2, "low": 1}

    def execute(self, state: GraphState, registry, agent_id: str) -> GraphState:
        if not isinstance(state, ReviewState):
            state.errors.append("ReviewMergeNode requires ReviewState")
            return state

        # Deduplicate: same file + line + message = duplicate
        seen = set()
        unique: List[ReviewFinding] = []
        for f in state.findings:
            key = (f.file_path, f.line, f.message)
            if key not in seen:
                seen.add(key)
                unique.append(f)

        # Sort by severity (high first), then category, then file
        unique.sort(
            key=lambda f: (-self.SEVERITY_ORDER.get(f.severity, 0), f.category, f.file_path)
        )
        state.findings = unique

        # Compute risk level
        high_count = sum(1 for f in unique if f.severity == "high")
        medium_count = sum(1 for f in unique if f.severity == "medium")

        if high_count >= 3 or (high_count >= 1 and medium_count >= 3):
            state.risk_level = "high"
        elif high_count >= 1 or medium_count >= 3:
            state.risk_level = "medium"
        elif unique:
            state.risk_level = "low"
        else:
            state.risk_level = "none"

        # Format report
        state.review_report = self._format_report(state)
        state.final_answer = state.review_report
        return state

    @staticmethod
    def _format_report(state: ReviewState) -> str:
        lines = []
        lines.append("# PR Review Report")
        lines.append("")
        lines.append(f"**Risk Level:** {state.risk_level.upper()}")
        lines.append(f"**Files Changed:** {len(state.pr_files)}")
        lines.append(f"**Total Findings:** {len(state.findings)}")
        lines.append("")

        if not state.findings:
            lines.append("No issues found. LGTM!")
            return "\n".join(lines)

        # Group by category
        categories = {}
        for f in state.findings:
            categories.setdefault(f.category, []).append(f)

        for category, findings in sorted(categories.items()):
            lines.append(f"## {category.title()} ({len(findings)})")
            lines.append("")
            for f in findings:
                loc = f.file_path
                if f.line is not None:
                    loc += f":{f.line}"
                severity_badge = f"[{f.severity.upper()}]"
                lines.append(f"- {severity_badge} `{loc}` — {f.message}")
                lines.append(f"  - Suggestion: {f.suggestion}")
            lines.append("")

        if state.errors:
            lines.append("## Errors")
            lines.append("")
            for err in state.errors:
                lines.append(f"- {err}")
            lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Continuous learning nodes
# ---------------------------------------------------------------------------


class LearningContextNode(Node):
    """Pre-review: queries review memory for historical patterns on changed files."""

    def execute(self, state: GraphState, registry, agent_id: str) -> GraphState:
        if not isinstance(state, ReviewState):
            state.errors.append("LearningContextNode requires ReviewState")
            return state

        if registry is None:
            return state

        # Search for similar findings based on changed files
        similar: List[Dict[str, Any]] = []
        for fp in state.pr_files[:10]:  # cap to avoid flooding
            result = registry.invoke(
                "review_memory.search_similar_findings",
                agent_id,
                file_path=fp,
                limit=20,
            )
            if result.success and result.data:
                similar.extend(result.data)
            state.tools_used.append("review_memory.search_similar_findings")

        # Get project conventions and false positive patterns
        conv_result = registry.invoke(
            "review_memory.get_project_conventions",
            agent_id,
            min_confidence=0.3,
            min_rejected=2,
            min_accepted=2,
        )
        state.tools_used.append("review_memory.get_project_conventions")

        conventions: List[Dict[str, Any]] = []
        false_positives: List[Dict[str, Any]] = []
        high_value: List[Dict[str, Any]] = []
        if conv_result.success and conv_result.data:
            conventions = conv_result.data.get("conventions", [])
            false_positives = conv_result.data.get("false_positive_patterns", [])
            high_value = conv_result.data.get("high_value_patterns", [])

        state.learning_context = {
            "similar_findings": similar,
            "false_positive_patterns": false_positives,
            "high_value_patterns": high_value,
            "conventions": conventions,
        }

        return state


class LearningAdjustNode(Node):
    """Post-merge: applies learning guidance to adjust finding priorities."""

    def execute(self, state: GraphState, registry, agent_id: str) -> GraphState:
        if not isinstance(state, ReviewState):
            state.errors.append("LearningAdjustNode requires ReviewState")
            return state

        ctx = state.learning_context
        if not ctx:
            return state

        guidance = learning_reviewer.analyze_history(
            similar_findings=ctx.get("similar_findings", []),
            false_positive_patterns=ctx.get("false_positive_patterns", []),
            high_value_patterns=ctx.get("high_value_patterns", []),
            conventions=ctx.get("conventions", []),
        )

        state.findings = learning_reviewer.apply_guidance(state.findings, guidance)
        state.learning_summary = guidance.summary

        # Append conventions section to report if available
        if guidance.conventions:
            lines = ["\n## Learned Conventions\n"]
            for conv in guidance.conventions:
                lines.append(f"- {conv}")
            state.review_report += "\n".join(lines) + "\n"

        if guidance.summary:
            state.review_report += f"\n**Learning:** {guidance.summary}\n"

        state.final_answer = state.review_report
        return state


class MemoryPersistNode(Node):
    """End: stores the review run to persistent memory."""

    def execute(self, state: GraphState, registry, agent_id: str) -> GraphState:
        if not isinstance(state, ReviewState):
            state.errors.append("MemoryPersistNode requires ReviewState")
            return state

        if registry is None:
            return state

        # Build a PR identifier
        pr_id = state.pr_id or f"local-{state.base_branch}"

        # Serialize findings
        findings_data = [
            {
                "category": f.category,
                "severity": f.severity,
                "file_path": f.file_path,
                "line": f.line,
                "message": f.message,
                "suggestion": f.suggestion,
            }
            for f in state.findings
        ]

        result = registry.invoke(
            "review_memory.store_review_run",
            agent_id,
            pr_id=pr_id,
            base_branch=state.base_branch,
            files=state.pr_files,
            risk_level=state.risk_level,
            report=state.review_report,
            findings=findings_data,
        )
        state.tools_used.append("review_memory.store_review_run")

        if not result.success:
            state.errors.append(f"Memory persist failed: {result.error}")

        return state
