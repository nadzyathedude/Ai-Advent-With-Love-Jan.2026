"""Tests for plugin discovery, manifest validation, and tool loading."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from core.registry.plugin_loader import PluginLoader, PluginManifestError
from core.registry.tool_registry import ToolRegistry


class TestPluginManifestValidation(unittest.TestCase):
    """Test manifest schema validation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.plugins_dir = os.path.join(self.tmpdir, "plugins")
        os.makedirs(self.plugins_dir)
        # Write a minimal plugins.yaml that enables our test plugin
        self.config_dir = os.path.join(self.tmpdir, "config")
        os.makedirs(self.config_dir)

    def _write_manifest(self, plugin_name, manifest):
        plugin_dir = os.path.join(self.plugins_dir, plugin_name)
        os.makedirs(plugin_dir, exist_ok=True)
        with open(os.path.join(plugin_dir, "plugin.json"), "w") as f:
            json.dump(manifest, f)

    def _write_config(self, enabled_plugins):
        import yaml
        config = {"plugins": {p: {"enabled": True} for p in enabled_plugins}}
        with open(os.path.join(self.config_dir, "plugins.yaml"), "w") as f:
            yaml.dump(config, f)

    def test_valid_manifest_discovered(self):
        """A valid manifest should be discovered successfully."""
        self._write_manifest("test_plugin", {
            "id": "test_plugin",
            "version": "1.0.0",
            "entrypoint": "tool_mod",
            "tools": [{"name": "test.tool", "class": "TestTool", "permissions": ["test:read"]}],
        })
        self._write_config(["test_plugin"])
        loader = PluginLoader(
            plugins_dir=self.plugins_dir,
            config_path=os.path.join(self.config_dir, "plugins.yaml"),
        )
        manifests = loader.discover()
        self.assertEqual(len(manifests), 1)
        self.assertEqual(manifests[0]["id"], "test_plugin")

    def test_missing_manifest_fields_raises(self):
        """A manifest missing required fields should raise PluginManifestError."""
        self._write_manifest("bad_plugin", {
            "id": "bad_plugin",
            # missing version, entrypoint, tools
        })
        self._write_config(["bad_plugin"])
        loader = PluginLoader(
            plugins_dir=self.plugins_dir,
            config_path=os.path.join(self.config_dir, "plugins.yaml"),
        )
        with self.assertRaises(PluginManifestError):
            loader.discover()

    def test_missing_tool_fields_raises(self):
        """A tool definition missing required fields should raise PluginManifestError."""
        self._write_manifest("bad_tools", {
            "id": "bad_tools",
            "version": "1.0.0",
            "entrypoint": "tool_mod",
            "tools": [{"name": "test.tool"}],  # missing class, permissions
        })
        self._write_config(["bad_tools"])
        loader = PluginLoader(
            plugins_dir=self.plugins_dir,
            config_path=os.path.join(self.config_dir, "plugins.yaml"),
        )
        with self.assertRaises(PluginManifestError):
            loader.discover()

    def test_disabled_plugin_skipped(self):
        """A disabled plugin should not be discovered."""
        self._write_manifest("disabled_plugin", {
            "id": "disabled_plugin",
            "version": "1.0.0",
            "entrypoint": "tool_mod",
            "tools": [{"name": "d.tool", "class": "DTool", "permissions": []}],
        })
        # Don't enable it
        self._write_config([])
        loader = PluginLoader(
            plugins_dir=self.plugins_dir,
            config_path=os.path.join(self.config_dir, "plugins.yaml"),
        )
        manifests = loader.discover()
        self.assertEqual(len(manifests), 0)


class TestPluginLoading(unittest.TestCase):
    """Test loading real plugins from the project."""

    def test_load_real_plugins(self):
        """Load the actual docs_rag and git_context plugins."""
        registry = ToolRegistry()
        loader = PluginLoader()
        loader.load_tools(registry)
        tools = registry.list_tools()
        tool_names = [t.name for t in tools]
        self.assertIn("docs.search_project_docs", tool_names)
        self.assertIn("git.current_branch", tool_names)


if __name__ == "__main__":
    unittest.main()
