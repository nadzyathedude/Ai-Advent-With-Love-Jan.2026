"""Tests for the task manager plugin — TaskDB CRUD, tool classes, filters."""

import os
import unittest

from plugins.task_manager.tool_task import (
    TaskDB,
    CreateTaskTool,
    ListTasksTool,
    UpdateTaskTool,
    GetTaskTool,
    ProjectStatusTool,
    get_db,
    reset_db,
)


class TestTaskDB(unittest.TestCase):
    """Test the TaskDB SQLite store."""

    def setUp(self):
        self.db = TaskDB(":memory:")

    def tearDown(self):
        self.db.close()

    def test_sample_data_populated(self):
        """Verify sample tasks are inserted."""
        row = self.db._conn.execute("SELECT COUNT(*) FROM tasks").fetchone()
        self.assertEqual(row[0], 8)

    def test_create_task(self):
        task = self.db.create_task(
            title="Test task",
            description="A test task",
            priority="high",
            effort="small",
            tags=["test"],
        )
        self.assertNotIn("error", task)
        self.assertEqual(task["title"], "Test task")
        self.assertEqual(task["priority"], "high")
        self.assertEqual(task["effort"], "small")
        self.assertEqual(task["status"], "todo")
        self.assertEqual(task["tags"], ["test"])

    def test_get_task(self):
        task = self.db.get_task(1)
        self.assertNotIn("error", task)
        self.assertEqual(task["id"], 1)
        self.assertIn("title", task)

    def test_get_task_nonexistent(self):
        task = self.db.get_task(9999)
        self.assertIn("error", task)

    def test_list_tasks(self):
        tasks = self.db.list_tasks()
        self.assertEqual(len(tasks), 8)

    def test_list_tasks_by_status(self):
        tasks = self.db.list_tasks(status="todo")
        for t in tasks:
            self.assertEqual(t["status"], "todo")

    def test_list_tasks_by_priority(self):
        tasks = self.db.list_tasks(priority="high")
        for t in tasks:
            self.assertEqual(t["priority"], "high")

    def test_list_tasks_by_tag(self):
        tasks = self.db.list_tasks(tag="api")
        self.assertGreater(len(tasks), 0)
        for t in tasks:
            self.assertIn("api", t["tags"])

    def test_list_tasks_with_limit(self):
        tasks = self.db.list_tasks(limit=3)
        self.assertEqual(len(tasks), 3)

    def test_update_task_status(self):
        result = self.db.update_task(1, status="in_progress")
        self.assertNotIn("error", result)
        self.assertEqual(result["status"], "in_progress")

    def test_update_task_priority(self):
        result = self.db.update_task(1, priority="critical")
        self.assertNotIn("error", result)
        self.assertEqual(result["priority"], "critical")

    def test_update_task_no_fields(self):
        result = self.db.update_task(1)
        self.assertIn("error", result)

    def test_update_task_nonexistent(self):
        result = self.db.update_task(9999, status="done")
        self.assertIn("error", result)

    def test_project_status(self):
        status = self.db.project_status()
        self.assertIn("total", status)
        self.assertEqual(status["total"], 8)
        self.assertIn("by_status", status)
        self.assertIn("by_priority", status)
        self.assertIn("blocked", status)
        self.assertIn("overdue", status)
        # Should have at least one blocked task
        self.assertGreater(len(status["blocked"]), 0)

    def test_json_fields_parsed(self):
        task = self.db.get_task(1)
        self.assertIsInstance(task["tags"], list)
        self.assertIsInstance(task["depends_on"], list)

    def test_ephemeral_fallback(self):
        db = TaskDB("/nonexistent/path/task.sqlite")
        self.assertTrue(db.ephemeral)
        tasks = db.list_tasks()
        self.assertGreater(len(tasks), 0)
        db.close()


class TestTaskTools(unittest.TestCase):
    """Test task manager tool classes directly."""

    def setUp(self):
        reset_db()
        os.environ["TASK_MANAGER_DB"] = ":memory:"

    def tearDown(self):
        reset_db()
        os.environ.pop("TASK_MANAGER_DB", None)

    def test_create_task_tool_properties(self):
        tool = CreateTaskTool()
        self.assertEqual(tool.name, "task.create")
        self.assertEqual(tool.required_permissions, ["task:write"])

    def test_create_task_tool_execute(self):
        tool = CreateTaskTool()
        result = tool.execute(title="New task", priority="high")
        self.assertTrue(result.success)
        self.assertEqual(result.data["title"], "New task")
        self.assertEqual(result.data["priority"], "high")

    def test_create_task_tool_missing_title(self):
        tool = CreateTaskTool()
        result = tool.execute()
        self.assertFalse(result.success)
        self.assertIn("title", result.error)

    def test_list_tasks_tool_properties(self):
        tool = ListTasksTool()
        self.assertEqual(tool.name, "task.list")
        self.assertEqual(tool.required_permissions, ["task:read"])

    def test_list_tasks_tool_execute(self):
        tool = ListTasksTool()
        result = tool.execute()
        self.assertTrue(result.success)
        self.assertGreater(len(result.data), 0)

    def test_list_tasks_tool_with_filter(self):
        tool = ListTasksTool()
        result = tool.execute(priority="high")
        self.assertTrue(result.success)
        for t in result.data:
            self.assertEqual(t["priority"], "high")

    def test_update_task_tool_properties(self):
        tool = UpdateTaskTool()
        self.assertEqual(tool.name, "task.update")
        self.assertEqual(tool.required_permissions, ["task:write"])

    def test_update_task_tool_execute(self):
        tool = UpdateTaskTool()
        result = tool.execute(task_id=1, status="in_progress")
        self.assertTrue(result.success)
        self.assertEqual(result.data["status"], "in_progress")

    def test_update_task_tool_missing_id(self):
        tool = UpdateTaskTool()
        result = tool.execute(status="done")
        self.assertFalse(result.success)
        self.assertIn("task_id", result.error)

    def test_get_task_tool_properties(self):
        tool = GetTaskTool()
        self.assertEqual(tool.name, "task.get")
        self.assertEqual(tool.required_permissions, ["task:read"])

    def test_get_task_tool_execute(self):
        tool = GetTaskTool()
        result = tool.execute(task_id=1)
        self.assertTrue(result.success)
        self.assertEqual(result.data["id"], 1)

    def test_get_task_tool_missing_id(self):
        tool = GetTaskTool()
        result = tool.execute()
        self.assertFalse(result.success)
        self.assertIn("task_id", result.error)

    def test_get_task_tool_nonexistent(self):
        tool = GetTaskTool()
        result = tool.execute(task_id=9999)
        self.assertFalse(result.success)
        self.assertIn("not found", result.error)

    def test_project_status_tool_properties(self):
        tool = ProjectStatusTool()
        self.assertEqual(tool.name, "task.project_status")
        self.assertEqual(tool.required_permissions, ["task:read"])

    def test_project_status_tool_execute(self):
        tool = ProjectStatusTool()
        result = tool.execute()
        self.assertTrue(result.success)
        self.assertIn("total", result.data)
        self.assertIn("by_status", result.data)


if __name__ == "__main__":
    unittest.main()
