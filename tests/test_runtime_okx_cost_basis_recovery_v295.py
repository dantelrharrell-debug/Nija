from __future__ import annotations

from types import SimpleNamespace

from bot import runtime_okx_cost_basis_recovery_v295_patch as v295


class _Broker:
    broker_type = SimpleNamespace(value="okx")
    account_identifier = "PLATFORM"

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get_bulk_entry_prices(self, symbols):
        self.calls.append(tuple(symbols))
        return dict(self.payload)


def _reset():
    with v295._FLIGHT_LOCK:
        v295._FLIGHTS.clear()
        v295._CACHE.clear()


def test_okx_identification_is_account_wrapper_safe():
    broker = _Broker({})
    assert v295._is_okx(broker) is True
    assert v295._is_okx(SimpleNamespace(_broker=broker)) is True
    assert v295._is_okx(SimpleNamespace(broker_type=SimpleNamespace(value="coinbase"))) is False


def test_genuine_okx_fill_history_is_accepted_as_trade_history():
    _reset()
    broker = _Broker({"BTC-USD": 64000.25})

    price, source = v295._bounded_okx_entry_price(broker, "BTC-USD")

    assert price == 64000.25
    assert source == "trade_history"
    assert broker.calls == [("BTC-USD",)]


def test_empty_okx_history_remains_unverified():
    _reset()
    broker = _Broker({})

    price, source = v295._bounded_okx_entry_price(broker, "ETH-USD")

    assert price == 0.0
    assert source == "okx_bulk_history_empty"
    assert broker.calls == [("ETH-USD",)]


def test_malformed_okx_history_remains_unverified():
    _reset()

    class _BadBroker(_Broker):
        def get_bulk_entry_prices(self, symbols):
            self.calls.append(tuple(symbols))
            return [123]

    broker = _BadBroker({})
    price, source = v295._bounded_okx_entry_price(broker, "BTC-USD")

    assert price == 0.0
    assert source == "okx_bulk_history_error"


def test_cached_genuine_price_avoids_duplicate_history_reads():
    _reset()
    broker = _Broker({"ETH-USD": 2200.0})

    first = v295._bounded_okx_entry_price(broker, "ETH-USD")
    second = v295._bounded_okx_entry_price(broker, "ETH-USD")

    assert first == (2200.0, "trade_history")
    assert second == (2200.0, "trade_history")
    assert broker.calls == [("ETH-USD",)]
