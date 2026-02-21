"""MCP bridge tools — mock MCP service abstraction layer.

Provides a simulated MCP service registry with handlers for calendar,
notifications, and metrics services. Designed to demonstrate the MCP
integration pattern without external dependencies.
"""

import time
from typing import Any, Dict, List, Optional

from core.registry.tool_registry import Tool, ToolResult


# ---------------------------------------------------------------------------
# Mock service handlers
# ---------------------------------------------------------------------------

def _handle_calendar(action: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Mock calendar service."""
    if action == "today":
        return {
            "events": [
                {"time": "09:00", "title": "Team standup", "duration": "15min"},
                {"time": "11:00", "title": "Sprint planning", "duration": "60min"},
                {"time": "14:00", "title": "Code review session", "duration": "30min"},
                {"time": "16:00", "title": "1:1 with manager", "duration": "30min"},
            ],
            "date": "2026-02-20",
        }
    if action == "next_meeting":
        return {
            "time": "09:00",
            "title": "Team standup",
            "duration": "15min",
            "in_minutes": 45,
        }
    if action == "free_slots":
        return {
            "date": "2026-02-20",
            "slots": ["10:00-11:00", "12:00-14:00", "15:00-16:00"],
        }
    return {"error": f"Unknown calendar action: {action}"}


def _handle_notifications(action: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Mock notifications service."""
    if action == "unread":
        return {
            "count": 3,
            "items": [
                {"type": "pr_review", "message": "PR #142 approved by alice", "age": "2h"},
                {"type": "ci_build", "message": "Build #891 passed on main", "age": "4h"},
                {"type": "mention", "message": "bob mentioned you in #dev-chat", "age": "6h"},
            ],
        }
    if action == "send":
        channel = params.get("channel", "default")
        message = params.get("message", "")
        return {"sent": True, "channel": channel, "message": message}
    return {"error": f"Unknown notifications action: {action}"}


def _handle_metrics(action: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Mock metrics service."""
    if action == "summary":
        return {
            "period": "last_7_days",
            "commits": 23,
            "prs_merged": 5,
            "prs_open": 3,
            "issues_closed": 8,
            "issues_open": 12,
            "avg_review_time_hours": 4.2,
        }
    if action == "velocity":
        return {
            "current_sprint": {"planned": 34, "completed": 21, "remaining": 13},
            "burn_rate": 3.0,
            "estimated_completion": "2026-02-25",
        }
    return {"error": f"Unknown metrics action: {action}"}


# ---------------------------------------------------------------------------
# Service registry
# ---------------------------------------------------------------------------

SERVICE_REGISTRY: Dict[str, Dict[str, Any]] = {
    "calendar": {
        "description": "Calendar and scheduling service",
        "actions": ["today", "next_meeting", "free_slots"],
        "handler": _handle_calendar,
    },
    "notifications": {
        "description": "Notification and messaging service",
        "actions": ["unread", "send"],
        "handler": _handle_notifications,
    },
    "metrics": {
        "description": "Development metrics and velocity tracking",
        "actions": ["summary", "velocity"],
        "handler": _handle_metrics,
    },
}


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


class CallServiceTool(Tool):
    """Calls a mock MCP service with a specified action."""

    @property
    def name(self) -> str:
        return "mcp.call_service"

    @property
    def description(self) -> str:
        return "Call an MCP service by name with an action and optional parameters."

    @property
    def required_permissions(self) -> List[str]:
        return ["mcp:read"]

    def execute(self, **kwargs) -> ToolResult:
        service_name = kwargs.get("service", "")
        action = kwargs.get("action", "")
        params = kwargs.get("params", {})

        if not service_name:
            return ToolResult(success=False, error="Missing required argument: service")
        if not action:
            return ToolResult(success=False, error="Missing required argument: action")

        service = SERVICE_REGISTRY.get(service_name)
        if service is None:
            available = ", ".join(sorted(SERVICE_REGISTRY.keys()))
            return ToolResult(
                success=False,
                error=f"Unknown service: {service_name}. Available: {available}",
            )

        if action not in service["actions"]:
            available = ", ".join(service["actions"])
            return ToolResult(
                success=False,
                error=f"Unknown action '{action}' for {service_name}. Available: {available}",
            )

        handler = service["handler"]
        result = handler(action, params if isinstance(params, dict) else {})
        if "error" in result:
            return ToolResult(success=False, error=result["error"])
        return ToolResult(success=True, data=result)


class ListServicesTool(Tool):
    """Lists all available MCP services."""

    @property
    def name(self) -> str:
        return "mcp.list_services"

    @property
    def description(self) -> str:
        return "List all available MCP services and their supported actions."

    @property
    def required_permissions(self) -> List[str]:
        return ["mcp:read"]

    def execute(self, **kwargs) -> ToolResult:
        services = []
        for name, info in SERVICE_REGISTRY.items():
            services.append({
                "name": name,
                "description": info["description"],
                "actions": info["actions"],
            })
        return ToolResult(success=True, data=services)
