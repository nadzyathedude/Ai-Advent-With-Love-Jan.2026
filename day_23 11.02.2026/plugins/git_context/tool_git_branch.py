"""Git branch tool — returns the current branch name via subprocess."""

import subprocess
from typing import List

from core.registry.tool_registry import Tool, ToolResult


class GitBranchTool(Tool):
    """Returns the current git branch name."""

    @property
    def name(self) -> str:
        return "git.current_branch"

    @property
    def description(self) -> str:
        return "Returns the name of the current git branch."

    @property
    def required_permissions(self) -> List[str]:
        return ["git:read"]

    def execute(self, **kwargs) -> ToolResult:
        try:
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    error=f"git exited with code {result.returncode}: {result.stderr.strip()}",
                )
            branch = result.stdout.strip()
            return ToolResult(success=True, data=branch)
        except FileNotFoundError:
            return ToolResult(success=False, error="git is not installed or not in PATH")
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error="git command timed out after 10s")
