"""Typed loader for a portable workspace registry."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ALLOWED_SYNC_MODES = frozenset(
    {"symlink", "junction", "junction-or-symlink", "route-only", "manual"}
)


@dataclass(frozen=True)
class AgentRegistryEntry:
    """A declared recipient workspace, without any machine-specific discovery."""

    identifier: str
    skills_mode: str
    global_route: str | None = None


@dataclass(frozen=True)
class WorkspaceRegistry:
    """Validated portable registry data."""

    schema_version: int
    agents: tuple[AgentRegistryEntry, ...]


def load_registry(path: str | Path) -> WorkspaceRegistry:
    """Load schema version 1 and reject incomplete or ambiguous agent entries."""
    source = Path(path).expanduser()
    try:
        data: Any = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid registry: {source}") from exc
    if not isinstance(data, dict) or data.get("schemaVersion") != 1:
        raise ValueError("schemaVersion must be 1")
    raw_agents = data.get("agents")
    if not isinstance(raw_agents, list):
        raise ValueError("agents must be an array")
    agents: list[AgentRegistryEntry] = []
    identifiers: set[str] = set()
    for raw_agent in raw_agents:
        if not isinstance(raw_agent, dict):
            raise ValueError("each agent must be an object")
        identifier = raw_agent.get("id")
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError("each agent needs a non-empty string id")
        if identifier in identifiers:
            raise ValueError(f"duplicate agent id: {identifier}")
        skills = raw_agent.get("skills")
        if not isinstance(skills, dict):
            raise ValueError(f"agent {identifier} skills must be an object")
        mode = skills.get("mode")
        if mode not in ALLOWED_SYNC_MODES:
            raise ValueError(f"unsupported skills mode: {mode}")
        route = raw_agent.get("globalRoute")
        if route is not None and not isinstance(route, str):
            raise ValueError(f"agent {identifier} globalRoute must be a string")
        identifiers.add(identifier)
        agents.append(
            AgentRegistryEntry(identifier=identifier, skills_mode=mode, global_route=route)
        )
    return WorkspaceRegistry(schema_version=1, agents=tuple(agents))
