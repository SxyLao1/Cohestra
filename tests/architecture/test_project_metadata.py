from __future__ import annotations

import ast
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_version_has_one_value_across_package_metadata() -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project_version = tomllib.load(handle)["project"]["version"]

    tree = ast.parse((ROOT / "src/cohestra/__init__.py").read_text(encoding="utf-8"))
    package_version = next(
        node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets
        )
        and isinstance(node.value, ast.Constant)
    )
    assert package_version == project_version


def test_mit_license_is_declared_and_materialized() -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    assert project["license"] == "MIT"
    assert (ROOT / "LICENSE").read_text(encoding="utf-8").startswith("MIT License\n")
