from __future__ import annotations

import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from cohestra.adapters import cli as adapters_cli
from cohestra.adapters import overlay as adapters_overlay
from cohestra.adapters.cli import main as adapters_main
from cohestra.adapters.overlay import (
    OverlayError,
    build_overlay,
    default_overlay_path,
    load_overlay,
    validate_overlay,
    write_overlay,
)
from cohestra.adapters.providers import ProviderDescriptor, detect_providers
from cohestra.wake import WakePolicy, validate_wake_policy


@pytest.mark.parametrize("platform_name", ["windows", "macos", "linux"])
def test_detection_has_a_portable_model_for_each_supported_platform(platform_name: str) -> None:
    results = detect_providers(platform_name=platform_name, which=lambda name: f"/bin/{name}")
    assert {item["provider_id"] for item in results} == {
        "codex",
        "claude",
        "workbuddy",
        "zcode",
        "freebuff",
    }
    assert {item["status"] for item in results} == {"executable_detected"}
    assert {item["platform_support"] for item in results} == {"candidate", "unsupported"}
    assert all(item["delivery"] == "not_attempted" for item in results)


def test_detection_and_configuration_fail_closed_when_provider_is_unsupported() -> None:
    restricted = ProviderDescriptor(
        "restricted",
        "Restricted",
        ("restricted",),
        {"linux": "candidate"},
        frozenset({"manual"}),
    )
    detected = detect_providers(
        platform_name="windows", which=lambda _: "/bin/restricted", providers=[restricted]
    )
    assert detected[0]["platform_support"] == "unsupported"
    with pytest.raises(ValueError, match="unsupported provider"):
        build_overlay(["unknown"], platform_name="linux")


def test_overlay_rejects_unstructured_launch_data_and_non_manual_wake() -> None:
    with pytest.raises(ValueError, match="unsupported fields"):
        validate_overlay({"schema_version": 1, "adapters": [], "command": "do-not-run"})
    with pytest.raises(ValueError, match="only disabled manual"):
        validate_overlay(
            {
                "schema_version": 1,
                "adapters": [
                    {
                        "adapter_id": "codex",
                        "provider_id": "codex",
                        "enabled": True,
                        "wake": {"mode": "launch"},
                    }
                ],
            }
        )


def test_configure_writes_only_explicit_overlay_and_health_is_read_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "private" / "adapters.json"
    assert adapters_main(["configure", "--provider", "codex", "--output", str(output)]) == 0
    configured = json.loads(capsys.readouterr().out)
    assert configured["data"]["scaffolded"] == ["codex"]
    assert configured["data"]["manual_only"] is True
    before = output.read_bytes()
    assert adapters_main(["health", "--overlay", str(output), "--platform", "linux"]) == 0
    health = json.loads(capsys.readouterr().out)
    assert health["data"]["overlay"] == str(output.resolve())
    assert health["data"]["providers"][0]["overlay_state"] == "scaffolded"
    assert health["data"]["providers"][0]["executable_state"] in {
        "executable_detected",
        "missing",
    }
    assert health["data"]["providers"][0]["runtime_state"] == "manual_only"
    assert health["data"]["providers"][0]["ready"] is False
    assert health["data"]["providers"][0]["delivery"] == "not_attempted"
    assert output.read_bytes() == before
    assert load_overlay(output)["schema_version"] == 1


def test_default_overlay_is_user_private_and_wake_policy_is_allowlisted(tmp_path: Path) -> None:
    target = default_overlay_path(
        home=tmp_path / "home", environ={"XDG_CONFIG_HOME": str(tmp_path / "config")}
    )
    assert target.is_relative_to(tmp_path / "config") or target.is_relative_to(tmp_path / "home")
    policy = validate_wake_policy(WakePolicy("codex", "manual"), frozenset({"codex"}))
    assert policy.mode == "manual"
    with pytest.raises(ValueError, match="allowlisted"):
        validate_wake_policy(WakePolicy("unknown", "manual"), frozenset({"codex"}))
    with pytest.raises(ValueError, match="unsupported wake mode"):
        validate_wake_policy(WakePolicy("codex", "launch"), frozenset({"codex"}))


