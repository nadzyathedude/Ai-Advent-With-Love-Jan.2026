"""Review-specific state extending GraphState with findings and report fields."""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional

from core.orchestration.graph import GraphState


@dataclass
class ReviewFinding:
    """A single review finding from a reviewer agent."""
    category: str       # "bug", "style", "security", "performance"
    severity: str       # "low", "medium", "high"
    file_path: str
    line: Optional[int]
    message: str
    suggestion: str


@dataclass
class ReviewState(GraphState):
    """Extended state for the PR review pipeline."""
    pr_diff: str = ""
    pr_files: List[str] = field(default_factory=list)
    base_branch: str = "main"
    findings: List[ReviewFinding] = field(default_factory=list)
    risk_level: str = ""
    review_report: str = ""
    # --- Continuous learning fields ---
    pr_id: str = ""                  # repo/PR# or commit SHA for memory
    learning_context: Dict[str, Any] = field(default_factory=dict)
    learning_summary: str = ""
