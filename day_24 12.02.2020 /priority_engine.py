"""Priority engine — rule-based task scoring and recommendation.

Weighted formula:
  due_date  0.30  (urgency from deadline proximity)
  priority  0.25  (critical/high/medium/low mapping)
  blockers  0.20  (how many tasks depend on this one)
  effort    0.15  (smaller effort = quicker wins)
  status    0.10  (in_progress > todo > blocked)

Produces a sorted list of tasks with numeric scores and reasoning strings.
"""

import datetime
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Weight configuration
# ---------------------------------------------------------------------------

WEIGHTS = {
    "due_date": 0.30,
    "priority": 0.25,
    "blockers": 0.20,
    "effort": 0.15,
    "status": 0.10,
}

PRIORITY_SCORES = {
    "critical": 1.0,
    "high": 0.75,
    "medium": 0.50,
    "low": 0.25,
}

EFFORT_SCORES = {
    "small": 1.0,
    "medium": 0.65,
    "large": 0.35,
    "xlarge": 0.15,
}

STATUS_SCORES = {
    "in_progress": 1.0,
    "todo": 0.60,
    "blocked": 0.20,
    "done": 0.0,
}


# ---------------------------------------------------------------------------
# Scoring functions
# ---------------------------------------------------------------------------


def score_due_date(due_date: Optional[str]) -> float:
    """Score based on deadline urgency. Closer deadlines score higher."""
    if not due_date:
        return 0.3  # No deadline — moderate baseline
    try:
        due = datetime.date.fromisoformat(due_date)
    except (ValueError, TypeError):
        return 0.3
    today = datetime.date.today()
    days_left = (due - today).days
    if days_left < 0:
        return 1.0  # Overdue
    if days_left == 0:
        return 0.95
    if days_left <= 3:
        return 0.85
    if days_left <= 7:
        return 0.65
    if days_left <= 14:
        return 0.45
    return 0.25


def score_priority(priority: str) -> float:
    """Map priority level to a score."""
    return PRIORITY_SCORES.get(priority, 0.50)


def score_blockers(task: Dict[str, Any], all_tasks: List[Dict[str, Any]]) -> float:
    """Score based on how many other tasks depend on this task."""
    task_id = task.get("id")
    if task_id is None:
        return 0.0
    blocked_count = 0
    for other in all_tasks:
        deps = other.get("depends_on", [])
        if isinstance(deps, list) and task_id in deps:
            blocked_count += 1
    if blocked_count >= 3:
        return 1.0
    if blocked_count == 2:
        return 0.75
    if blocked_count == 1:
        return 0.50
    return 0.10


def score_effort(effort: str) -> float:
    """Smaller effort = quicker wins = higher score."""
    return EFFORT_SCORES.get(effort, 0.50)


def score_status(status: str) -> float:
    """In-progress tasks get priority to avoid context switching."""
    return STATUS_SCORES.get(status, 0.50)


# ---------------------------------------------------------------------------
# Main scoring
# ---------------------------------------------------------------------------


def compute_task_score(task: Dict[str, Any], all_tasks: List[Dict[str, Any]]) -> float:
    """Compute a weighted score for a single task."""
    s_due = score_due_date(task.get("due_date"))
    s_pri = score_priority(task.get("priority", "medium"))
    s_blk = score_blockers(task, all_tasks)
    s_eff = score_effort(task.get("effort", "medium"))
    s_sta = score_status(task.get("status", "todo"))

    total = (
        WEIGHTS["due_date"] * s_due
        + WEIGHTS["priority"] * s_pri
        + WEIGHTS["blockers"] * s_blk
        + WEIGHTS["effort"] * s_eff
        + WEIGHTS["status"] * s_sta
    )
    return round(total, 4)


def build_reasoning(task: Dict[str, Any], all_tasks: List[Dict[str, Any]]) -> str:
    """Build a human-readable reasoning string for the task's score."""
    reasons = []

    # Priority
    priority = task.get("priority", "medium")
    if priority == "critical":
        reasons.append("CRITICAL priority")
    elif priority == "high":
        reasons.append("high priority")

    # Due date
    due = task.get("due_date")
    if due:
        try:
            days_left = (datetime.date.fromisoformat(due) - datetime.date.today()).days
            if days_left < 0:
                reasons.append(f"OVERDUE by {abs(days_left)} day(s)")
            elif days_left == 0:
                reasons.append("due TODAY")
            elif days_left <= 3:
                reasons.append(f"due in {days_left} day(s)")
            elif days_left <= 7:
                reasons.append(f"due this week ({due})")
        except (ValueError, TypeError):
            pass

    # Blockers
    task_id = task.get("id")
    if task_id is not None:
        blocked_count = sum(
            1 for t in all_tasks
            if isinstance(t.get("depends_on", []), list) and task_id in t.get("depends_on", [])
        )
        if blocked_count > 0:
            reasons.append(f"blocks {blocked_count} other task(s)")

    # Status
    status = task.get("status", "todo")
    if status == "in_progress":
        reasons.append("already in progress")
    elif status == "blocked":
        blocked_by = task.get("blocked_by", "")
        reasons.append(f"BLOCKED: {blocked_by}" if blocked_by else "BLOCKED")

    # Effort
    effort = task.get("effort", "medium")
    if effort == "small":
        reasons.append("quick win (small effort)")

    return "; ".join(reasons) if reasons else "standard priority"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def prioritize_tasks(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Score and sort tasks by priority. Returns list with score and reasoning."""
    active = [t for t in tasks if t.get("status") != "done"]
    scored = []
    for task in active:
        score = compute_task_score(task, tasks)
        reasoning = build_reasoning(task, tasks)
        scored.append({
            "task": task,
            "score": score,
            "reasoning": reasoning,
        })
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


def get_recommendation(scored_tasks: List[Dict[str, Any]]) -> str:
    """Build a recommendation string from scored tasks."""
    if not scored_tasks:
        return "No active tasks to prioritize."

    lines = ["## Priority Recommendations", ""]

    for i, item in enumerate(scored_tasks, 1):
        task = item["task"]
        score = item["score"]
        reasoning = item["reasoning"]
        status_badge = f"[{task['status'].upper()}]"
        prio_badge = f"({task['priority']})"
        lines.append(
            f"{i}. **{task['title']}** {status_badge} {prio_badge} — score: {score}"
        )
        lines.append(f"   {reasoning}")
        lines.append("")

    top = scored_tasks[0]
    lines.append(f"**Recommendation:** Start with \"{top['task']['title']}\" — {top['reasoning']}.")
    return "\n".join(lines)
