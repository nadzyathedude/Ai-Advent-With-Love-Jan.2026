#!/usr/bin/env python3
"""
Task Tracker MCP Server.

A minimal MCP server that exposes task tracking tools via stdio transport.
Uses SQLite for persistent storage.

Usage:
    python task_tracker_server.py

The server implements the following MCP tools:
    - task_create: Create a new task
    - task_list_open: List all open tasks
    - task_get_open_count: Get count of open tasks
    - task_complete: Mark a task as completed
"""

import asyncio
import json
import logging
import re
import smtplib
import sqlite3
import ssl
from contextlib import contextmanager
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Load SMTP configuration from config.py
SMTP_HOST = "smtp.yandex.ru"
SMTP_PORT = 587
SMTP_USER = ""
SMTP_PASSWORD = ""
SMTP_FROM_EMAIL = ""
SMTP_USE_TLS = True

try:
    from config import yandex_smtp_email, yandex_smtp_password
    if yandex_smtp_email and yandex_smtp_password:
        SMTP_USER = yandex_smtp_email
        SMTP_PASSWORD = yandex_smtp_password
        SMTP_FROM_EMAIL = yandex_smtp_email
except ImportError:
    pass

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Database path
DB_PATH = Path(__file__).parent / "tasks.db"


# =============================================================================
# Database Layer
# =============================================================================

def init_database() -> None:
    """Initialize the SQLite database with the tasks table."""
    with get_db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                UNIQUE(user_id, title)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_user_status
            ON tasks(user_id, status)
        """)
        # Reminder preferences table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reminder_preferences (
                user_id TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 0,
                schedule_hour INTEGER NOT NULL DEFAULT 9,
                schedule_minute INTEGER NOT NULL DEFAULT 0,
                last_reminder TIMESTAMP,
                email_enabled INTEGER DEFAULT 0,
                email_recipient TEXT
            )
        """)
        # Migration: Add email columns if they don't exist
        try:
            conn.execute("ALTER TABLE reminder_preferences ADD COLUMN email_enabled INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE reminder_preferences ADD COLUMN email_recipient TEXT")
        except sqlite3.OperationalError:
            pass
        # Task-specific reminders table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                user_id TEXT NOT NULL,
                reminder_time TIMESTAMP NOT NULL,
                message TEXT,
                is_sent INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_task_reminders_time
            ON task_reminders(reminder_time, is_sent)
        """)
        conn.commit()
    logger.info(f"Database initialized at {DB_PATH}")


@contextmanager
def get_db_connection():
    """Context manager for database connections."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def create_task(user_id: str, title: str, description: Optional[str] = None) -> dict:
    """
    Create a new task.

    Args:
        user_id: User identifier
        title: Task title
        description: Optional task description

    Returns:
        Dict with task info or error
    """
    with get_db_connection() as conn:
        # Check if an open task with this title already exists
        cursor = conn.execute(
            "SELECT id FROM tasks WHERE user_id = ? AND title = ? AND status = 'open'",
            (user_id, title)
        )
        if cursor.fetchone():
            return {
                "success": False,
                "error": f"Task with title '{title}' already exists"
            }

        try:
            cursor = conn.execute(
                """
                INSERT INTO tasks (user_id, title, description, status)
                VALUES (?, ?, ?, 'open')
                """,
                (user_id, title, description)
            )
            conn.commit()
            task_id = cursor.lastrowid
            logger.info(f"Created task {task_id} for user {user_id}: {title}")
            return {
                "success": True,
                "task_id": task_id,
                "title": title,
                "message": f"Task '{title}' created successfully"
            }
        except sqlite3.IntegrityError:
            # A completed task with this title exists - delete it and retry
            conn.execute(
                "DELETE FROM tasks WHERE user_id = ? AND title = ? AND status = 'completed'",
                (user_id, title)
            )
            cursor = conn.execute(
                """
                INSERT INTO tasks (user_id, title, description, status)
                VALUES (?, ?, ?, 'open')
                """,
                (user_id, title, description)
            )
            conn.commit()
            task_id = cursor.lastrowid
            logger.info(f"Created task {task_id} for user {user_id}: {title} (replaced completed)")
            return {
                "success": True,
                "task_id": task_id,
                "title": title,
                "message": f"Task '{title}' created successfully"
            }


