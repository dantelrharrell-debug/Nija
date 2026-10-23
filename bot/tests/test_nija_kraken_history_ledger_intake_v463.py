"""Offline-only Kraken v441 receipt / pending-close intake contract tests."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time

import pytest

from scripts.nija_kraken_history_ledger_intake_v463 import inspect_intake
from scripts.nija_kraken_readonly_history_collector_v441 import collect_history


def _broker_read(endpoint, params):
    if endpoint == "Balance":
        return {"error": [], "result": {"ZUSD": "100.00"}}
    if endpoint == "OpenOrders":
        assert params["with_cursor"] is True
        return {"error": [], "result": {"open": {}, "cursor": {"next": ""}}}
    field = {"TradesHistory": "trades", "ClosedOrders": "closed", "Ledgers": "ledger"}[endpoint]
    rows = {
        "trades": {"trade-1": {"ordertxid": "CLOSE-1", "pair": "ETHUSD",
                                "type": "sell", "vol": "0.01", "cost": "25.0", "fee": "0.05"}},
        "closed": {"CLOSE-1": {"status": "closed", "vol_exec": "0.01", "fee": "0.05"}},
        "ledger": {"ledger-1": {"refid": "trade-1", "type": "trade"}},
    }
    assert params == {"ofs": 0}
    return {"error": [], "result": {"count": 1, field: rows[field]}}


@pytest.fixture
def sample(tmp_path):
    source = tmp_path / "recovery.evidence.json"
    ledger = tmp_path / "ledger.db"
    with sqlite3.connect(ledger) as con:
        for table in ("trade_ledger", "open_positions", "completed_trades"):
            con.execute('CREATE TABLE "' + table + '" (id INTEGER PRIMARY KEY)')
        con.execute(
            "CREATE TABLE pending_kraken_closes (broker TEXT, account_scope TEXT, "
            "order_id TEXT, state TEXT)"
        )
        con.execute("INSERT INTO pending_kraken_closes VALUES (?,?,?,?)",
                    ("kraken", "platform:kraken", "CLOSE-1", "pending"))
        con.execute("INSERT INTO pending_kraken_closes VALUES (?,?,?,?)",
                    ("kraken", "platform:kraken", "CLOSE-2", "pending"))
        con.execute("INSERT INTO pending_kraken_closes VALUES (?,?,?,?)",
                    ("kraken", "user:other:kraken", "CLOSE-USER", "pending"))
    start = time.time()
    evidence = collect_history(
        _broker_read, account_scope="platform:kraken", max_pages=2,
        include_balance=True, include_open_orders=True,
    )
    document = {
        "request_id": "a" * 32,
        "collection_succeeded": True, "trading_authorized": False,
        "collection_started_at": start, "collection_finished_at": time.time(),
        "evidence": evidence,
    }
    source.write_text(json.dumps(document), encoding="utf-8")
    source.chmod(0o600)
    return source, ledger, document


def _rewrite(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)


def test_intake_counts_exact_ids_without_reconciling_or_writing(sample):
    source, ledger, _ = sample
    original_hash = hashlib.sha256(ledger.read_bytes()).hexdigest()
    report = inspect_intake(source, ledger, "platform:kraken")
    assert report["status"] == "READ_ONLY_INTAKE_COMPLETE"
    assert report["receipt_integrity_consistent"] is True
    assert report["pending_confirmed_closes"] == 2
    assert report["closed_order_ids_present"] == 1
    assert report["trade_order_ids_present"] == 1
    assert report["both_order_and_trade_ids_present"] == 1
    assert report["pending_closes_still_unresolved"] == 2
    for field in (
        "authenticated_account_owner_certified", "fills_and_fees_reconciled",
        "protective_exits_broker_verified", "offhost_backup_restore_certified",
        "execution_ready", "execution_authority", "authorizes_orders",
        "writes_performed",
    ):
        assert report[field] is False
    assert hashlib.sha256(ledger.read_bytes()).hexdigest() == original_hash


def test_payload_tamper_does_not_gain_identity_or_proof(sample):
    source, ledger, document = sample
    document["evidence"]["history"]["closed"]["CLOSE-1"]["status"] = "not-closed"
    _rewrite(source, document)
    report = inspect_intake(source, ledger, "platform:kraken")
    assert report["status"] == "FAILED_CLOSED"
    assert report["failure_code"] == "receipt_digest_mismatch"
    assert report["execution_authority"] is False


def test_self_claimed_authenticated_certification_rejected(sample):
    source, ledger, document = sample
    document["evidence"]["ledger_links_verified"] = True
    _rewrite(source, document)
    report = inspect_intake(source, ledger, "platform:kraken")
    assert report["failure_code"] == "receipt_provenance_invalid"
    assert report["authorizes_orders"] is False


def test_cross_account_receipt_rejected(sample):
    source, ledger, _ = sample
    assert inspect_intake(source, ledger, "user:other:kraken")["failure_code"] == "receipt_scope_mismatch"
    assert inspect_intake(source, ledger, "platform: kraken")["failure_code"] == "account_scope_invalid"


def test_world_readable_or_symlink_receipt_rejected(sample, tmp_path):
    source, ledger, _ = sample
    source.chmod(0o644)
    assert inspect_intake(source, ledger, "platform:kraken")["failure_code"] == "receipt_not_private_regular"
    source.chmod(0o600)
    link = tmp_path / "alias.json"
    link.symlink_to(source)
    assert inspect_intake(link, ledger, "platform:kraken")["failure_code"] == "receipt_location_invalid"


def test_missing_ledger_table_denied(sample):
    source, ledger, _ = sample
    with sqlite3.connect(ledger) as con:
        con.execute("DROP TABLE pending_kraken_closes")
    assert inspect_intake(source, ledger, "platform:kraken")["failure_code"] == "ledger_schema_missing"


def test_missing_trade_order_reference_denied(sample):
    source, ledger, document = sample
    document["evidence"]["history"]["trades"]["trade-1"].pop("ordertxid")
    envelope = {key: document["evidence"][key] for key in (
        "account_scope_asserted_by_caller", "history", "balance",
        "open_orders", "open_orders_observations",
    )}
    document["evidence"]["evidence_sha256"] = hashlib.sha256(
        json.dumps(envelope, sort_keys=True, separators=(",", ":"), allow_nan=False)
        .encode("utf-8")
    ).hexdigest()
    _rewrite(source, document)
    assert inspect_intake(source, ledger, "platform:kraken")["failure_code"] == "trade_order_identity_invalid"


def test_duplicate_receipt_keys_denied(sample):
    source, ledger, _ = sample
    source.write_text('{"request_id":"a","request_id":"b"}', encoding="utf-8")
    source.chmod(0o600)
    assert inspect_intake(source, ledger, "platform:kraken")["failure_code"] == "receipt_duplicate_key"
