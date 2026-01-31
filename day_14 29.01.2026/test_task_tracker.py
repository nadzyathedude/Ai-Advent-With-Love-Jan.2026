#!/usr/bin/env python3
"""
Test script for Task Tracker MCP integration.

This script demonstrates end-to-end MCP communication:
1. Connects to the Task Tracker MCP server
2. Lists available tools
3. Creates some tasks
4. Gets open task count
5. Lists tasks
6. Completes a task

Usage:
    python test_task_tracker.py
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from task_tracker_client import TaskTrackerMCPClient


async def main():
    """Run the test."""
    print("=" * 60)
    print("Task Tracker MCP Integration Test")
    print("=" * 60)
    print()

    # Create client
    client = TaskTrackerMCPClient()

    # Test 1: List tools
    print("1. Listing MCP tools...")
    try:
        tools = await client.list_tools()
        print(f"   Found {len(tools)} tools:")
        for tool in tools:
            print(f"   - {tool.name}: {tool.description[:50]}...")
        print()
    except Exception as e:
        print(f"   ERROR: {e}")
        return

    # Test 2: Create tasks
    print("2. Creating test tasks...")
    test_user_id = "test_user_123"

    tasks_to_create = [
        ("Learn MCP protocol", "Study the Model Context Protocol specification"),
        ("Build MCP server", "Implement Task Tracker MCP server"),
        ("Test integration", None),
    ]

    for title, description in tasks_to_create:
        result = await client.create_task(test_user_id, title, description)
        if result.success:
            task_id = result.data.get("task_id", "?")
            print(f"   Created task {task_id}: {title}")
        else:
            print(f"   Note: {result.error}")
    print()

    # Test 3: Get open count
    print("3. Getting open task count...")
    result = await client.get_open_count(test_user_id)
    if result.success:
        count = result.data.get("count", 0)
        print(f"   Open tasks: {count}")
    else:
        print(f"   ERROR: {result.error}")
    print()

    # Test 4: List open tasks
    print("4. Listing open tasks...")
    result = await client.list_open_tasks(test_user_id)
    if result.success:
        tasks = result.data.get("tasks", [])
        for task in tasks:
            print(f"   [{task['id']}] {task['title']}")
            if task.get("description"):
                print(f"       {task['description']}")
    else:
        print(f"   ERROR: {result.error}")
    print()

    # Test 5: Complete a task (if any exist)
    if result.success and tasks:
        first_task_id = tasks[0]["id"]
        print(f"5. Completing task {first_task_id}...")
        result = await client.complete_task(test_user_id, first_task_id)
        if result.success:
            print(f"   Task {first_task_id} completed!")
        else:
            print(f"   ERROR: {result.error}")
        print()

        # Test 6: Verify count decreased
        print("6. Verifying task count decreased...")
        result = await client.get_open_count(test_user_id)
        if result.success:
            count = result.data.get("count", 0)
            print(f"   Open tasks: {count}")
        else:
            print(f"   ERROR: {result.error}")
        print()

    print("=" * 60)
    print("Test completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
