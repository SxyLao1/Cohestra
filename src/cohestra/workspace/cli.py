"""Command-line interface for explicit portable workspace operations."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict

from cohestra.adapters.filesystem import get_link_strategy

from .health import check_workspace
from .registry import load_registry
from .sections import read_sections
from .sync import sync_playbooks


def _route_values(values: list[str]) -> dict[str, str]:
    routes: dict[str, str] = {}
    for value in values:
        identifier, separator, path = value.partition("=")
        if not separator or not identifier or not path:
            raise ValueError("routes must use ID=PATH")
        routes[identifier] = path
    return routes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cohestra workspace")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--registry", required=True)
    validate.add_argument("--guide", required=True)
    validate.add_argument("--sections", default="1,4")
    sections = commands.add_parser("sections")
    sections.add_argument("--guide", required=True)
    sections.add_argument("--select", default="1,4")
    sync = commands.add_parser("sync")
    sync.add_argument("--playbooks", required=True)
    sync.add_argument("--skills", required=True)
    sync.add_argument("--platform")
    sync.add_argument("--link-mode", default="symlink")
    sync.add_argument("--apply", action="store_true")
    health = commands.add_parser("health")
    health.add_argument("--registry", required=True)
    health.add_argument("--guide", required=True)
    health.add_argument("--route", action="append", default=[])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            registry = load_registry(args.registry)
            read_sections(args.guide, args.sections)
            print(json.dumps({"agents": len(registry.agents), "status": "PASS"}))
        elif args.command == "sections":
            print(read_sections(args.guide, args.select))
        elif args.command == "sync":
            strategy = get_link_strategy(args.platform, args.link_mode) if args.apply else None
            results = sync_playbooks(
                args.playbooks,
                args.skills,
                apply=args.apply,
                link_mode=args.link_mode,
                strategy=strategy,
            )
            print(
                json.dumps([asdict(result) | {"target": str(result.target)} for result in results])
            )
        else:
            checks = check_workspace(
                args.registry, shared_guide=args.guide, routes=_route_values(args.route)
            )
            print(json.dumps([asdict(check) for check in checks]))
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    return 0
