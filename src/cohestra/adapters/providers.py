"""Portable, declarative provider descriptions and non-executing detection."""

from __future__ import annotations

import platform as platform_module
import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass

PLATFORMS = ("windows", "macos", "linux")
PLATFORM_CANDIDATE = {platform: "candidate" for platform in PLATFORMS}
PLATFORM_UNSUPPORTED = {platform: "unsupported" for platform in PLATFORMS}


@dataclass(frozen=True)
class ProviderDescriptor:
    provider_id: str
    display_name: str
    executable_names: tuple[str, ...]
    platform_support: dict[str, str]
    wake_modes: frozenset[str]
    audit_status: str = "generic-baseline"


PROVIDERS: tuple[ProviderDescriptor, ...] = (
    ProviderDescriptor("codex", "Codex", ("codex",), PLATFORM_CANDIDATE, frozenset({"manual"})),
    ProviderDescriptor(
        "claude",
        "Claude",
        ("claude",),
        PLATFORM_CANDIDATE,
        frozenset({"manual", "headless_candidate"}),
    ),
    ProviderDescriptor(
        "workbuddy",
        "WorkBuddy",
        ("workbuddy",),
        PLATFORM_CANDIDATE,
        frozenset({"manual", "headless_candidate"}),
    ),
    ProviderDescriptor(
        "zcode",
        "ZCode",
        ("zcode",),
        PLATFORM_CANDIDATE,
        frozenset({"manual", "headless_candidate"}),
    ),
    ProviderDescriptor(
        "freebuff", "FreeBuff", ("freebuff",), PLATFORM_UNSUPPORTED, frozenset({"manual"})
    ),
)


def normalize_platform(platform_name: str | None = None) -> str:
    value = (platform_name or platform_module.system()).strip().lower()
    aliases = {"darwin": "macos", "mac": "macos", "win32": "windows", "nt": "windows"}
    return aliases.get(value, value)


def get_provider(provider_id: str) -> ProviderDescriptor:
    for provider in PROVIDERS:
        if provider.provider_id == provider_id:
            return provider
    raise ValueError(f"unsupported provider: {provider_id}")


def detect_providers(
    *,
    platform_name: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
    providers: Iterable[ProviderDescriptor] = PROVIDERS,
) -> list[dict[str, object]]:
    """Inspect declared executable names only; this never starts a provider."""
    normalized_platform = normalize_platform(platform_name)
    results: list[dict[str, object]] = []
    for provider in providers:
        platform_support = provider.platform_support.get(normalized_platform, "unsupported")
        executable = next((name for name in provider.executable_names if which(name)), None)
        status = "executable_detected" if executable else "missing"
        results.append(
            {
                "provider_id": provider.provider_id,
                "display_name": provider.display_name,
                "platform": normalized_platform,
                "status": status,
                "platform_support": platform_support,
                "detected_executable": executable is not None,
                "wake_modes": sorted(provider.wake_modes),
                "delivery": "not_attempted",
                "audit_status": provider.audit_status,
            }
        )
    return results
