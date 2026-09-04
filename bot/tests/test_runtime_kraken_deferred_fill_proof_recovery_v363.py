from __future__ import annotations

import json

import pytest

from bot import runtime_kraken_deferred_fill_proof_recovery_v363_patch as v363
from bot import runtime_kraken_delayed_fill_reconciliation_v357_patch as v357


class KrakenBroker:
    broker_type = "kraken"
    connected = True

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def _kraken_private_call(self, method, params=None, **kwargs):
        self.calls.append((method, dict(params or {})))
        value = self.responses.get(method, {})
        return value() if callable(value) else value


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "NIJA_KRAKEN_PENDING_FILL_PROOF_PATH", str(tmp_path / "pending.json")
    )
    monkeypatch.delenv("NIJA_KRAKEN_RECOVER_FILL_ORDER_IDS", raising=False)
    yield


def _pending(tmp_path):
    path = tmp_path / "pending.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("orders", {})


def test_ack_only_kraken_order_is_recorded_for_deferred_recovery(tmp_path):
    assert v363._patch_v357_enrichment() is True
    broker = KrakenBroker({})
    result = v357._enrich_kraken_final_order(
        broker,
        {"status": "accepted", "order_id": "OZMGFF-7RNH5-6I4AYM"},
        symbol="ETH-USD",
        side="buy",
    )
    assert result.get("filled_price") is None
    orders = _pending(tmp_path)
    assert "OZMGFF-7RNH5-6I4AYM" in orders
    assert orders["OZMGFF-7RNH5-6I4AYM"]["side"] == "buy"


def test_recovery_promotes_authenticated_trade_history_fill(tmp_path, monkeypatch):
    v363.record_pending_order(order_id="ORDER-A", symbol="ETH-USD", side="buy")
    broker = KrakenBroker(
        {
            "QueryOrders": {"error": [], "result": {"ORDER-A": {"status": "closed"}}},
            "TradesHistory": {
                "error": [],
                "result": {
                    "trades": {
                        "T1": {
                            "ordertxid": "ORDER-A",
                            "type": "buy",
                            "vol": "0.0115",
                            "price": "2500",
                            "cost": "28.75",
                        }
                    }
                },
            },
        }
    )
    monkeypatch.setattr(v363, "_kraken_brokers", lambda: [broker])

    promoted = []

    def fake_normalize(result, *, symbol, side):
        promoted.append((dict(result), symbol, side))
        return float(result["filled_price"]), float(result["filled_size_usd"])

    class FakeV328:
        _normalize_dict_fill = staticmethod(fake_normalize)

    monkeypatch.setattr(v363, "_v328", lambda: FakeV328)
    monkeypatch.setattr(v363, "_wake_activation", lambda: None)

    assert v363.recover_once() == 1
    assert promoted and promoted[0][0]["kraken_trade_history_reconciled"] is True
    assert _pending(tmp_path) == {}


def test_recovery_without_fill_evidence_stays_fail_closed(tmp_path, monkeypatch):
    v363.record_pending_order(order_id="ORDER-B", symbol="ETH-USD", side="buy")
    broker = KrakenBroker(
        {
            "QueryOrders": {"error": [], "result": {"ORDER-B": {"status": "open"}}},
            "TradesHistory": {"error": [], "result": {"trades": {}}},
        }
    )
    monkeypatch.setattr(v363, "_kraken_brokers", lambda: [broker])

    def fail_normalize(result, *, symbol, side):  # pragma: no cover - must not run
        raise AssertionError("unproven order must never reach the canonical verifier")

    class FakeV328:
        _normalize_dict_fill = staticmethod(fail_normalize)

    monkeypatch.setattr(v363, "_v328", lambda: FakeV328)

    assert v363.recover_once() == 0
    assert "ORDER-B" in _pending(tmp_path)


def test_expired_pending_entry_is_discarded(tmp_path, monkeypatch):
    v363.record_pending_order(order_id="ORDER-C", symbol="ETH-USD", side="buy")
    monkeypatch.setenv("NIJA_KRAKEN_FILL_PROOF_MAX_AGE_S", "60")
    path = tmp_path / "pending.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["orders"]["ORDER-C"]["first_seen_epoch"] = 0.0
    path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(v363, "_kraken_brokers", lambda: [KrakenBroker({})])
    assert v363.recover_once() == 0
    assert _pending(tmp_path) == {}


def test_proven_result_clears_any_pending_entry(tmp_path):
    assert v363._patch_v357_enrichment() is True
    v363.record_pending_order(order_id="ORDER-D", symbol="ETH-USD", side="buy")
    broker = KrakenBroker({})
    v357._enrich_kraken_final_order(
        broker,
        {
            "status": "filled",
            "order_id": "ORDER-D",
            "filled_price": 2500.0,
            "filled_size": 0.0115,
            "filled_size_usd": 28.75,
        },
        symbol="ETH-USD",
        side="buy",
    )
    assert _pending(tmp_path) == {}


def test_seed_env_queues_operator_supplied_order_ids(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "NIJA_KRAKEN_RECOVER_FILL_ORDER_IDS", "OZMGFF-7RNH5-6I4AYM:ETH-USD:buy"
    )
    v363._seed_orders()
    orders = _pending(tmp_path)
    assert orders["OZMGFF-7RNH5-6I4AYM"]["symbol"] == "ETH-USD"
    assert orders["OZMGFF-7RNH5-6I4AYM"]["side"] == "buy"


def test_install_is_idempotent_and_sets_ready_flag(monkeypatch):
    assert v363.install_import_hook() is True
    assert v363.install_import_hook() is True
