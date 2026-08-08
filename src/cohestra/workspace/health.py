"""Health checks over caller-supplied workspace paths."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .registry import load_registry


@dataclass(frozen=True)
class HealthCheck:
    name: str
    status: str
    detail: str


def check_workspace(
    registry_path: str | Path,
    *,
    shared_guide: str | Path,
    routes: Mapping[str, str | Path] | None = None,
) -> tuple[HealthCheck, ...]:
    """Check only paths explicitly provided by the caller or its registry."""
    registry = load_registry(registry_path)
    checks = [HealthCheck("registry", "PASS", f"{len(registry.agents)} agents")]
    guide = Path(shared_guide).expanduser()
    checks.append(HealthCheck("shared_guide", "PASS" if guide.is_file() else "FAIL", str(guide)))
    supplied_routes = routes or {}
    for agent in registry.agents:
        route = supplied_routes.get(agent.identifier, agent.global_route)
        if route is not None:
            target = Path(route).expanduser()
            checks.append(
                HealthCheck(
                    f"route:{agent.identifier}", "PASS" if target.is_file() else "FAIL", str(target)
                )
            )
    return tuple(checks)
