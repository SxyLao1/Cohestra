"""Explicit, dry-run-first workspace synchronization."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

LinkStrategy = Callable[[Path, Path], None]
MATERIALIZED_MODES = frozenset({"symlink", "junction", "junction-or-symlink"})


@dataclass(frozen=True)
class SyncResult:
    status: str
    name: str
    target: Path
    detail: str


def _validate_roots(source_root: Path, destination_root: Path) -> None:
    if not source_root.is_dir():
        raise ValueError(f"playbooks root is missing: {source_root}")
    if destination_root.is_symlink():
        raise ValueError("skills root must not be a symlink")
    if destination_root.exists() and not destination_root.is_dir():
        raise ValueError("skills root must be a directory")
    source = source_root.resolve()
    destination = destination_root.resolve(strict=False)
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError("playbooks and skills roots must not overlap")


def sync_playbooks(
    playbooks_root: str | Path,
    skills_root: str | Path,
    *,
    apply: bool = False,
    link_mode: str = "symlink",
    strategy: LinkStrategy | None = None,
) -> tuple[SyncResult, ...]:
    """Plan or create links for direct playbook children containing ``SKILL.md``.

    Existing targets are preserved. Mutation requires both ``apply=True`` and a
    caller-selected filesystem strategy.
    """
    source_root = Path(playbooks_root).expanduser()
    destination_root = Path(skills_root).expanduser()
    if link_mode not in MATERIALIZED_MODES | {"route-only", "manual"}:
        raise ValueError(f"unsupported link mode: {link_mode}")
    _validate_roots(source_root, destination_root)
    results: list[SyncResult] = []
    for source in sorted(source_root.iterdir(), key=lambda item: item.name):
        if not source.is_dir() or not (source / "SKILL.md").is_file():
            continue
        destination = destination_root / source.name
        # A generated child name can never escape the supplied root.
        if destination.parent != destination_root or source.name in {"", ".", ".."}:
            raise ValueError("unsafe synchronization target")
        if destination.exists() or destination.is_symlink():
            results.append(
                SyncResult("CONFLICT", source.name, destination, "existing path preserved")
            )
        elif not apply:
            status = "CREATE" if link_mode in MATERIALIZED_MODES else "SKIP"
            results.append(SyncResult(status, source.name, destination, "dry-run"))
        elif link_mode not in MATERIALIZED_MODES:
            results.append(
                SyncResult("SKIP", source.name, destination, "mode does not materialize")
            )
        else:
            if strategy is None:
                raise ValueError("apply requires an explicit link strategy")
            destination_root.mkdir(parents=True, exist_ok=True)
            strategy(source, destination)
            results.append(SyncResult("CREATED", source.name, destination, "link created"))
    return tuple(results)
