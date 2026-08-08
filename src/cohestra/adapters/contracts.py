"""Declarative contracts implemented by recipient-provided adapters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class Capability(StrEnum):
    """Portable operation categories; providers may opt into a finite subset."""

    DISPATCH = "dispatch"
    HEALTH = "health"


@dataclass(frozen=True)
class DispatchRequest:
    request_id: str
    adapter_id: str
    capability: Capability
    payload: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.request_id or not self.adapter_id:
            raise ValueError("request_id and adapter_id must be non-empty")


@dataclass(frozen=True)
class DispatchResult:
    request_id: str
    adapter_id: str
    capability: Capability
    success: bool
    code: str
    detail: str
    data: Mapping[str, object] = field(default_factory=dict)


class Adapter(Protocol):
    """An in-process object registered by the embedding application."""

    @property
    def adapter_id(self) -> str: ...

    @property
    def capabilities(self) -> frozenset[Capability]: ...

    def dispatch(self, request: DispatchRequest) -> DispatchResult: ...
