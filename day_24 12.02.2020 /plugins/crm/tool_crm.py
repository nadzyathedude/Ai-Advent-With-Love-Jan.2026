"""CRM tools — SQLite-backed simulated CRM with user and ticket data.

Provides read-only access to user profiles, support tickets, and ticket history.
Supports ephemeral mode (in-memory DB) when persistent storage is unavailable.
"""

import os
import sqlite3
import sys
import time
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

CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    email      TEXT NOT NULL,
    plan       TEXT NOT NULL DEFAULT 'free',
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS tickets (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    subject    TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'open',
    priority   TEXT NOT NULL DEFAULT 'medium',
    category   TEXT NOT NULL DEFAULT 'general',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS ticket_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id  INTEGER NOT NULL REFERENCES tickets(id),
    timestamp  REAL NOT NULL,
    action     TEXT NOT NULL,
    details    TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_tickets_user_id ON tickets(user_id);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
CREATE INDEX IF NOT EXISTS idx_tickets_category ON tickets(category);
CREATE INDEX IF NOT EXISTS idx_ticket_history_ticket_id ON ticket_history(ticket_id);
"""

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_USERS = [
    ("Alice Johnson", "alice@example.com", "pro", 1700000000.0),
    ("Bob Smith", "bob@example.com", "free", 1701000000.0),
    ("Carol White", "carol@example.com", "enterprise", 1702000000.0),
    ("Dave Brown", "dave@example.com", "pro", 1703000000.0),
    ("Eve Davis", "eve@example.com", "free", 1704000000.0),
    ("Frank Miller", "frank@example.com", "enterprise", 1705000000.0),
    ("Grace Wilson", "grace@example.com", "pro", 1706000000.0),
    ("Hank Taylor", "hank@example.com", "free", 1707000000.0),
]

SAMPLE_TICKETS = [
    # (user_id, subject, status, priority, category, created_at, updated_at)
    (1, "Cannot log in after password reset", "open", "high", "login", 1708000000.0, 1708100000.0),
    (1, "Dashboard loading slowly", "resolved", "medium", "performance", 1707500000.0, 1707800000.0),
    (2, "How to upgrade from free plan?", "open", "low", "billing", 1708200000.0, 1708200000.0),
    (2, "API rate limit exceeded unexpectedly", "open", "high", "api", 1708300000.0, 1708350000.0),
    (3, "SSO integration not working", "in_progress", "high", "integration", 1708100000.0, 1708400000.0),
    (3, "Need invoice for last quarter", "resolved", "low", "billing", 1707000000.0, 1707200000.0),
    (3, "Webhook events missing payloads", "open", "medium", "api", 1708500000.0, 1708500000.0),
    (4, "MFA setup fails on mobile", "open", "medium", "login", 1708400000.0, 1708450000.0),
    (4, "Export data stuck at 50%", "in_progress", "medium", "performance", 1708350000.0, 1708400000.0),
    (5, "Cannot cancel subscription", "open", "high", "billing", 1708500000.0, 1708500000.0),
    (5, "Error 429 when calling /users endpoint", "resolved", "medium", "api", 1707800000.0, 1708000000.0),
    (6, "Enterprise API key rotation", "resolved", "low", "api", 1707600000.0, 1707900000.0),
    (6, "Team member permissions not syncing", "open", "high", "integration", 1708600000.0, 1708600000.0),
    (7, "Refund for double charge", "in_progress", "high", "billing", 1708400000.0, 1708550000.0),
    (7, "Search feature returns wrong results", "open", "medium", "performance", 1708500000.0, 1708500000.0),
    (8, "Password reset email not received", "open", "medium", "login", 1708600000.0, 1708600000.0),
    (8, "How to set up webhooks?", "resolved", "low", "general", 1707400000.0, 1707500000.0),
    (8, "API authentication fails with new key", "open", "high", "api", 1708700000.0, 1708700000.0),
]

SAMPLE_HISTORY = [
    # (ticket_id, timestamp, action, details)
    (1, 1708000000.0, "created", "User reported login failure after password reset"),
    (1, 1708050000.0, "assigned", "Assigned to support team"),
    (1, 1708100000.0, "comment", "Requested browser and OS details from user"),
    (2, 1707500000.0, "created", "User reported slow dashboard loading"),
    (2, 1707600000.0, "assigned", "Assigned to performance team"),
    (2, 1707700000.0, "comment", "Identified slow query in analytics module"),
    (2, 1707800000.0, "resolved", "Optimized query, response time improved from 8s to 0.5s"),
    (3, 1708200000.0, "created", "User asked about upgrading plan"),
    (4, 1708300000.0, "created", "Rate limit hit at 50 requests, expected 100"),
    (4, 1708320000.0, "escalated", "Escalated to API team for investigation"),
    (4, 1708350000.0, "comment", "Free plan limit is 50/min, user needs to upgrade for higher limits"),
    (5, 1708100000.0, "created", "SSO SAML integration returning invalid response"),
    (5, 1708200000.0, "assigned", "Assigned to integrations team"),
    (5, 1708300000.0, "comment", "Identified certificate mismatch in SAML config"),
    (5, 1708400000.0, "in_progress", "Working with customer to update certificates"),
    (6, 1707000000.0, "created", "Invoice request for Q3"),
    (6, 1707100000.0, "comment", "Invoice generated and sent to billing email"),
    (6, 1707200000.0, "resolved", "Customer confirmed receipt"),
    (7, 1708500000.0, "created", "Webhook POST events missing request body"),
    (8, 1708400000.0, "created", "MFA QR code not scanning on iOS"),
    (8, 1708420000.0, "comment", "Suggested manual key entry as workaround"),
    (8, 1708450000.0, "comment", "User confirmed manual entry works, investigating QR issue"),
    (9, 1708350000.0, "created", "CSV export hangs at 50%"),
    (9, 1708380000.0, "in_progress", "Investigating memory limits on export worker"),
    (9, 1708400000.0, "comment", "Increased worker memory, re-processing export"),
    (10, 1708500000.0, "created", "Cancel button returns 500 error"),
    (11, 1707800000.0, "created", "429 errors on /users endpoint"),
    (11, 1707900000.0, "comment", "User was polling every second, suggested reducing frequency"),
    (11, 1708000000.0, "resolved", "User adjusted polling interval to 30s"),
    (12, 1707600000.0, "created", "Requesting API key rotation for compliance"),
    (12, 1707700000.0, "comment", "Keys rotated, old keys revoked"),
    (12, 1707900000.0, "resolved", "Customer confirmed new keys working"),
    (13, 1708600000.0, "created", "Team members added via admin panel not appearing in project"),
    (14, 1708400000.0, "created", "Double charge on Feb invoice"),
    (14, 1708450000.0, "assigned", "Assigned to billing team"),
    (14, 1708500000.0, "in_progress", "Processing refund for duplicate charge"),
    (14, 1708550000.0, "comment", "Refund initiated, 3-5 business days to process"),
    (15, 1708500000.0, "created", "Full-text search returning irrelevant results"),
    (16, 1708600000.0, "created", "Password reset email not arriving"),
    (17, 1707400000.0, "created", "Webhook setup question"),
    (17, 1707450000.0, "comment", "Provided webhook documentation link and example"),
    (17, 1707500000.0, "resolved", "User successfully configured webhooks"),
    (18, 1708700000.0, "created", "New API key returns 401 on all endpoints"),
]


def _resolve_db_path(db_path: Optional[str] = None) -> str:
    """Determine the database path. Returns ':memory:' as last resort."""
    if db_path:
        return db_path
    env_path = os.environ.get("CRM_DB")
    if env_path:
        return env_path
    base = Path(__file__).resolve().parents[2]
    default = base / "crm.db"
    return str(default)


class CrmDB:
    """SQLite wrapper for the simulated CRM store."""

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
                f"[crm] WARNING: Cannot open {resolved}, using ephemeral in-memory DB",
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
        self._populate_sample_data()

    def _populate_sample_data(self) -> None:
        """Insert sample data if users table is empty."""
        count = self._conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count > 0:
            return
        for name, email, plan, created_at in SAMPLE_USERS:
            self._conn.execute(
                "INSERT INTO users (name, email, plan, created_at) VALUES (?, ?, ?, ?)",
                (name, email, plan, created_at),
            )
        for user_id, subject, status, priority, category, created_at, updated_at in SAMPLE_TICKETS:
            self._conn.execute(
                """INSERT INTO tickets (user_id, subject, status, priority, category,
                   created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (user_id, subject, status, priority, category, created_at, updated_at),
            )
        for ticket_id, timestamp, action, details in SAMPLE_HISTORY:
            self._conn.execute(
                "INSERT INTO ticket_history (ticket_id, timestamp, action, details) VALUES (?, ?, ?, ?)",
                (ticket_id, timestamp, action, details),
            )
        self._conn.commit()

    # -- read operations ---------------------------------------------------

    def get_user_tickets(
        self,
        user_id: int,
        status: Optional[str] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """Get user profile and their tickets."""
        user_row = self._conn.execute(
            "SELECT id, name, email, plan, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not user_row:
            return {"error": f"User {user_id} not found"}

        user = dict(user_row)
        clauses = ["t.user_id = ?"]
        params: list = [user_id]
        if status:
            clauses.append("t.status = ?")
            params.append(status)
        params.append(limit)
        where = " AND ".join(clauses)
        rows = self._conn.execute(
            f"""SELECT t.id, t.subject, t.status, t.priority, t.category,
                       t.created_at, t.updated_at
                FROM tickets t
                WHERE {where}
                ORDER BY t.updated_at DESC
                LIMIT ?""",
            params,
        ).fetchall()
        tickets = [dict(row) for row in rows]
        return {"user": user, "tickets": tickets}

    def get_ticket_details(self, ticket_id: int) -> Dict[str, Any]:
        """Get full ticket details including history."""
        ticket_row = self._conn.execute(
            """SELECT t.id, t.user_id, t.subject, t.status, t.priority, t.category,
                      t.created_at, t.updated_at, u.name as user_name, u.email as user_email,
                      u.plan as user_plan
               FROM tickets t
               JOIN users u ON t.user_id = u.id
               WHERE t.id = ?""",
            (ticket_id,),
        ).fetchone()
        if not ticket_row:
            return {"error": f"Ticket {ticket_id} not found"}

        ticket = dict(ticket_row)
        history_rows = self._conn.execute(
            """SELECT id, timestamp, action, details
               FROM ticket_history
               WHERE ticket_id = ?
               ORDER BY timestamp ASC""",
            (ticket_id,),
        ).fetchall()
        ticket["history"] = [dict(row) for row in history_rows]
        return ticket

    def search_similar_issues(
        self,
        query: str,
        category: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search tickets by keyword in subject, optionally filtered by category."""
        clauses = ["t.subject LIKE ?"]
        params: list = [f"%{query}%"]
        if category:
            clauses.append("t.category = ?")
            params.append(category)
        params.append(limit)
        where = " AND ".join(clauses)
        rows = self._conn.execute(
            f"""SELECT t.id, t.user_id, t.subject, t.status, t.priority, t.category,
                       t.created_at, t.updated_at, u.name as user_name
                FROM tickets t
                JOIN users u ON t.user_id = u.id
                WHERE {where}
                ORDER BY t.updated_at DESC
                LIMIT ?""",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        self._conn.close()


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_db_instance: Optional[CrmDB] = None


def get_db(db_path: Optional[str] = None) -> CrmDB:
    global _db_instance
    if _db_instance is None:
        _db_instance = CrmDB(db_path)
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


class GetUserTicketsTool(Tool):
    """Retrieves a user profile and their support tickets."""

    @property
    def name(self) -> str:
        return "crm.get_user_tickets"

    @property
    def description(self) -> str:
        return "Get a user profile and their support tickets from the CRM."

    @property
    def required_permissions(self) -> List[str]:
        return ["crm:read"]

    def execute(self, **kwargs) -> ToolResult:
        user_id = kwargs.get("user_id")
        if user_id is None:
            return ToolResult(success=False, error="Missing required argument: user_id")
        db = get_db()
        data = db.get_user_tickets(
            user_id=int(user_id),
            status=kwargs.get("status"),
            limit=kwargs.get("limit", 20),
        )
        if "error" in data:
            return ToolResult(success=False, error=data["error"])
        return ToolResult(success=True, data=data)


class GetTicketDetailsTool(Tool):
    """Retrieves full ticket details including history."""

    @property
    def name(self) -> str:
        return "crm.get_ticket_details"

    @property
    def description(self) -> str:
        return "Get full ticket details including conversation history from the CRM."

    @property
    def required_permissions(self) -> List[str]:
        return ["crm:read"]

    def execute(self, **kwargs) -> ToolResult:
        ticket_id = kwargs.get("ticket_id")
        if ticket_id is None:
            return ToolResult(success=False, error="Missing required argument: ticket_id")
        db = get_db()
        data = db.get_ticket_details(int(ticket_id))
        if "error" in data:
            return ToolResult(success=False, error=data["error"])
        return ToolResult(success=True, data=data)


class SearchSimilarIssuesTool(Tool):
    """Searches tickets by keyword to find similar issues."""

    @property
    def name(self) -> str:
        return "crm.search_similar_issues"

    @property
    def description(self) -> str:
        return "Search CRM tickets by keyword to find similar reported issues."

    @property
    def required_permissions(self) -> List[str]:
        return ["crm:read"]

    def execute(self, **kwargs) -> ToolResult:
        query = kwargs.get("query", "")
        if not query:
            return ToolResult(success=False, error="Missing required argument: query")
        db = get_db()
        results = db.search_similar_issues(
            query=query,
            category=kwargs.get("category"),
            limit=kwargs.get("limit", 10),
        )
        return ToolResult(success=True, data=results)
