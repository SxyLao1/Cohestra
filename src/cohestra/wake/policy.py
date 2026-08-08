"""Fail-closed wake policy validation for future recipient-local runtimes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WakePolicy:
    adapter_id: str
    mode: str


def validate_wake_policy(policy: WakePolicy, allowed_adapter_ids: frozenset[str]) -> WakePolicy:
    if policy.adapter_id not in allowed_adapter_ids:
        raise ValueError("wake adapter is not allowlisted")
    if policy.mode != "manual":
        raise ValueError("unsupported wake mode")
    return policy
