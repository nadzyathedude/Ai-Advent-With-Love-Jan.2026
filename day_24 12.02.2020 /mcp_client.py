"""MCP client — thin wrapper around mcp.call_service and mcp.list_services tools.

Provides a clean interface for the assistant agent to call MCP services
via the tool registry.
"""

from typing import Any, Dict, List

from core.registry.tool_registry import ToolResult


def call_service(
    registry, agent_id: str, service: str, action: str, params: Dict[str, Any] = None
) -> Dict[str, Any]:
    """Call an MCP service via the mcp_bridge plugin.

    Returns the service response data or an error dict.
    """
    if registry is None:
        return {"error": "No registry available"}
    result: ToolResult = registry.invoke(
        "mcp.call_service", agent_id,
        service=service, action=action, params=params or {},
    )
    if result.success:
        return result.data
    return {"error": result.error}


def list_services(registry, agent_id: str) -> List[Dict[str, Any]]:
    """List all available MCP services.

    Returns a list of {name, description, actions} dicts.
    """
    if registry is None:
        return []
    result: ToolResult = registry.invoke("mcp.list_services", agent_id)
    if result.success and result.data:
        return result.data
    return []
