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
from agents.reviewers.review_orchestrator import review_pr


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


def cmd_review(args):
    """Handle the 'review' subcommand."""
    registry = setup_registry()
    report = review_pr(
        base_branch=args.base,
        registry=registry,
        debug=args.debug,
        pr_id=args.pr_id,
    )
    print(report)


def cmd_feedback(args):
    """Handle the 'feedback' subcommand."""
    registry = setup_registry()
    result = registry.invoke(
        "review_memory.record_feedback",
        "review_orchestrator",
        finding_id=args.finding_id,
        label=args.label,
        comment=args.comment or "",
    )
    if result.success:
        print(f"Feedback recorded: finding {args.finding_id} -> {args.label}")
    else:
        print(f"Error: {result.error}", file=sys.stderr)
        sys.exit(1)


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


def cmd_history(args):
    """Handle the 'history' subcommand — search past review findings."""
    registry = setup_registry()
    result = registry.invoke(
        "review_memory.search_similar_findings",
        "review_orchestrator",
        category=args.category,
        file_path=args.file,
        keyword=args.keyword,
        limit=args.limit,
    )
    if not result.success:
        print(f"Error: {result.error}", file=sys.stderr)
        sys.exit(1)
    findings = result.data or []
    if not findings:
        print("No findings in history.")
        return
    for f in findings:
        label = f.get("label", "pending")
        badge = f"[{f['severity'].upper()}]" if f.get("severity") else ""
        loc = f.get("file_path", "?")
        line = f.get("line")
        if line:
            loc += f":{line}"
        print(f"  #{f['id']:>4d} {badge:8s} {f['category']:12s} {loc}")
        print(f"         {f['message']}")
        print(f"         label={label}  pr={f.get('pr_id', '?')}")


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

    # review
    review_parser = subparsers.add_parser("review", help="Run multi-agent PR review")
    review_parser.add_argument("--base", type=str, default="main", help="Base branch to diff against")
    review_parser.add_argument("--pr-id", type=str, default="", help="PR identifier for memory tracking")
    review_parser.add_argument("--debug", action="store_true", help="Show debug info")
    review_parser.set_defaults(func=cmd_review)

    # feedback
    fb_parser = subparsers.add_parser("feedback", help="Record feedback on a review finding")
    fb_parser.add_argument("finding_id", type=int, help="Finding ID from review history")
    fb_parser.add_argument("label", choices=["accepted", "rejected", "fixed", "ignored"],
                           help="Feedback label")
    fb_parser.add_argument("--comment", type=str, default="", help="Optional comment")
    fb_parser.set_defaults(func=cmd_feedback)

    # history
    hist_parser = subparsers.add_parser("history", help="Search past review findings")
    hist_parser.add_argument("--category", type=str, default=None, help="Filter by category")
    hist_parser.add_argument("--file", type=str, default=None, help="Filter by file path")
    hist_parser.add_argument("--keyword", type=str, default=None, help="Filter by keyword")
    hist_parser.add_argument("--limit", type=int, default=20, help="Max results")
    hist_parser.set_defaults(func=cmd_history)

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
