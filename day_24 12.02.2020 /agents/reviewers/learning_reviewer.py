"""Continuous learning reviewer — analyzes historical review data to guide current reviews.

Queries the review memory for patterns of confirmed vs false positive findings,
recurring issues, and project-specific conventions. Returns guidance that the
orchestrator uses to adjust priorities and filter noise.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Set

from .review_state import ReviewFinding


@dataclass
class LearningGuidance:
    """Guidance produced by the learning reviewer for the current review."""
    # Finding messages to deprioritize (historically rejected / false positives)
    deprioritize: List[Dict[str, str]] = field(default_factory=list)
    # Finding messages to boost (historically accepted / fixed)
    boost: List[Dict[str, str]] = field(default_factory=list)
    # Inferred project conventions
    conventions: List[str] = field(default_factory=list)
    # Summary for the report
    summary: str = ""


def analyze_history(
    similar_findings: List[Dict[str, Any]],
    false_positive_patterns: List[Dict[str, Any]],
    high_value_patterns: List[Dict[str, Any]],
    conventions: List[Dict[str, Any]],
) -> LearningGuidance:
    """Analyze historical data and produce guidance for the current review.

    Args:
        similar_findings: Past findings matching current files/keywords.
        false_positive_patterns: Messages rejected >= N times.
        high_value_patterns: Messages accepted/fixed >= N times.
        conventions: Stored project conventions.

    Returns:
        LearningGuidance with deprioritize/boost lists and conventions.
    """
    guidance = LearningGuidance()

    # Build deprioritize set from known false positives
    fp_messages: Set[str] = set()
    for fp in false_positive_patterns:
        msg = fp.get("message", "")
        count = fp.get("rejected_count", 0)
        if msg:
            fp_messages.add(msg)
            guidance.deprioritize.append({
                "message": msg,
                "category": fp.get("category", ""),
                "reason": f"Historically rejected {count} time(s)",
            })

    # Build boost set from high-value patterns
    hv_messages: Set[str] = set()
    for hv in high_value_patterns:
        msg = hv.get("message", "")
        count = hv.get("confirmed_count", 0)
        if msg:
            hv_messages.add(msg)
            guidance.boost.append({
                "message": msg,
                "category": hv.get("category", ""),
                "reason": f"Confirmed important {count} time(s)",
            })

    # Also analyze similar_findings for additional signal
    # Count accept/reject ratios per message
    message_stats: Dict[str, Dict[str, int]] = {}
    for f in similar_findings:
        msg = f.get("message", "")
        lbl = f.get("label", "pending")
        if msg not in message_stats:
            message_stats[msg] = {"accepted": 0, "rejected": 0, "fixed": 0, "ignored": 0, "pending": 0}
        if lbl in message_stats[msg]:
            message_stats[msg][lbl] += 1

    for msg, stats in message_stats.items():
        total_feedback = stats["accepted"] + stats["rejected"] + stats["fixed"] + stats["ignored"]
        if total_feedback < 2:
            continue  # Not enough data
        rejected_ratio = stats["rejected"] / total_feedback if total_feedback > 0 else 0
        accepted_ratio = (stats["accepted"] + stats["fixed"]) / total_feedback if total_feedback > 0 else 0

        if rejected_ratio >= 0.7 and msg not in fp_messages:
            guidance.deprioritize.append({
                "message": msg,
                "category": "",
                "reason": f"Rejected {stats['rejected']}/{total_feedback} times",
            })
            fp_messages.add(msg)

        if accepted_ratio >= 0.7 and msg not in hv_messages:
            guidance.boost.append({
                "message": msg,
                "category": "",
                "reason": f"Confirmed {stats['accepted'] + stats['fixed']}/{total_feedback} times",
            })
            hv_messages.add(msg)

    # Gather conventions
    for conv in conventions:
        pattern = conv.get("pattern", "")
        confidence = conv.get("confidence", 0)
        if pattern and confidence >= 0.3:
            guidance.conventions.append(pattern)

    # Build summary
    parts = []
    if guidance.deprioritize:
        parts.append(f"{len(guidance.deprioritize)} pattern(s) deprioritized as likely false positives")
    if guidance.boost:
        parts.append(f"{len(guidance.boost)} pattern(s) boosted as historically important")
    if guidance.conventions:
        parts.append(f"{len(guidance.conventions)} project convention(s) applied")
    guidance.summary = "; ".join(parts) if parts else "No historical learning data available"

    return guidance


def apply_guidance(
    findings: List[ReviewFinding],
    guidance: LearningGuidance,
) -> List[ReviewFinding]:
    """Apply learning guidance to adjust finding priorities.

    - Deprioritized findings: severity downgraded (high->medium, medium->low)
    - Boosted findings: severity upgraded (low->medium, medium->high)
    - Findings matching false positive patterns are marked but NOT removed,
      keeping them visible while reducing their impact on risk calculation.

    Returns the modified findings list.
    """
    deprioritize_msgs = {d["message"] for d in guidance.deprioritize}
    boost_msgs = {b["message"] for b in guidance.boost}

    downgrade = {"high": "medium", "medium": "low", "low": "low"}
    upgrade = {"low": "medium", "medium": "high", "high": "high"}

    adjusted: List[ReviewFinding] = []
    for f in findings:
        if f.message in deprioritize_msgs:
            new_severity = downgrade.get(f.severity, f.severity)
            adjusted.append(ReviewFinding(
                category=f.category,
                severity=new_severity,
                file_path=f.file_path,
                line=f.line,
                message=f.message,
                suggestion=f.suggestion + " [deprioritized by learning]",
            ))
        elif f.message in boost_msgs:
            new_severity = upgrade.get(f.severity, f.severity)
            adjusted.append(ReviewFinding(
                category=f.category,
                severity=new_severity,
                file_path=f.file_path,
                line=f.line,
                message=f.message,
                suggestion=f.suggestion + " [boosted by learning]",
            ))
        else:
            adjusted.append(f)

    return adjusted
