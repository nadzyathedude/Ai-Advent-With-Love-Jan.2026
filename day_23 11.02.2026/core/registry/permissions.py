"""Permission checker that loads agent allow-lists from agents.yaml."""

import os
from pathlib import Path
from typing import Dict, List

import yaml


class PermissionDeniedError(Exception):
    """Raised when an agent lacks a required permission."""

    def __init__(self, agent_id: str, missing: List[str]):
        self.agent_id = agent_id
        self.missing = missing
        super().__init__(
            f"Agent '{agent_id}' lacks permissions: {', '.join(missing)}"
        )


class PermissionChecker:
    """Loads per-agent permission allow-lists and enforces them."""

    def __init__(self, config_path: str | None = None):
        if config_path is None:
            base = Path(__file__).resolve().parents[2]
            config_path = str(base / "config" / "agents.yaml")
        self._agents: Dict[str, List[str]] = {}
        self._load(config_path)

    def _load(self, path: str) -> None:
        if not os.path.exists(path):
            return
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}
        for agent_id, cfg in data.get("agents", {}).items():
            self._agents[agent_id] = cfg.get("permissions", [])

    def check(self, agent_id: str, required: List[str]) -> bool:
        """Return True if the agent has all required permissions."""
        allowed = self._agents.get(agent_id, [])
        return all(perm in allowed for perm in required)

    def enforce(self, agent_id: str, required: List[str]) -> None:
        """Raise PermissionDeniedError if any required permission is missing."""
        allowed = self._agents.get(agent_id, [])
        missing = [p for p in required if p not in allowed]
        if missing:
            raise PermissionDeniedError(agent_id, missing)
