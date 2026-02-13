#!/usr/bin/env python3
"""
MCP Server for Kubernetes deployment.

A production-ready MCP server that exposes:
- Task Tracker tools (create, list, count, complete)
- Reminder tool (generate_summary)

Uses HTTP/SSE transport for Kubernetes inter-pod communication.
Uses SQLite for persistent storage (mounted via PVC).

Usage:
    python mcp_server.py

Environment variables:
    MCP_SERVER_HOST: Host to bind (default: 0.0.0.0)
    MCP_SERVER_PORT: Port to bind (default: 8080)
    DATA_DIR: Directory for persistent data (default: /data)
"""

import asyncio
import json
import logging
import os
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

from aiohttp import web
from mcp.server import Server
from mcp.types import Tool, TextContent

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Configuration from environment
HOST = os.getenv("MCP_SERVER_HOST", "0.0.0.0")
PORT = int(os.getenv("MCP_SERVER_PORT", "8080"))
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))

# SMTP Configuration from environment (default: Yandex Mail)
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.yandex.ru")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"

# Try to load from config.py for local development (if env vars not set)
if not SMTP_USER or not SMTP_PASSWORD:
    try:
        from config import yandex_smtp_email, yandex_smtp_password
        if yandex_smtp_email and yandex_smtp_password:
            SMTP_USER = SMTP_USER or yandex_smtp_email
            SMTP_PASSWORD = SMTP_PASSWORD or yandex_smtp_password
            SMTP_FROM_EMAIL = SMTP_FROM_EMAIL or yandex_smtp_email
            logger.info("SMTP credentials loaded from config.py")
    except ImportError:
        pass  # Config not available, use environment variables only

# Database path
DB_PATH = DATA_DIR / "tasks.db"


# =============================================================================
# Database Layer
# =============================================================================

