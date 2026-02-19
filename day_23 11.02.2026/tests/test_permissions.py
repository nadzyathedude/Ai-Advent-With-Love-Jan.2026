"""Tests for permission checking and enforcement."""

import os
import tempfile
import unittest

import yaml

from core.registry.permissions import PermissionChecker, PermissionDeniedError


class TestPermissionChecker(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.tmpdir, "agents.yaml")
        config = {
            "agents": {
                "test_agent": {"permissions": ["docs:read", "git:read"]},
                "limited_agent": {"permissions": ["docs:read"]},
            }
        }
        with open(self.config_path, "w") as f:
            yaml.dump(config, f)
        self.checker = PermissionChecker(config_path=self.config_path)

    def test_check_all_perms_present(self):
        """Agent with all required permissions should pass check."""
        self.assertTrue(self.checker.check("test_agent", ["docs:read", "git:read"]))

    def test_check_subset_perms(self):
        """Agent should pass check for a subset of its permissions."""
        self.assertTrue(self.checker.check("test_agent", ["docs:read"]))

    def test_check_missing_perm(self):
        """Agent missing a permission should fail check."""
        self.assertFalse(self.checker.check("limited_agent", ["docs:read", "git:read"]))

    def test_check_unknown_agent(self):
        """Unknown agent should fail check for any permission."""
        self.assertFalse(self.checker.check("unknown_agent", ["docs:read"]))

    def test_check_empty_perms(self):
        """Empty permissions requirement should always pass."""
        self.assertTrue(self.checker.check("unknown_agent", []))

    def test_enforce_passes(self):
        """Enforce should not raise when all permissions are present."""
        self.checker.enforce("test_agent", ["docs:read", "git:read"])

    def test_enforce_raises(self):
        """Enforce should raise PermissionDeniedError for missing permissions."""
        with self.assertRaises(PermissionDeniedError) as ctx:
            self.checker.enforce("limited_agent", ["git:read"])
        self.assertEqual(ctx.exception.agent_id, "limited_agent")
        self.assertIn("git:read", ctx.exception.missing)

    def test_enforce_unknown_agent(self):
        """Enforce should raise for unknown agent with any permissions."""
        with self.assertRaises(PermissionDeniedError):
            self.checker.enforce("unknown_agent", ["docs:read"])


class TestPermissionCheckerFromProject(unittest.TestCase):
    """Test with the actual project config."""

    def test_project_helper_has_perms(self):
        checker = PermissionChecker()
        self.assertTrue(checker.check("project_helper", ["docs:read", "git:read"]))


if __name__ == "__main__":
    unittest.main()
