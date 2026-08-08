"""Fail when distributable text contains private-machine or credential material."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
}
TEXT_SUFFIXES = {
    ".cfg",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}

# Keep source patterns split so this policy file does not match its own rules.
BLOCKED = {
    "windows user profile": re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+", re.IGNORECASE),
    "private drive layout": re.compile(r"[EF]:\\(?:Home|ProGram|Tools|Software)\\", re.IGNORECASE),
    "posix user profile": re.compile(r"/(?:Users|home)/[^/\s]+/", re.IGNORECASE),
    "credential assignment": re.compile(
        r"(?i)(?:api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*['\"][^'\"]+['\"]"
    ),
}
PRIVATE_MARKERS = tuple(
    "".join(parts)
    for parts in (
        ("Agent", "Workspace"),
        ("generic", "-macos"),
    )
)


def iter_text_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(
            part in SKIP_PARTS or part.endswith(".egg-info") for part in path.parts
        ):
            continue
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in {"MANIFEST.in"}:
            files.append(path)
    return sorted(files)


def main() -> int:
    violations: list[str] = []
    policy_path = Path(__file__).resolve()
    for path in iter_text_files():
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(ROOT)
        for label, pattern in BLOCKED.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                violations.append(f"{relative}:{line}: {label}")
        if path.resolve() == policy_path:
            continue
        folded = text.casefold()
        for marker in PRIVATE_MARKERS:
            if marker.casefold() in folded:
                violations.append(f"{relative}: private source marker {marker!r}")

    if violations:
        print("Sensitive-data scan failed:", file=sys.stderr)
        print("\n".join(f"- {item}" for item in violations), file=sys.stderr)
        return 1
    print(f"Sensitive-data scan passed ({len(iter_text_files())} text files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
