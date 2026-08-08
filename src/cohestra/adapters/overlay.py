"""Strict, user-private adapter overlay storage without runtime execution."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import cast

from .providers import get_provider

OVERLAY_SCHEMA_VERSION = 1


class OverlayError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def default_overlay_path(
    *, home: Path | None = None, environ: dict[str, str] | None = None
) -> Path:
    environment = os.environ if environ is None else environ
    user_home = Path.home() if home is None else home
    if os.name == "nt":
        configured_base = environment.get("LOCALAPPDATA")
        base = Path(configured_base) if configured_base else user_home / "AppData" / "Local"
    else:
        configured_base = environment.get("XDG_CONFIG_HOME")
        base = Path(configured_base) if configured_base else user_home / ".config"
    return base / "cohestra" / "adapters.json"


def build_overlay(
    provider_ids: list[str], *, platform_name: str | None = None
) -> dict[str, object]:
    if not provider_ids:
        raise ValueError("at least one provider is required")
    if len(provider_ids) != len(set(provider_ids)):
        raise ValueError("providers must be unique")
    adapters: list[dict[str, object]] = []
    for provider_id in provider_ids:
        provider = get_provider(provider_id)
        adapters.append(
            {
                "adapter_id": provider.provider_id,
                "provider_id": provider.provider_id,
                "enabled": False,
                "wake": {"mode": "manual"},
            }
        )
    return {"schema_version": OVERLAY_SCHEMA_VERSION, "adapters": adapters}


def _has_symlink_component(path: Path) -> bool:
    def is_link_or_junction(candidate: Path) -> bool:
        is_junction = getattr(candidate, "is_junction", None)
        return candidate.is_symlink() or (callable(is_junction) and is_junction())

    return any(is_link_or_junction(candidate) for candidate in (path, *path.parents))


def _is_git_worktree(path: Path) -> bool:
    return any((ancestor / ".git").exists() for ancestor in (path.parent, *path.parents))


def write_overlay(path: Path | str, overlay: dict[str, object], *, replace: bool = False) -> Path:
    requested = Path(path).expanduser()
    if _has_symlink_component(requested):
        raise OverlayError("overlay_symlink", "overlay path must not contain a symlink")
    target = requested.resolve()
    validate_overlay(overlay)
    if _is_git_worktree(target):
        raise OverlayError("overlay_git_worktree", "overlay path must not be inside a Git worktree")
    target.parent.mkdir(parents=True, exist_ok=True)
    if _has_symlink_component(target):
        raise OverlayError("overlay_symlink", "overlay path must not be a symlink")
    if target.exists() and (not replace or not target.is_file()):
        raise OverlayError(
            "overlay_exists", "overlay already exists; use --replace for a regular file"
        )
    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp", text=True
    )
    temporary = Path(temporary_name)
    reservation_identity: tuple[int, int] | None = None
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(overlay, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        if not replace:
            try:
                reservation = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError as exc:
                raise OverlayError("overlay_exists", "overlay already exists") from exc
            else:
                reservation_stat = os.fstat(reservation)
                reservation_identity = (reservation_stat.st_dev, reservation_stat.st_ino)
                os.close(reservation)
        try:
            os.replace(temporary, target)
        except OSError:
            try:
                if reservation_identity is not None and target.is_file():
                    current = target.stat()
                    if (current.st_dev, current.st_ino) == reservation_identity:
                        target.unlink()
            except OSError:
                pass
            raise
        if os.name != "nt":
            target.chmod(stat.S_IRUSR | stat.S_IWUSR)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def load_overlay(path: Path | str) -> dict[str, object]:
    target = Path(path).expanduser().resolve()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise OverlayError("overlay_missing", f"adapter overlay is missing: {target}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise OverlayError("overlay_invalid", f"invalid adapter overlay: {target}") from exc
    if not isinstance(raw, dict):
        raise ValueError("adapter overlay must be an object")
    overlay = cast(dict[str, object], raw)
    validate_overlay(overlay)
    return overlay


def validate_overlay(overlay: dict[str, object]) -> None:
    if set(overlay) != {"schema_version", "adapters"}:
        raise ValueError("adapter overlay has unsupported fields")
    if overlay["schema_version"] != OVERLAY_SCHEMA_VERSION:
        raise ValueError("unsupported adapter overlay schema")
    adapters = overlay["adapters"]
    if not isinstance(adapters, list) or not adapters:
        raise ValueError("adapter overlay requires adapters")
    identifiers: set[str] = set()
    for adapter in adapters:
        if not isinstance(adapter, dict) or set(adapter) != {
            "adapter_id",
            "provider_id",
            "enabled",
            "wake",
        }:
            raise ValueError("adapter entry has unsupported fields")
        adapter_id = adapter.get("adapter_id")
        provider_id = adapter.get("provider_id")
        if not isinstance(adapter_id, str) or adapter_id in identifiers:
            raise ValueError("adapter_id must be unique")
        if not isinstance(provider_id, str) or adapter_id != provider_id:
            raise ValueError("adapter must use a known provider identifier")
        get_provider(provider_id)
        if adapter.get("enabled") is not False or adapter.get("wake") != {"mode": "manual"}:
            raise ValueError("only disabled manual wake adapters are supported")
        identifiers.add(adapter_id)
