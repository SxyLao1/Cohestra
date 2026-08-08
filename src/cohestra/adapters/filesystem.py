"""Platform-selected directory link strategies for explicit sync operations."""

from __future__ import annotations

import os
import platform as platform_module
import subprocess
from pathlib import Path

from cohestra.workspace.sync import LinkStrategy


def _symlink(source: Path, destination: Path) -> None:
    os.symlink(source, destination, target_is_directory=True)


def _junction_command(source: Path, destination: Path) -> str:
    for value in (source, destination):
        rendered = str(value)
        if any(character in rendered for character in '"&|<>^%!\r\n'):
            raise ValueError("junction paths contain unsupported command characters")
    return f'mklink /J "{destination}" "{source}"'


def _junction(source: Path, destination: Path) -> None:
    if os.name != "nt":
        raise RuntimeError("Windows junction strategy requires a Windows host")
    try:
        subprocess.run(
            ["cmd.exe", "/d", "/s", "/c", _junction_command(source, destination)],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("Windows junction creation failed") from exc


def get_link_strategy(platform_name: str | None, link_mode: str) -> LinkStrategy:
    """Return the selected strategy or fail rather than silently crossing platforms."""
    normalized = (platform_name or platform_module.system()).lower()
    if normalized in {"darwin", "macos", "linux"} and link_mode == "symlink":
        return _symlink
    if normalized == "windows" and link_mode in {"junction", "junction-or-symlink"}:
        if os.name != "nt":
            raise RuntimeError("Windows junction strategy requires a Windows host")
        return _junction
    raise ValueError(f"unsupported platform/link mode: {normalized}/{link_mode}")
