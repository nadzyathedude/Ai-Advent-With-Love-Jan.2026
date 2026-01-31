"""
MCP HTTP Client for Kubernetes deployment.

This module provides an HTTP-based MCP client that connects to the MCP server
via REST API. Designed for Kubernetes inter-pod communication.

Features:
- Connection pooling with aiohttp
- Automatic retries with exponential backoff
- Health check support
- Configurable timeout and retry settings
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

import aiohttp
from aiohttp import ClientTimeout, ClientError

logger = logging.getLogger(__name__)

# Configuration from environment
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8080")
MCP_TIMEOUT = int(os.getenv("MCP_TIMEOUT", "30"))
MCP_MAX_RETRIES = int(os.getenv("MCP_MAX_RETRIES", "3"))


@dataclass
class MCPTool:
    """Represents an MCP tool."""
    name: str
    description: str
    input_schema: dict


@dataclass
class MCPResult:
    """Result from an MCP tool call."""
    success: bool
    data: Optional[dict] = None
    error: Optional[str] = None


class MCPHttpClient:
    """
    HTTP-based MCP client for Kubernetes.

    Connects to MCP server via REST API with automatic retries
    and connection pooling.
    """

    def __init__(self, base_url: Optional[str] = None,
                 timeout: int = MCP_TIMEOUT,
                 max_retries: int = MCP_MAX_RETRIES):
        """
        Initialize the MCP HTTP client.

        Args:
            base_url: Base URL of the MCP server
            timeout: Request timeout in seconds
            max_retries: Maximum number of retries
        """
        self.base_url = (base_url or MCP_SERVER_URL).rstrip("/")
        self.timeout = ClientTimeout(total=timeout)
        self.max_retries = max_retries
        self._session: Optional[aiohttp.ClientSession] = None
        self._tools_cache: Optional[list[MCPTool]] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
        return self._session

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _request_with_retry(self, method: str, endpoint: str,
                                  json_data: Optional[dict] = None) -> dict:
        """
        Make HTTP request with automatic retries.

        Args:
            method: HTTP method (GET, POST)
            endpoint: API endpoint
            json_data: Optional JSON body

        Returns:
            Response JSON data

        Raises:
            Exception: If all retries fail
        """
        url = f"{self.base_url}{endpoint}"
        last_error = None

        for attempt in range(self.max_retries):
            try:
                session = await self._get_session()

                if method == "GET":
                    async with session.get(url) as response:
                        response.raise_for_status()
                        return await response.json()
                elif method == "POST":
                    async with session.post(url, json=json_data) as response:
                        response.raise_for_status()
                        return await response.json()

            except ClientError as e:
                last_error = e
                wait_time = 2 ** attempt  # Exponential backoff
                logger.warning(
                    f"MCP request failed (attempt {attempt + 1}/{self.max_retries}): {e}. "
                    f"Retrying in {wait_time}s..."
                )
                await asyncio.sleep(wait_time)

            except asyncio.TimeoutError:
                last_error = TimeoutError("Request timed out")
                wait_time = 2 ** attempt
                logger.warning(
                    f"MCP request timed out (attempt {attempt + 1}/{self.max_retries}). "
                    f"Retrying in {wait_time}s..."
                )
                await asyncio.sleep(wait_time)

        raise Exception(f"MCP request failed after {self.max_retries} attempts: {last_error}")

    async def health_check(self) -> bool:
        """
        Check if the MCP server is healthy.

        Returns:
            True if healthy, False otherwise
        """
        try:
            data = await self._request_with_retry("GET", "/health")
            return data.get("status") == "healthy"
        except Exception as e:
            logger.error(f"MCP health check failed: {e}")
            return False

    async def is_ready(self) -> bool:
        """
        Check if the MCP server is ready.

        Returns:
            True if ready, False otherwise
        """
        try:
            data = await self._request_with_retry("GET", "/ready")
            return data.get("status") == "ready"
        except Exception as e:
            logger.error(f"MCP readiness check failed: {e}")
            return False

    async def list_tools(self, use_cache: bool = True) -> list[MCPTool]:
        """
        List available MCP tools.

        Args:
            use_cache: Whether to use cached results

        Returns:
            List of MCPTool objects
        """
        if use_cache and self._tools_cache is not None:
            return self._tools_cache

        try:
            data = await self._request_with_retry("GET", "/tools")
            tools = [
                MCPTool(
                    name=t["name"],
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {})
                )
                for t in data.get("tools", [])
            ]
            self._tools_cache = tools
            logger.info(f"Fetched {len(tools)} MCP tools")
            return tools

        except Exception as e:
            logger.error(f"Failed to list MCP tools: {e}")
            raise

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> MCPResult:
        """
        Call an MCP tool.

        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments

        Returns:
            MCPResult with the result or error
        """
        logger.info(f"Calling MCP tool: {tool_name} with args: {arguments}")

        try:
            data = await self._request_with_retry(
                "POST",
                "/tools/call",
                json_data={"name": tool_name, "arguments": arguments}
            )

            result = data.get("result", {})

            if "error" in result and not result.get("success", True):
                return MCPResult(success=False, error=result["error"])

            return MCPResult(success=True, data=result)

        except Exception as e:
            error_msg = f"MCP tool call failed: {e}"
            logger.error(error_msg)
            return MCPResult(success=False, error=error_msg)

    # ==========================================================================
    # Convenience methods for Task Tracker
    # ==========================================================================

    async def create_task(self, user_id: str, title: str,
                         description: Optional[str] = None,
                         priority: str = "normal") -> MCPResult:
        """Create a new task."""
        args = {"user_id": user_id, "title": title, "priority": priority}
        if description:
            args["description"] = description
        return await self.call_tool("task_create", args)

    async def list_open_tasks(self, user_id: str) -> MCPResult:
        """List all open tasks for a user."""
        return await self.call_tool("task_list_open", {"user_id": user_id})

    async def get_open_count(self, user_id: Optional[str] = None) -> MCPResult:
        """Get count of open tasks."""
        args = {}
        if user_id:
            args["user_id"] = user_id
        return await self.call_tool("task_get_open_count", args)

    async def complete_task(self, user_id: str, task_id: int) -> MCPResult:
        """Mark a task as completed."""
        return await self.call_tool("task_complete", {"user_id": user_id, "task_id": task_id})

    # ==========================================================================
    # Convenience methods for Reminder
    # ==========================================================================

    async def generate_summary(self, user_id: str,
                              include_completed: bool = False) -> MCPResult:
        """Generate a task summary."""
        return await self.call_tool("reminder_generate_summary", {
            "user_id": user_id,
            "include_completed": include_completed
        })

    async def get_reminder_preferences(self, user_id: str) -> MCPResult:
        """Get reminder preferences for a user."""
        return await self.call_tool("reminder_get_preferences", {"user_id": user_id})

    async def set_reminder_preferences(self, user_id: str, enabled: bool,
                                       hour: int = 9, minute: int = 0) -> MCPResult:
        """Set reminder preferences."""
        return await self.call_tool("reminder_set_preferences", {
            "user_id": user_id,
            "enabled": enabled,
            "hour": hour,
            "minute": minute
        })

    async def get_scheduled_users(self, hour: int, minute: int) -> MCPResult:
        """Get users scheduled for reminder at given time."""
        return await self.call_tool("reminder_get_scheduled_users", {
            "hour": hour,
            "minute": minute
        })

    async def mark_reminder_sent(self, user_id: str) -> MCPResult:
        """Mark that a reminder was sent."""
        return await self.call_tool("reminder_mark_sent", {"user_id": user_id})


# Global client instance
_mcp_client: Optional[MCPHttpClient] = None


def init_mcp_http_client(base_url: Optional[str] = None) -> MCPHttpClient:
    """
    Initialize the global MCP HTTP client.

    Args:
        base_url: Optional base URL for the MCP server

    Returns:
        MCPHttpClient instance
    """
    global _mcp_client
    _mcp_client = MCPHttpClient(base_url=base_url)
    logger.info(f"MCP HTTP client initialized: {_mcp_client.base_url}")
    return _mcp_client


def get_mcp_http_client() -> Optional[MCPHttpClient]:
    """Get the global MCP HTTP client."""
    return _mcp_client


async def close_mcp_http_client() -> None:
    """Close the global MCP HTTP client."""
    global _mcp_client
    if _mcp_client:
        await _mcp_client.close()
        _mcp_client = None
