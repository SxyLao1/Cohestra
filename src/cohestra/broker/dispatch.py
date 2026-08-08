"""Auditable dispatch to explicitly registered in-process adapter objects."""

from __future__ import annotations

from dataclasses import dataclass

from cohestra.adapters.contracts import Adapter, DispatchRequest, DispatchResult


@dataclass(frozen=True)
class AuditRecord:
    request_id: str
    adapter_id: str
    capability: str
    code: str
    success: bool


class AdapterBroker:
    """Finite adapter registry with no discovery, shell, process, or wake behavior."""

    def __init__(self) -> None:
        self._adapters: dict[str, Adapter] = {}
        self._audit: list[AuditRecord] = []

    @property
    def audit_log(self) -> tuple[AuditRecord, ...]:
        return tuple(self._audit)

    def register(self, adapter: Adapter) -> None:
        adapter_id = adapter.adapter_id
        if not adapter_id:
            raise ValueError("adapter_id must be non-empty")
        if adapter_id in self._adapters:
            raise ValueError(f"adapter already registered: {adapter_id}")
        self._adapters[adapter_id] = adapter

    def dispatch(self, request: DispatchRequest) -> DispatchResult:
        adapter = self._adapters.get(request.adapter_id)
        if adapter is None:
            result = self._failure(request, "UNKNOWN_ADAPTER", "adapter is not registered")
        elif request.capability not in adapter.capabilities:
            result = self._failure(
                request, "UNSUPPORTED_CAPABILITY", "adapter does not declare capability"
            )
        else:
            try:
                candidate = adapter.dispatch(request)
            except Exception:  # Recipient code must not bypass an audit record.
                result = self._failure(
                    request,
                    "ADAPTER_ERROR",
                    "adapter raised an exception; inspect recipient-local diagnostics",
                )
            else:
                result = (
                    candidate
                    if isinstance(candidate, DispatchResult)
                    else self._failure(
                        request, "INVALID_RESULT", "adapter returned an invalid result"
                    )
                )
        self._audit.append(
            AuditRecord(
                request.request_id,
                request.adapter_id,
                request.capability.value,
                result.code,
                result.success,
            )
        )
        return result

    @staticmethod
    def _failure(request: DispatchRequest, code: str, detail: str) -> DispatchResult:
        return DispatchResult(
            request_id=request.request_id,
            adapter_id=request.adapter_id,
            capability=request.capability,
            success=False,
            code=code,
            detail=detail,
        )
