"""Fail-closed selective reader for numbered Markdown guides."""

from __future__ import annotations

import re
from pathlib import Path

HEADER = re.compile(r"^## ([1-8])\.\s+.+$", re.MULTILINE)
EXPECTED_SECTIONS = tuple(str(index) for index in range(1, 9))


def read_sections(path: str | Path, selected: str = "1,4") -> str:
    """Return requested guide sections only after validating the full section shape."""
    try:
        text = Path(path).expanduser().read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"unable to read guide: {path}") from exc
    matches = list(HEADER.finditer(text))
    if tuple(match.group(1) for match in matches) != EXPECTED_SECTIONS:
        raise ValueError("guide must contain exactly one ordered section 1 through 8")
    requested = {item.strip() for item in selected.split(",") if item.strip()}
    if not requested or not requested.issubset(EXPECTED_SECTIONS):
        raise ValueError("selected sections must be a non-empty subset of 1 through 8")
    result: list[str] = []
    preamble = text[: matches[0].start()].strip()
    if preamble:
        result.append(preamble)
    for index, match in enumerate(matches):
        if match.group(1) in requested:
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            result.append(text[match.start() : end].strip())
    return "\n\n".join(result)
