from __future__ import annotations

from dataclasses import dataclass

import pytest

from cohestra.adapters.contracts import Capability, DispatchRequest, DispatchResult
from cohestra.broker import AdapterBroker


@dataclass
class FakeAdapter:
    adapter_id: str = "fake"
    capabilities: frozenset[Capability] = frozenset({Capability.DISPATCH})
    fail: bool = False

    def dispatch(self, request: DispatchRequest) -> DispatchResult:
        if self.fail:
            raise RuntimeError("recipient failure")
        return DispatchResult(
            request.request_id,
            self.adapter_id,
            request.capability,
            True,
            "OK",
            "accepted",
            {"seen": True},
        )


def _request(
    *, adapter_id: str = "fake", capability: Capability = Capability.DISPATCH
) -> DispatchRequest:
    return DispatchRequest("request-1", adapter_id, capability, {"message": "neutral"})


def test_unknown_adapter_is_failed_and_audited() -> None:
    broker = AdapterBroker()
    result = broker.dispatch(_request(adapter_id="missing"))
    assert result.success is False
    assert result.code == "UNKNOWN_ADAPTER"
    assert broker.audit_log[0].adapter_id == "missing"


def test_unsupported_capability_is_failed_and_audited() -> None:
    broker = AdapterBroker()
    broker.register(FakeAdapter())
    result = broker.dispatch(_request(capability=Capability.HEALTH))
    assert result.code == "UNSUPPORTED_CAPABILITY"
    assert broker.audit_log[0].capability == "health"


def test_success_and_adapter_failure_have_stable_result_shape() -> None:
    broker = AdapterBroker()
    broker.register(FakeAdapter())
    successful = broker.dispatch(_request())
    assert successful.success is True
    assert successful.data == {"seen": True}
    failing_broker = AdapterBroker()
    failing_broker.register(FakeAdapter(fail=True))
    failed = failing_broker.dispatch(_request())
    assert (failed.success, failed.code, failed.request_id) == (False, "ADAPTER_ERROR", "request-1")
    assert "recipient failure" not in failed.detail


def test_duplicate_registration_is_rejected() -> None:
    broker = AdapterBroker()
    broker.register(FakeAdapter())
    with pytest.raises(ValueError, match="already"):
        broker.register(FakeAdapter())
