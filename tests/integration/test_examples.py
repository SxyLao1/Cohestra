from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from cohestra.workspace.registry import load_registry
from cohestra.workspace.sections import read_sections

ROOT = Path(__file__).parents[2]


def test_recipient_overlay_examples_validate() -> None:
    registry = load_registry(ROOT / "examples/registry.json")
    guide = read_sections(ROOT / "examples/shared-guide.md", "1,4")
    assert [agent.identifier for agent in registry.agents] == ["coordinator", "worker"]
    assert "## 1." in guide
    assert "## 4." in guide
    assert "## 2." not in guide


def test_adapter_example_dispatches_successfully() -> None:
    path = ROOT / "examples/adapter.py"
    spec = importlib.util.spec_from_file_location("cohestra_example_adapter", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        assert module.main() == 0
    finally:
        sys.modules.pop(spec.name, None)
