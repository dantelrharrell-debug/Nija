from __future__ import annotations

import time

import pytest

from bot import ecel_execution_compiler as ecel
from bot import runtime_execution_convergence_v342_patch as v342


def setup_function() -> None:
    with v342._LOCK:
        v342._FLIGHTS.clear()
        v342._GENERATIONS.clear()


def test_broker_budget_accepts_late_but_valid_coinbase_result(monkeypatch):
    monkeypatch.setattr(v342, "_timeout_s", lambda broker: 0.20)
    monkeypatch.setattr(v342, "_stale_after_s", lambda broker: 0.40)

    def raw(_self):
        time.sleep(0.08)
        return [{"symbol": "BTC-USD", "quantity": 0.001}]

    wrapped = v342._broker_bounded_generation(raw, "coinbase")
    broker = object()
    result = wrapped(broker)

    assert result == [{"symbol": "BTC-USD", "quantity": 0.001}]
    assert v342._GENERATIONS[id(broker)] == 1


def test_broker_budget_discards_superseded_late_generation(monkeypatch):
    monkeypatch.setattr(v342, "_timeout_s", lambda broker: 0.03)
    monkeypatch.setattr(v342, "_stale_after_s", lambda broker: 0.06)

    calls = 0

    def raw(_self):
        nonlocal calls
        calls += 1
        if calls == 1:
            time.sleep(0.12)
            return [{"symbol": "STALE"}]
        return [{"symbol": "FRESH"}]

    wrapped = v342._broker_bounded_generation(raw, "coinbase")
    broker = object()

    with pytest.raises(TimeoutError):
        wrapped(broker)
    time.sleep(0.07)
    assert wrapped(broker) == [{"symbol": "FRESH"}]
    time.sleep(0.06)
    assert v342._GENERATIONS[id(broker)] == 2


def _compiler_with_rule(min_notional: float) -> ecel.ECELExecutionCompiler:
    compiler = ecel.ECELExecutionCompiler()
    compiler.schema._live_refresh_enabled = False
    compiler.schema.upsert_rule(
        ecel.ContractRule(
            broker="kraken",
            symbol="ORCA-USD",
            base_asset="ORCA",
            quote_asset="USD",
            min_notional_usd=min_notional,
            min_base_size=0.01,
            base_step_size=0.00000001,
            price_step_size=0.0001,
            base_precision=8,
            price_precision=4,
        )
    )
    v342._patch_ecel_exact_close()
    return compiler


def test_exact_close_never_inflates_verified_held_quantity():
    compiler = _compiler_with_rule(1.0)
    held = 2.41188714
    result = compiler.compile(
        ecel.CompileRequest(
            broker="kraken",
            symbol="ORCA-USD",
            side="sell",
            order_type="MARKET",
            desired_notional_usd=held * 1.247,
            sizing_mode="units",
            desired_units=held,
            reduce_only=True,
            intent_type="protective_exit",
            price_hint_usd=1.247,
        )
    )

    assert result.accepted is True
    assert result.compiled_base_size is not None
    assert result.compiled_base_size <= held
    assert result.compiled_base_size == pytest.approx(held)


def test_below_genuine_close_minimum_is_dust_not_synthetic_ten_dollar_sell():
    compiler = _compiler_with_rule(10.0)
    held = 2.41188714
    result = compiler.compile(
        ecel.CompileRequest(
            broker="kraken",
            symbol="ORCA-USD",
            side="sell",
            order_type="MARKET",
            desired_notional_usd=held * 1.247,
            sizing_mode="units",
            desired_units=held,
            reduce_only=True,
            intent_type="protective_exit",
            price_hint_usd=1.247,
        )
    )

    assert result.accepted is False
    assert result.reason == "CLOSE_BELOW_MIN_NOTIONAL_DUST"
    assert result.compiled_base_size is None
