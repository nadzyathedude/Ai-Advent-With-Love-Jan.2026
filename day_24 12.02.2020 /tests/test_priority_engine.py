"""Tests for the priority engine — scoring functions, ordering, recommendation format."""

import datetime
import unittest

from priority_engine import (
    WEIGHTS,
    compute_task_score,
    score_due_date,
    score_priority,
    score_blockers,
    score_effort,
    score_status,
    prioritize_tasks,
    get_recommendation,
    build_reasoning,
)


class TestScoringFunctions(unittest.TestCase):
    """Test individual scoring functions."""

    def test_score_due_date_overdue(self):
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        self.assertEqual(score_due_date(yesterday), 1.0)

    def test_score_due_date_today(self):
        today = datetime.date.today().isoformat()
        self.assertEqual(score_due_date(today), 0.95)

    def test_score_due_date_3_days(self):
        future = (datetime.date.today() + datetime.timedelta(days=2)).isoformat()
        self.assertEqual(score_due_date(future), 0.85)

    def test_score_due_date_7_days(self):
        future = (datetime.date.today() + datetime.timedelta(days=6)).isoformat()
        self.assertEqual(score_due_date(future), 0.65)

    def test_score_due_date_14_days(self):
        future = (datetime.date.today() + datetime.timedelta(days=10)).isoformat()
        self.assertEqual(score_due_date(future), 0.45)

    def test_score_due_date_far_future(self):
        future = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
        self.assertEqual(score_due_date(future), 0.25)

    def test_score_due_date_none(self):
        self.assertEqual(score_due_date(None), 0.3)

    def test_score_due_date_empty(self):
        self.assertEqual(score_due_date(""), 0.3)

    def test_score_due_date_invalid(self):
        self.assertEqual(score_due_date("not-a-date"), 0.3)

    def test_score_priority_values(self):
        self.assertEqual(score_priority("critical"), 1.0)
        self.assertEqual(score_priority("high"), 0.75)
        self.assertEqual(score_priority("medium"), 0.50)
        self.assertEqual(score_priority("low"), 0.25)

    def test_score_priority_unknown(self):
        self.assertEqual(score_priority("unknown"), 0.50)

    def test_score_blockers_none(self):
        task = {"id": 1}
        others = [{"id": 2, "depends_on": []}]
        self.assertEqual(score_blockers(task, others), 0.10)

    def test_score_blockers_one(self):
        task = {"id": 1}
        others = [{"id": 2, "depends_on": [1]}]
        self.assertEqual(score_blockers(task, others), 0.50)

    def test_score_blockers_two(self):
        task = {"id": 1}
        others = [
            {"id": 2, "depends_on": [1]},
            {"id": 3, "depends_on": [1]},
        ]
        self.assertEqual(score_blockers(task, others), 0.75)

    def test_score_blockers_three_plus(self):
        task = {"id": 1}
        others = [
            {"id": 2, "depends_on": [1]},
            {"id": 3, "depends_on": [1]},
            {"id": 4, "depends_on": [1]},
        ]
        self.assertEqual(score_blockers(task, others), 1.0)

    def test_score_effort_values(self):
        self.assertEqual(score_effort("small"), 1.0)
        self.assertEqual(score_effort("medium"), 0.65)
        self.assertEqual(score_effort("large"), 0.35)
        self.assertEqual(score_effort("xlarge"), 0.15)

    def test_score_status_values(self):
        self.assertEqual(score_status("in_progress"), 1.0)
        self.assertEqual(score_status("todo"), 0.60)
        self.assertEqual(score_status("blocked"), 0.20)
        self.assertEqual(score_status("done"), 0.0)


class TestComputeTaskScore(unittest.TestCase):
    """Test the combined scoring function."""

    def test_score_is_between_0_and_1(self):
        task = {"id": 1, "priority": "high", "effort": "small",
                "status": "todo", "due_date": None}
        score = compute_task_score(task, [task])
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_critical_overdue_scores_high(self):
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        task = {"id": 1, "priority": "critical", "effort": "small",
                "status": "in_progress", "due_date": yesterday}
        others = [task, {"id": 2, "depends_on": [1]}]
        score = compute_task_score(task, others)
        self.assertGreater(score, 0.8)

    def test_low_priority_far_due_scores_low(self):
        far = (datetime.date.today() + datetime.timedelta(days=60)).isoformat()
        task = {"id": 1, "priority": "low", "effort": "xlarge",
                "status": "todo", "due_date": far}
        score = compute_task_score(task, [task])
        self.assertLess(score, 0.4)

    def test_weights_sum_to_one(self):
        total = sum(WEIGHTS.values())
        self.assertAlmostEqual(total, 1.0, places=4)


