from __future__ import annotations

from enum import Enum

from bot import runtime_kraken_delayed_fill_reconciliation_v357_patch as v357


class KrakenBroker:
    connected = True

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def _kraken_private_call(self, method, params=None, **kwargs):
        self.calls.append((method, dict(params or {})))
        value = self.responses.get(method, {})
        return value() if callable(value) else value


def test_ack_alone_is_not_fill_and_does_not_query():
    broker = KrakenBroker({})
    result = v357._enrich_kraken_final_order(
        broker,
        {"status": "accepted", "order_id": "ORDER-1"},
        symbol="ETH-USD",
        side="buy",
    )
    assert result.get("filled_price") is None
    assert result.get("filled_size_usd") is None
    # An accepted ACK is allowed to be inspected read-only, but cannot become a
    # fill without a final exact order state and fill-specific exchange fields.
    assert not result.get("kraken_query_order_reconciled")
    assert not result.get("kraken_trade_history_reconciled")


def test_final_status_without_fill_evidence_stays_unproven():
    broker = KrakenBroker({
        "QueryOrders": {"error": [], "result": {"ORDER-2": {"status": "closed"}}},
        "TradesHistory": {"error": [], "result": {"trades": {}}},
    })
    result = v357._enrich_kraken_final_order(
        broker,
        {"status": "filled", "order_id": "ORDER-2"},
        symbol="ETH-USD",
        side="buy",
    )
    assert result.get("filled_price") is None
    assert result.get("filled_size_usd") is None
    assert not result.get("kraken_trade_history_reconciled")


def test_queryorders_exact_final_fill_is_admitted():
    broker = KrakenBroker({
        "QueryOrders": {
            "error": [],
            "result": {
                "ORDER-3": {
                    "status": "closed",
                    "vol_exec": "0.0115",
                    "cost": "28.75",
                }
            },
        }
    })
    result = v357._enrich_kraken_final_order(
        broker,
        {"status": "filled", "order_id": "ORDER-3"},
        symbol="ETH-USD",
        side="buy",
    )
    assert result["kraken_query_order_reconciled"] is True
    assert result["filled_size"] == 0.0115
    assert result["filled_size_usd"] == 28.75
    assert result["filled_price"] == 28.75 / 0.0115


def test_exact_ordertxid_trade_history_can_supply_missing_fill_fields():
    broker = KrakenBroker({
        "QueryOrders": {"error": [], "result": {"ORDER-4": {"status": "closed"}}},
        "TradesHistory": {
            "error": [],
            "result": {
                "trades": {
                    "T1": {
                        "ordertxid": "ORDER-4",
                        "type": "buy",
                        "vol": "0.006",
                        "price": "2500",
                        "cost": "15.0",
                    },
                    "T2": {
                        "ordertxid": "ORDER-4",
                        "type": "buy",
                        "vol": "0.0055",
                        "price": "2500",
                        "cost": "13.75",
                    },
                }
            },
        },
    })
    result = v357._enrich_kraken_final_order(
        broker,
        {"status": "filled", "order_id": "ORDER-4"},
        symbol="ETH-USD",
        side="buy",
    )
    assert result["kraken_trade_history_reconciled"] is True
    assert result["kraken_trade_history_match_count"] == 2
    assert abs(result["filled_size"] - 0.0115) < 1e-12
    assert abs(result["filled_size_usd"] - 28.75) < 1e-12
    assert abs(result["filled_price"] - 2500.0) < 1e-12


def test_unrelated_trade_history_never_proves_fill():
    broker = KrakenBroker({
        "QueryOrders": {"error": [], "result": {"ORDER-5": {"status": "closed"}}},
        "TradesHistory": {
            "error": [],
            "result": {
                "trades": {
                    "T1": {
                        "ordertxid": "SOME-OTHER-ORDER",
                        "type": "buy",
                        "vol": "0.0115",
                        "price": "2500",
                        "cost": "28.75",
                    }
                }
            },
        },
    })
    result = v357._enrich_kraken_final_order(
        broker,
        {"status": "filled", "order_id": "ORDER-5"},
        symbol="ETH-USD",
        side="buy",
    )
    assert result.get("filled_price") is None
    assert result.get("filled_size_usd") is None
    assert not result.get("kraken_trade_history_reconciled")


def test_wrong_side_trade_for_same_order_is_not_used():
    broker = KrakenBroker({
        "QueryOrders": {"error": [], "result": {"ORDER-6": {"status": "closed"}}},
        "TradesHistory": {
            "error": [],
            "result": {
                "trades": {
                    "T1": {
                        "ordertxid": "ORDER-6",
                        "type": "sell",
                        "vol": "0.0115",
                        "price": "2500",
                        "cost": "28.75",
                    }
                }
            },
        },
    })
    result = v357._enrich_kraken_final_order(
        broker,
        {"status": "filled", "order_id": "ORDER-6"},
        symbol="ETH-USD",
        side="buy",
    )
    assert result.get("filled_price") is None
    assert not result.get("kraken_trade_history_reconciled")


def test_existing_fill_specific_evidence_is_preserved_without_replacement():
    broker = KrakenBroker({})
    original = {
        "status": "filled",
        "order_id": "ORDER-7",
        "filled_price": 2499.0,
        "filled_size": 0.011,
        "filled_size_usd": 27.489,
    }
    result = v357._enrich_kraken_final_order(
        broker, original, symbol="ETH-USD", side="buy"
    )
    assert result == original
    assert broker.calls == []


def test_private_reads_use_kraken_monitoring_category_not_plain_string(monkeypatch):
    class Category(Enum):
        MONITORING = "monitoring"

    seen = []

    class StrictKrakenBroker:
        broker_type = "kraken"

        def _kraken_private_call(self, method, params=None, category=None):
            # Production rate/fairness wrappers access category.value.  This
            # reproduces the failure that occurred when v357 passed "query".
            seen.append((method, category.value))
            return {
                "error": [],
                "result": {
                    "ORDER-8": {
                        "status": "closed",
                        "vol_exec": "0.0115",
                        "cost": "28.75",
                    }
                },
            }

    monkeypatch.setattr(v357, "_monitoring_category", lambda: Category.MONITORING)
    result = v357._enrich_kraken_final_order(
        StrictKrakenBroker(),
        {"status": "filled", "order_id": "ORDER-8"},
        symbol="ETH-USD",
        side="buy",
    )

    assert seen == [("QueryOrders", "monitoring")]
    assert result["kraken_query_order_reconciled"] is True
    assert result["filled_size_usd"] == 28.75
