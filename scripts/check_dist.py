"""Inspect built distributions before they are retained as release artifacts."""

from __future__ import annotations

import argparse
import sys
import tarfile
import tomllib
import zipfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PARTS = {
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "data",
    "logs",
}
FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".pyc", ".pyo"}


def validate_names(names: Iterable[str], required_suffixes: set[str]) -> list[str]:
    normalized = [PurePosixPath(name) for name in names]
    errors: list[str] = []
    for path in normalized:
        if any(part in FORBIDDEN_PARTS for part in path.parts):
            errors.append(f"forbidden path in distribution: {path}")
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            errors.append(f"forbidden file type in distribution: {path}")
    for suffix in sorted(required_suffixes):
        if not any(
            path.as_posix() == suffix.lstrip("/") or path.as_posix().endswith(suffix)
            for path in normalized
        ):
            errors.append(f"required distribution member is missing: *{suffix}")
    return errors


def inspect_wheel(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        errors = validate_names(
            archive.namelist(),
            {
                "/cohestra/__init__.py",
                "/cohestra/cli.py",
                "/cohestra/adapters/providers.py",
                "/cohestra/bridge/__init__.py",
                "/cohestra/wake/policy.py",
                "/cohestra/workspace/__init__.py",
            },
        )
        bad_roots = {
            PurePosixPath(name).parts[0]
            for name in archive.namelist()
            if PurePosixPath(name).parts
            and not (
                PurePosixPath(name).parts[0] == "cohestra"
                or PurePosixPath(name).parts[0].startswith("cohestra-")
            )
        }
        errors.extend(f"unexpected wheel root: {root}" for root in sorted(bad_roots))
        return errors


def inspect_sdist(path: Path) -> list[str]:
    with tarfile.open(path, "r:gz") as archive:
        return validate_names(
            (member.name for member in archive.getmembers()),
            {
                "/README.md",
                "/README.zh-CN.md",
                "/SECURITY.md",
                "/docs/ARCHITECTURE.md",
                "/docs/zh-CN/ARCHITECTURE.md",
                "/examples/registry.json",
                "/src/cohestra/__init__.py",
                "/tests/unit/test_bridge.py",
                "/tests/unit/test_wake_adapters.py",
            },
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("dist", nargs="?", type=Path, default=ROOT / "dist")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with (ROOT / "pyproject.toml").open("rb") as handle:
        version = tomllib.load(handle)["project"]["version"]
    wheel = sorted(args.dist.glob(f"cohestra-{version}-*.whl"))
    sdist = sorted(args.dist.glob(f"cohestra-{version}.tar.gz"))
    errors: list[str] = []
    if len(wheel) != 1:
        errors.append(f"expected one Cohestra {version} wheel, found {len(wheel)}")
    if len(sdist) != 1:
        errors.append(f"expected one Cohestra {version} sdist, found {len(sdist)}")
    if len(wheel) == 1:
        errors.extend(inspect_wheel(wheel[0]))
    if len(sdist) == 1:
        errors.extend(inspect_sdist(sdist[0]))
    if errors:
        print("Distribution checks failed:", file=sys.stderr)
        print("\n".join(f"- {error}" for error in errors), file=sys.stderr)
        return 1
    print(f"Distribution checks passed for Cohestra {version}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
