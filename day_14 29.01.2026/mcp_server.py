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
import sqlite3
from contextlib import contextmanager
from datetime import datetime
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
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
