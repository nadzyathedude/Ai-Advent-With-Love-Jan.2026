"""Review memory tools — SQLite-backed persistent store for continuous learning.

Stores review runs, findings, feedback, and inferred conventions.
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

CREATE TABLE IF NOT EXISTS review_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pr_id       TEXT NOT NULL,          -- repo/PR# or commit SHA
    timestamp   REAL NOT NULL,          -- epoch seconds
    base_branch TEXT NOT NULL DEFAULT 'main',
    files_json  TEXT NOT NULL DEFAULT '[]',  -- JSON list of changed file paths
    risk_level  TEXT NOT NULL DEFAULT '',
    report      TEXT NOT NULL DEFAULT '',     -- final markdown report (capped)
    meta_json   TEXT NOT NULL DEFAULT '{}'    -- arbitrary metadata
);

CREATE TABLE IF NOT EXISTS findings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES review_runs(id),
    category    TEXT NOT NULL,           -- bug/style/security/performance
    severity    TEXT NOT NULL,           -- low/medium/high
    file_path   TEXT NOT NULL DEFAULT 'unknown',
    line        INTEGER,
    message     TEXT NOT NULL,
    suggestion  TEXT NOT NULL DEFAULT '',
    label       TEXT NOT NULL DEFAULT 'pending'  -- pending/accepted/rejected/fixed/ignored
);

CREATE TABLE IF NOT EXISTS feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    finding_id  INTEGER NOT NULL REFERENCES findings(id),
    timestamp   REAL NOT NULL,
    label       TEXT NOT NULL,           -- accepted/rejected/fixed/ignored
    comment     TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS conventions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern     TEXT NOT NULL,           -- e.g. "prefer snake_case"
    source      TEXT NOT NULL DEFAULT 'inferred',  -- inferred/manual
    confidence  REAL NOT NULL DEFAULT 0.5,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_findings_category ON findings(category);
CREATE INDEX IF NOT EXISTS idx_findings_file_path ON findings(file_path);
CREATE INDEX IF NOT EXISTS idx_findings_message ON findings(message);
CREATE INDEX IF NOT EXISTS idx_findings_label ON findings(label);
CREATE INDEX IF NOT EXISTS idx_review_runs_pr_id ON review_runs(pr_id);
"""


def _resolve_db_path(db_path: Optional[str] = None) -> str:
    """Determine the database path. Returns ':memory:' as last resort."""
    if db_path:
        return db_path
    env_path = os.environ.get("REVIEW_MEMORY_DB")
    if env_path:
        return env_path
    base = Path(__file__).resolve().parents[2]
    default = base / "review_memory.db"
    return str(default)