def init_database() -> None:
    """Initialize the SQLite database with the tasks table."""
    # Ensure data directory exists
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with get_db_connection() as conn:
        # Tasks table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                priority TEXT DEFAULT 'normal',
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
                enabled INTEGER DEFAULT 0,
                schedule_hour INTEGER DEFAULT 9,
                schedule_minute INTEGER DEFAULT 0,
                last_reminder TIMESTAMP,
                email_enabled INTEGER DEFAULT 0,
                email_recipient TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Migration: Add email columns if they don't exist (for existing databases)
        try:
            conn.execute("ALTER TABLE reminder_preferences ADD COLUMN email_enabled INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            conn.execute("ALTER TABLE reminder_preferences ADD COLUMN email_recipient TEXT")
        except sqlite3.OperationalError:
            pass  # Column already exists
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


# =============================================================================
# Task Tracker Functions
# =============================================================================

def create_task(user_id: str, title: str, description: Optional[str] = None,
                priority: str = "normal") -> dict:
    """Create a new task."""
    with get_db_connection() as conn:
        try:
            cursor = conn.execute(
                """
                INSERT INTO tasks (user_id, title, description, priority, status)
                VALUES (?, ?, ?, ?, 'open')
                """,
                (user_id, title, description, priority)
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
            return {
                "success": False,
                "error": f"Task with title '{title}' already exists"
            }


def list_open_tasks(user_id: str) -> list[dict]:
    """List all open tasks for a user."""
    with get_db_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, title, description, priority, created_at
            FROM tasks
            WHERE user_id = ? AND status = 'open'
            ORDER BY
                CASE priority
                    WHEN 'high' THEN 1
                    WHEN 'normal' THEN 2
                    WHEN 'low' THEN 3
                END,
                created_at DESC
            """,
            (user_id,)
        )
        tasks = [
            {
                "id": row["id"],
                "title": row["title"],
                "description": row["description"],
                "priority": row["priority"],
                "created_at": row["created_at"]
            }
            for row in cursor.fetchall()
        ]
        logger.info(f"Listed {len(tasks)} open tasks for user {user_id}")
        return tasks


def list_completed_tasks(user_id: str, limit: int = 5) -> list[dict]:
    """List recently completed tasks for a user."""
    with get_db_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, title, description, completed_at
            FROM tasks
            WHERE user_id = ? AND status = 'completed'
            ORDER BY completed_at DESC
            LIMIT ?
            """,
            (user_id, limit)
        )
        tasks = [
            {
                "id": row["id"],
                "title": row["title"],
                "description": row["description"],
                "completed_at": row["completed_at"]
            }
            for row in cursor.fetchall()
        ]
        return tasks


def get_open_count(user_id: Optional[str] = None) -> dict:
    """Get count of open tasks."""
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
        return {"count": count, "user_id": user_id or "all"}


def complete_task(user_id: str, task_id: int) -> dict:
    """Mark a task as completed."""
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

def generate_summary(user_id: str, include_completed: bool = False) -> dict:
    """
    Generate a task summary for reminders.

    Args:
        user_id: User identifier
        include_completed: Whether to include recently completed tasks

    Returns:
        Dict with summary text and metadata
    """
    open_tasks = list_open_tasks(user_id)
    completed_tasks = list_completed_tasks(user_id, limit=3) if include_completed else []

    # Build summary text
    lines = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines.append(f"📋 Task Summary ({now})")
    lines.append("")

    # Open tasks section
    if open_tasks:
        lines.append(f"📌 Open Tasks ({len(open_tasks)}):")
        for i, task in enumerate(open_tasks, 1):
            priority_emoji = {"high": "🔴", "normal": "🟡", "low": "🟢"}.get(task["priority"], "🟡")
            lines.append(f"  {i}. {priority_emoji} {task['title']}")
            if task.get("description"):
                lines.append(f"     └─ {task['description'][:50]}...")
    else:
        lines.append("✅ No open tasks! Great job!")

    # Completed tasks section
    if completed_tasks:
        lines.append("")
        lines.append(f"✓ Recently Completed ({len(completed_tasks)}):")
        for task in completed_tasks:
            lines.append(f"  • {task['title']}")

    # Statistics
    lines.append("")
    high_priority = sum(1 for t in open_tasks if t.get("priority") == "high")
    if high_priority > 0:
        lines.append(f"⚠️ {high_priority} high-priority task(s) need attention!")

    summary_text = "\n".join(lines)

    logger.info(f"Generated summary for user {user_id}: {len(open_tasks)} open tasks")

    return {
        "success": True,
        "summary": summary_text,
        "open_count": len(open_tasks),
        "completed_count": len(completed_tasks),
        "high_priority_count": high_priority,
        "generated_at": now
    }


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


def update_last_reminder(user_id: str) -> None:
    """Update the last reminder timestamp for a user."""
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


def get_users_for_reminder(hour: int, minute: int) -> list[str]:
    """Get list of user IDs that should receive reminders at given time."""
    with get_db_connection() as conn:
        cursor = conn.execute(
            """
            SELECT user_id FROM reminder_preferences
            WHERE enabled = 1 AND schedule_hour = ? AND schedule_minute = ?
            """,
            (hour, minute)
        )
        return [row["user_id"] for row in cursor.fetchall()]


# =============================================================================
# Email Functions
# =============================================================================

EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
)


def validate_email(email: str) -> bool:
    """
    Validate email format.

    Args:
        email: Email address to validate

    Returns:
        True if valid, False otherwise
    """
    if not email or not isinstance(email, str):
        return False
    return EMAIL_REGEX.match(email.strip()) is not None


def is_smtp_configured() -> bool:
    """Check if SMTP is properly configured."""
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD and SMTP_FROM_EMAIL)


def send_email_sync(recipient_email: str, subject: str, message_text: str) -> dict:
    """
    Send email via SMTP (synchronous version).

    Args:
        recipient_email: Recipient email address
        subject: Email subject
        message_text: Email body text

    Returns:
        Dict with success status and message/error
    """
    if not is_smtp_configured():
        return {
            "success": False,
            "error": "SMTP not configured. Set SMTP_HOST, SMTP_USER, SMTP_PASSWORD, SMTP_FROM_EMAIL environment variables."
        }

    if not validate_email(recipient_email):
        return {
            "success": False,
            "error": f"Invalid email format: {recipient_email}"
        }

    try:
        # Create message
        msg = MIMEMultipart()
        msg["From"] = SMTP_FROM_EMAIL
        msg["To"] = recipient_email.strip()
        msg["Subject"] = subject

        # Add body
        msg.attach(MIMEText(message_text, "plain", "utf-8"))

        # Connect and send
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
        return {
            "success": True,
            "message": f"Email sent to {recipient_email}"
        }

    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"SMTP authentication failed: {e}")
        return {
            "success": False,
            "error": "SMTP authentication failed. Check credentials."
        }
    except smtplib.SMTPException as e:
        logger.error(f"SMTP error: {e}")
        return {
            "success": False,
            "error": f"SMTP error: {str(e)}"
        }
    except Exception as e:
        logger.error(f"Email send failed: {e}", exc_info=True)
        return {
            "success": False,
            "error": f"Failed to send email: {str(e)}"
        }


