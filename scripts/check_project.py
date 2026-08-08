"""Validate version alignment and required public project artifacts."""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {
    ".github/dependabot.yml",
    ".github/workflows/ci.yml",
    ".github/workflows/tag-build.yml",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "README.md",
    "README.zh-CN.md",
    "SECURITY.md",
    "docs/ARCHITECTURE.md",
    "docs/ADAPTERS.md",
    "docs/INSTALLATION.md",
    "docs/SECURITY_MODEL.md",
    "docs/zh-CN/ADAPTERS.md",
    "docs/zh-CN/ARCHITECTURE.md",
    "docs/zh-CN/CLI.md",
    "docs/zh-CN/INSTALLATION.md",
    "docs/zh-CN/RELEASE.md",
    "docs/zh-CN/SECURITY_MODEL.md",
    "examples/adapter.py",
    "examples/registry.json",
    "examples/shared-guide.md",
    "pyproject.toml",
    "src/cohestra/__init__.py",
}
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def broken_local_links() -> list[str]:
    errors: list[str] = []
    for document in sorted(ROOT.rglob("*.md")):
        if any(part == ".git" for part in document.parts):
            continue
        text = document.read_text(encoding="utf-8")
        for match in MARKDOWN_LINK.finditer(text):
            target = match.group(1).strip().strip("<>")
            if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            target = unquote(target.split("#", 1)[0])
            candidate = (document.parent / target).resolve()
            try:
                candidate.relative_to(ROOT)
            except ValueError:
                errors.append(
                    f"markdown link escapes the project: {document.relative_to(ROOT)} -> {target}"
                )
            else:
                if not candidate.exists():
                    errors.append(f"broken markdown link: {document.relative_to(ROOT)} -> {target}")
    return errors


def package_version() -> str:
    module = ast.parse((ROOT / "src/cohestra/__init__.py").read_text(encoding="utf-8"))
    for node in module.body:
        if isinstance(node, ast.Assign):
            if any(
                isinstance(target, ast.Name) and target.id == "__version__"
                for target in node.targets
            ):
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    return node.value.value
    raise ValueError("src/cohestra/__init__.py has no literal __version__")


def main() -> int:
    errors = [
        f"missing required artifact: {path}"
        for path in sorted(REQUIRED)
        if not (ROOT / path).is_file()
    ]
    errors.extend(broken_local_links())
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    if project["version"] != package_version():
        errors.append("pyproject.toml and package __version__ differ")
    if project.get("license") != "MIT":
        errors.append("pyproject.toml must declare the MIT SPDX license")
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    if not license_text.startswith("MIT License\n"):
        errors.append("LICENSE does not contain the MIT license text")
    if errors:
        print("Project checks failed:", file=sys.stderr)
        print("\n".join(f"- {error}" for error in errors), file=sys.stderr)
        return 1
    print(f"Project checks passed for Cohestra {project['version']}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
