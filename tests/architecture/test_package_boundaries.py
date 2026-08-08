from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[2] / "src" / "cohestra"
FORBIDDEN_PREFIXES = ("agent_bridge",)


def test_package_does_not_import_private_source_namespaces() -> None:
    violations: list[str] = []
    for path in PACKAGE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            for name in names:
                if name.startswith(FORBIDDEN_PREFIXES):
                    violations.append(f"{path.relative_to(PACKAGE_ROOT)}:{node.lineno}:{name}")
    assert violations == []
