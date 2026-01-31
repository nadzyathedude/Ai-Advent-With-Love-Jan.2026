"""
Task Tracker MCP Client Module.

This module provides a client for connecting to the Task Tracker MCP Server
via stdio transport. It allows the Telegram bot to call task management tools
through the MCP protocol.
"""

import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


@dataclass
class TaskTrackerTool:
    """Represents a Task Tracker MCP tool."""
    name: str
    description: str
    input_schema: dict


@dataclass
class TaskTrackerResult:
    """Result from a Task Tracker tool call."""
    success: bool
    data: Optional[dict] = None
    error: Optional[str] = None


class TaskTrackerMCPClient:
    """
    Client for connecting to the Task Tracker MCP Server.

    Uses stdio transport to communicate with the server.
    """

    def __init__(self, server_script_path: Optional[str] = None):
        """
        Initialize the Task Tracker MCP client.

        Args:
            server_script_path: Path to task_tracker_server.py.
                               If None, uses the default path relative to this file.
        """
        if server_script_path is None:
            self.server_script_path = str(
                Path(__file__).parent / "task_tracker_server.py"
            )
        else:
            self.server_script_path = server_script_path

        self._tools_cache: Optional[list[TaskTrackerTool]] = None

    def _get_server_params(self) -> StdioServerParameters:
        """Get server parameters for stdio connection."""
        return StdioServerParameters(
            command=sys.executable,  # Use the same Python interpreter
            args=[self.server_script_path]
        )

    async def list_tools(self) -> list[TaskTrackerTool]:
        """
        List available tools from the Task Tracker MCP Server.

        Returns:
            List of TaskTrackerTool objects
        """
        # Return cached tools if available
        if self._tools_cache is not None:
            return self._tools_cache

        server_params = self._get_server_params()
        logger.info("Connecting to Task Tracker MCP Server...")

        try:
            async with stdio_client(server_params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    logger.info("Task Tracker MCP session initialized")

                    response = await session.list_tools()

                    tools = []
                    for tool in response.tools:
                        tracker_tool = TaskTrackerTool(
                            name=tool.name,
                            description=tool.description or "No description",
                            input_schema=tool.inputSchema if hasattr(tool, 'inputSchema') else {}
                        )
                        tools.append(tracker_tool)
                        logger.info(f"Found Task Tracker tool: {tool.name}")

                    self._tools_cache = tools
                    return tools

        except Exception as e:
            logger.error(f"Failed to list Task Tracker tools: {e}", exc_info=True)
            raise

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> TaskTrackerResult:
        """
        Call a Task Tracker MCP tool.

        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments

        Returns:
            TaskTrackerResult with the result or error
        """
        server_params = self._get_server_params()
        logger.info(f"Calling Task Tracker tool: {tool_name} with args: {arguments}")

        try:
            async with stdio_client(server_params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    result = await session.call_tool(tool_name, arguments)

                    # Parse the result
                    if result.content and len(result.content) > 0:
                        text_content = result.content[0]
                        if hasattr(text_content, 'text'):
                            data = json.loads(text_content.text)

                            # Check if the result indicates an error
                            if "error" in data and not data.get("success", True):
                                return TaskTrackerResult(
                                    success=False,
                                    error=data["error"]
                                )

                            return TaskTrackerResult(success=True, data=data)

                    return TaskTrackerResult(
                        success=False,
                        error="Empty response from server"
                    )

        except asyncio.TimeoutError:
            error_msg = "Task Tracker MCP Server connection timed out"
            logger.error(error_msg)
            return TaskTrackerResult(success=False, error=error_msg)

        except Exception as e:
            error_msg = f"Failed to call Task Tracker tool: {e}"
            logger.error(error_msg, exc_info=True)
            return TaskTrackerResult(success=False, error=error_msg)

    async def create_task(self, user_id: str, title: str, description: Optional[str] = None) -> TaskTrackerResult:
        """
        Create a new task.

        Args:
            user_id: User identifier
            title: Task title
            description: Optional task description

        Returns:
            TaskTrackerResult with task info
        """
        args = {"user_id": user_id, "title": title}
        if description:
            args["description"] = description
        return await self.call_tool("task_create", args)

    async def list_open_tasks(self, user_id: str) -> TaskTrackerResult:
        """
        List all open tasks for a user.

        Args:
            user_id: User identifier

        Returns:
            TaskTrackerResult with list of tasks
        """
        return await self.call_tool("task_list_open", {"user_id": user_id})

    async def get_open_count(self, user_id: Optional[str] = None) -> TaskTrackerResult:
        """
        Get count of open tasks.

        Args:
            user_id: Optional user identifier

        Returns:
            TaskTrackerResult with count
        """
        args = {}
        if user_id:
            args["user_id"] = user_id
        return await self.call_tool("task_get_open_count", args)

    async def complete_task(self, user_id: str, task_id: int) -> TaskTrackerResult:
        """
        Mark a task as completed.

        Args:
            user_id: User identifier
            task_id: Task ID

        Returns:
            TaskTrackerResult with result
        """
        return await self.call_tool("task_complete", {"user_id": user_id, "task_id": task_id})


# Global client instance
_task_tracker_client: Optional[TaskTrackerMCPClient] = None


def init_task_tracker_client(server_script_path: Optional[str] = None) -> None:
    """
    Initialize the global Task Tracker MCP client.

    Args:
        server_script_path: Optional path to the server script
    """
    global _task_tracker_client
    _task_tracker_client = TaskTrackerMCPClient(server_script_path)
    logger.info("Task Tracker MCP client initialized")


def get_task_tracker_client() -> Optional[TaskTrackerMCPClient]:
    """
    Get the global Task Tracker MCP client.

    Returns:
        TaskTrackerMCPClient instance or None
    """
    return _task_tracker_client


async def get_task_tracker_tools() -> list[TaskTrackerTool]:
    """
    Convenience function to get Task Tracker tools.

    Returns:
        List of available tools

    Raises:
        RuntimeError: If client not initialized
    """
    client = get_task_tracker_client()
    if client is None:
        raise RuntimeError("Task Tracker MCP client not initialized")
    return await client.list_tools()


def format_tasks_for_telegram(result: TaskTrackerResult) -> str:
    """
    Format task list result for Telegram message.

    Args:
        result: TaskTrackerResult from list_open_tasks()

    Returns:
        Formatted string for Telegram (Markdown)
    """
    if not result.success:
        return f"*Error:* {result.error}"

    if not result.data:
        return "No data received from server."

    tasks = result.data.get("tasks", [])
    count = result.data.get("count", len(tasks))

    if count == 0:
        return "No open tasks found. Use `/task_add <title>` to create one."

    lines = [f"*Open Tasks ({count}):*\n"]

    for task in tasks:
        task_id = task.get("id", "?")
        title = task.get("title", "Untitled")
        description = task.get("description")

        # Escape underscores for Telegram Markdown
        title_escaped = title.replace("_", "\\_")

        line = f"{task_id}. {title_escaped}"
        if description:
            desc_escaped = description.replace("_", "\\_")
            line += f"\n   _{desc_escaped}_"
        lines.append(line)

    lines.append(f"\nUse `/task_done <id>` to complete a task.")
    return "\n".join(lines)


def format_open_count_for_telegram(result: TaskTrackerResult) -> str:
    """
    Format open count result for Telegram message.

    Args:
        result: TaskTrackerResult from get_open_count()

    Returns:
        Formatted string for Telegram
    """
    if not result.success:
        return f"*Error:* {result.error}"

    if not result.data:
        return "No data received from server."

    count = result.data.get("count", 0)
    user_id = result.data.get("user_id", "all")

    if user_id == "all":
        return f"Open tasks (all users): **{count}**"
    else:
        return f"Open tasks: **{count}**"