def test_overlay_refuses_existing_files_symlinks_and_git_worktrees(tmp_path: Path) -> None:
    overlay = build_overlay(["codex"], platform_name="linux")
    existing = tmp_path / "existing.json"
    existing.write_text("preserve", encoding="utf-8")
    with pytest.raises(OverlayError, match="already exists"):
        write_overlay(existing, overlay)
    assert existing.read_text(encoding="utf-8") == "preserve"
    write_overlay(existing, overlay, replace=True)
    assert load_overlay(existing)["schema_version"] == 1

    link = tmp_path / "link.json"
    link.symlink_to(existing)
    with pytest.raises(OverlayError, match="symlink"):
        write_overlay(link, overlay, replace=True)

    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / ".git").mkdir()
    with pytest.raises(OverlayError, match="Git worktree"):
        write_overlay(repository / "overlay.json", overlay)
    nested = repository / "nested" / "config"
    with pytest.raises(OverlayError, match="Git worktree"):
        write_overlay(nested / "overlay.json", overlay)


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are not portable on Windows")
def test_overlay_uses_private_posix_permissions(tmp_path: Path) -> None:
    overlay = build_overlay(["codex"], platform_name="linux")
    target = write_overlay(tmp_path / "private.json", overlay)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_overlay_unique_temporary_files_and_auto_detection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "concurrent.json"
    overlay = build_overlay(["claude"], platform_name="linux")

    def write_once() -> str:
        try:
            return str(write_overlay(target, overlay))
        except OverlayError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: write_once(), range(2)))
    assert sum(result == str(target) for result in results) == 1
    assert results.count("overlay_exists") == 1
    assert not list(tmp_path.glob(".concurrent.json.*.tmp"))

    detected = [
        {
            "provider_id": "claude",
            "status": "executable_detected",
            "platform_support": "candidate",
        }
    ]
    monkeypatch.setattr(adapters_cli, "detect_providers", lambda **_: detected)
    automatic = tmp_path / "automatic.json"
    assert adapters_main(["configure", "--output", str(automatic)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["scaffolded"] == ["claude"]


def test_missing_overlay_is_a_stable_json_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing.json"
    assert adapters_main(["health", "--overlay", str(missing)]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "overlay_missing"


def test_freebuff_scaffolds_manual_only_but_health_stays_unsupported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "freebuff.json"
    assert adapters_main(["configure", "--provider", "freebuff", "--output", str(target)]) == 0
    capsys.readouterr()
    monkeypatch.setattr(
        adapters_cli,
        "detect_providers",
        lambda **_: [
            {"provider_id": "freebuff", "status": "missing", "platform_support": "unsupported"}
        ],
    )
    assert adapters_main(["health", "--overlay", str(target)]) == 0
    provider = json.loads(capsys.readouterr().out)["data"]["providers"][0]
    assert (provider["unsupported"], provider["runtime_state"]) == (True, "manual_only")


def test_missing_headless_candidate_is_unconfigured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "claude.json"
    write_overlay(target, build_overlay(["claude"]))
    monkeypatch.setattr(
        adapters_cli,
        "detect_providers",
        lambda **_: [
            {"provider_id": "claude", "status": "missing", "platform_support": "candidate"}
        ],
    )
    assert adapters_main(["health", "--overlay", str(target)]) == 0
    runtime_state = json.loads(capsys.readouterr().out)["data"]["providers"][0]["runtime_state"]
    assert runtime_state == "unconfigured"


def test_replace_failure_removes_new_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "replace-failure.json"

    def fail_replace(_: object, __: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(adapters_overlay.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated"):
        write_overlay(target, build_overlay(["codex"]))
    assert not target.exists()
