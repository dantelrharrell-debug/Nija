from __future__ import annotations

from types import ModuleType

import disconnected_broker_execution_guard_patch as guard


class CoinbaseBroker:
    connected = False
    client = None

    def get_positions(self):
        raise AssertionError("disconnected Coinbase position reader must not run")


class KrakenBroker:
    connected = True
    client = object()


def test_explicitly_disconnected_broker_is_rejected() -> None:
    ready, reason = guard._connection_state(CoinbaseBroker())
    assert ready is False
    assert reason in {"connected=false", "client_missing"}


def test_connected_kraken_remains_eligible() -> None:
    ready, reason = guard._connection_state(KrakenBroker())
    assert ready is True
    assert reason == "explicit_ready"


def test_execution_helpers_do_not_reuse_aggregate_balance_for_disconnected_broker() -> None:
    module = ModuleType("test_broker_independent_live_execution_patch")
    module._broker_is_connected_or_ready = lambda broker: True
    module._broker_entry_balance = lambda name, broker, fallback: fallback
    module._broker_position_count = lambda broker, fallback=0: broker.get_positions()

    assert guard._patch_execution_module(module) is True
    broker = CoinbaseBroker()
    assert module._broker_is_connected_or_ready(broker) is False
    assert module._broker_entry_balance("coinbase", broker, 335.0) == 0.0
    assert module._broker_position_count(broker, 0) == 0


def test_disconnected_coinbase_position_reader_returns_empty() -> None:
    class TestCoinbaseBroker(CoinbaseBroker):
        pass

    assert guard._patch_broker_class(TestCoinbaseBroker) is True
    assert TestCoinbaseBroker().get_positions() == []
