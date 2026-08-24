from __future__ import annotations

from types import SimpleNamespace


def _fake_request_class():
    class FakePipelineRequest:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    return FakePipelineRequest


def test_heartbeat_missing_price_hint_uses_selected_broker_price(monkeypatch):
    from bot import runtime_execution_pipeline_late_binding_v204_patch as patch

    calls = []

    class Broker:
        def get_current_price(self, symbol):
            calls.append(symbol)
            return 64123.45

    wrapped = patch._wrap_pipeline_request_constructor(_fake_request_class())
    request = wrapped(
        strategy="HEARTBEAT_TRADE",
        symbol="BTC-USD",
        price_hint_usd=None,
        metadata={"broker_client": Broker()},
    )

    assert request.price_hint_usd == 64123.45
    assert calls == ["BTC-USD"]


def test_non_heartbeat_request_does_not_synthesize_price_hint(monkeypatch):
    from bot import runtime_execution_pipeline_late_binding_v204_patch as patch

    calls = []

    class Broker:
        def get_current_price(self, symbol):
            calls.append(symbol)
            return 64123.45

    wrapped = patch._wrap_pipeline_request_constructor(_fake_request_class())
    request = wrapped(
        strategy="APEX_ENTRY",
        symbol="BTC-USD",
        price_hint_usd=None,
        metadata={"broker_client": Broker()},
    )

    assert request.price_hint_usd is None
    assert calls == []


def test_existing_positive_heartbeat_price_hint_is_preserved(monkeypatch):
    from bot import runtime_execution_pipeline_late_binding_v204_patch as patch

    calls = []

    class Broker:
        def get_current_price(self, symbol):
            calls.append(symbol)
            return 64123.45

    wrapped = patch._wrap_pipeline_request_constructor(_fake_request_class())
    request = wrapped(
        strategy="HEARTBEAT_TRADE",
        symbol="BTC-USD",
        price_hint_usd=63000.0,
        metadata={"broker_client": Broker()},
    )

    assert request.price_hint_usd == 63000.0
    assert calls == []


def test_invalid_heartbeat_price_stays_missing_for_ecel_fail_closed(monkeypatch):
    from bot import runtime_execution_pipeline_late_binding_v204_patch as patch

    class Broker:
        def get_current_price(self, symbol):
            return 0.0

    wrapped = patch._wrap_pipeline_request_constructor(_fake_request_class())
    request = wrapped(
        strategy="HEARTBEAT_TRADE_CLOSE",
        symbol="BTC-USD",
        price_hint_usd=None,
        metadata={"broker_client": Broker()},
    )

    assert request.price_hint_usd is None


def test_heartbeat_price_lookup_exception_stays_missing(monkeypatch):
    from bot import runtime_execution_pipeline_late_binding_v204_patch as patch

    class Broker:
        def get_current_price(self, symbol):
            raise TimeoutError("price feed unavailable")

    wrapped = patch._wrap_pipeline_request_constructor(_fake_request_class())
    request = wrapped(
        strategy="HEARTBEAT_TRADE",
        symbol="BTC-USD",
        price_hint_usd=None,
        metadata={"broker_client": Broker()},
    )

    assert request.price_hint_usd is None