def list_open_tasks(user_id: str) -> list[dict]:
    """
    List all open tasks for a user.

    Args:
        user_id: User identifier

    Returns:
        List of task dicts
    """
    with get_db_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, title, description, created_at
            FROM tasks
            WHERE user_id = ? AND status = 'open'
            ORDER BY created_at DESC
            """,
            (user_id,)
        )
        tasks = [
            {
                "id": row["id"],
                "title": row["title"],
                "description": row["description"],
                "created_at": row["created_at"]
            }
            for row in cursor.fetchall()
        ]
        logger.info(f"Listed {len(tasks)} open tasks for user {user_id}")
        return tasks


def get_open_count(user_id: Optional[str] = None) -> dict:
    """
    Get count of open tasks.

    Args:
        user_id: Optional user identifier. If None, counts all open tasks.

    Returns:
        Dict with count info
    """
    with get_db_connection() as conn:
        if user_id:
            cursor = conn.execute(
                "SELECT COUNT(*) as count FROM tasks WHERE user_id = ? AND status = 'open'",
                (user_id,)
            )
        else:
            cursor = conn.execute(
                "SELECT COUNT(*) as count FROM tasks WHERE status = 'open'"
            )
        count = cursor.fetchone()["count"]
        logger.info(f"Open task count for user {user_id or 'all'}: {count}")
        return {
            "count": count,
            "user_id": user_id or "all"
        }


def complete_task(user_id: str, task_id: int) -> dict:
    """
    Mark a task as completed.

    Args:
        user_id: User identifier
        task_id: Task ID to complete

    Returns:
        Dict with result info
    """
    with get_db_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE tasks
            SET status = 'completed', completed_at = CURRENT_TIMESTAMP
            WHERE id = ? AND user_id = ? AND status = 'open'
            """,
            (task_id, user_id)
        )
        conn.commit()

        if cursor.rowcount > 0:
            logger.info(f"Completed task {task_id} for user {user_id}")
            return {
                "success": True,
                "task_id": task_id,
                "message": f"Task {task_id} marked as completed"
            }
        else:
            return {
                "success": False,
                "error": f"Task {task_id} not found or already completed"
            }


# =============================================================================
# Reminder Functions
# =============================================================================

def get_reminder_preferences(user_id: str) -> dict:
    """Get reminder preferences for a user."""
    with get_db_connection() as conn:
        cursor = conn.execute(
            "SELECT * FROM reminder_preferences WHERE user_id = ?",
            (user_id,)
        )
        row = cursor.fetchone()
        if row:
            return {
                "enabled": bool(row["enabled"]),
                "schedule_hour": row["schedule_hour"],
                "schedule_minute": row["schedule_minute"],
                "last_reminder": row["last_reminder"]
            }
        return {
            "enabled": False,
            "schedule_hour": 9,
            "schedule_minute": 0,
            "last_reminder": None
        }


