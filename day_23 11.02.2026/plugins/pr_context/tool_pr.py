"""PR context tools — fetch git diff and file contents via subprocess."""

import subprocess
from pathlib import Path
from typing import List

from core.registry.tool_registry import Tool, ToolResult


class PRGetDiffTool(Tool):
    """Returns the unified diff between the current branch and a base branch."""

    @property
    def name(self) -> str:
        return "pr.get_diff"

    @property
    def description(self) -> str:
        return "Returns git diff against a base branch (default: main)."

    @property
    def required_permissions(self) -> List[str]:
        return ["pr:read"]

    def execute(self, **kwargs) -> ToolResult:
        base_branch = kwargs.get("base_branch", "main")
        try:
            result = subprocess.run(
                ["git", "diff", base_branch],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    error=f"git diff exited with code {result.returncode}: {result.stderr.strip()}",
                )
            return ToolResult(success=True, data=result.stdout)
        except FileNotFoundError:
            return ToolResult(success=False, error="git is not installed or not in PATH")
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error="git diff timed out after 30s")


class PRGetFileContentTool(Tool):
    """Reads the content of a file from the working tree."""

    @property
    def name(self) -> str:
        return "pr.get_file_content"

    @property
    def description(self) -> str:
        return "Reads the content of a file from the working tree."

    @property
    def required_permissions(self) -> List[str]:
        return ["pr:read"]

    def execute(self, **kwargs) -> ToolResult:
        file_path = kwargs.get("file_path", "")
        if not file_path:
            return ToolResult(success=False, error="Missing required argument: file_path")
        path = Path(file_path)
        if not path.exists():
            return ToolResult(success=False, error=f"File not found: {file_path}")
        try:
            content = path.read_text(encoding="utf-8")
            return ToolResult(success=True, data=content)
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to read file: {e}")
