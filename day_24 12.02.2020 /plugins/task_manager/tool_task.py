"""Task manager tools — SQLite-backed task CRUD with priorities, dependencies, and project status.

Provides create, list, update, get, and project_status operations.
Supports ephemeral mode (in-memory DB) when persistent storage is unavailable.
"""

import json
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

CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'todo',
    priority    TEXT NOT NULL DEFAULT 'medium',
    effort      TEXT NOT NULL DEFAULT 'medium',
    due_date    TEXT DEFAULT NULL,
    depends_on  TEXT NOT NULL DEFAULT '[]',
    blocked_by  TEXT NOT NULL DEFAULT '',
    tags        TEXT NOT NULL DEFAULT '[]',
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority);
"""

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_TASKS = [
    # (title, description, status, priority, effort, due_date, depends_on, blocked_by, tags)
    (
        "Fix login redirect loop",
        "Users on Safari get stuck in an OAuth redirect loop after clicking Login.",
        "todo", "critical", "medium", "2026-02-25",
        "[]", "", '["auth", "bug"]',
    ),
    (
        "Add rate-limit headers to API responses",
        "Return X-RateLimit-Remaining and X-RateLimit-Reset headers on every API response.",
        "in_progress", "high", "small", "2026-03-01",
        "[]", "", '["api", "feature"]',
    ),
    (
        "Write onboarding email sequence",
        "Create a 3-email drip campaign for new free-tier signups.",
        "todo", "medium", "large", "2026-03-10",
        "[]", "", '["marketing", "content"]',
    ),
    (
        "Migrate user table to partitioned schema",
        "Partition the users table by created_at month for query performance.",
        "blocked", "high", "xlarge", "2026-03-15",
        "[]", "Waiting for DBA approval", '["database", "performance"]',
    ),
    (
        "Update Python dependencies",
        "Bump all pinned packages to latest compatible versions and run full test suite.",
        "done", "low", "small", "",
        "[]", "", '["maintenance"]',
    ),
    (
        "Implement webhook retry logic",
        "Add exponential backoff retry (max 5 attempts) for failed webhook deliveries.",
        "todo", "high", "medium", "2026-03-05",
        "[2]", "", '["api", "reliability"]',
    ),
    (
        "Design dashboard dark mode",
        "Create Figma mockups for dashboard dark mode theme.",
        "in_progress", "medium", "medium", "2026-03-08",
        "[]", "", '["ui", "design"]',
    ),
    (
        "Set up staging environment",
        "Provision a staging cluster mirroring production for QA testing.",
        "todo", "high", "large", "2026-02-28",
        "[]", "", '["infra", "devops"]',
    ),
]


def _resolve_db_path(db_path: Optional[str] = None) -> str:
    """Determine the database path. Returns ':memory:' as last resort."""
    if db_path:
        return db_path
    env_path = os.environ.get("TASK_MANAGER_DB")
    if env_path:
        return env_path
    base = Path(__file__).resolve().parents[2]
    default = base / "task_manager.db"
    return str(default)


class TaskDB:
    """SQLite wrapper for the task management store."""

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
                f"[task_manager] WARNING: Cannot open {resolved}, using ephemeral in-memory DB",
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
        """Insert sample data if tasks table is empty."""
        count = self._conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        if count > 0:
            return
        now = time.time()
        for title, desc, status, priority, effort, due, deps, blocked, tags in SAMPLE_TASKS:
            self._conn.execute(
                """INSERT INTO tasks (title, description, status, priority, effort,
                   due_date, depends_on, blocked_by, tags, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (title, desc, status, priority, effort, due or None, deps, blocked, tags, now, now),
            )
        self._conn.commit()

    # -- CRUD operations ---------------------------------------------------

    def create_task(
        self,
        title: str,
        description: str = "",
        priority: str = "medium",
        effort: str = "medium",
        due_date: str = "",
        depends_on: Optional[List[int]] = None,
        blocked_by: str = "",
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Create a new task and return it."""
        now = time.time()
        deps_json = json.dumps(depends_on or [])
        tags_json = json.dumps(tags or [])
        cursor = self._conn.execute(
            """INSERT INTO tasks (title, description, status, priority, effort,
               due_date, depends_on, blocked_by, tags, created_at, updated_at)
               VALUES (?, ?, 'todo', ?, ?, ?, ?, ?, ?, ?, ?)""",
            (title, description, priority, effort, due_date or None,
             deps_json, blocked_by, tags_json, now, now),
        )
        self._conn.commit()
        return self.get_task(cursor.lastrowid)

    def get_task(self, task_id: int) -> Dict[str, Any]:
        """Get a single task by ID."""
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not row:
            return {"error": f"Task {task_id} not found"}
        return self._row_to_dict(row)

    def list_tasks(
        self,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List tasks with optional filters."""
        clauses = []
        params: list = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if priority:
            clauses.append("priority = ?")
            params.append(priority)
        if tag:
            clauses.append("tags LIKE ?")
            params.append(f'%"{tag}"%')
        params.append(limit)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM tasks{where} ORDER BY updated_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def update_task(self, task_id: int, **fields) -> Dict[str, Any]:
        """Update task fields. Returns updated task or error dict."""
        allowed = {"title", "description", "status", "priority", "effort",
                    "due_date", "depends_on", "blocked_by", "tags"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return {"error": "No valid fields to update"}

        # Serialize list fields
        if "depends_on" in updates and isinstance(updates["depends_on"], list):
            updates["depends_on"] = json.dumps(updates["depends_on"])
        if "tags" in updates and isinstance(updates["tags"], list):
            updates["tags"] = json.dumps(updates["tags"])

        updates["updated_at"] = time.time()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        params = list(updates.values()) + [task_id]
        self._conn.execute(
            f"UPDATE tasks SET {set_clause} WHERE id = ?", params
        )
        self._conn.commit()
        return self.get_task(task_id)

    def project_status(self) -> Dict[str, Any]:
        """Return aggregate project status."""
        rows = self._conn.execute(
            "SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status"
        ).fetchall()
        status_counts = {row["status"]: row["cnt"] for row in rows}

        prio_rows = self._conn.execute(
            "SELECT priority, COUNT(*) as cnt FROM tasks WHERE status NOT IN ('done') GROUP BY priority"
        ).fetchall()
        priority_counts = {row["priority"]: row["cnt"] for row in prio_rows}

        total = self._conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]

        blocked_rows = self._conn.execute(
            "SELECT id, title, blocked_by FROM tasks WHERE status = 'blocked'"
        ).fetchall()
        blocked = [{"id": r["id"], "title": r["title"], "blocked_by": r["blocked_by"]}
                    for r in blocked_rows]

        overdue = []
        import datetime
        today = datetime.date.today().isoformat()
        overdue_rows = self._conn.execute(
            "SELECT id, title, due_date, priority FROM tasks "
            "WHERE due_date IS NOT NULL AND due_date != '' AND due_date < ? "
            "AND status NOT IN ('done')",
            (today,),
        ).fetchall()
        overdue = [{"id": r["id"], "title": r["title"], "due_date": r["due_date"],
                     "priority": r["priority"]} for r in overdue_rows]

        return {
            "total": total,
            "by_status": status_counts,
            "by_priority": priority_counts,
            "blocked": blocked,
            "overdue": overdue,
        }

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        # Parse JSON fields
        for field in ("depends_on", "tags"):
            if field in d and isinstance(d[field], str):
                try:
                    d[field] = json.loads(d[field])
                except (json.JSONDecodeError, TypeError):
                    d[field] = []
        return d

    def close(self) -> None:
        self._conn.close()


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_db_instance: Optional[TaskDB] = None


def get_db(db_path: Optional[str] = None) -> TaskDB:
    global _db_instance
    if _db_instance is None:
        _db_instance = TaskDB(db_path)
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


class CreateTaskTool(Tool):
    """Creates a new task in the task manager."""

    @property
    def name(self) -> str:
        return "task.create"

    @property
    def description(self) -> str:
        return "Create a new task with title, description, priority, effort, due date, and tags."

    @property
    def required_permissions(self) -> List[str]:
        return ["task:write"]

    def execute(self, **kwargs) -> ToolResult:
        title = kwargs.get("title", "")
        if not title:
            return ToolResult(success=False, error="Missing required argument: title")
        db = get_db()
        task = db.create_task(
            title=title,
            description=kwargs.get("description", ""),
            priority=kwargs.get("priority", "medium"),
            effort=kwargs.get("effort", "medium"),
            due_date=kwargs.get("due_date", ""),
            depends_on=kwargs.get("depends_on"),
            blocked_by=kwargs.get("blocked_by", ""),
            tags=kwargs.get("tags"),
        )
        if "error" in task:
            return ToolResult(success=False, error=task["error"])
        return ToolResult(success=True, data=task)


class ListTasksTool(Tool):
    """Lists tasks with optional filters."""

    @property
    def name(self) -> str:
        return "task.list"

    @property
    def description(self) -> str:
        return "List tasks filtered by status, priority, or tag."

    @property
    def required_permissions(self) -> List[str]:
        return ["task:read"]

    def execute(self, **kwargs) -> ToolResult:
        db = get_db()
        tasks = db.list_tasks(
            status=kwargs.get("status"),
            priority=kwargs.get("priority"),
            tag=kwargs.get("tag"),
            limit=kwargs.get("limit", 50),
        )
        return ToolResult(success=True, data=tasks)


class UpdateTaskTool(Tool):
    """Updates an existing task."""

    @property
    def name(self) -> str:
        return "task.update"

    @property
    def description(self) -> str:
        return "Update task fields (status, priority, effort, due_date, etc.) by task ID."

    @property
    def required_permissions(self) -> List[str]:
        return ["task:write"]

    def execute(self, **kwargs) -> ToolResult:
        task_id = kwargs.get("task_id")
        if task_id is None:
            return ToolResult(success=False, error="Missing required argument: task_id")
        fields = {k: v for k, v in kwargs.items() if k != "task_id"}
        db = get_db()
        result = db.update_task(int(task_id), **fields)
        if "error" in result:
            return ToolResult(success=False, error=result["error"])
        return ToolResult(success=True, data=result)


class GetTaskTool(Tool):
    """Gets a single task by ID."""

    @property
    def name(self) -> str:
        return "task.get"

    @property
    def description(self) -> str:
        return "Get full details of a task by its ID."

    @property
    def required_permissions(self) -> List[str]:
        return ["task:read"]

    def execute(self, **kwargs) -> ToolResult:
        task_id = kwargs.get("task_id")
        if task_id is None:
            return ToolResult(success=False, error="Missing required argument: task_id")
        db = get_db()
        task = db.get_task(int(task_id))
        if "error" in task:
            return ToolResult(success=False, error=task["error"])
        return ToolResult(success=True, data=task)


class ProjectStatusTool(Tool):
    """Returns aggregate project status."""

    @property
    def name(self) -> str:
        return "task.project_status"

    @property
    def description(self) -> str:
        return "Get project-wide task status: counts by status/priority, blocked items, overdue items."

    @property
    def required_permissions(self) -> List[str]:
        return ["task:read"]

    def execute(self, **kwargs) -> ToolResult:
        db = get_db()
        status = db.project_status()
        return ToolResult(success=True, data=status)