def set_reminder_preferences(user_id: str, enabled: bool,
                             hour: int = 9, minute: int = 0) -> dict:
    """Set reminder preferences for a user."""
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO reminder_preferences (user_id, enabled, schedule_hour, schedule_minute)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                enabled = excluded.enabled,
                schedule_hour = excluded.schedule_hour,
                schedule_minute = excluded.schedule_minute
            """,
            (user_id, int(enabled), hour, minute)
        )
        conn.commit()
        logger.info(f"Set reminder for user {user_id}: enabled={enabled}, time={hour:02d}:{minute:02d}")
        return {
            "success": True,
            "enabled": enabled,
            "schedule_hour": hour,
            "schedule_minute": minute
        }


def get_users_for_reminder(hour: int, minute: int) -> list[str]:
    """Get list of user IDs scheduled for reminder at given time."""
    with get_db_connection() as conn:
        cursor = conn.execute(
            """
            SELECT user_id FROM reminder_preferences
            WHERE enabled = 1 AND schedule_hour = ? AND schedule_minute = ?
            """,
            (hour, minute)
        )
        return [row["user_id"] for row in cursor.fetchall()]


def update_last_reminder(user_id: str) -> None:
    """Update the last_reminder timestamp for a user."""
    with get_db_connection() as conn:
        conn.execute(
            """
            UPDATE reminder_preferences
            SET last_reminder = CURRENT_TIMESTAMP
            WHERE user_id = ?
            """,
            (user_id,)
        )
        conn.commit()


def generate_reminder_summary(user_id: str, include_completed: bool = False) -> dict:
    """Generate a task summary for reminders."""
    with get_db_connection() as conn:
        # Get open tasks
        cursor = conn.execute(
            """
            SELECT id, title, description, created_at
            FROM tasks
            WHERE user_id = ? AND status = 'open'
            ORDER BY created_at DESC
            """,
            (user_id,)
        )
        open_tasks = cursor.fetchall()

        completed_tasks = []
        if include_completed:
            cursor = conn.execute(
                """
                SELECT id, title, completed_at
                FROM tasks
                WHERE user_id = ? AND status = 'completed'
                AND date(completed_at) = date('now')
                ORDER BY completed_at DESC
                LIMIT 5
                """,
                (user_id,)
            )
            completed_tasks = cursor.fetchall()

        # Build summary
        lines = ["📋 *Сводка задач*\n"]

        if open_tasks:
            lines.append(f"*Открытые задачи ({len(open_tasks)}):*")
            for task in open_tasks:
                lines.append(f"• {task['title']}")
        else:
            lines.append("✅ Нет открытых задач!")

        if completed_tasks:
            lines.append(f"\n*Выполнено сегодня ({len(completed_tasks)}):*")
            for task in completed_tasks:
                lines.append(f"✓ {task['title']}")

        return {
            "summary": "\n".join(lines),
            "open_count": len(open_tasks),
            "completed_today": len(completed_tasks)
        }


# =============================================================================
# Task Reminder Functions
# =============================================================================

def get_task(user_id: str, task_id: int) -> dict:
    """
    Get a task by ID.

    Args:
        user_id: User identifier
        task_id: Task ID

    Returns:
        Dict with task info or error
    """
    with get_db_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, title, description, status, created_at, completed_at
            FROM tasks
            WHERE id = ? AND user_id = ?
            """,
            (task_id, user_id)
        )
        row = cursor.fetchone()
        if row:
            return {
                "success": True,
                "task": {
                    "id": row["id"],
                    "title": row["title"],
                    "description": row["description"],
                    "status": row["status"],
                    "created_at": row["created_at"],
                    "completed_at": row["completed_at"]
                }
            }
        return {
            "success": False,
            "error": f"Task {task_id} not found"
        }


