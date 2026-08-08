"""Minimal in-process Cohestra adapter example."""

from __future__ import annotations

from dataclasses import dataclass

from cohestra.adapters import Adapter, Capability, DispatchRequest, DispatchResult
from cohestra.broker import AdapterBroker


@dataclass(frozen=True)
class ExampleAdapter:
    adapter_id: str = "example"
    capabilities: frozenset[Capability] = frozenset({Capability.DISPATCH})

    def dispatch(self, request: DispatchRequest) -> DispatchResult:
        return DispatchResult(
            request_id=request.request_id,
            adapter_id=self.adapter_id,
            capability=request.capability,
            success=True,
            code="ACCEPTED",
            detail="accepted by the example adapter",
        )


def main() -> int:
    broker = AdapterBroker()
    adapter: Adapter = ExampleAdapter()
    broker.register(adapter)
    result = broker.dispatch(
        DispatchRequest(
            request_id="example-request",
            adapter_id=adapter.adapter_id,
            capability=Capability.DISPATCH,
            payload={"task": "demonstrate the public adapter contract"},
        )
    )
    print(result.code)
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
