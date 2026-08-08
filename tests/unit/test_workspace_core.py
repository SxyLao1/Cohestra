from __future__ import annotations

import json
from pathlib import Path

import pytest

from cohestra.workspace.health import check_workspace
from cohestra.workspace.registry import load_registry
from cohestra.workspace.sections import read_sections
from cohestra.workspace.sync import sync_playbooks


def _registry(path: Path, *, agents: object | None = None) -> None:
    path.write_text(
        json.dumps({"schemaVersion": 1, "agents": agents if agents is not None else []}),
        encoding="utf-8",
    )


def _guide(path: Path) -> None:
    path.write_text(
        "intro\n" + "\n".join(f"## {i}. Section\nbody {i}" for i in range(1, 9)), encoding="utf-8"
    )


def test_registry_rejects_malformed_duplicate_and_unsupported_mode(tmp_path: Path) -> None:
    registry = tmp_path / "registry.json"
    _registry(registry, agents="not-a-list")
    with pytest.raises(ValueError, match="agents"):
        load_registry(registry)
    _registry(
        registry,
        agents=[
            {"id": "a", "skills": {"mode": "manual"}},
            {"id": "a", "skills": {"mode": "manual"}},
        ],
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_registry(registry)
    _registry(registry, agents=[{"id": "a", "skills": {"mode": "unbounded"}}])
    with pytest.raises(ValueError, match="unsupported"):
        load_registry(registry)


def test_sections_are_selective_and_fail_closed(tmp_path: Path) -> None:
    guide = tmp_path / "guide.md"
    _guide(guide)
    result = read_sections(guide, "1,4")
    assert "body 1" in result
    assert "body 4" in result
    assert "body 2" not in result
    guide.write_text("## 1. Incomplete\nbody", encoding="utf-8")
    with pytest.raises(ValueError, match="exactly one"):
        read_sections(guide)


def test_sync_is_dry_run_idempotent_and_preserves_existing_target(tmp_path: Path) -> None:
    playbooks = tmp_path / "playbooks"
    source = playbooks / "demo"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("neutral fixture", encoding="utf-8")
    skills = tmp_path / "skills"
    plan = sync_playbooks(playbooks, skills)
    assert plan[0].status == "CREATE"
    assert not skills.exists()
    calls: list[tuple[Path, Path]] = []
    created = sync_playbooks(
        playbooks, skills, apply=True, strategy=lambda src, dst: calls.append((src, dst))
    )
    assert created[0].status == "CREATED"
    assert len(calls) == 1
    (skills / "demo").mkdir()
    assert sync_playbooks(playbooks, skills)[0].status == "CONFLICT"


def test_sync_rejects_unsafe_replacement_roots(tmp_path: Path) -> None:
    playbooks = tmp_path / "playbooks"
    playbooks.mkdir()
    with pytest.raises(ValueError, match="must not overlap"):
        sync_playbooks(playbooks, playbooks)
    nested = playbooks / "nested"
    with pytest.raises(ValueError, match="must not overlap"):
        sync_playbooks(playbooks, nested)
    with pytest.raises(ValueError, match="must not overlap"):
        sync_playbooks(playbooks, tmp_path)
    target_file = tmp_path / "target"
    target_file.write_text("not a directory", encoding="utf-8")
    with pytest.raises(ValueError, match="directory"):
        sync_playbooks(playbooks, target_file)


def test_health_uses_only_explicit_paths(tmp_path: Path) -> None:
    registry = tmp_path / "registry.json"
    _registry(registry, agents=[{"id": "demo", "skills": {"mode": "manual"}}])
    guide = tmp_path / "guide.md"
    guide.write_text("guide", encoding="utf-8")
    route = tmp_path / "route.md"
    route.write_text("route", encoding="utf-8")
    checks = check_workspace(registry, shared_guide=guide, routes={"demo": route})
    assert [check.status for check in checks] == ["PASS", "PASS", "PASS"]
