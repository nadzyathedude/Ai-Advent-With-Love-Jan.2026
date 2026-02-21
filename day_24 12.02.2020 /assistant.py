"""Entry point for the unified AI project assistant.

Usage:
    python assistant.py "What is the project architecture?"
    python assistant.py "Create a high priority task to fix login bug"
    python assistant.py "What is the current project status?" --debug
"""

import argparse
import sys
import os

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.registry.tool_registry import ToolRegistry
from core.registry.permissions import PermissionChecker
from core.registry.plugin_loader import PluginLoader
from agents.assistant_agent import assistant_query


def setup_registry() -> ToolRegistry:
    """Initialize registry with permission checker and load plugins."""
    checker = PermissionChecker()
    registry = ToolRegistry(permission_checker=checker)
    loader = PluginLoader()
    loader.load_tools(registry)
    return registry


def main():
    parser = argparse.ArgumentParser(
        prog="assistant",
        description="Unified AI Project Assistant — RAG + MCP + Tasks + Priority",
    )
    parser.add_argument("question", type=str, help="The question or command to process")
    parser.add_argument("--debug", action="store_true", help="Show debug info")

    args = parser.parse_args()
    registry = setup_registry()
    answer = assistant_query(args.question, registry, debug=args.debug)
    print(answer)


if __name__ == "__main__":
    main()
