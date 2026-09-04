from __future__ import annotations

import importlib

v365 = importlib.import_module("bot.runtime_kraken_margin_protective_scan_v365_patch")


class Broker:
    def __init__(self, payload):
        self.payload = payload

    def _kraken_api_call(self, method, params=None):
        assert method == "OpenPositions"
        assert (params or {}).get("docalcs") == "true"
        return self.payload


def test_long_eth_openposition_becomes_visible_without_fill_proof():
    broker = Broker({
        "error": [],
        "result": {
            "TX": {
                "pair": "XETHZUSD",
                "type": "buy",
                "vol": "0.13742703",
                "vol_closed": "0",
                "cost": "343.393906",
                "value": "336.95",
                "margin": "171.69",
            }
        },
    })
    rows, reason = v365._openposition_rows(broker)
    assert reason == "ok"
    assert len(rows) == 1
    row = rows[0]
    assert row["symbol"] == "ETH-USD"
    assert abs(row["quantity"] - 0.13742703) < 1e-12
    assert abs(row["entry_price"] - (343.393906 / 0.13742703)) < 1e-9
    assert row["broker_position_state_only"] is True
    assert row["confirmed_fill_proof"] is False
    assert row["cost_basis_verified"] is True


def test_short_openposition_not_promoted_by_long_visibility_patch():
    broker = Broker({
        "error": [],
        "result": {
            "TX": {
                "pair": "XETHZUSD", "type": "sell", "vol": "0.1",
                "vol_closed": "0", "cost": "250",
            }
        },
    })
    rows, reason = v365._openposition_rows(broker)
    assert reason == "ok"
    assert rows == []


def test_closed_or_zero_cost_position_not_promoted():
    broker = Broker({
        "error": [],
        "result": {
            "A": {"pair": "XETHZUSD", "type": "buy", "vol": "0.1", "vol_closed": "0.1", "cost": "250"},
            "B": {"pair": "XETHZUSD", "type": "buy", "vol": "0.1", "vol_closed": "0", "cost": "0"},
        },
    })
    rows, reason = v365._openposition_rows(broker)
    assert reason == "ok"
    assert rows == []


def test_openpositions_error_fails_closed():
    broker = Broker({"error": ["EAPI:Invalid nonce"], "result": {}})
    rows, reason = v365._openposition_rows(broker)
    assert rows == []
    assert reason.startswith("openpositions_rejected:")


def test_parser_does_not_mutate_execution_readiness(monkeypatch):
    monkeypatch.setenv("NIJA_EXECUTION_READY", "0")
    broker = Broker({
        "error": [],
        "result": {
            "TX": {"pair": "XETHZUSD", "type": "buy", "vol": "0.1", "vol_closed": "0", "cost": "250"}
        },
    })
    rows, reason = v365._openposition_rows(broker)
    assert reason == "ok" and rows
    import os
    assert os.environ["NIJA_EXECUTION_READY"] == "0"
