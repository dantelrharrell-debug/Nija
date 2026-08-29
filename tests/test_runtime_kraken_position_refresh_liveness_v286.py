from __future__ import annotations

import sys
import threading
import types

import pytest


def _load_v286(monkeypatch):
    monkeypatch.setenv("NIJA_KRAKEN_AUTHORITATIVE_POSITION_WAIT_S", "1")
    sys.modules.pop("bot.runtime_kraken_position_refresh_liveness_v286_patch", None)
    from bot import runtime_kraken_position_refresh_liveness_v286_patch as v286
    return v286


class _BrokerType:
    value = "kraken"


class _Broker:
    broker_type = _BrokerType()
    account_identifier = "USER:test"
    connected = True
    _FIAT_ASSETS = {"USD", "USDT", "USDC"}

    def __init__(self, response):
        self.response = response
        self._nija_kraken_local_read_busy_seq_v242 = 0
        self._price_cache = {"BTC-USD": {"price": 100.0, "ts": 1.0}}

    def supports_symbol(self, symbol):
        return symbol in {"BTC-USD", "ETH-USD"}

    def _normalize_kraken_asset_code(self, value):
        return {"XXBT": "BTC", "XETH": "ETH", "ZUSD": "USD"}.get(value, value)

    def _kraken_private_call(self, method, category=None):
        assert method == "Balance"
        return self.response


def test_authoritative_balance_enumerates_positive_holdings_without_price(monkeypatch):
    v286 = _load_v286(monkeypatch)
    broker = _Broker({"error": [], "result": {"ZUSD": "12.5", "XXBT": "0.25", "XETH": "2"}})
    rows = v286._build_authoritative_rows(broker, broker.response["result"])
    assert [row["symbol"] for row in rows] == ["BTC-USD", "ETH-USD"]
    assert rows[0]["quantity"] == pytest.approx(0.25)
    assert rows[0]["pricing_verified"] is True
    assert rows[1]["quantity"] == pytest.approx(2.0)
    assert rows[1]["pricing_verified"] is False


def test_authoritative_balance_api_error_cannot_be_empty_snapshot(monkeypatch):
    v286 = _load_v286(monkeypatch)
    broker = _Broker({"error": ["EAPI:Invalid key"], "result": {}})
    failures = []
    monkeypatch.setattr(v286, "_record_snapshot_failure", lambda _broker, reason: failures.append(reason))
    with pytest.raises(RuntimeError, match="kraken_balance_error"):
        v286._fetch_authoritative_rows_sync(broker)
    assert failures and "EAPI:Invalid key" in failures[-1]


def test_local_contention_sequence_cannot_be_empty_snapshot(monkeypatch):
    v286 = _load_v286(monkeypatch)
    broker = _Broker({"error": [], "result": {}})
    failures = []
    monkeypatch.setattr(v286, "_record_snapshot_failure", lambda _broker, reason: failures.append(reason))

    def private(method, category=None):
        broker._nija_kraken_local_read_busy_seq_v242 += 1
        return {"error": [], "result": {}}

    broker._kraken_private_call = private
    with pytest.raises(RuntimeError, match="local_read_contention"):
        v286._fetch_authoritative_rows_sync(broker)
    assert failures and "local_read_contention" in failures[-1]


def test_authoritative_position_single_flight_reuses_inflight(monkeypatch):
    v286 = _load_v286(monkeypatch)
    broker = _Broker({"error": [], "result": {"XXBT": "0.5"}})
    started = threading.Event()
    release = threading.Event()
    calls = []

    def fetch(_broker):
        calls.append(1)
        started.set()
        release.wait(2)
        return [{"symbol": "BTC-USD", "quantity": 0.5}]

    monkeypatch.setattr(v286, "_fetch_authoritative_rows_sync", fetch)
    results = []

    t1 = threading.Thread(target=lambda: results.append(v286._authoritative_positions(broker)))
    t2 = threading.Thread(target=lambda: results.append(v286._authoritative_positions(broker)))
    t1.start()
    assert started.wait(1)
    t2.start()
    release.set()
    t1.join(2)
    t2.join(2)
    assert len(calls) == 1
    assert len(results) == 2
    assert all(result[0]["quantity"] == pytest.approx(0.5) for result in results)


def test_mutating_calls_never_receive_v286_prewait(monkeypatch):
    v286 = _load_v286(monkeypatch)
    broker = _Broker({"error": [], "result": {}})
    monkeypatch.setattr(v286, "_mutating_methods", lambda: {"AddOrder"})
    delay, reason = v286._read_rate_delay(broker, "AddOrder", ("AddOrder",), {})
    assert delay == 0.0
    assert reason == "mutating_unchanged"
