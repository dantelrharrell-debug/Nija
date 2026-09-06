from __future__ import annotations

from bot import runtime_universal_position_materialization_v377_patch as v377


class _SymbolTracker:
    def __init__(self):
        self.rows = {
            "BTC-USD": {
                "position_id": "btc-1",
                "symbol": "BTC-USD",
                "side": "long",
                "quantity": 0.01,
                "entry_price": 50000.0,
            },
            "ETH-USD": {
                "position_id": "eth-1",
                "symbol": "ETH-USD",
                "side": "short",
                "quantity": 0.20,
                "entry_price": 2500.0,
            },
        }

    def get_all_positions(self):
        return list(self.rows)

    def get_position(self, symbol):
        return self.rows.get(symbol)


class _Broker:
    broker_type = "future_broker"
    account_id = "user:future"

    def __init__(self):
        self.position_tracker = _SymbolTracker()


def test_symbol_only_position_tracker_materializes_full_rows():
    rows = v377._local_tracker_rows(_Broker())

    assert {row["symbol"] for row in rows} == {"BTC-USD", "ETH-USD"}
    assert all(row["account_id"] == "user:future" for row in rows)
    assert all(float(row["quantity"]) > 0 for row in rows)
    assert all(float(row["entry_price"]) > 0 for row in rows)


def test_supervisor_patch_supplements_symbol_only_tracker(monkeypatch):
    import bot.universal_broker_exit_supervisor_patch as supervisor

    broker = _Broker()
    monkeypatch.setattr(supervisor, "_tracker_positions", lambda _broker: [])

    assert v377._patch_supervisor() is True
    rows = supervisor._tracker_positions(broker)

    assert {row["position_id"] for row in rows} == {"btc-1", "eth-1"}
    assert {row["side"] for row in rows} == {"long", "short"}


def test_materializer_does_not_invent_missing_quantity():
    broker = _Broker()
    broker.position_tracker.rows["ZERO-USD"] = {
        "position_id": "zero-1",
        "symbol": "ZERO-USD",
        "side": "long",
        "entry_price": 1.0,
        "quantity": 0.0,
    }

    rows = v377._local_tracker_rows(broker)

    assert "ZERO-USD" not in {row["symbol"] for row in rows}
