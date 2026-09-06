from __future__ import annotations

import importlib

import pytest

v365 = importlib.import_module("bot.runtime_kraken_margin_protective_scan_v365_patch")


class Broker:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def _kraken_api_call(self, method, params=None):
        assert method == "OpenPositions"
        assert (params or {}).get("docalcs") == "true"
        self.calls.append((method, dict(params or {})))
        return self.payload


def _position(pair: str, quantity: float, entry: float, *, closed: float = 0.0, leverage: int = 2):
    return {
        "pair": pair,
        "type": "buy",
        "vol": str(quantity),
        "vol_closed": str(closed),
        "cost": str(quantity * entry),
        "leverage": str(leverage),
        "opentm": "1788650000",
    }


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


def test_same_pair_openposition_legs_aggregate_to_full_remaining_quantity():
    entry = 2498.67649763
    quantities = [0.02289589, 0.02289589, 0.02289589, 0.02289589, 0.02289589, 0.02294758]
    assert sum(quantities) == pytest.approx(0.13742703)
    result = {
        f"POS{i + 1}": _position("XETHZUSD", quantity, entry)
        for i, quantity in enumerate(quantities)
    }
    broker = Broker({"error": [], "result": result})

    rows, reason = v365._openposition_rows(broker)

    assert reason == "ok"
    assert len(rows) == 1
    row = rows[0]
    assert row["symbol"] == "ETH-USD"
    assert row["quantity"] == pytest.approx(0.13742703)
    assert row["qty"] == pytest.approx(0.13742703)
    assert row["entry_price"] == pytest.approx(entry)
    assert row["avg_entry_price"] == pytest.approx(entry)
    assert row["cost_basis_usd"] == pytest.approx(0.13742703 * entry)
    assert row["leverage"] == pytest.approx(2.0)
    assert row["position_ids"] == tuple(f"POS{i}" for i in range(1, 7))
    assert row["position_id"] == "POS1,POS2,POS3,POS4,POS5,POS6"
    assert row["kraken_margin_openpositions"] is True
    assert row["broker_position_state_only"] is True
    assert row["confirmed_fill_proof"] is False
    assert broker.calls == [("OpenPositions", {"docalcs": "true"})]


def test_same_pair_aggregation_uses_remaining_quantity_and_prorated_cost():
    broker = Broker({
        "error": [],
        "result": {
            "LEG1": _position("XETHZUSD", 0.05, 2500.0, closed=0.01),
            "LEG2": _position("XETHZUSD", 0.02, 2500.0),
        },
    })

    rows, reason = v365._openposition_rows(broker)

    assert reason == "ok"
    assert len(rows) == 1
    row = rows[0]
    assert row["quantity"] == pytest.approx(0.06)
    assert row["cost_basis_usd"] == pytest.approx(150.0)
    assert row["entry_price"] == pytest.approx(2500.0)
    assert row["position_ids"] == ("LEG1", "LEG2")


def test_different_pairs_remain_separate_aggregate_rows():
    broker = Broker({
        "error": [],
        "result": {
            "ETH1": _position("XETHZUSD", 0.1, 2500.0),
            "ETH2": _position("XETHZUSD", 0.05, 2520.0),
            "BTC1": _position("XXBTZUSD", 0.002, 80000.0),
        },
    })

    rows, reason = v365._openposition_rows(broker)

    assert reason == "ok"
    assert len(rows) == 2
    by_symbol = {row["symbol"]: row for row in rows}
    assert by_symbol["ETH-USD"]["quantity"] == pytest.approx(0.15)
    assert by_symbol["ETH-USD"]["entry_price"] == pytest.approx((0.1 * 2500.0 + 0.05 * 2520.0) / 0.15)
    assert by_symbol["BTC-USD"]["quantity"] == pytest.approx(0.002)
    assert by_symbol["BTC-USD"]["entry_price"] == pytest.approx(80000.0)


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
