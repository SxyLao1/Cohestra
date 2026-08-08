from __future__ import annotations

import json
from pathlib import Path

from cohestra.cli import main as router_main
from cohestra.workspace.cli import main


def test_workspace_cli_validate_and_dry_run_sync(tmp_path: Path, capsys: object) -> None:
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"schemaVersion": 1, "agents": []}), encoding="utf-8")
    guide = tmp_path / "guide.md"
    guide.write_text("\n".join(f"## {i}. Section\nbody" for i in range(1, 9)), encoding="utf-8")
    assert main(["validate", "--registry", str(registry), "--guide", str(guide)]) == 0
    assert (
        router_main(["workspace", "validate", "--registry", str(registry), "--guide", str(guide)])
        == 0
    )
    playbook = tmp_path / "playbooks" / "demo"
    playbook.mkdir(parents=True)
    (playbook / "SKILL.md").write_text("fixture", encoding="utf-8")
    assert (
        main(
            [
                "sync",
                "--playbooks",
                str(tmp_path / "playbooks"),
                "--skills",
                str(tmp_path / "skills"),
            ]
        )
        == 0
    )
