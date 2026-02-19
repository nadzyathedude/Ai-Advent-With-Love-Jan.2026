"""Support memory tools — SQLite-backed persistent store for customer interaction history.

Stores conversations, issue summaries, and per-user context across sessions.
Supports ephemeral mode (in-memory DB) when persistent storage is unavailable.
Includes automatic summarization of old interactions to control memory growth.
"""

import json
import os
import re
import sqlite3
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.registry.tool_registry import Tool, ToolResult


# ---------------------------------------------------------------------------
# Schema & migration
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS interactions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER NOT NULL,
    conversation_id   TEXT NOT NULL,
    timestamp         REAL NOT NULL,
    user_message      TEXT NOT NULL,
    assistant_response TEXT NOT NULL DEFAULT '',
    issue_summary     TEXT NOT NULL DEFAULT '',
    category          TEXT NOT NULL DEFAULT 'general',
    resolution_status TEXT NOT NULL DEFAULT 'pending',
    meta_json         TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS user_summaries (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL UNIQUE,
    summary             TEXT NOT NULL DEFAULT '',
    recurring_issues_json TEXT NOT NULL DEFAULT '[]',
    key_facts_json      TEXT NOT NULL DEFAULT '[]',
    interaction_count   INTEGER NOT NULL DEFAULT 0,
    updated_at          REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_interactions_user_id ON interactions(user_id);
CREATE INDEX IF NOT EXISTS idx_interactions_conversation_id ON interactions(conversation_id);
CREATE INDEX IF NOT EXISTS idx_interactions_category ON interactions(category);
CREATE INDEX IF NOT EXISTS idx_interactions_timestamp ON interactions(timestamp);
"""

# Maximum recent interactions to keep as raw entries before summarizing
SUMMARIZE_THRESHOLD = 20
# Number of most recent interactions to keep raw (rest get summarized)
KEEP_RECENT = 10

# ---------------------------------------------------------------------------
# Category detection
# ---------------------------------------------------------------------------

CATEGORY_KEYWORDS = {
    "auth": {"login", "password", "mfa", "sso", "authentication", "credentials",
             "log in", "sign in", "2fa", "reset password", "forgot password",
             "unauthorized", "401"},
    "billing": {"billing", "invoice", "payment", "subscription", "refund",
                "charge", "plan", "upgrade", "downgrade", "cancel", "price",
                "cost", "credit card"},
    "api": {"api", "endpoint", "rate limit", "429", "webhook", "sdk",
            "rest", "authorization header", "api key", "token"},
    "performance": {"slow", "performance", "timeout", "loading", "speed",
                    "latency", "hang", "stuck", "freeze", "lag"},
    "integration": {"integration", "sso", "oauth", "saml", "sync",
                    "connector", "webhook", "third-party", "plugin"},
}


def detect_category(text: str) -> str:
    """Detect issue category from text using keyword matching."""
    text_lower = text.lower()
    scores: Dict[str, int] = {}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            scores[cat] = score
    if not scores:
        return "general"
    return max(scores, key=scores.get)


def extract_summary(user_message: str, assistant_response: str) -> str:
    """Extract a brief issue summary from the interaction."""
    # Use the user message as the base, truncated
    msg = user_message.strip()
    if len(msg) > 200:
        msg = msg[:200] + "..."

    # Try to extract a resolution hint from the response
    response_lower = assistant_response.lower()
    resolution_hints = []
    for keyword in ["resolved", "fixed", "solution", "try ", "workaround", "steps"]:
        if keyword in response_lower:
            resolution_hints.append(keyword)

    summary = f"Issue: {msg}"
    if resolution_hints:
        summary += f" (response mentions: {', '.join(resolution_hints[:3])})"
    return summary


# ---------------------------------------------------------------------------
# DB path resolution
# ---------------------------------------------------------------------------

def _resolve_db_path(db_path: Optional[str] = None) -> str:
    """Determine the database path. Returns ':memory:' as last resort."""
    if db_path:
        return db_path
    env_path = os.environ.get("SUPPORT_MEMORY_DB")
    if env_path:
        return env_path
    base = Path(__file__).resolve().parents[2]
    default = base / "support_memory.db"
    return str(default)


class SupportMemoryDB:
    """SQLite wrapper for the customer interaction memory store."""

    def __init__(self, db_path: Optional[str] = None):
        resolved = _resolve_db_path(db_path)
        self._ephemeral = resolved == ":memory:"
        try:
            self._conn = sqlite3.connect(resolved)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._migrate()
        except sqlite3.OperationalError:
            print(
                f"[support_memory] WARNING: Cannot open {resolved}, using ephemeral in-memory DB",
                file=sys.stderr,
            )
            self._conn = sqlite3.connect(":memory:")
            self._conn.row_factory = sqlite3.Row
            self._ephemeral = True
            self._migrate()

    @property
    def ephemeral(self) -> bool:
        return self._ephemeral

    def _migrate(self) -> None:
        self._conn.executescript(SCHEMA_SQL)
        existing = self._conn.execute(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        ).fetchone()
        if not existing:
            self._conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,)
            )
        self._conn.commit()

    # -- write operations --------------------------------------------------

    def store_interaction(
        self,
        user_id: int,
        user_message: str,
        assistant_response: str = "",
        issue_summary: str = "",
        category: str = "",
        resolution_status: str = "pending",
        conversation_id: str = "",
        meta: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Store a support interaction. Auto-detects category and summary if not provided."""
        now = time.time()
        if not conversation_id:
            conversation_id = str(uuid.uuid4())[:8]
        if not category:
            category = detect_category(user_message + " " + assistant_response)
        if not issue_summary:
            issue_summary = extract_summary(user_message, assistant_response)

        cur = self._conn.execute(
            """INSERT INTO interactions
               (user_id, conversation_id, timestamp, user_message, assistant_response,
                issue_summary, category, resolution_status, meta_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                conversation_id,
                now,
                user_message[:5000],  # cap message size
                assistant_response[:10000],  # cap response size
                issue_summary[:500],
                category,
                resolution_status,
                json.dumps(meta or {}),
            ),
        )
        self._conn.commit()
        interaction_id = cur.lastrowid

        # Trigger summarization check
        self._maybe_summarize(user_id)

        return interaction_id

    def _maybe_summarize(self, user_id: int) -> None:
        """Summarize old interactions if count exceeds threshold."""
        count = self._conn.execute(
            "SELECT COUNT(*) FROM interactions WHERE user_id = ?", (user_id,)
        ).fetchone()[0]

        if count <= SUMMARIZE_THRESHOLD:
            return

        # Get all interactions ordered by timestamp
        rows = self._conn.execute(
            """SELECT id, timestamp, user_message, issue_summary, category,
                      resolution_status
               FROM interactions
               WHERE user_id = ?
               ORDER BY timestamp ASC""",
            (user_id,),
        ).fetchall()

        # Keep the most recent KEEP_RECENT, summarize the rest
        to_summarize = rows[:-KEEP_RECENT]
        if not to_summarize:
            return

        # Build summary from old interactions
        categories: Dict[str, int] = {}
        issues: List[str] = []
        for row in to_summarize:
            cat = row["category"]
            categories[cat] = categories.get(cat, 0) + 1
            summary = row["issue_summary"]
            if summary and summary not in issues:
                issues.append(summary)

        # Build recurring issues list (categories with 2+ occurrences)
        recurring = [
            {"category": cat, "count": cnt}
            for cat, cnt in sorted(categories.items(), key=lambda x: -x[1])
            if cnt >= 2
        ]

        # Build key facts from summaries (keep most recent unique ones)
        key_facts = issues[-10:]  # keep last 10 unique summaries

        # Compose summary text
        summary_parts = [
            f"User has had {len(to_summarize)} past support interactions.",
        ]
        if recurring:
            top_cats = ", ".join(f"{r['category']} ({r['count']}x)" for r in recurring[:5])
            summary_parts.append(f"Recurring issue categories: {top_cats}.")
        if key_facts:
            summary_parts.append("Recent past issues: " + "; ".join(key_facts[-5:]))

        summary_text = " ".join(summary_parts)

        # Upsert user summary
        now = time.time()
        existing = self._conn.execute(
            "SELECT id FROM user_summaries WHERE user_id = ?", (user_id,)
        ).fetchone()

        if existing:
            self._conn.execute(
                """UPDATE user_summaries
                   SET summary = ?, recurring_issues_json = ?, key_facts_json = ?,
                       interaction_count = ?, updated_at = ?
                   WHERE user_id = ?""",
                (
                    summary_text,
                    json.dumps(recurring),
                    json.dumps(key_facts),
                    count,
                    now,
                    user_id,
                ),
            )
        else:
            self._conn.execute(
                """INSERT INTO user_summaries
                   (user_id, summary, recurring_issues_json, key_facts_json,
                    interaction_count, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    user_id,
                    summary_text,
                    json.dumps(recurring),
                    json.dumps(key_facts),
                    count,
                    now,
                ),
            )

        # Delete summarized interactions
        ids_to_delete = [row["id"] for row in to_summarize]
        placeholders = ",".join("?" * len(ids_to_delete))
        self._conn.execute(
            f"DELETE FROM interactions WHERE id IN ({placeholders})",
            ids_to_delete,
        )
        self._conn.commit()

    # -- read operations ---------------------------------------------------

    def get_user_history(
        self,
        user_id: int,
        limit: int = 10,
    ) -> Dict[str, Any]:
        """Get recent interactions and summary for a user."""
        # Get recent interactions
        rows = self._conn.execute(
            """SELECT id, conversation_id, timestamp, user_message,
                      assistant_response, issue_summary, category,
                      resolution_status
               FROM interactions
               WHERE user_id = ?
               ORDER BY timestamp DESC
               LIMIT ?""",
            (user_id, limit),
        ).fetchall()
        recent = [dict(row) for row in rows]

        # Get user summary if available
        summary_row = self._conn.execute(
            """SELECT summary, recurring_issues_json, key_facts_json,
                      interaction_count, updated_at
               FROM user_summaries
               WHERE user_id = ?""",
            (user_id,),
        ).fetchone()

        summary = None
        if summary_row:
            summary = {
                "summary": summary_row["summary"],
                "recurring_issues": json.loads(summary_row["recurring_issues_json"]),
                "key_facts": json.loads(summary_row["key_facts_json"]),
                "interaction_count": summary_row["interaction_count"],
            }

        # Count total interactions (current + summarized)
        current_count = self._conn.execute(
            "SELECT COUNT(*) FROM interactions WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
        total = current_count
        if summary:
            total = max(summary["interaction_count"], current_count)

        return {
            "user_id": user_id,
            "total_interactions": total,
            "recent": recent,
            "summary": summary,
        }

    def search_past_issues(
        self,
        user_id: int,
        query: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search past interactions for a user by keyword in message or summary."""
        rows = self._conn.execute(
            """SELECT id, conversation_id, timestamp, user_message,
                      issue_summary, category, resolution_status
               FROM interactions
               WHERE user_id = ?
                 AND (user_message LIKE ? OR issue_summary LIKE ?)
               ORDER BY timestamp DESC
               LIMIT ?""",
            (user_id, f"%{query}%", f"%{query}%", limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def delete_user_history(self, user_id: int) -> int:
        """Delete all interactions and summaries for a user. Returns count deleted."""
        count = self._conn.execute(
            "SELECT COUNT(*) FROM interactions WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
        self._conn.execute(
            "DELETE FROM interactions WHERE user_id = ?", (user_id,)
        )
        self._conn.execute(
            "DELETE FROM user_summaries WHERE user_id = ?", (user_id,)
        )
        self._conn.commit()
        return count

    def close(self) -> None:
        self._conn.close()


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_db_instance: Optional[SupportMemoryDB] = None


def get_db(db_path: Optional[str] = None) -> SupportMemoryDB:
    global _db_instance
    if _db_instance is None:
        _db_instance = SupportMemoryDB(db_path)
    return _db_instance


def reset_db() -> None:
    """Reset the singleton (for testing)."""
    global _db_instance
    if _db_instance is not None:
        _db_instance.close()
    _db_instance = None


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


class StoreInteractionTool(Tool):
    """Stores a support interaction in the customer memory."""

    @property
    def name(self) -> str:
        return "support_memory.store_interaction"

    @property
    def description(self) -> str:
        return "Store a support interaction (user message + response) in persistent customer memory."

    @property
    def required_permissions(self) -> List[str]:
        return ["support_memory:write"]

    def execute(self, **kwargs) -> ToolResult:
        user_id = kwargs.get("user_id")
        user_message = kwargs.get("user_message", "")
        if user_id is None:
            return ToolResult(success=False, error="Missing required argument: user_id")
        if not user_message:
            return ToolResult(success=False, error="Missing required argument: user_message")
        db = get_db()
        interaction_id = db.store_interaction(
            user_id=int(user_id),
            user_message=user_message,
            assistant_response=kwargs.get("assistant_response", ""),
            issue_summary=kwargs.get("issue_summary", ""),
            category=kwargs.get("category", ""),
            resolution_status=kwargs.get("resolution_status", "pending"),
            conversation_id=kwargs.get("conversation_id", ""),
            meta=kwargs.get("meta"),
        )
        return ToolResult(
            success=True,
            data={"interaction_id": interaction_id, "ephemeral": db.ephemeral},
        )


class GetUserHistoryTool(Tool):
    """Retrieves recent interaction history and summary for a user."""

    @property
    def name(self) -> str:
        return "support_memory.get_user_history"

    @property
    def description(self) -> str:
        return "Get recent conversation history and summarized past issues for a user."

    @property
    def required_permissions(self) -> List[str]:
        return ["support_memory:read"]

    def execute(self, **kwargs) -> ToolResult:
        user_id = kwargs.get("user_id")
        if user_id is None:
            return ToolResult(success=False, error="Missing required argument: user_id")
        db = get_db()
        data = db.get_user_history(
            user_id=int(user_id),
            limit=kwargs.get("limit", 10),
        )
        return ToolResult(success=True, data=data)


class SearchPastIssuesTool(Tool):
    """Searches a user's past interactions by keyword."""

    @property
    def name(self) -> str:
        return "support_memory.search_past_issues"

    @property
    def description(self) -> str:
        return "Search a user's past support interactions by keyword."

    @property
    def required_permissions(self) -> List[str]:
        return ["support_memory:read"]

    def execute(self, **kwargs) -> ToolResult:
        user_id = kwargs.get("user_id")
        query = kwargs.get("query", "")
        if user_id is None:
            return ToolResult(success=False, error="Missing required argument: user_id")
        if not query:
            return ToolResult(success=False, error="Missing required argument: query")
        db = get_db()
        results = db.search_past_issues(
            user_id=int(user_id),
            query=query,
            limit=kwargs.get("limit", 10),
        )
        return ToolResult(success=True, data=results)
