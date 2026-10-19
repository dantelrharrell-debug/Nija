from __future__ import annotations

import importlib
import threading
from types import SimpleNamespace

import bot.runtime_kraken_cost_basis_history_pagination_v304_patch as v304


def _run_as_v288_worker(fn):
    result = {}

    def target():
        result["value"] = fn()

    thread = threading.Thread(target=target, name="kraken-bulk-entry-price-v288-PLATFORM")
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive()
    return result.get("value")


def test_wrap_is_noop_outside_v288_worker(monkeypatch):
    broker = SimpleNamespace(account_identifier="PLATFORM")
    calls = []

    def original(self, symbols):
        calls.append(tuple(symbols))
        return {}

    monkeypatch.setattr(v304, "_supplement_older_history", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not supplement")))
    wrapped = v304._wrap_bulk_entry_prices(original)
    assert wrapped(broker, ["ETH-USD"]) == {}
    assert calls == [("ETH-USD",)]


def test_v288_worker_recovers_missing_symbol_from_older_authenticated_buy(monkeypatch):
    responses = {
        50: {
            "error": [],
            "result": {
                "count": 100,
                "trades": {
                    "t1": {"type": "sell", "pair": "XETHZUSD", "price": "9999", "vol": "1", "time": "1"},
                    "t2": {"type": "buy", "pair": "XETHZUSD", "price": "2000", "vol": "0.05", "time": "2"},
                    "t3": {"type": "buy", "pair": "XETHZUSD", "price": "2200", "vol": "0.05", "time": "3"},
                },
            },
        }
    }
    private_calls = []

    class Broker:
        account_identifier = "PLATFORM"

        def _kraken_private_call(self, method, params, category=None):
            private_calls.append((method, dict(params), category))
            return responses[int(params["ofs"])]

    @v304.contextmanager
    def fake_priority():
        yield

    monkeypatch.setattr(v304, "_authoritative_history_priority", fake_priority)
    monkeypatch.setattr(v304, "_history_category", lambda: "monitoring")
    monkeypatch.setattr(v304, "_max_extra_pages", lambda: 4)

    def original(self, symbols):
        return {}

    wrapped = v304._wrap_bulk_entry_prices(original)
    result = _run_as_v288_worker(lambda: wrapped(Broker(), ["ETH-USD"]))

    assert result == {"ETH-USD": 2100.0}
    assert private_calls == [("TradesHistory", {"ofs": 50}, "monitoring")]


def test_only_buy_fills_are_admitted(monkeypatch):
    class Broker:
        account_identifier = "PLATFORM"

        def _kraken_private_call(self, method, params, category=None):
            return {
                "error": [],
                "result": {
                    "count": 50,
                    "trades": {
                        "t1": {"type": "sell", "pair": "XETHZUSD", "price": "2000", "vol": "1", "time": "1"},
                    },
                },
            }

    @v304.contextmanager
    def fake_priority():
        yield

    monkeypatch.setattr(v304, "_authoritative_history_priority", fake_priority)
    monkeypatch.setattr(v304, "_history_category", lambda: "monitoring")
    monkeypatch.setattr(v304, "_max_extra_pages", lambda: 1)

    recovered = v304._supplement_older_history(Broker(), ("ETH-USD",))
    assert recovered == {}


def test_existing_verified_result_is_preserved_and_only_missing_symbol_is_supplemented(monkeypatch):
    broker = SimpleNamespace(account_identifier="PLATFORM")
    seen = []

    def original(self, symbols):
        return {"BTC-USD": 50000.0}

    def supplement(_broker, missing):
        seen.append(missing)
        return {"ETH-USD": 2100.0}

    monkeypatch.setattr(v304, "_supplement_older_history", supplement)
    wrapped = v304._wrap_bulk_entry_prices(original)
    result = _run_as_v288_worker(lambda: wrapped(broker, ["BTC-USD", "ETH-USD"]))

    assert result == {"BTC-USD": 50000.0, "ETH-USD": 2100.0}
    assert seen == [("ETH-USD",)]


def test_v288_source_chains_v304():
    v288 = importlib.import_module("bot.runtime_kraken_cost_basis_bulk_v288_patch")
    source = open(v288.__file__, "r", encoding="utf-8").read()
    assert "runtime_kraken_cost_basis_history_pagination_v304_patch" in source
    assert "v304_history_pagination" in source


def test_multiple_authenticated_buys_on_same_history_page_use_volume_weighted_price(monkeypatch):
    """Every valid buy fill on a page contributes to the reported VWAP."""
    class Broker:
        account_identifier = "PLATFORM"

        def _kraken_private_call(self, method, params, category=None):
            assert method == "TradesHistory"
            assert params == {"ofs": 50}
            return {
                "error": [],
                "result": {
                    "count": 54,
                    "trades": {
                        "a": {"type": "buy", "pair": "BABYUSD", "price": "10", "vol": "2", "time": "1"},
                        "b": {"type": "buy", "pair": "BABYUSD", "price": "20", "vol": "1", "time": "2"},
                        "c": {"type": "sell", "pair": "BABYUSD", "price": "999", "vol": "1", "time": "3"},
                    },
                },
            }

    @v304.contextmanager
    def fake_priority():
        yield

    monkeypatch.setattr(v304, "_authoritative_history_priority", fake_priority)
    monkeypatch.setattr(v304, "_history_category", lambda: "monitoring")
    assert v304._supplement_older_history(Broker(), ("BABY-USD",)) == {"BABY-USD": 40 / 3}


def test_nonfinite_history_prices_and_volumes_do_not_produce_verified_cost_basis(monkeypatch):
    """NaN/Infinity may parse as floats, but are not broker price evidence."""
    class Broker:
        account_identifier = "PLATFORM"

        def _kraken_private_call(self, method, params, category=None):
            return {
                "error": [],
                "result": {
                    "count": 53,
                    "trades": {
                        "nan": {"type": "buy", "pair": "BABYUSD", "price": "nan", "vol": "1", "time": "1"},
                        "inf": {"type": "buy", "pair": "BABYUSD", "price": "inf", "vol": "1", "time": "1"},
                        "vol": {"type": "buy", "pair": "BABYUSD", "price": "2", "vol": "inf", "time": "1"},
                    },
                },
            }

    @v304.contextmanager
    def fake_priority():
        yield

    monkeypatch.setattr(v304, "_authoritative_history_priority", fake_priority)
    monkeypatch.setattr(v304, "_history_category", lambda: "monitoring")
    assert v304._supplement_older_history(Broker(), ("BABY-USD",)) == {}
    assert v304._positive_price_map({"BABY-USD": float("inf"), "ETH-USD": float("nan")}) == {}
