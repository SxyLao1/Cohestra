"""Top-level Cohestra command router."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from cohestra import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cohestra",
        description="Local-first coordination for heterogeneous AI agents.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="component", required=True)
    commands.add_parser("adapters", add_help=False, help="Detect or configure portable adapters")
    commands.add_parser("bridge", add_help=False, help="Use the schema-7 SQLite bridge")
    commands.add_parser("workspace", add_help=False, help="Validate or synchronize an overlay")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args, remainder = parser.parse_known_args(argv)

    if args.component == "bridge":
        from cohestra.bridge.cli import main as bridge_main

        return bridge_main(remainder)
    if args.component == "adapters":
        from cohestra.adapters.cli import main as adapters_main

        return adapters_main(remainder)
    if args.component == "workspace":
        from cohestra.workspace.cli import main as workspace_main

        return workspace_main(remainder)

    parser.error("a component is required")
    return 2