class TestPrioritizeTasks(unittest.TestCase):
    """Test the prioritize_tasks function."""

    def test_done_tasks_excluded(self):
        tasks = [
            {"id": 1, "title": "Active", "status": "todo", "priority": "high",
             "effort": "small", "due_date": None, "depends_on": []},
            {"id": 2, "title": "Done", "status": "done", "priority": "critical",
             "effort": "small", "due_date": None, "depends_on": []},
        ]
        scored = prioritize_tasks(tasks)
        titles = [s["task"]["title"] for s in scored]
        self.assertIn("Active", titles)
        self.assertNotIn("Done", titles)

    def test_sorted_by_score_descending(self):
        tasks = [
            {"id": 1, "title": "Low", "status": "todo", "priority": "low",
             "effort": "xlarge", "due_date": None, "depends_on": []},
            {"id": 2, "title": "High", "status": "todo", "priority": "critical",
             "effort": "small", "due_date": datetime.date.today().isoformat(), "depends_on": []},
        ]
        scored = prioritize_tasks(tasks)
        self.assertEqual(scored[0]["task"]["title"], "High")
        self.assertGreater(scored[0]["score"], scored[1]["score"])

    def test_has_reasoning(self):
        tasks = [
            {"id": 1, "title": "Task", "status": "todo", "priority": "high",
             "effort": "small", "due_date": None, "depends_on": []},
        ]
        scored = prioritize_tasks(tasks)
        self.assertIn("reasoning", scored[0])
        self.assertIsInstance(scored[0]["reasoning"], str)

    def test_empty_list(self):
        scored = prioritize_tasks([])
        self.assertEqual(scored, [])


class TestBuildReasoning(unittest.TestCase):
    """Test reasoning string generation."""

    def test_critical_priority(self):
        task = {"id": 1, "priority": "critical", "status": "todo", "effort": "medium", "depends_on": []}
        reasoning = build_reasoning(task, [task])
        self.assertIn("CRITICAL", reasoning)

    def test_overdue(self):
        yesterday = (datetime.date.today() - datetime.timedelta(days=2)).isoformat()
        task = {"id": 1, "priority": "medium", "status": "todo",
                "effort": "medium", "due_date": yesterday, "depends_on": []}
        reasoning = build_reasoning(task, [task])
        self.assertIn("OVERDUE", reasoning)

    def test_blocks_others(self):
        task = {"id": 1, "priority": "medium", "status": "todo", "effort": "medium", "depends_on": []}
        others = [task, {"id": 2, "depends_on": [1]}]
        reasoning = build_reasoning(task, others)
        self.assertIn("blocks 1 other", reasoning)

    def test_in_progress(self):
        task = {"id": 1, "priority": "medium", "status": "in_progress", "effort": "medium", "depends_on": []}
        reasoning = build_reasoning(task, [task])
        self.assertIn("in progress", reasoning)

    def test_blocked(self):
        task = {"id": 1, "priority": "medium", "status": "blocked",
                "effort": "medium", "blocked_by": "DBA approval", "depends_on": []}
        reasoning = build_reasoning(task, [task])
        self.assertIn("BLOCKED", reasoning)
        self.assertIn("DBA approval", reasoning)

    def test_quick_win(self):
        task = {"id": 1, "priority": "medium", "status": "todo", "effort": "small", "depends_on": []}
        reasoning = build_reasoning(task, [task])
        self.assertIn("quick win", reasoning)


class TestGetRecommendation(unittest.TestCase):
    """Test the recommendation formatter."""

    def test_empty_list(self):
        result = get_recommendation([])
        self.assertIn("No active tasks", result)

    def test_has_header(self):
        scored = [{"task": {"title": "Task 1", "status": "todo", "priority": "high"},
                   "score": 0.8, "reasoning": "high priority"}]
        result = get_recommendation(scored)
        self.assertIn("Priority Recommendations", result)

    def test_has_recommendation_line(self):
        scored = [{"task": {"title": "Fix bug", "status": "todo", "priority": "critical"},
                   "score": 0.9, "reasoning": "CRITICAL priority"}]
        result = get_recommendation(scored)
        self.assertIn("**Recommendation:**", result)
        self.assertIn("Fix bug", result)

    def test_multiple_items(self):
        scored = [
            {"task": {"title": "First", "status": "todo", "priority": "critical"},
             "score": 0.9, "reasoning": "critical"},
            {"task": {"title": "Second", "status": "todo", "priority": "low"},
             "score": 0.3, "reasoning": "low priority"},
        ]
        result = get_recommendation(scored)
        self.assertIn("1.", result)
        self.assertIn("2.", result)


if __name__ == "__main__":
    unittest.main()