class ReviewMemoryDB:
    """SQLite wrapper for the review memory store."""

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
            # Fall back to in-memory if disk path fails (e.g. read-only FS)
            print(
                f"[review_memory] WARNING: Cannot open {resolved}, using ephemeral in-memory DB",
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
        cur = self._conn.executescript(SCHEMA_SQL)
        # Stamp version
        existing = self._conn.execute(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        ).fetchone()
        if not existing:
            self._conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,)
            )
        self._conn.commit()

    # -- write operations --------------------------------------------------

    def store_run(
        self,
        pr_id: str,
        base_branch: str,
        files: List[str],
        risk_level: str,
        report: str,
        findings: List[Dict[str, Any]],
        meta: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Persist a review run and its findings. Returns run_id."""
        now = time.time()
        # Cap report at 50 KB to avoid bloat
        capped_report = report[:50_000] if len(report) > 50_000 else report
        cur = self._conn.execute(
            """INSERT INTO review_runs (pr_id, timestamp, base_branch, files_json,
               risk_level, report, meta_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                pr_id,
                now,
                base_branch,
                json.dumps(files),
                risk_level,
                capped_report,
                json.dumps(meta or {}),
            ),
        )
        run_id = cur.lastrowid
        for f in findings:
            self._conn.execute(
                """INSERT INTO findings
                   (run_id, category, severity, file_path, line, message, suggestion)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    f.get("category", ""),
                    f.get("severity", ""),
                    f.get("file_path", "unknown"),
                    f.get("line"),
                    f.get("message", ""),
                    f.get("suggestion", ""),
                ),
            )
        self._conn.commit()
        return run_id

    def record_feedback(
        self, finding_id: int, label: str, comment: str = ""
    ) -> bool:
        """Record developer feedback on a finding."""
        # Verify finding exists
        row = self._conn.execute(
            "SELECT id FROM findings WHERE id = ?", (finding_id,)
        ).fetchone()
        if not row:
            return False
        now = time.time()
        self._conn.execute(
            "INSERT INTO feedback (finding_id, timestamp, label, comment) VALUES (?, ?, ?, ?)",
            (finding_id, now, label, comment),
        )
        # Update finding label to latest feedback
        self._conn.execute(
            "UPDATE findings SET label = ? WHERE id = ?", (label, finding_id)
        )
        self._conn.commit()
        return True

    def store_convention(
        self, pattern: str, source: str = "inferred", confidence: float = 0.5
    ) -> int:
        now = time.time()
        cur = self._conn.execute(
            """INSERT INTO conventions (pattern, source, confidence, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (pattern, source, confidence, now, now),
        )
        self._conn.commit()
        return cur.lastrowid

    # -- read operations ---------------------------------------------------

    def search_findings(
        self,
        category: Optional[str] = None,
        file_path: Optional[str] = None,
        keyword: Optional[str] = None,
        label: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Search historical findings with optional filters."""
        clauses = []
        params: list = []
        if category:
            clauses.append("f.category = ?")
            params.append(category)
        if file_path:
            clauses.append("f.file_path LIKE ?")
            params.append(f"%{file_path}%")
        if keyword:
            clauses.append("(f.message LIKE ? OR f.suggestion LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        if label:
            clauses.append("f.label = ?")
            params.append(label)
        where = " AND ".join(clauses) if clauses else "1=1"
        params.append(limit)
        rows = self._conn.execute(
            f"""SELECT f.id, f.run_id, f.category, f.severity, f.file_path,
                       f.line, f.message, f.suggestion, f.label,
                       r.pr_id, r.timestamp
                FROM findings f
                JOIN review_runs r ON f.run_id = r.id
                WHERE {where}
                ORDER BY r.timestamp DESC
                LIMIT ?""",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def get_finding_stats(
        self, category: Optional[str] = None, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Get aggregated stats on finding patterns: how often each message
        appeared and how often it was accepted vs rejected."""
        cat_clause = "WHERE f.category = ?" if category else ""
        params: list = [category] if category else []
        params.append(limit)
        rows = self._conn.execute(
            f"""SELECT f.message,
                       f.category,
                       COUNT(*) as total_count,
                       SUM(CASE WHEN f.label = 'accepted' THEN 1 ELSE 0 END) as accepted,
                       SUM(CASE WHEN f.label = 'rejected' THEN 1 ELSE 0 END) as rejected,
                       SUM(CASE WHEN f.label = 'fixed' THEN 1 ELSE 0 END) as fixed,
                       SUM(CASE WHEN f.label = 'ignored' THEN 1 ELSE 0 END) as ignored,
                       SUM(CASE WHEN f.label = 'pending' THEN 1 ELSE 0 END) as pending
                FROM findings f
                {cat_clause}
                GROUP BY f.message, f.category
                ORDER BY total_count DESC
                LIMIT ?""",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def get_conventions(self, min_confidence: float = 0.0) -> List[Dict[str, Any]]:
        """Return stored conventions above a confidence threshold."""
        rows = self._conn.execute(
            """SELECT id, pattern, source, confidence, created_at, updated_at
               FROM conventions
               WHERE confidence >= ?
               ORDER BY confidence DESC""",
            (min_confidence,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_false_positive_patterns(self, min_rejected: int = 2) -> List[Dict[str, Any]]:
        """Return finding messages that have been rejected at least N times."""
        rows = self._conn.execute(
            """SELECT f.message, f.category, COUNT(*) as rejected_count
               FROM findings f
               WHERE f.label = 'rejected'
               GROUP BY f.message, f.category
               HAVING COUNT(*) >= ?
               ORDER BY rejected_count DESC""",
            (min_rejected,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_high_value_patterns(self, min_accepted: int = 2) -> List[Dict[str, Any]]:
        """Return finding messages that have been accepted/fixed at least N times."""
        rows = self._conn.execute(
            """SELECT f.message, f.category, COUNT(*) as confirmed_count
               FROM findings f
               WHERE f.label IN ('accepted', 'fixed')
               GROUP BY f.message, f.category
               HAVING COUNT(*) >= ?
               ORDER BY confirmed_count DESC""",
            (min_accepted,),
        ).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        self._conn.close()


# ---------------------------------------------------------------------------
# Singleton accessor — tools share one DB connection per process
# ---------------------------------------------------------------------------

_db_instance: Optional[ReviewMemoryDB] = None


def get_db(db_path: Optional[str] = None) -> ReviewMemoryDB:
    global _db_instance
    if _db_instance is None:
        _db_instance = ReviewMemoryDB(db_path)
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


class StoreReviewRunTool(Tool):
    """Persists a review run and its findings to the learning memory."""

    @property
    def name(self) -> str:
        return "review_memory.store_review_run"

    @property
    def description(self) -> str:
        return "Store a PR review run (findings, risk level, report) in the learning memory."

    @property
    def required_permissions(self) -> List[str]:
        return ["review_memory:write"]

    def execute(self, **kwargs) -> ToolResult:
        pr_id = kwargs.get("pr_id", "")
        if not pr_id:
            return ToolResult(success=False, error="Missing required argument: pr_id")
        db = get_db()
        run_id = db.store_run(
            pr_id=pr_id,
            base_branch=kwargs.get("base_branch", "main"),
            files=kwargs.get("files", []),
            risk_level=kwargs.get("risk_level", ""),
            report=kwargs.get("report", ""),
            findings=kwargs.get("findings", []),
            meta=kwargs.get("meta"),
        )
        return ToolResult(success=True, data={"run_id": run_id, "ephemeral": db.ephemeral})


class SearchSimilarFindingsTool(Tool):
    """Searches historical findings by category, file path, or keyword."""

    @property
    def name(self) -> str:
        return "review_memory.search_similar_findings"

    @property
    def description(self) -> str:
        return "Search past review findings by category, file path, keyword, or label."

    @property
    def required_permissions(self) -> List[str]:
        return ["review_memory:read"]

    def execute(self, **kwargs) -> ToolResult:
        db = get_db()
        results = db.search_findings(
            category=kwargs.get("category"),
            file_path=kwargs.get("file_path"),
            keyword=kwargs.get("keyword"),
            label=kwargs.get("label"),
            limit=kwargs.get("limit", 50),
        )
        return ToolResult(success=True, data=results)


class RecordFeedbackTool(Tool):
    """Records developer feedback on a specific finding."""

    @property
    def name(self) -> str:
        return "review_memory.record_feedback"

    @property
    def description(self) -> str:
        return "Record feedback (accepted/rejected/fixed/ignored) on a past finding."

    @property
    def required_permissions(self) -> List[str]:
        return ["review_memory:write"]

    def execute(self, **kwargs) -> ToolResult:
        finding_id = kwargs.get("finding_id")
        label = kwargs.get("label", "")
        if finding_id is None:
            return ToolResult(success=False, error="Missing required argument: finding_id")
        if label not in ("accepted", "rejected", "fixed", "ignored"):
            return ToolResult(
                success=False,
                error=f"Invalid label '{label}'. Must be: accepted, rejected, fixed, ignored",
            )
        db = get_db()
        ok = db.record_feedback(
            finding_id=int(finding_id),
            label=label,
            comment=kwargs.get("comment", ""),
        )
        if not ok:
            return ToolResult(success=False, error=f"Finding {finding_id} not found")
        return ToolResult(success=True, data={"finding_id": finding_id, "label": label})


class GetProjectConventionsTool(Tool):
    """Returns project conventions discovered from review history."""

    @property
    def name(self) -> str:
        return "review_memory.get_project_conventions"

    @property
    def description(self) -> str:
        return "Get project-specific conventions inferred from review history."

    @property
    def required_permissions(self) -> List[str]:
        return ["review_memory:read"]

    def execute(self, **kwargs) -> ToolResult:
        db = get_db()
        conventions = db.get_conventions(
            min_confidence=kwargs.get("min_confidence", 0.0)
        )
        false_positives = db.get_false_positive_patterns(
            min_rejected=kwargs.get("min_rejected", 2)
        )
        high_value = db.get_high_value_patterns(
            min_accepted=kwargs.get("min_accepted", 2)
        )
        return ToolResult(
            success=True,
            data={
                "conventions": conventions,
                "false_positive_patterns": false_positives,
                "high_value_patterns": high_value,
            },
        )
