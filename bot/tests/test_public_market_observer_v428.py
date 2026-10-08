"""Safety and coverage regressions for the isolated v428 public market observer.

All API results are synthetic fixtures. No live exchange or trading account I/O.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import unquote

import pytest

from scripts import public_market_observer_v428 as observer


@pytest.fixture()
def market_fixture(monkeypatch):
    now = [1000.0]
    calls: list[str] = []
    catalogs = {
        "kraken": {
            "error": [],
            "result": {
                f"X{i:03d}ZUSD": {"wsname": f"K{i:03d}/USD", "status": "online"}
                for i in range(21)
            },
        },
        "coinbase": [
            {"id": f"C{i:03d}-USD", "status": "online", "quote_currency": "USD",
             "trading_disabled": False}
            for i in range(23)
        ],
        "okx": {
            "code": "0",
            "data": [
                {"instId": f"T{i:03d}-USDT", "quoteCcy": "USDT", "state": "live"}
                for i in range(43)
            ],
        },
    }

    def fake_http(url, timeout=4.0):
        assert 1.0 <= timeout <= 5.0
        assert any(url.startswith(h + "/") for h in observer.HOSTS.values())
        calls.append(url)
        if url.endswith("/0/public/AssetPairs"):
            return catalogs["kraken"]
        if url.endswith("/products"):
            return catalogs["coinbase"]
        if url.endswith("public/instruments?instType=SPOT"):
            return catalogs["okx"]
        if "/0/public/Ticker?pair=" in url:
            pairs = unquote(url.split("?pair=", 1)[1]).split(",")
            return {
                "error": [],
                "result": {
                    pair: {"a": ["101"], "b": ["99"], "c": ["100"]}
                    for pair in pairs
                },
            }
        if url.endswith("market/tickers?instType=SPOT"):
            return {
                "code": "0",
                "data": [
                    {"instId": f"T{i:03d}-USDT", "bidPx": "99",
                     "askPx": "101", "last": "100"}
                    for i in range(43)
                ],
            }
        if "/products/" in url and url.endswith("/ticker"):
            return {"bid": "99", "ask": "101", "price": "100"}
        raise AssertionError("unexpected public URL: " + url)

    monkeypatch.setattr(observer, "_http_json", fake_http)
    monkeypatch.setattr(observer.time, "time", lambda: now[0])
    return now, calls, catalogs


def test_all_three_venues_rotate_every_eligible_ticker_without_trading(market_fixture):
    clock, calls, _ = market_fixture
    service = observer.PublicMarketObserver(max_symbols=500, interval_s=150)
    assert service.max_symbols == 20  # Bounded regardless of dashboard setting
    for _ in range(3):
        report = service.poll_once()
        assert report["orders_submitted"] is False
        assert report["broker_credentials_used"] is False
        assert report["trading_authority_unchanged"] is True
        assert all(v["window_attempted"] <= 20 for v in report["venues"].values())
        clock[0] += 151.0
    final = service.snapshot()
    assert final["venues"]["kraken"]["catalog_count"] == 21
    assert final["venues"]["coinbase"]["catalog_count"] == 23
    assert final["venues"]["okx"]["catalog_count"] == 43
    assert all(v["coverage_pct_24h"] == 100.0 for v in final["venues"].values())
    assert any("0/public/Ticker?pair=" in url for url in calls)
    assert any("api.exchange.coinbase.com" in url for url in calls)
    assert any("api/v5/market/tickers?" in url for url in calls)


def test_observer_runs_when_live_execution_is_blocked(monkeypatch, market_fixture):
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "LIVE_PENDING_CONFIRMATION")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0")
    service = observer.PublicMarketObserver(max_symbols=5)
    report = service.poll_once()
    assert report["status"] == "running"
    assert all(v["quotes_verified_this_cycle"] == 5 for v in report["venues"].values())
    assert report["orders_submitted"] is False


def test_invalid_ask_below_bid_does_not_count_as_evaluated(monkeypatch, market_fixture):
    original_http = observer._http_json

    def invalid(url, timeout=4.0):
        if "/products/" in url and url.endswith("/ticker"):
            return {"bid": "105", "ask": "100", "price": "101"}
        return original_http(url, timeout)

    monkeypatch.setattr(observer, "_http_json", invalid)
    report = observer.PublicMarketObserver(max_symbols=2).poll_once()
    assert report["venues"]["coinbase"]["quotes_verified_this_cycle"] == 0
    assert report["venues"]["coinbase"]["unique_quotes_verified_24h"] == 0
    assert report["venues"]["coinbase"]["unique_attempted_24h"] == 2


def test_catalog_api_failure_does_not_claim_completed_coverage(monkeypatch):
    monkeypatch.setattr(observer, "_http_json", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    report = observer.PublicMarketObserver().poll_once()
    assert report["status"] == "degraded"
    assert all(v["catalog_count"] == 0 for v in report["venues"].values())
    assert all(v["coverage_pct_24h"] == 0.0 for v in report["venues"].values())
    assert all(v["errors"] for v in report["venues"].values())


def test_only_literal_exchange_public_hosts_and_get_method(monkeypatch):
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return None

        def read(self, _max_bytes):
            return json.dumps({"ok": True}).encode()

    def fake_urlopen(request, timeout):
        requests.append(request)
        assert request.get_method() == "GET"
        assert not any(k.lower() in ("authorization", "api-key", "api-sign") for k, _ in request.header_items())
        return Response()

    monkeypatch.setattr(observer, "urlopen", fake_urlopen)
    assert observer._http_json("https://api.kraken.com/0/public/AssetPairs") == {"ok": True}
    assert len(requests) == 1
    with pytest.raises(ValueError, match="host_not_allowed"):
        observer._http_json("https://evil.example/orders")


def test_render_liveness_config_still_disables_live_heartbeat_orders():
    root = Path(__file__).resolve().parents[2]
    source = (root / "scripts" / "render_entrypoint.sh").read_text()
    liveness = (root / "render_liveness_server.py").read_text()
    scanner = (root / "scripts" / "public_market_observer_v428.py").read_text()
    assert "export NIJA_ALLOW_LIVE_HEARTBEAT_ORDERS=false" in source
    assert "export HEARTBEAT_TRADE=false" in source
    assert "export NIJA_PUBLIC_MARKET_OBSERVER_ENABLED=true" in source
    assert '"/market-observerz"' in liveness
    assert "import bot." not in scanner and "from bot." not in scanner
    assert "place_market_order" not in scanner and "submit_order" not in scanner
    assert '"trading_authority_unchanged": True' in scanner