def update_task_description(user_id: str, task_id: int, description: str) -> dict:
    """
    Update a task's description.

    Args:
        user_id: User identifier
        task_id: Task ID
        description: New description

    Returns:
        Dict with result info
    """
    with get_db_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE tasks
            SET description = ?
            WHERE id = ? AND user_id = ?
            """,
            (description, task_id, user_id)
        )
        conn.commit()

        if cursor.rowcount > 0:
            logger.info(f"Updated description for task {task_id}")
            return {
                "success": True,
                "task_id": task_id,
                "message": f"Task {task_id} description updated"
            }
        else:
            return {
                "success": False,
                "error": f"Task {task_id} not found"
            }


def create_task_reminder(task_id: int, user_id: str, reminder_time: str,
                         message: Optional[str] = None) -> dict:
    """
    Create a reminder for a task.

    Args:
        task_id: Task ID
        user_id: User identifier
        reminder_time: ISO format datetime string
        message: Optional reminder message

    Returns:
        Dict with reminder info or error
    """
    with get_db_connection() as conn:
        # Verify task exists and belongs to user
        cursor = conn.execute(
            "SELECT id, title FROM tasks WHERE id = ? AND user_id = ?",
            (task_id, user_id)
        )
        task = cursor.fetchone()
        if not task:
            return {
                "success": False,
                "error": f"Task {task_id} not found"
            }

        try:
            cursor = conn.execute(
                """
                INSERT INTO task_reminders (task_id, user_id, reminder_time, message)
                VALUES (?, ?, ?, ?)
                """,
                (task_id, user_id, reminder_time, message)
            )
            conn.commit()
            reminder_id = cursor.lastrowid
            logger.info(f"Created reminder {reminder_id} for task {task_id}")
            return {
                "success": True,
                "reminder_id": reminder_id,
                "task_id": task_id,
                "task_title": task["title"],
                "reminder_time": reminder_time,
                "message": f"Reminder set for task '{task['title']}'"
            }
        except Exception as e:
            logger.error(f"Error creating reminder: {e}")
            return {
                "success": False,
                "error": str(e)
            }


def get_due_task_reminders(current_time: str) -> list[dict]:
    """
    Get task reminders that are due.

    Args:
        current_time: ISO format datetime string

    Returns:
        List of due reminders
    """
    with get_db_connection() as conn:
        cursor = conn.execute(
            """
            SELECT tr.id, tr.task_id, tr.user_id, tr.reminder_time,
                   tr.message, t.title as task_title, t.description as task_description
            FROM task_reminders tr
            JOIN tasks t ON tr.task_id = t.id
            WHERE tr.is_sent = 0
            AND tr.reminder_time <= ?
            ORDER BY tr.reminder_time
            """,
            (current_time,)
        )
        reminders = [
            {
                "id": row["id"],
                "task_id": row["task_id"],
                "user_id": row["user_id"],
                "reminder_time": row["reminder_time"],
                "message": row["message"],
                "task_title": row["task_title"],
                "task_description": row["task_description"]
            }
            for row in cursor.fetchall()
        ]
        return reminders


def mark_task_reminder_sent(reminder_id: int) -> dict:
    """
    Mark a task reminder as sent.

    Args:
        reminder_id: Reminder ID

    Returns:
        Dict with result info
    """
    with get_db_connection() as conn:
        cursor = conn.execute(
            "UPDATE task_reminders SET is_sent = 1 WHERE id = ?",
            (reminder_id,)
        )
        conn.commit()

        if cursor.rowcount > 0:
            logger.info(f"Marked reminder {reminder_id} as sent")
            return {"success": True, "reminder_id": reminder_id}
        else:
            return {"success": False, "error": f"Reminder {reminder_id} not found"}


# =============================================================================
# Email Functions
# =============================================================================

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def validate_email(email: str) -> bool:
    """Validate email format."""
    if not email or not isinstance(email, str):
        return False
    return EMAIL_REGEX.match(email.strip()) is not None


def is_smtp_configured() -> bool:
    """Check if SMTP is properly configured."""
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD and SMTP_FROM_EMAIL)


def send_email_sync(recipient_email: str, subject: str, message_text: str) -> dict:
    """Send email via SMTP."""
    if not is_smtp_configured():
        return {
            "success": False,
            "error": "SMTP not configured. Set yandex_smtp_email and yandex_smtp_password in config.py"
        }

    if not validate_email(recipient_email):
        return {
            "success": False,
            "error": f"Invalid email format: {recipient_email}"
        }

    try:
        msg = MIMEMultipart()
        msg["From"] = SMTP_FROM_EMAIL
        msg["To"] = recipient_email.strip()
        msg["Subject"] = subject
        msg.attach(MIMEText(message_text, "plain", "utf-8"))

        if SMTP_USE_TLS:
            context = ssl.create_default_context()
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls(context=context)
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)

        logger.info(f"Email sent successfully to {recipient_email}")
        return {"success": True, "message": f"Email sent to {recipient_email}"}

    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"SMTP authentication failed: {e}")
        return {"success": False, "error": "SMTP authentication failed"}
    except Exception as e:
        logger.error(f"Email send failed: {e}")
        return {"success": False, "error": str(e)}


async def send_email_async(recipient_email: str, subject: str, message_text: str) -> dict:
    """Send email asynchronously with retry."""
    loop = asyncio.get_event_loop()
    for attempt in range(3):
        try:
            result = await loop.run_in_executor(
                None, send_email_sync, recipient_email, subject, message_text
            )
            if result["success"] or "Invalid email" in result.get("error", "") or "not configured" in result.get("error", ""):
                return result
        except Exception as e:
            logger.error(f"Email attempt {attempt + 1} failed: {e}")
        if attempt < 2:
            await asyncio.sleep(2 ** attempt)
    return {"success": False, "error": "Failed after 3 attempts"}


def set_email_preferences(user_id: str, email_enabled: bool, email_recipient: Optional[str] = None) -> dict:
    """Set email notification preferences."""
    if email_enabled and email_recipient and not validate_email(email_recipient):
        return {"success": False, "error": f"Invalid email format: {email_recipient}"}

    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO reminder_preferences (user_id, email_enabled, email_recipient)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                email_enabled = excluded.email_enabled,
                email_recipient = excluded.email_recipient
            """,
            (user_id, int(email_enabled), email_recipient)
        )
        conn.commit()

    logger.info(f"Set email preferences for user {user_id}: enabled={email_enabled}")
    return {"success": True, "email_enabled": email_enabled, "email_recipient": email_recipient}


