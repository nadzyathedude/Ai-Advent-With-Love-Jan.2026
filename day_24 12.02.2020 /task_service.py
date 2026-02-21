"""Task service — thin wrapper around the task manager plugin tools.

Provides a clean interface for the assistant agent to perform task CRUD
operations via the tool registry.
"""

from typing import Any, Dict, List, Optional

from core.registry.tool_registry import ToolResult


def create_task(
    registry, agent_id: str,
    title: str,
    description: str = "",
    priority: str = "medium",
    effort: str = "medium",
    due_date: str = "",
    tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create a new task via the task_manager plugin."""
    if registry is None:
        return {"error": "No registry available"}
    result: ToolResult = registry.invoke(
        "task.create", agent_id,
        title=title, description=description, priority=priority,
        effort=effort, due_date=due_date, tags=tags,
    )
    if result.success:
        return result.data
    return {"error": result.error}


def list_tasks(
    registry, agent_id: str,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """List tasks with optional filters via the task_manager plugin."""
    if registry is None:
        return []
    result: ToolResult = registry.invoke(
        "task.list", agent_id,
        status=status, priority=priority, tag=tag, limit=limit,
    )
    if result.success and result.data:
        return result.data
    return []


def get_task(registry, agent_id: str, task_id: int) -> Dict[str, Any]:
    """Get a single task by ID."""
    if registry is None:
        return {"error": "No registry available"}
    result: ToolResult = registry.invoke("task.get", agent_id, task_id=task_id)
    if result.success:
        return result.data
    return {"error": result.error}


def project_status(registry, agent_id: str) -> Dict[str, Any]:
    """Get aggregate project status."""
    if registry is None:
        return {"error": "No registry available"}
    result: ToolResult = registry.invoke("task.project_status", agent_id)
    if result.success:
        return result.data
    return {"error": result.error}
