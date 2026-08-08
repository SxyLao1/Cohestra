"""Command interface for declarative adapter discovery and overlays."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .overlay import OverlayError, build_overlay, default_overlay_path, load_overlay, write_overlay
from .providers import detect_providers, get_provider


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cohestra adapters")
    commands = parser.add_subparsers(dest="command", required=True)
    detect = commands.add_parser(
        "detect", help="Inspect declared provider names without launching them"
    )
    detect.add_argument("--platform")
    configure = commands.add_parser(
        "configure", help="Write a disabled, user-private adapter overlay"
    )
    configure.add_argument("--provider", action="append")
    configure.add_argument("--output", type=Path)
    configure.add_argument("--platform")
    configure.add_argument("--replace", action="store_true")
    health = commands.add_parser(
        "health", help="Validate an overlay and inspect its provider names"
    )
    health.add_argument("--overlay", type=Path)
    health.add_argument("--platform")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "detect":
            result: dict[str, object] = {"providers": detect_providers(platform_name=args.platform)}
        elif args.command == "configure":
            detections = detect_providers(platform_name=args.platform)
            provider_ids = args.provider or [
                str(item["provider_id"])
                for item in detections
                if item["status"] == "executable_detected"
                and item["platform_support"] != "unsupported"
            ]
            if not provider_ids:
                raise OverlayError(
                    "no_provider_detected", "no portable provider executable was detected"
                )
            overlay = build_overlay(provider_ids, platform_name=args.platform)
            target = write_overlay(
                args.output or default_overlay_path(), overlay, replace=args.replace
            )
            result = {
                "overlay": str(target),
                "scaffolded": provider_ids,
                "manual_only": True,
                "next_action": "review the overlay before configuring a recipient-local runtime",
            }
        else:
            overlay_path = args.overlay or default_overlay_path()
            overlay = load_overlay(overlay_path)
            adapters = overlay["adapters"]
            if not isinstance(adapters, list):
                raise ValueError("adapter overlay requires adapters")
            provider_ids = [str(item["provider_id"]) for item in adapters if isinstance(item, dict)]
            detections = detect_providers(platform_name=args.platform)
            selected: list[dict[str, object]] = []
            for provider_id in provider_ids:
                detection = next(item for item in detections if item["provider_id"] == provider_id)
                provider = get_provider(provider_id)
                unsupported = (
                    detection["platform_support"] == "unsupported" or not provider.wake_modes
                )
                selected.append(
                    {
                        "provider_id": provider_id,
                        "overlay_state": "scaffolded",
                        "executable_state": detection["status"],
                        "runtime_state": (
                            "manual_only"
                            if provider.wake_modes == {"manual"}
                            else "candidate"
                            if not unsupported and detection["status"] == "executable_detected"
                            else "unconfigured"
                        ),
                        "ready": False,
                        "unsupported": unsupported,
                        "delivery": "not_attempted",
                    }
                )
            result = {
                "overlay": str(overlay_path.expanduser().resolve()),
                "status": (
                    "unsupported" if any(item["unsupported"] for item in selected) else "scaffolded"
                ),
                "providers": selected,
            }
        print(json.dumps({"ok": True, "data": result}, ensure_ascii=False, separators=(",", ":")))
        return 0
    except (OSError, ValueError) as exc:
        code = exc.code if isinstance(exc, OverlayError) else "adapter_error"
        print(
            json.dumps(
                {"ok": False, "error": {"code": code, "message": str(exc)}},
                separators=(",", ":"),
            )
        )
        return 2


__all__ = ["build_parser", "main"]