def get_email_preferences(user_id: str) -> dict:
    """Get email notification preferences."""
    with get_db_connection() as conn:
        cursor = conn.execute(
            "SELECT email_enabled, email_recipient FROM reminder_preferences WHERE user_id = ?",
            (user_id,)
        )
        row = cursor.fetchone()
        if row:
            return {
                "email_enabled": bool(row["email_enabled"]) if row["email_enabled"] is not None else False,
                "email_recipient": row["email_recipient"]
            }
        return {"email_enabled": False, "email_recipient": None}


# =============================================================================
# MCP Server Setup
# =============================================================================

# Create MCP server instance
server = Server("task-tracker")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """
    List available tools.

    This is called when clients request tools/list.
    """
    return [
        Tool(
            name="task_create",
            description="Create a new task for tracking",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "User identifier (e.g., Telegram user ID)"
                    },
                    "title": {
                        "type": "string",
                        "description": "Task title"
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional task description"
                    }
                },
                "required": ["user_id", "title"]
            }
        ),
        Tool(
            name="task_list_open",
            description="List all open (not completed) tasks for a user",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "User identifier"
                    }
                },
                "required": ["user_id"]
            }
        ),
        Tool(
            name="task_get_open_count",
            description="Get the count of open tasks. Returns number of tasks that are not yet completed.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "Optional user identifier. If not provided, returns total count for all users."
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="task_complete",
            description="Mark a task as completed",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "User identifier"
                    },
                    "task_id": {
                        "type": "integer",
                        "description": "Task ID to mark as completed"
                    }
                },
                "required": ["user_id", "task_id"]
            }
        ),
        Tool(
            name="reminder_get_preferences",
            description="Get reminder preferences for a user",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "User identifier"
                    }
                },
                "required": ["user_id"]
            }
        ),
        Tool(
            name="reminder_set_preferences",
            description="Set reminder preferences for a user",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "User identifier"
                    },
                    "enabled": {
                        "type": "boolean",
                        "description": "Enable or disable reminders"
                    },
                    "hour": {
                        "type": "integer",
                        "description": "Hour for daily reminder (0-23)"
                    },
                    "minute": {
                        "type": "integer",
                        "description": "Minute for daily reminder (0-59)"
                    }
                },
                "required": ["user_id", "enabled"]
            }
        ),
        Tool(
            name="reminder_get_scheduled_users",
            description="Get list of users scheduled for reminder at given time",
            inputSchema={
                "type": "object",
                "properties": {
                    "hour": {
                        "type": "integer",
                        "description": "Hour (0-23)"
                    },
                    "minute": {
                        "type": "integer",
                        "description": "Minute (0-59)"
                    }
                },
                "required": ["hour", "minute"]
            }
        ),
        Tool(
            name="reminder_generate_summary",
            description="Generate a task summary for reminders",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "User identifier"
                    },
                    "include_completed": {
                        "type": "boolean",
                        "description": "Include completed tasks in summary"
                    }
                },
                "required": ["user_id"]
            }
        ),
        Tool(
            name="reminder_mark_sent",
            description="Mark that a reminder was sent to a user",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "User identifier"
                    }
                },
                "required": ["user_id"]
            }
        ),
        Tool(
            name="task_get",
            description="Get a task by ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "User identifier"
                    },
                    "task_id": {
                        "type": "integer",
                        "description": "Task ID"
                    }
                },
                "required": ["user_id", "task_id"]
            }
        ),
        Tool(
            name="task_update_description",
            description="Update a task's description (e.g., to add a sublist)",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "User identifier"
                    },
                    "task_id": {
                        "type": "integer",
                        "description": "Task ID"
                    },
                    "description": {
                        "type": "string",
                        "description": "New description for the task"
                    }
                },
                "required": ["user_id", "task_id", "description"]
            }
        ),
        Tool(
            name="task_reminder_create",
            description="Create a reminder for a specific task",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "integer",
                        "description": "Task ID to set reminder for"
                    },
                    "user_id": {
                        "type": "string",
                        "description": "User identifier"
                    },
                    "reminder_time": {
                        "type": "string",
                        "description": "ISO format datetime for reminder (e.g., 2026-01-31T14:30:00)"
                    },
                    "message": {
                        "type": "string",
                        "description": "Optional custom reminder message"
                    }
                },
                "required": ["task_id", "user_id", "reminder_time"]
            }
        ),
        Tool(
            name="task_reminder_get_due",
            description="Get task reminders that are due now",
            inputSchema={
                "type": "object",
                "properties": {
                    "current_time": {
                        "type": "string",
                        "description": "Current time in ISO format"
                    }
                },
                "required": ["current_time"]
            }
        ),
        Tool(
            name="task_reminder_mark_sent",
            description="Mark a task reminder as sent",
            inputSchema={
                "type": "object",
                "properties": {
                    "reminder_id": {
                        "type": "integer",
                        "description": "Reminder ID to mark as sent"
                    }
                },
                "required": ["reminder_id"]
            }
        ),
        # Email notification tools
        Tool(
            name="notification_send_email",
            description="Send an email notification",
            inputSchema={
                "type": "object",
                "properties": {
                    "recipient_email": {"type": "string", "description": "Recipient email address"},
                    "subject": {"type": "string", "description": "Email subject"},
                    "message_text": {"type": "string", "description": "Email body text"}
                },
                "required": ["recipient_email", "subject", "message_text"]
            }
        ),
        Tool(
            name="notification_set_email_preferences",
            description="Set email notification preferences",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "User identifier"},
                    "email_enabled": {"type": "boolean", "description": "Enable/disable email notifications"},
                    "email_recipient": {"type": "string", "description": "Email address for notifications"}
                },
                "required": ["user_id", "email_enabled"]
            }
        ),
        Tool(
            name="notification_get_email_preferences",
            description="Get email notification preferences",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "User identifier"}
                },
                "required": ["user_id"]
            }
        ),
        Tool(
            name="notification_validate_email",
            description="Validate an email address format",
            inputSchema={
                "type": "object",
                "properties": {
                    "email": {"type": "string", "description": "Email address to validate"}
                },
                "required": ["email"]
            }
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """
    Handle tool invocations.

    Args:
        name: Tool name
        arguments: Tool arguments

    Returns:
        List of TextContent with the result
    """
    logger.info(f"Tool called: {name} with args: {arguments}")

    try:
        if name == "task_create":
            result = create_task(
                user_id=arguments["user_id"],
                title=arguments["title"],
                description=arguments.get("description")
            )
        elif name == "task_list_open":
            tasks = list_open_tasks(user_id=arguments["user_id"])
            result = {"tasks": tasks, "count": len(tasks)}
        elif name == "task_get_open_count":
            result = get_open_count(user_id=arguments.get("user_id"))
        elif name == "task_complete":
            result = complete_task(
                user_id=arguments["user_id"],
                task_id=arguments["task_id"]
            )
        elif name == "reminder_get_preferences":
            result = get_reminder_preferences(user_id=arguments["user_id"])
        elif name == "reminder_set_preferences":
            result = set_reminder_preferences(
                user_id=arguments["user_id"],
                enabled=arguments["enabled"],
                hour=arguments.get("hour", 9),
                minute=arguments.get("minute", 0)
            )
        elif name == "reminder_get_scheduled_users":
            users = get_users_for_reminder(
                hour=arguments["hour"],
                minute=arguments["minute"]
            )
            result = {"users": users, "count": len(users)}
        elif name == "reminder_generate_summary":
            result = generate_reminder_summary(
                user_id=arguments["user_id"],
                include_completed=arguments.get("include_completed", False)
            )
        elif name == "reminder_mark_sent":
            update_last_reminder(user_id=arguments["user_id"])
            result = {"success": True}
        elif name == "task_get":
            result = get_task(
                user_id=arguments["user_id"],
                task_id=arguments["task_id"]
            )
        elif name == "task_update_description":
            result = update_task_description(
                user_id=arguments["user_id"],
                task_id=arguments["task_id"],
                description=arguments["description"]
            )
        elif name == "task_reminder_create":
            result = create_task_reminder(
                task_id=arguments["task_id"],
                user_id=arguments["user_id"],
                reminder_time=arguments["reminder_time"],
                message=arguments.get("message")
            )
        elif name == "task_reminder_get_due":
            reminders = get_due_task_reminders(
                current_time=arguments["current_time"]
            )
            result = {"reminders": reminders, "count": len(reminders)}
        elif name == "task_reminder_mark_sent":
            result = mark_task_reminder_sent(
                reminder_id=arguments["reminder_id"]
            )
        # Email notification tools
        elif name == "notification_send_email":
            result = await send_email_async(
                recipient_email=arguments["recipient_email"],
                subject=arguments["subject"],
                message_text=arguments["message_text"]
            )
        elif name == "notification_set_email_preferences":
            result = set_email_preferences(
                user_id=arguments["user_id"],
                email_enabled=arguments["email_enabled"],
                email_recipient=arguments.get("email_recipient")
            )
        elif name == "notification_get_email_preferences":
            result = get_email_preferences(user_id=arguments["user_id"])
        elif name == "notification_validate_email":
            email = arguments["email"]
            is_valid = validate_email(email)
            result = {"valid": is_valid, "email": email}
        else:
            result = {"error": f"Unknown tool: {name}"}

        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

    except Exception as e:
        logger.error(f"Error calling tool {name}: {e}", exc_info=True)
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def main():
    """Run the MCP server."""
    # Initialize database
    init_database()

    logger.info("Starting Task Tracker MCP Server (stdio transport)...")

    # Run the server using stdio transport
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
