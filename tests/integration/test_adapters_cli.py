from __future__ import annotations

import json
from pathlib import Path

from cohestra.cli import main


def test_top_level_adapters_router_configures_explicit_private_overlay(
    tmp_path: Path, capsys: object
) -> None:
    overlay = tmp_path / "overlay.json"
    assert main(["adapters", "configure", "--provider", "claude", "--output", str(overlay)]) == 0
    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["ok"] is True
    assert overlay.is_file()
