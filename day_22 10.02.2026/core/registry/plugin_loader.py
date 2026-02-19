"""Scan plugins/ directory, validate manifests, and import tool classes."""

import importlib
import json
import os
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from .tool_registry import Tool, ToolRegistry


REQUIRED_MANIFEST_FIELDS = {"id", "version", "entrypoint", "tools"}
REQUIRED_TOOL_FIELDS = {"name", "class", "permissions"}


class PluginManifestError(Exception):
    """Raised when a plugin.json is invalid."""


class PluginLoader:
    """Discovers and loads plugins from the plugins/ directory."""

    def __init__(
        self,
        plugins_dir: str | None = None,
        config_path: str | None = None,
    ):
        base = Path(__file__).resolve().parents[2]
        self._plugins_dir = Path(plugins_dir) if plugins_dir else base / "plugins"
        if config_path is None:
            config_path = str(base / "config" / "plugins.yaml")
        self._enabled: Dict[str, bool] = {}
        self._load_config(config_path)
        self._loaded_plugins: List[dict] = []

    def _load_config(self, path: str) -> None:
        if not os.path.exists(path):
            return
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}
        for plugin_id, cfg in data.get("plugins", {}).items():
            self._enabled[plugin_id] = cfg.get("enabled", False)

    def _validate_manifest(self, manifest: dict, path: str) -> None:
        missing = REQUIRED_MANIFEST_FIELDS - set(manifest.keys())
        if missing:
            raise PluginManifestError(
                f"{path}: missing fields: {', '.join(sorted(missing))}"
            )
        for i, tool_def in enumerate(manifest["tools"]):
            tmissing = REQUIRED_TOOL_FIELDS - set(tool_def.keys())
            if tmissing:
                raise PluginManifestError(
                    f"{path}: tools[{i}] missing fields: {', '.join(sorted(tmissing))}"
                )

    def discover(self) -> List[dict]:
        """Find all valid plugin manifests in enabled plugins."""
        manifests = []
        if not self._plugins_dir.exists():
            return manifests
        for entry in sorted(self._plugins_dir.iterdir()):
            if not entry.is_dir() or entry.name.startswith("_"):
                continue
            manifest_path = entry / "plugin.json"
            if not manifest_path.exists():
                continue
            with open(manifest_path, "r") as f:
                manifest = json.load(f)
            self._validate_manifest(manifest, str(manifest_path))
            if not self._enabled.get(manifest["id"], False):
                continue
            manifest["_dir"] = str(entry)
            manifests.append(manifest)
        self._loaded_plugins = manifests
        return manifests

    def load_tools(self, registry: ToolRegistry) -> None:
        """Import tool classes from discovered plugins and register them."""
        manifests = self.discover()
        for manifest in manifests:
            plugin_dir = manifest["_dir"]
            entrypoint = manifest["entrypoint"]
            # Convert directory-based plugin path to module path
            # e.g. plugins/docs_rag -> plugins.docs_rag
            rel = os.path.relpath(plugin_dir, Path(self._plugins_dir).parent)
            module_base = rel.replace(os.sep, ".")
            module_path = f"{module_base}.{entrypoint}"
            module = importlib.import_module(module_path)
            for tool_def in manifest["tools"]:
                cls = getattr(module, tool_def["class"])
                tool_instance = cls()
                registry.register(tool_instance)

    def list_plugins(self) -> List[dict]:
        """Return loaded plugin manifests."""
        if not self._loaded_plugins:
            self.discover()
        return self._loaded_plugins