async def send_email_async(recipient_email: str, subject: str, message_text: str,
                          max_retries: int = 3) -> dict:
    """
    Send email asynchronously with retry logic.

    Args:
        recipient_email: Recipient email address
        subject: Email subject
        message_text: Email body text
        max_retries: Maximum number of retries

    Returns:
        Dict with success status and message/error
    """
    loop = asyncio.get_event_loop()
    last_error = None

    for attempt in range(max_retries):
        try:
            result = await loop.run_in_executor(
                None,
                send_email_sync,
                recipient_email,
                subject,
                message_text
            )
            if result["success"]:
                return result
            last_error = result.get("error", "Unknown error")

            # Don't retry for validation errors
            if "Invalid email" in last_error or "not configured" in last_error:
                return result

        except Exception as e:
            last_error = str(e)
            logger.error(f"Email attempt {attempt + 1} failed: {e}")

        if attempt < max_retries - 1:
            await asyncio.sleep(2 ** attempt)  # Exponential backoff

    return {
        "success": False,
        "error": f"Failed after {max_retries} attempts: {last_error}"
    }


def set_email_preferences(user_id: str, email_enabled: bool,
                          email_recipient: Optional[str] = None) -> dict:
    """
    Set email notification preferences for a user.

    Args:
        user_id: User identifier
        email_enabled: Whether email notifications are enabled
        email_recipient: Email address for notifications

    Returns:
        Dict with success status
    """
    # Validate email if provided
    if email_enabled and email_recipient:
        if not validate_email(email_recipient):
            return {
                "success": False,
                "error": f"Invalid email format: {email_recipient}"
            }

    with get_db_connection() as conn:
        # First ensure user has a row
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

    logger.info(f"Set email preferences for user {user_id}: enabled={email_enabled}, recipient={email_recipient}")
    return {
        "success": True,
        "email_enabled": email_enabled,
        "email_recipient": email_recipient
    }


def get_email_preferences(user_id: str) -> dict:
    """
    Get email notification preferences for a user.

    Args:
        user_id: User identifier

    Returns:
        Dict with email preferences
    """
    with get_db_connection() as conn:
        cursor = conn.execute(
            "SELECT email_enabled, email_recipient FROM reminder_preferences WHERE user_id = ?",
            (user_id,)
        )
        row = cursor.fetchone()
        if row:
            return {
                "email_enabled": bool(row["email_enabled"]),
                "email_recipient": row["email_recipient"]
            }
        return {
            "email_enabled": False,
            "email_recipient": None
        }


# =============================================================================
# MCP Server Setup
# =============================================================================

