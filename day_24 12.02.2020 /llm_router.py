"""Intent detection via keyword scoring — routes user queries to the appropriate
assistant pipeline without any external AI dependency.

Supported intents:
  knowledge   — documentation/architecture questions
  task_create — create a new task
  status      — project/task status inquiry
  prioritize  — ask for priority recommendations
  combined    — multiple intents detected
"""

from typing import Dict, List, Tuple


# ---------------------------------------------------------------------------
# Keyword sets per intent
# ---------------------------------------------------------------------------

INTENT_KEYWORDS: Dict[str, Dict[str, float]] = {
    "knowledge": {
        "architecture": 2.0, "docs": 1.5, "documentation": 1.5, "design": 1.5,
        "how": 1.0, "what": 1.0, "explain": 1.5, "overview": 1.5,
        "structure": 1.5, "module": 1.0, "component": 1.0, "plugin": 1.0,
        "pattern": 1.0, "pipeline": 1.0, "graph": 1.0, "workflow": 1.0,
    },
    "task_create": {
        "create": 3.0, "add": 2.5, "new": 2.0, "task": 2.0,
        "todo": 2.0, "ticket": 1.5, "assign": 1.5, "schedule": 1.0,
    },
    "status": {
        "status": 3.0, "progress": 2.0, "report": 1.5, "overview": 1.0,
        "blocked": 2.0, "overdue": 2.0, "done": 1.5, "completed": 1.5,
        "remaining": 1.5, "list": 1.5, "show": 1.0, "tasks": 1.5,
    },
    "prioritize": {
        "priority": 3.0, "prioritize": 3.0, "priorities": 3.0,
        "suggest": 2.0, "recommend": 2.0, "next": 1.5, "first": 1.5,
        "important": 1.5, "urgent": 2.0, "focus": 1.5, "order": 1.0,
    },
}

# Minimum score threshold to consider an intent active
MIN_SCORE = 2.0


def detect_intent(question: str) -> Tuple[str, Dict[str, float]]:
    """Detect the primary intent from a question string.

    Returns (intent_name, {intent: score, ...}) where intent_name is one of:
    knowledge, task_create, status, prioritize, or combined.
    """
    words = question.lower().split()
    scores: Dict[str, float] = {}

    for intent, keywords in INTENT_KEYWORDS.items():
        total = 0.0
        for word in words:
            if word in keywords:
                total += keywords[word]
        if total >= MIN_SCORE:
            scores[intent] = round(total, 2)

    if not scores:
        # Default to knowledge if nothing matches
        return "knowledge", {"knowledge": 0.0}

    if len(scores) > 1:
        return "combined", scores

    intent = max(scores, key=scores.get)
    return intent, scores
