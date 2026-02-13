"""
MCP Client Module for Perplexity MCP Server integration.

This module provides a minimal MCP client that connects to the Perplexity MCP Server
via stdio transport and allows querying available tools.
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


@dataclass
class MCPTool:
    """Represents an MCP tool with its metadata."""
    name: str
    description: str
    input_schema: dict


@dataclass
class MCPToolsResult:
    """Result of listing MCP tools."""
    tools: list[MCPTool]
    error: Optional[str] = None
    cached: bool = False


@dataclass
class MCPCallResult:
    """Result of calling an MCP tool."""
    success: bool
    data: Optional[dict] = None
    error: Optional[str] = None


class PerplexityMCPClient:
    """
    Client for connecting to the Perplexity MCP Server.

    Uses stdio transport to communicate with the server via npx.
    Implements connection pooling and caching for efficiency.
    """

    # Cache settings
    CACHE_TTL_SECONDS = 30

    def __init__(self, api_key: str):
        """
        Initialize the MCP client.

        Args:
            api_key: Perplexity API key for authentication
        """
        self.api_key = api_key
        self._tools_cache: Optional[list[MCPTool]] = None
        self._cache_timestamp: float = 0

    def _is_cache_valid(self) -> bool:
        """Check if the cached tools are still valid."""
        if self._tools_cache is None:
            return False
        return (time.time() - self._cache_timestamp) < self.CACHE_TTL_SECONDS

    async def list_tools(self, use_cache: bool = True) -> MCPToolsResult:
        """
        List all available tools from the Perplexity MCP Server.

        Args:
            use_cache: Whether to use cached results if available (default: True)

        Returns:
            MCPToolsResult with list of tools or error message
        """
        # Check cache first
        if use_cache and self._is_cache_valid():
            logger.info("Returning cached MCP tools")
            return MCPToolsResult(tools=self._tools_cache, cached=True)

        try:
            tools = await self._fetch_tools()

            # Update cache
            self._tools_cache = tools
            self._cache_timestamp = time.time()

            return MCPToolsResult(tools=tools)

        except FileNotFoundError as e:
            error_msg = (
                "Node.js/npx not found. Please install Node.js to use the Perplexity MCP Server. "
                f"Error: {e}"
            )
            logger.error(error_msg)
            return MCPToolsResult(tools=[], error=error_msg)

        except asyncio.TimeoutError:
            error_msg = "Connection to Perplexity MCP Server timed out"
            logger.error(error_msg)
            return MCPToolsResult(tools=[], error=error_msg)

        except Exception as e:
            error_msg = f"Failed to connect to Perplexity MCP Server: {e}"
            logger.error(error_msg, exc_info=True)
            return MCPToolsResult(tools=[], error=error_msg)

    async def _fetch_tools(self) -> list[MCPTool]:
        """
        Fetch tools from the MCP server via stdio.

        Returns:
            List of MCPTool objects
        """
        # Configure server parameters for Perplexity MCP Server
        server_params = StdioServerParameters(
            command="npx",
            args=["-yq", "@perplexity-ai/mcp-server"],
            env={
                **os.environ,
                "PERPLEXITY_API_KEY": self.api_key
            }
        )

        logger.info("Connecting to Perplexity MCP Server...")

        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                # Initialize the MCP session
                await session.initialize()
                logger.info("MCP session initialized")

                # Request the list of tools
                response = await session.list_tools()

                tools = []
                for tool in response.tools:
                    mcp_tool = MCPTool(
                        name=tool.name,
                        description=tool.description or "No description available",
                        input_schema=tool.inputSchema if hasattr(tool, 'inputSchema') else {}
                    )
                    tools.append(mcp_tool)
                    logger.info(f"Found MCP tool: {tool.name}")

                return tools

    async def call_tool(self, tool_name: str, arguments: dict) -> MCPCallResult:
        """
        Call an MCP tool on the Perplexity server.

        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments

        Returns:
            MCPCallResult with the result or error
        """
        server_params = StdioServerParameters(
            command="npx",
            args=["-yq", "@perplexity-ai/mcp-server"],
            env={
                **os.environ,
                "PERPLEXITY_API_KEY": self.api_key
            }
        )

        logger.info(f"Calling Perplexity MCP tool: {tool_name}")

        try:
            async with stdio_client(server_params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    result = await session.call_tool(tool_name, arguments)

                    # Parse the result
                    if result.content and len(result.content) > 0:
                        text_content = result.content[0]
                        if hasattr(text_content, 'text'):
                            return MCPCallResult(
                                success=True,
                                data={"text": text_content.text}
                            )

                    return MCPCallResult(
                        success=False,
                        error="Empty response from Perplexity server"
                    )

        except Exception as e:
            error_msg = f"Failed to call Perplexity tool: {e}"
            logger.error(error_msg, exc_info=True)
            return MCPCallResult(success=False, error=error_msg)

    async def ask_perplexity(self, query: str) -> MCPCallResult:
        """
        Ask Perplexity a question using the perplexity_ask tool.

        Args:
            query: The question to ask

        Returns:
            MCPCallResult with the response or error
        """
        # Perplexity MCP server expects a messages array
        messages = [
            {"role": "user", "content": query}
        ]
        return await self.call_tool("perplexity_ask", {"messages": messages})


# Global client instance (initialized lazily)
_mcp_client: Optional[PerplexityMCPClient] = None


def init_mcp_client(api_key: str) -> None:
    """
    Initialize the global MCP client instance.

    Args:
        api_key: Perplexity API key
    """
    global _mcp_client
    _mcp_client = PerplexityMCPClient(api_key)
    logger.info("MCP client initialized")


def get_mcp_client() -> Optional[PerplexityMCPClient]:
    """
    Get the global MCP client instance.

    Returns:
        PerplexityMCPClient instance or None if not initialized
    """
    return _mcp_client


async def get_mcp_tools() -> MCPToolsResult:
    """
    Convenience function to get MCP tools.

    Returns:
        MCPToolsResult with tools or error
    """
    client = get_mcp_client()
    if client is None:
        return MCPToolsResult(
            tools=[],
            error="MCP client not initialized. Please configure PERPLEXITY_API_KEY."
        )
    return await client.list_tools()


def format_tools_for_telegram(result: MCPToolsResult) -> str:
    """
    Format MCP tools list for Telegram message.

    Args:
        result: MCPToolsResult from list_tools()

    Returns:
        Formatted string for Telegram (Markdown)
    """
    if result.error:
        return f"*Error:* {result.error}"

    if not result.tools:
        return "No MCP tools available from the Perplexity server."

    lines = ["*Perplexity MCP Server Tools:*\n"]

    for i, tool in enumerate(result.tools, 1):
        # Escape underscores for Telegram Markdown
        name = tool.name.replace("_", "\\_")
        description = tool.description.replace("_", "\\_")

        lines.append(f"{i}. `{name}`")
        lines.append(f"   {description}\n")

    if result.cached:
        lines.append("\n_Cached result_")

    return "\n".join(lines)


async def ask_perplexity(query: str) -> MCPCallResult:
    """
    Convenience function to ask Perplexity a question.

    Args:
        query: The question to ask

    Returns:
        MCPCallResult with response or error
    """
    client = get_mcp_client()
    if client is None:
        return MCPCallResult(
            success=False,
            error="MCP client not initialized. Please configure PERPLEXITY_API_KEY."
        )
    return await client.ask_perplexity(query)