server = Server("mcp-planner")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available MCP tools."""
    return [
        # Task Tracker Tools
        Tool(
            name="task_create",
            description="Create a new task for tracking",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "User identifier"},
                    "title": {"type": "string", "description": "Task title"},
                    "description": {"type": "string", "description": "Optional task description"},
                    "priority": {"type": "string", "enum": ["high", "normal", "low"],
                                "description": "Task priority (default: normal)"}
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
                    "user_id": {"type": "string", "description": "User identifier"}
                },
                "required": ["user_id"]
            }
        ),
        Tool(
            name="task_get_open_count",
            description="Get the count of open tasks",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "Optional user identifier"}
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
                    "user_id": {"type": "string", "description": "User identifier"},
                    "task_id": {"type": "integer", "description": "Task ID to complete"}
                },
                "required": ["user_id", "task_id"]
            }
        ),
        # Reminder Tools
        Tool(
            name="reminder_generate_summary",
            description="Generate a task summary for reminders. Returns formatted text with open tasks, priorities, and optionally completed tasks.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "User identifier"},
                    "include_completed": {"type": "boolean",
                                         "description": "Include recently completed tasks (default: false)"}
                },
                "required": ["user_id"]
            }
        ),
        Tool(
            name="reminder_get_preferences",
            description="Get reminder preferences for a user",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "User identifier"}
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
                    "user_id": {"type": "string", "description": "User identifier"},
                    "enabled": {"type": "boolean", "description": "Enable or disable reminders"},
                    "hour": {"type": "integer", "description": "Hour for daily reminder (0-23)"},
                    "minute": {"type": "integer", "description": "Minute for daily reminder (0-59)"}
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
                    "hour": {"type": "integer", "description": "Hour (0-23)"},
                    "minute": {"type": "integer", "description": "Minute (0-59)"}
                },
                "required": ["hour", "minute"]
            }
        ),
        Tool(
            name="reminder_mark_sent",
            description="Mark that a reminder was sent to a user",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "User identifier"}
                },
                "required": ["user_id"]
            }
        ),
        # Email Notification Tools
        Tool(
            name="notification_send_email",
            description="Send an email notification. Requires SMTP configuration via environment variables.",
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
            description="Set email notification preferences for reminder notifications",
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
            description="Get email notification preferences for a user",
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
    """Handle tool invocations."""
    logger.info(f"Tool called: {name} with args: {arguments}")

    try:
        # Task Tracker tools
        if name == "task_create":
            result = create_task(
                user_id=arguments["user_id"],
                title=arguments["title"],
                description=arguments.get("description"),
                priority=arguments.get("priority", "normal")
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
        # Reminder tools
        elif name == "reminder_generate_summary":
            result = generate_summary(
                user_id=arguments["user_id"],
                include_completed=arguments.get("include_completed", False)
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
        elif name == "reminder_mark_sent":
            update_last_reminder(user_id=arguments["user_id"])
            result = {"success": True}
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
            result = {
                "valid": is_valid,
                "email": email,
                "message": "Valid email format" if is_valid else "Invalid email format"
            }
        else:
            result = {"error": f"Unknown tool: {name}"}

        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

    except Exception as e:
        logger.error(f"Error calling tool {name}: {e}", exc_info=True)
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


# =============================================================================
# HTTP Server (REST API for Kubernetes)
# =============================================================================

async def handle_health(request: web.Request) -> web.Response:
    """Health check endpoint for Kubernetes probes."""
    return web.json_response({"status": "healthy", "service": "mcp-planner"})


async def handle_ready(request: web.Request) -> web.Response:
    """Readiness check endpoint."""
    try:
        # Check database connection
        with get_db_connection() as conn:
            conn.execute("SELECT 1")
        return web.json_response({"status": "ready"})
    except Exception as e:
        return web.json_response({"status": "not ready", "error": str(e)}, status=503)


async def handle_list_tools(request: web.Request) -> web.Response:
    """List available MCP tools via HTTP."""
    tools = await list_tools()
    tools_data = [
        {
            "name": tool.name,
            "description": tool.description,
            "inputSchema": tool.inputSchema
        }
        for tool in tools
    ]
    return web.json_response({"tools": tools_data})


async def handle_call_tool(request: web.Request) -> web.Response:
    """Call an MCP tool via HTTP."""
    try:
        data = await request.json()
        tool_name = data.get("name")
        arguments = data.get("arguments", {})

        if not tool_name:
            return web.json_response({"error": "Missing tool name"}, status=400)

        result = await call_tool(tool_name, arguments)

        # Parse the result from TextContent
        if result and len(result) > 0:
            result_data = json.loads(result[0].text)
            return web.json_response({"result": result_data})

        return web.json_response({"error": "Empty result"}, status=500)

    except json.JSONDecodeError:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    except Exception as e:
        logger.error(f"Error handling tool call: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)


def create_app() -> web.Application:
    """Create the aiohttp application."""
    app = web.Application()

    # Routes
    app.router.add_get("/health", handle_health)
    app.router.add_get("/ready", handle_ready)
    app.router.add_get("/tools", handle_list_tools)
    app.router.add_post("/tools/call", handle_call_tool)

    return app


async def main():
    """Run the MCP server with HTTP transport."""
    # Initialize database
    init_database()

    # Create and run HTTP server
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, HOST, PORT)

    logger.info(f"Starting MCP Planner Server on {HOST}:{PORT}")
    logger.info(f"Data directory: {DATA_DIR}")
    logger.info("Endpoints:")
    logger.info(f"  - GET  /health      - Health check")
    logger.info(f"  - GET  /ready       - Readiness check")
    logger.info(f"  - GET  /tools       - List tools")
    logger.info(f"  - POST /tools/call  - Call a tool")

    await site.start()

    # Keep running
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
