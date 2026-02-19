"""CLI interface for the agent platform."""

import argparse
import sys
import os

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.registry.tool_registry import ToolRegistry
from core.registry.permissions import PermissionChecker
from core.registry.plugin_loader import PluginLoader
from core.agents.project_helper import ask


def setup_registry() -> ToolRegistry:
    """Initialize registry with permission checker and load plugins."""
    checker = PermissionChecker()
    registry = ToolRegistry(permission_checker=checker)
    loader = PluginLoader()
    loader.load_tools(registry)
    return registry


def cmd_ask(args):
    """Handle the 'ask' subcommand."""
    registry = setup_registry()
    answer = ask(args.question, registry, debug=args.debug)
    print(answer)


def cmd_list_tools(args):
    """Handle the 'list-tools' subcommand."""
    registry = setup_registry()
    tools = registry.list_tools()
    if not tools:
        print("No tools loaded.")
        return
    for tool in tools:
        perms = ", ".join(tool.required_permissions)
        print(f"  {tool.name:40s} {tool.description}")
        print(f"  {'':40s} permissions: [{perms}]")


def cmd_list_plugins(args):
    """Handle the 'list-plugins' subcommand."""
    loader = PluginLoader()
    plugins = loader.list_plugins()
    if not plugins:
        print("No plugins loaded.")
        return
    for p in plugins:
        tool_names = [t["name"] for t in p.get("tools", [])]
        print(f"  {p['id']:20s} v{p['version']}  tools: {', '.join(tool_names)}")


def main():
    parser = argparse.ArgumentParser(
        prog="agent-platform",
        description="Standalone Agent Platform with plugin-based tools",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ask
    ask_parser = subparsers.add_parser("ask", help="Ask the project helper agent a question")
    ask_parser.add_argument("question", type=str, help="The question to ask")
    ask_parser.add_argument("--debug", action="store_true", help="Show debug info")
    ask_parser.set_defaults(func=cmd_ask)

    # list-tools
    lt_parser = subparsers.add_parser("list-tools", help="List all registered tools")
    lt_parser.set_defaults(func=cmd_list_tools)

    # list-plugins
    lp_parser = subparsers.add_parser("list-plugins", help="List all loaded plugins")
    lp_parser.set_defaults(func=cmd_list_plugins)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
