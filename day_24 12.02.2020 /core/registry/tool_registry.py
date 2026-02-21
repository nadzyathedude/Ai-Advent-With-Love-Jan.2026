"""Tool abstraction, result type, and registry with permission-checked invocation."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ToolResult:
    """Result returned by every tool execution."""
    success: bool
    data: Any = None
    error: Optional[str] = None


class Tool(ABC):
    """Base class for all tools loaded from plugins."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique tool name, e.g. 'docs.search_project_docs'."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of the tool."""

    @property
    @abstractmethod
    def required_permissions(self) -> List[str]:
        """Permissions the calling agent must have."""

    @abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        """Run the tool and return a ToolResult."""


class ToolRegistry:
    """Stores tools and invokes them with permission enforcement."""

    def __init__(self, permission_checker=None):
        self._tools: Dict[str, Tool] = {}
        self._permission_checker = permission_checker

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list_tools(self) -> List[Tool]:
        return list(self._tools.values())

    def invoke(self, tool_name: str, agent_id: str, **kwargs) -> ToolResult:
        """Invoke a tool by name, enforcing permissions for the given agent."""
        tool = self._tools.get(tool_name)
        if tool is None:
            return ToolResult(success=False, error=f"Tool '{tool_name}' not found")

        if self._permission_checker:
            self._permission_checker.enforce(agent_id, tool.required_permissions)

        return tool.execute(**kwargs)
