from __future__ import annotations

import sys
import threading
import time


def _load(monkeypatch):
    sys.modules.pop("bot.runtime_kraken_cost_basis_bulk_v288_patch", None)
    from bot import runtime_kraken_cost_basis_bulk_v288_patch as v288
    v288._BULK_FLIGHTS.clear()
    v288._BULK_CACHE.clear()
    v288._LAST_ERROR_AT.clear()
    monkeypatch.setattr(v288, "_wait_slice_s", lambda: 0.02)
    return v288


class _BulkBroker:
    broker_type = "kraken"
    account_identifier = "USER:test"

    def __init__(self):
        self.calls = 0
        self._nija_authoritative_position_raw_rows_v286 = (
            {"symbol": "AAVE-USD", "quantity": 0.85},
            {"symbol": "CELO-USD", "quantity": 12.0},
            {"symbol": "ORCA-USD", "quantity": 3.0},
            {"symbol": "PROVE-USD", "quantity": 7.0},
        )

    def get_bulk_entry_prices(self, symbols):
        self.calls += 1
        assert set(symbols) == {"AAVE-USD", "CELO-USD", "ORCA-USD", "PROVE-USD"}
        return {
            "AAVE-USD": 117.25,
            "CELO-USD": 0.42,
            "ORCA-USD": 2.18,
            "PROVE-USD": 0.73,
        }


def test_authoritative_symbols_collect_entire_account(monkeypatch):
    v288 = _load(monkeypatch)
    broker = _BulkBroker()

    symbols = v288._authoritative_symbols(broker, "AAVE-USD")

    assert symbols == ("AAVE-USD", "CELO-USD", "ORCA-USD", "PROVE-USD")


def test_bulk_history_called_once_and_reused_for_all_symbols(monkeypatch):
    v288 = _load(monkeypatch)
    broker = _BulkBroker()

    first, first_source = v288._bounded_bulk_entry_price(broker, "AAVE-USD")
    second, second_source = v288._bounded_bulk_entry_price(broker, "CELO-USD")
    third, third_source = v288._bounded_bulk_entry_price(broker, "ORCA-USD")

    assert first == 117.25
    assert second == 0.42
    assert third == 2.18
    assert first_source == second_source == third_source == "trade_history"
    assert broker.calls == 1


def test_pending_bulk_history_is_single_flight(monkeypatch):
    v288 = _load(monkeypatch)
    release = threading.Event()

    class SlowBroker(_BulkBroker):
        def get_bulk_entry_prices(self, symbols):
            self.calls += 1
            release.wait(1.0)
            return {symbol: 1.25 for symbol in symbols}

    broker = SlowBroker()

    price1, source1 = v288._bounded_bulk_entry_price(broker, "AAVE-USD")
    price2, source2 = v288._bounded_bulk_entry_price(broker, "CELO-USD")

    assert price1 == 0.0
    assert price2 == 0.0
    assert source1 == source2 == "bulk_api_pending"
    assert broker.calls == 1

    release.set()
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        flight = v288._BULK_FLIGHTS.get(id(broker))
        if flight is not None and flight["event"].is_set():
            break
        time.sleep(0.005)

    price3, source3 = v288._bounded_bulk_entry_price(broker, "PROVE-USD")
    assert price3 == 1.25
    assert source3 == "trade_history"
    assert broker.calls == 1


def test_proxy_suppresses_per_symbol_history_only():
    from bot.runtime_kraken_cost_basis_bulk_v288_patch import _NoPerSymbolEntryPriceProxy

    class Broker:
        marker = "preserved"

        def get_real_entry_price(self, symbol):
            raise AssertionError("per-symbol history must be suppressed")

    proxy = _NoPerSymbolEntryPriceProxy(Broker())

    assert proxy.marker == "preserved"
    assert hasattr(proxy, "get_real_entry_price") is False
