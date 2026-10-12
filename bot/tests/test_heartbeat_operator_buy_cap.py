from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot import pipeline_order_submitter as submitter


def _cap_error(**overrides):
    values = dict(
        strategy="HEARTBEAT_TRADE", side="buy", intent_type="entry",
        reduce_only=False, size_type="quote", size_usd=25.0, maximum_usd="30",
    )
    values.update(overrides)
    return submitter._heartbeat_operator_buy_cap_error(**values)


@pytest.mark.parametrize("maximum", ["", "invalid", "0", "-1", "nan", "inf", "-inf"])
def test_invalid_configured_ceiling_fails_closed(maximum):
    assert _cap_error(maximum_usd=maximum) == "heartbeat_operator_buy_cap_invalid"


@pytest.mark.parametrize("amount", [0.0, -1.0, float("nan"), float("inf")])
def test_invalid_planned_quote_fails_closed(amount):
    assert _cap_error(size_usd=amount) == "heartbeat_operator_buy_notional_invalid"


def test_exact_ceiling_allowed_without_increasing_order():
    assert _cap_error(size_usd=30.0) is None
    assert _cap_error(size_usd=30.000001) == "heartbeat_operator_buy_cap_exceeded"


def test_base_sized_probe_cannot_use_estimated_quote_as_spending_ceiling():
    assert _cap_error(size_type="base") == "heartbeat_operator_buy_cap_requires_quote_size"


@pytest.mark.parametrize("overrides", [
    {"strategy": "APEX"}, {"side": "sell"}, {"intent_type": "exit"},
    {"intent_type": "reduce"}, {"reduce_only": True}, {"maximum_usd": None},
])
def test_cap_does_not_change_ordinary_or_reducing_orders(overrides):
    values = {"maximum_usd": "invalid"}
    values.update(overrides)
    assert _cap_error(**values) is None


def test_exchange_minimum_cannot_raise_probe_above_operator_cap(monkeypatch):
    broker = SimpleNamespace(broker_type=SimpleNamespace(value="kraken"), account_identifier="platform")
    dispatched = []
    finalized = []

    def pipeline_getter():
        dispatched.append(True)
        raise AssertionError("Over-cap probe must never reach execution")

    monkeypatch.setenv("NIJA_HEARTBEAT_MAX_BUY_NOTIONAL_USD", "20")
    monkeypatch.setattr(submitter, "_resolve_execution_pipeline_dependencies", lambda: (object, pipeline_getter))
    monkeypatch.setattr(submitter, "assert_distributed_writer_authority", lambda: None)
    monkeypatch.setattr(submitter, "_resolve_available_balance", lambda *_: 758.0)
    monkeypatch.setattr(submitter, "_resolve_account_equity", lambda *_: 758.0)
    monkeypatch.setattr(submitter, "_risk_bounded_heartbeat_size", lambda *_: 20.60)
    monkeypatch.setattr(submitter, "_finalize_pre_submit_v2_duplicate", lambda data: finalized.append(data))

    result = submitter.submit_market_order_via_pipeline(
        broker=broker, symbol="BTC-USD", side="buy", quantity=10.0,
        strategy="HEARTBEAT_TRADE",
    )

    assert result["error"] == "INTERNAL_DISPATCH_FAILURE: heartbeat_operator_buy_cap_exceeded"
    assert result["broker_dispatch"] is False
    assert result["v2_pre_submit_proven"] is True
    assert dispatched == []
    assert len(finalized) == 1


@pytest.mark.parametrize("effect", ["close", "reduce"])
@pytest.mark.parametrize("maximum", ["invalid", "1"])
def test_position_effect_buy_close_reaches_existing_guard(monkeypatch, effect, maximum):
    from bot import broker_capital_floor_guard

    broker = SimpleNamespace(broker_type=SimpleNamespace(value="coinbase"), account_identifier="default")
    checked = []

    def existing_guard(**kwargs):
        checked.append(kwargs)
        raise RuntimeError("isolated downstream guard sentinel")

    monkeypatch.setenv("NIJA_HEARTBEAT_MAX_BUY_NOTIONAL_USD", maximum)
    monkeypatch.setattr(submitter, "_resolve_execution_pipeline_dependencies", lambda: (object, lambda: None))
    monkeypatch.setattr(submitter, "assert_distributed_writer_authority", lambda: None)
    monkeypatch.setattr(submitter, "_resolve_available_balance", lambda *_: 100.0)
    monkeypatch.setattr(submitter, "_resolve_account_equity", lambda *_: 100.0)
    monkeypatch.setattr(broker_capital_floor_guard, "evaluate_broker_capital_floor", existing_guard)
    result = submitter.submit_market_order_via_pipeline(
        broker=broker, symbol="BTC-USD", side="buy", quantity=25.0,
        strategy="HEARTBEAT_TRADE_CLOSE", position_effect=effect,
    )
    assert len(checked) == 1
    assert result["error"] == "broker_capital_floor_guard_error:RuntimeError"
    assert result["broker_dispatch"] is False
