"""Synthetic, offline fail-closed tests. No exchange traffic or live proof."""
from __future__ import annotations

import copy
import importlib.util
import sqlite3
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "nija_kraken_exact_pending_readback_v466.py"
SPEC = importlib.util.spec_from_file_location("v466_exact_pending_readback", SOURCE)
readback = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(readback)

ACCOUNT = "platform:kraken"
IDS = [f"OAAAA{i % 10}-A{i:04d}-A{i:05d}" for i in range(1, 14)]


class Broker:
    broker_type = "kraken"
    account_type = "platform"
    user_id = None
    connected = True

    def __init__(self, rows):
        self.rows = rows
        self.calls = []
        self.callback = None

    def _kraken_private_call(self, endpoint, params, *, category):
        self.calls.append((endpoint, params, category))
        assert endpoint == "QueryOrders"
        assert category is CATEGORY
        if self.callback:
            self.callback()
        return {"error": [], "result": copy.deepcopy(self.rows)}


CATEGORY = object()


@pytest.fixture
def ledger(tmp_path):
    path = tmp_path / "trade_ledger.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE pending_kraken_closes (broker TEXT, account_scope TEXT, order_id TEXT, symbol TEXT, side TEXT, fill_price REAL, filled_usd REAL, exit_fee REAL, state TEXT)")
        db.executemany(
            "INSERT INTO pending_kraken_closes VALUES (?,?,?,?,?,?,?,?,?)",
            [("kraken", ACCOUNT, oid, "XXBTZUSD", "sell", 125.00, 250.0, 0.30, "pending") for oid in IDS],
        )
    return path


@pytest.fixture
def broker():
    rows = {}
    for oid in IDS:
        rows[oid] = {
            "status": "closed",
            "descr": {"pair": "XBTUSD", "type": "sell"},
            "price": "125", "cost": "250", "fee": "0.30", "vol_exec": "2",
        }
    return Broker(rows)


def inspect(ledger, broker, *, scope=ACCOUNT, category=CATEGORY):
    return readback.inspect_exact_pending_orders(ledger, broker, account_scope=scope, monitoring_category=category)


def test_one_exact_query_is_read_only_and_non_authorizing(ledger, broker):
    original = ledger.read_bytes()
    result = inspect(ledger, broker)
    assert result["status"] == "READ_ONLY_EXACT_ORDERS_OBSERVED"
    assert result["requested_pending"] == 13
    assert result["audit_terms_consistent"] == 13
    assert result["single_authenticated_query"] is True
    assert result["fills_and_fees_independently_reconciled"] is False
    assert result["execution_authorized"] is False
    assert result["orders_submitted"] is False
    assert len(broker.calls) == 1
    assert broker.calls[0][0] == "QueryOrders"
    assert broker.calls[0][1] == {"txid": ",".join(sorted(IDS)), "trades": True}
    assert ledger.read_bytes() == original
    assert all(oid not in str(result) for oid in IDS)


@pytest.mark.parametrize("field,value", [
    ("status", "new"), ("descr", None), ("price", "NaN"),
    ("vol_exec", "0"), ("cost", "0"), ("fee", None),
])
def test_bad_broker_rows_fail_closed(ledger, broker, field, value):
    broker.rows[IDS[0]][field] = value
    with pytest.raises(readback.ReadbackDenied):
        inspect(ledger, broker)
    assert len(broker.calls) == 1


def test_partial_query_results_fail_closed(ledger, broker):
    broker.rows.pop(IDS[-1])
    assert readback.safe_inspection(ledger, broker, account_scope=ACCOUNT, monitoring_category=CATEGORY)["failure_code"] == "exact_broker_order_set_incomplete"


def test_wrong_account_fails_without_broker_read(ledger, broker):
    with pytest.raises(readback.ReadbackDenied, match="account_scope_invalid"):
        inspect(ledger, broker, scope="user:someone:kraken")
    assert broker.calls == []


def test_broker_routing_cannot_switch_account(ledger, broker):
    broker.account_type = "user"
    broker.user_id = "someone"
    with pytest.raises(readback.ReadbackDenied, match="account_routing_mismatch"):
        inspect(ledger, broker)
    assert broker.calls == []


def test_disconnected_broker_cannot_read(ledger, broker):
    broker.connected = False
    with pytest.raises(readback.ReadbackDenied, match="authenticated_client_unavailable"):
        inspect(ledger, broker)
    assert broker.calls == []


def test_pending_ledger_changed_during_call_fails_closed(ledger, broker):
    def change():
        with sqlite3.connect(ledger) as db:
            db.execute("UPDATE pending_kraken_closes SET filled_usd=filled_usd+1 WHERE order_id=?", (IDS[0],))
    broker.callback = change
    with pytest.raises(readback.ReadbackDenied, match="ledger_changed_during_readback"):
        inspect(ledger, broker)
    assert len(broker.calls) == 1


def test_duplicate_order_id_fails_before_broker_call(ledger, broker):
    with sqlite3.connect(ledger) as db:
        db.execute("INSERT INTO pending_kraken_closes SELECT * FROM pending_kraken_closes WHERE order_id=?", (IDS[0],))
    with pytest.raises(readback.ReadbackDenied, match="pending_order_ids_invalid_or_duplicated"):
        inspect(ledger, broker)
    assert broker.calls == []


def test_missing_ledger_does_not_imply_no_positions(tmp_path, broker):
    with pytest.raises(readback.ReadbackDenied, match="ledger_path_unverified"):
        inspect(tmp_path / "missing.db", broker)
    assert broker.calls == []


def test_zero_pending_does_not_certify_account(ledger, broker):
    with sqlite3.connect(ledger) as db:
        db.execute("DELETE FROM pending_kraken_closes")
    with pytest.raises(readback.ReadbackDenied, match="pending_count_unavailable"):
        inspect(ledger, broker)
    assert broker.calls == []


def test_unknown_order_id_not_accepted(ledger, broker):
    with sqlite3.connect(ledger) as db:
        db.execute("UPDATE pending_kraken_closes SET order_id='invalid' WHERE order_id=?", (IDS[0],))
    with pytest.raises(readback.ReadbackDenied, match="pending_order_ids_invalid_or_duplicated"):
        inspect(ledger, broker)
    assert broker.calls == []


def test_result_does_not_expose_upstream_exception_or_replay(ledger, broker):
    def fail():
        raise RuntimeError("SECRET-EXCHANGE-NONCE-DO-NOT-LEAK")
    broker.callback = fail
    result = readback.safe_inspection(ledger, broker, account_scope=ACCOUNT, monitoring_category=CATEGORY)
    assert result["status"] == "FAILED_CLOSED"
    assert result["failure_code"] == "authenticated_read_unavailable"
    assert "SECRET-EXCHANGE" not in str(result)
    assert result["orders_submitted"] is False
    assert len(broker.calls) == 1


def test_long_history_page_limit_irrelevant_to_targeted_query(ledger, broker):
    assert inspect(ledger, broker)["requested_pending"] == 13
    assert len(broker.calls) == 1
