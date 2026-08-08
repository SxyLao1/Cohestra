from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_top_level_router_delegates_to_explicit_bridge_database(tmp_path: Path) -> None:
    database = tmp_path / "bridge.sqlite3"
    environment = os.environ | {
        "PYTHONPATH": os.pathsep.join((str(PROJECT_ROOT / "src"), os.environ.get("PYTHONPATH", "")))
    }
    completed = subprocess.run(
        [sys.executable, "-m", "cohestra", "bridge", "--db", str(database), "init"],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert payload["data"]["schema_version"] == 7
    assert database.is_file()
