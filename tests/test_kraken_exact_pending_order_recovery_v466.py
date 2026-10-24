"""Offline synthetic regression tests for one-shot authenticated Kraken v466 reads."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import stat
import time

import pytest

from bot import kraken_exact_pending_order_recovery_v466 as mod

NOW = 1792820000.0
SCOPE = "platform:kraken"
CATEGORY = object()


def oid(n):
    return f"OABC{n:02d}-ABCDE-ABCDEF"


def tid(n):
    return f"TABC{n:02d}-ABCDE-ABCDEF"


class Broker:
    connected = True
    broker_type = "kraken"
    account_type = "platform"
    user_id = None

    def __init__(self, rows, *, extra_trade=False, fail_trade=False):
        self.calls = []
        self.rows = rows
        self.extra_trade = extra_trade
        self.fail_trade = fail_trade

    def _kraken_private_call(self, endpoint, params, *, category):
        assert category is CATEGORY
        self.calls.append((endpoint, dict(params)))
        ids = params["txid"].split(",")
        if endpoint == "QueryOrders":
            rows = {}
            for order_id in ids:
                pair, side, trade_ids = self.rows[order_id]
                rows[order_id] = {
                    "descr": {"pair": pair, "type": side},
                    "vol_exec": str(len(trade_ids) * .05),
                    "trades": trade_ids,
                    "status": "closed",
                }
            return {"error": [], "result": rows}
        if endpoint == "QueryTrades":
            trades = {}
            for trade_id in ids:
                order_id = next(k for k, v in self.rows.items() if trade_id in v[2])
                pair, side, _ = self.rows[order_id]
                trades[trade_id] = {
                    "ordertxid": order_id, "pair": pair, "type": side,
                    "vol": "0.05", "price": "2000", "fee": "0.10",
                }
            if self.fail_trade:
                trades.pop(next(iter(trades)))
            if self.extra_trade:
                trades["TEXTRA-ABCDE-ABCDEF"] = {}
            return {"error": [], "result": trades}
        pytest.fail("Unexpected, potentially mutating broker endpoint")


def sample(tmp_path: Path, count=13, trade_per_order=2):
    source = tmp_path / "private"
    source.mkdir(mode=0o700)
    ledger = tmp_path / "ledger.db"
    rows = {}
    with sqlite3.connect(ledger) as db:
        db.execute("""CREATE TABLE pending_kraken_closes (
            broker TEXT, account_scope TEXT, user_id TEXT, order_id TEXT,
            state TEXT, symbol TEXT, side TEXT
        )""")
        for n in range(count):
            order = oid(n)
            side = "buy" if n < 7 else "sell"
            pair = "XETHZUSD"
            fills = [tid(n*2 + j) for j in range(trade_per_order)]
            rows[order] = (pair, side, fills)
            db.execute("INSERT INTO pending_kraken_closes VALUES (?,?,?,?,?,?,?)",
                       ("kraken", SCOPE, "platform", order, "pending", pair, side))
    (source / "exact_request.json").write_text(json.dumps({
        "request_id": "a" * 32,
        "account_scope": SCOPE,
        "created_at": NOW - 2,
        "max_pages": 1,
    }))
    (source / "exact_request.json").chmod(0o600)
    return source, ledger, Broker(rows)


def test_exact_13_order_26_trade_batched_snapshot_is_diagnostic_only(tmp_path):
    root, ledger, broker = sample(tmp_path)
    assert mod.collect_requested_exact_pending_orders(
        root, [broker], monitoring_category=CATEGORY, ledger_path=ledger, now=NOW)
    methods = [x[0] for x in broker.calls]
    assert methods == ["QueryOrders", "QueryTrades", "QueryTrades"]
    assert all(len(x[1]["txid"].split(",")) <= 20 for x in broker.calls)
    receipt = root / ("a"*32 + ".exact.evidence.json")
    claim = root / ("a"*32 + ".exact.claimed.json")
    report = json.loads(receipt.read_text())
    assert report["collection_succeeded"] is True
    assert report["evidence"]["order_count"] == 13
    assert report["evidence"]["trade_count"] == 26
    assert report["trading_authorized"] is False
    assert report["evidence"]["historical_lots_fees_reconciled"] is False
    assert report["evidence"]["protective_exits_verified"] is False
    assert stat.S_IMODE(receipt.stat().st_mode) == 0o600
    assert stat.S_IMODE(claim.stat().st_mode) == 0o600
    assert not (root / "exact_request.json").exists()
    # No repeat or accidental order placement.
    assert mod.collect_requested_exact_pending_orders(
        root, [broker], monitoring_category=CATEGORY, ledger_path=ledger, now=NOW) is False
    assert len(broker.calls) == 3
    with sqlite3.connect(ledger) as db:
        assert db.execute("SELECT COUNT(*) FROM pending_kraken_closes WHERE state='pending'").fetchone()[0] == 13


def test_missing_request_never_reads_broker(tmp_path):
    root, ledger, broker = sample(tmp_path)
    (root / "exact_request.json").unlink()
    assert mod.collect_requested_exact_pending_orders(
        root, [broker], monitoring_category=CATEGORY, ledger_path=ledger, now=NOW) is False
    assert broker.calls == []


def test_broker_ambiguity_never_claims_request(tmp_path):
    root, ledger, broker = sample(tmp_path)
    second = Broker(broker.rows)
    assert mod.collect_requested_exact_pending_orders(
        root, [broker, second], monitoring_category=CATEGORY,
        ledger_path=ledger, now=NOW) is False
    assert broker.calls == [] and second.calls == []
    assert (root / "exact_request.json").exists()


def test_exact_trade_set_missing_is_fail_closed(tmp_path):
    root, ledger, broker = sample(tmp_path)
    broker.fail_trade = True
    assert mod.collect_requested_exact_pending_orders(
        root, [broker], monitoring_category=CATEGORY, ledger_path=ledger, now=NOW)
    receipt = json.loads((root / ("a"*32 + ".exact.evidence.json")).read_text())
    assert receipt["collection_succeeded"] is False
    assert receipt["trading_authorized"] is False
    assert receipt["failure_code"] == "broker_exact_id_set_incomplete"


def test_exact_trade_set_extra_is_fail_closed(tmp_path):
    root, ledger, broker = sample(tmp_path)
    broker.extra_trade = True
    assert mod.collect_requested_exact_pending_orders(
        root, [broker], monitoring_category=CATEGORY, ledger_path=ledger, now=NOW)
    receipt = json.loads((root / ("a"*32 + ".exact.evidence.json")).read_text())
    assert receipt["collection_succeeded"] is False
    assert receipt["trading_authorized"] is False


def test_missing_ledger_fails_before_first_broker_read(tmp_path):
    root, ledger, broker = sample(tmp_path)
    ledger.unlink()
    assert mod.collect_requested_exact_pending_orders(
        root, [broker], monitoring_category=CATEGORY, ledger_path=ledger, now=NOW)
    receipt = json.loads((root / ("a"*32 + ".exact.evidence.json")).read_text())
    assert receipt["collection_succeeded"] is False
    assert broker.calls == []


def test_unsafe_scope_rejected_without_broker_call(tmp_path):
    root, ledger, broker = sample(tmp_path)
    claim = json.loads((root / "exact_request.json").read_text())
    claim["account_scope"] = "user:other:kraken"
    (root / "exact_request.json").write_text(json.dumps(claim))
    (root / "exact_request.json").chmod(0o600)
    with pytest.raises(mod.ExactReadDenied, match="exact_request_scope_or_budget_invalid"):
        mod.collect_requested_exact_pending_orders(
            root, [broker], monitoring_category=CATEGORY, ledger_path=ledger, now=NOW)
    assert broker.calls == []


def test_unverified_or_conflicting_ledger_ownership_fails(tmp_path):
    root, ledger, broker = sample(tmp_path)
    with sqlite3.connect(ledger) as db:
        db.execute("UPDATE pending_kraken_closes SET account_scope='opaque' WHERE order_id=?", (oid(0),))
    assert mod.collect_requested_exact_pending_orders(
        root, [broker], monitoring_category=CATEGORY, ledger_path=ledger, now=NOW)
    report = json.loads((root / ("a"*32 + ".exact.evidence.json")).read_text())
    assert report["collection_succeeded"] is False
    assert broker.calls == []


def test_broker_partial_order_not_accepted_as_fill(tmp_path):
    root, ledger, broker = sample(tmp_path, count=1)
    source = broker._kraken_private_call
    def unfilled(endpoint, params, *, category):
        reply = source(endpoint, params, category=category)
        if endpoint == "QueryOrders":
            reply["result"][oid(0)]["vol_exec"] = "0"
        return reply
    broker._kraken_private_call = unfilled
    assert mod.collect_requested_exact_pending_orders(
        root, [broker], monitoring_category=CATEGORY, ledger_path=ledger, now=NOW)
    report = json.loads((root / ("a"*32 + ".exact.evidence.json")).read_text())
    assert report["collection_succeeded"] is False
    assert report["failure_code"] == "order_unfilled"


def test_expired_request_never_claimed_or_read(tmp_path):
    root, ledger, broker = sample(tmp_path)
    claim = json.loads((root / "exact_request.json").read_text())
    claim["created_at"] = NOW - 301
    (root / "exact_request.json").write_text(json.dumps(claim))
    (root / "exact_request.json").chmod(0o600)
    with pytest.raises(ValueError, match="expired_or_invalid"):
        mod.collect_requested_exact_pending_orders(
            root, [broker], monitoring_category=CATEGORY, ledger_path=ledger, now=NOW)
    assert broker.calls == []
