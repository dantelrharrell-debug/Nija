from __future__ import annotations

import os
from contextlib import contextmanager

import pytest

from bot import broker_independent_live_execution_patch as independent
from bot import held_trade_cap_guard_patch as held
from bot import universal_broker_exit_supervisor_patch as exits
import final_runtime_convergence_patch as convergence


def _layer(inner):
    def outer(*args, **kwargs):
        return inner(*args, **kwargs)
    outer.__wrapped__ = inner
    return outer


@pytest.mark.parametrize(
    "finder,marker",
    [
        (held._chain_has_attr, held._PATCHED_ATTR),
        (independent._chain_has_attr, independent._WRAP_ATTR),
        (convergence._chain_has_attr, "_nija_final_result_contract_e"),
    ],
)
def test_wrapper_owner_is_found_below_outer_layers(finder, marker):
    def owner():
        return None

    setattr(owner, marker, True)
    wrapped = _layer(_layer(owner))
    assert finder(wrapped, marker) is True


def test_three_live_venues_are_entry_enabled(monkeypatch):
    monkeypatch.setenv("NIJA_ALLOWED_EXECUTION_BROKERS", "kraken,coinbase,okx")
    monkeypatch.delenv("NIJA_DISABLED_BROKERS", raising=False)
    assert all(independent._broker_enabled(name) for name in ("kraken", "coinbase", "okx"))


@pytest.mark.parametrize("venue", ["kraken", "coinbase", "okx"])
def test_take_profit_trigger_and_exit_submission_for_each_venue(venue):
    class Broker:
        broker_type = venue

        def __init__(self):
            self.orders = []

        def place_market_order(self, **kwargs):
            self.orders.append(kwargs)
            return {"status": "filled", "order_id": venue + "-exit", "filled_price": 102.0}

    broker = Broker()
    position = {
        "position_id": venue + "-position",
        "symbol": "ETH-USD",
        "side": "long",
        "quantity": 0.1,
        "entry_price": 100.0,
        "take_profit_1": 101.0,
        "take_profit_2": 103.0,
        "take_profit_3": 105.0,
    }

    hit, reason, target = exits._trigger(broker, position, 102.0)
    assert hit is True
    assert reason == "take_profit_1"
    assert target == pytest.approx(101.0)

    result = exits.auto_exit._exit_order(broker, position, 102.0)
    assert exits.auto_exit._ok(result)
    assert broker.orders == [{"symbol": "ETH-USD", "side": "sell", "size": 0.1}]
