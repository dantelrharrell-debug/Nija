"""Fail-closed tests for read-only, account-scoped Kraken evidence pagination."""
from enum import Enum
from types import SimpleNamespace

import pytest

from scripts.nija_kraken_readonly_history_collector_v441 import (
    IncompleteHistory, collect_from_existing_broker, collect_history,
)


def _reader(endpoint, params):
    field = {"TradesHistory": "trades", "ClosedOrders": "closed", "Ledgers": "ledger"}[endpoint]
    ofs = params["ofs"]
    return {"error": [], "result": {"count": 51, field: {
        str(i): {"vol": "1"} for i in range(ofs, min(51, ofs + 50))
    }}}


def test_all_pages_retrieved_without_writes():
    calls = []
    def read(endpoint, params):
        calls.append((endpoint, dict(params)))
        return _reader(endpoint, params)
    report = collect_history(read, account_scope="platform:kraken")
    assert len(report["history"]["trades"]) == 51
    assert len(report["history"]["closed"]) == 51
    assert len(report["history"]["ledger"]) == 51
    assert len(calls) == 12
    assert all(sorted(p) == ["ofs"] for _, p in calls)
    assert report["trading_authorized"] is False
    assert report["entry_exit_reconciliation_verified"] is False


def test_page_limit_fails_closed():
    with pytest.raises(IncompleteHistory, match="page limit"):
        collect_history(_reader, account_scope="platform:kraken", max_pages=1)


def test_bad_account_scope_rejected():
    with pytest.raises(ValueError):
        collect_history(_reader, account_scope="user:kraken")


def test_api_error_and_missing_page_fail_closed():
    def failure(endpoint, params):
        if params["ofs"] == 50:
            return {"error": ["EGeneral:Permission denied"]}
        return _reader(endpoint, params)
    with pytest.raises(IncompleteHistory):
        collect_history(failure, account_scope="platform:kraken")


def test_duplicate_ids_rejected():
    def overlapping(endpoint, params):
        result = _reader(endpoint, params)
        if params["ofs"] == 50:
            field = {"TradesHistory": "trades", "ClosedOrders": "closed", "Ledgers": "ledger"}[endpoint]
            result["result"][field] = {"0": {"vol": "1"}}
        return result
    with pytest.raises(IncompleteHistory, match="duplicate"):
        collect_history(overlapping, account_scope="platform:kraken")


def test_existing_broker_wrapper_restricts_endpoints_and_category():
    class Broker:
        broker_type = "kraken"
        account_type = "platform"
        user_id = None

        def _kraken_private_call(self, endpoint, params, *, category):
            assert category == "monitoring"
            assert set(params) == {"ofs"}
            assert endpoint in {"TradesHistory", "ClosedOrders", "Ledgers"}
            field = {"TradesHistory": "trades", "ClosedOrders": "closed", "Ledgers": "ledger"}[endpoint]
            return {"error": [], "result": {"count": 0, field: {}}}
    report = collect_from_existing_broker(Broker(), account_scope="platform:kraken", monitoring_category="monitoring")
    assert report["trading_authorized"] is False
    assert report["ledger_links_verified"] is False


@pytest.mark.parametrize(("account_type", "user_id", "scope"), [
    ("user", "client", "platform:kraken"),
    ("platform", None, "user:client:kraken"),
    ("user", "client", "user:other:kraken"),
])
def test_existing_broker_rejects_cross_account_scope_before_read(account_type, user_id, scope):
    calls = []
    broker = SimpleNamespace(
        broker_type="kraken", account_type=account_type, user_id=user_id,
        _kraken_private_call=lambda *args, **kwargs: calls.append(args),
    )
    with pytest.raises(ValueError, match="does not match"):
        collect_from_existing_broker(broker, account_scope=scope, monitoring_category="monitoring")
    assert calls == []


@pytest.mark.parametrize("metadata", [
    {},
    {"broker_type": "okx", "account_type": "platform"},
    {"broker_type": "kraken"},
    {"broker_type": "kraken", "account_type": "platform"},
    {"broker_type": "kraken", "account_type": "unknown"},
    {"broker_type": "kraken", "account_type": "platform", "user_id": "client"},
    {"broker_type": "kraken", "account_type": "user", "user_id": None},
    {"broker_type": "kraken", "account_type": "user", "user_id": ""},
    {"broker_type": "kraken", "account_type": "user", "user_id": " client "},
    {"broker_type": "kraken", "account_type": "user", "user_id": "client:kraken"},
    {"broker_type": "kraken", "account_type": "user", "user_id": 123},
])
def test_existing_broker_rejects_ambiguous_metadata_before_read(metadata):
    calls = []
    broker = SimpleNamespace(**metadata, _kraken_private_call=lambda *args, **kwargs: calls.append(args))
    with pytest.raises(ValueError, match="metadata required"):
        collect_from_existing_broker(broker, account_scope="platform:kraken", monitoring_category="monitoring")
    assert calls == []


def test_existing_user_broker_accepts_exact_enum_routing_without_certifying_identity():
    class BrokerType(Enum):
        KRAKEN = "kraken"

    class AccountType(Enum):
        USER = "user"

    calls = []

    def read(endpoint, params, *, category):
        calls.append((endpoint, dict(params), category))
        field = dict(TradesHistory="trades", ClosedOrders="closed", Ledgers="ledger")[endpoint]
        return {"error": [], "result": {"count": 0, field: {}}}

    broker = SimpleNamespace(
        broker_type=BrokerType.KRAKEN, account_type=AccountType.USER, user_id="client",
        _kraken_private_call=read,
    )
    report = collect_from_existing_broker(
        broker, account_scope="user:client:kraken", monitoring_category="monitoring",
    )
    assert len(calls) == 6
    assert report["account_scope_asserted_by_caller"] == "user:client:kraken"
    assert report["authenticated_identity_independently_verified"] is False
    assert report["entry_exit_reconciliation_verified"] is False
    assert report["trading_authorized"] is False


@pytest.mark.parametrize("change_on_call", [1, 6])
def test_existing_broker_scope_change_during_read_aborts_report(change_on_call):
    calls = []
    broker = SimpleNamespace(broker_type="kraken", account_type="platform", user_id=None)

    def read(endpoint, params, *, category):
        calls.append(endpoint)
        if len(calls) == change_on_call:
            broker.account_type = "user"
            broker.user_id = "other"
        field = dict(TradesHistory="trades", ClosedOrders="closed", Ledgers="ledger")[endpoint]
        return {"error": [], "result": {"count": 0, field: {}}}

    broker._kraken_private_call = read
    with pytest.raises(ValueError, match="does not match"):
        collect_from_existing_broker(broker, account_scope="platform:kraken", monitoring_category="monitoring")
    assert len(calls) == change_on_call


def test_equal_counts_with_changed_record_content_fail_closed():
    page_zero_reads = 0

    def changing(endpoint, params):
        nonlocal page_zero_reads
        response = _reader(endpoint, params)
        if endpoint == "TradesHistory" and params["ofs"] == 0:
            page_zero_reads += 1
            if page_zero_reads == 2:
                response["result"]["trades"]["0"] = {"vol": "999"}
        return response

    with pytest.raises(IncompleteHistory, match="changed between verification passes"):
        collect_history(changing, account_scope="platform:kraken")


def test_equal_counts_with_replaced_identifier_fail_closed():
    page_zero_reads = 0

    def changing(endpoint, params):
        nonlocal page_zero_reads
        response = _reader(endpoint, params)
        if endpoint == "TradesHistory" and params["ofs"] == 0:
            page_zero_reads += 1
            if page_zero_reads == 2:
                response["result"]["trades"]["replacement"] = response["result"]["trades"].pop("0")
        return response

    with pytest.raises(IncompleteHistory, match="changed between verification passes"):
        collect_history(changing, account_scope="platform:kraken")


def test_account_scope_is_part_of_canonical_evidence_hash():
    platform = collect_history(_reader, account_scope="platform:kraken")
    user = collect_history(_reader, account_scope="user:owner:kraken")
    assert platform["history"] == user["history"]
    assert platform["evidence_sha256"] != user["evidence_sha256"]
    assert platform["repeat_read_consistent"] is True
    assert platform["atomic_broker_snapshot_verified"] is False
    assert platform["authenticated_identity_independently_verified"] is False


def test_no_broker_snapshot_claim_from_empty_history():
    def empty(endpoint, params):
        field = {"TradesHistory": "trades", "ClosedOrders": "closed", "Ledgers": "ledger"}[endpoint]
        return {"error": [], "result": {"count": 0, field: {}}}

    report = collect_history(empty, account_scope="platform:kraken")
    assert all(not rows for rows in report["history"].values())
    assert report["atomic_broker_snapshot_verified"] is False
    assert report["trading_authorized"] is False


def test_invalid_nonfinite_broker_row_fails_closed():
    def nonfinite(endpoint, params):
        response = _reader(endpoint, params)
        if endpoint == "TradesHistory" and params["ofs"] == 0:
            response["result"]["trades"]["0"]["vol"] = float("nan")
        return response

    with pytest.raises(IncompleteHistory, match="non-JSON"):
        collect_history(nonfinite, account_scope="platform:kraken")


def test_balance_brackets_history_and_is_hashed_without_authorizing():
    calls = []

    def read(endpoint, params):
        calls.append((endpoint, params))
        if endpoint == "Balance":
            assert params == {}
            return {"error": [], "result": {"BABY": "0.00142000"}}
        return _reader(endpoint, params)

    report = collect_history(read, account_scope="platform:kraken", include_balance=True)
    assert calls[0] == calls[-1] == ("Balance", {})
    assert report["balance"] == {"BABY": "0.00142000"}
    assert report["entry_exit_reconciliation_verified"] is False
    assert report["trading_authorized"] is False
    assert report["atomic_broker_snapshot_verified"] is False
    history_only = collect_history(_reader, account_scope="platform:kraken")
    assert report["evidence_sha256"] != history_only["evidence_sha256"]


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-0.001", "invalid", None])
def test_invalid_balance_fails_closed(value):
    def read(endpoint, params):
        if endpoint == "Balance":
            return {"error": [], "result": {"BABY": value}}
        return _reader(endpoint, params)

    with pytest.raises(IncompleteHistory, match="Balance: invalid"):
        collect_history(read, account_scope="platform:kraken", include_balance=True)


def test_changing_balance_fails_closed():
    balances = iter(["0.00142000", "0"])

    def read(endpoint, params):
        if endpoint == "Balance":
            return {"error": [], "result": {"BABY": next(balances)}}
        return _reader(endpoint, params)

    with pytest.raises(IncompleteHistory, match="balance changed"):
        collect_history(read, account_scope="platform:kraken", include_balance=True)


def test_existing_broker_balance_uses_same_monitoring_controls():
    calls = []

    def read(endpoint, params, *, category):
        assert category == "monitoring"
        calls.append(endpoint)
        if endpoint == "Balance":
            assert params == {}
            return {"error": [], "result": {"BABY": "0.00142000"}}
        return _reader(endpoint, params)

    broker = SimpleNamespace(
        broker_type="kraken", account_type="platform", user_id=None,
        _kraken_private_call=read,
    )
    report = collect_from_existing_broker(
        broker, account_scope="platform:kraken", monitoring_category="monitoring", include_balance=True,
    )
    assert calls[0] == calls[-1] == "Balance"
    assert report["balance"]["BABY"] == "0.00142000"
    assert report["authenticated_identity_independently_verified"] is False


def test_current_orders_paginate_repeat_and_preserve_observation_intervals(monkeypatch):
    from scripts import nija_kraken_readonly_history_collector_v441 as api
    import hashlib
    import json

    calls = []
    clock = iter([1000.0, 1001.0, 1002.0, 1003.0, 1004.0, 1005.0])
    monkeypatch.setattr(api.time, "time", lambda: next(clock))

    def read(endpoint, params):
        calls.append((endpoint, dict(params)))
        if endpoint != "OpenOrders":
            return _reader(endpoint, params)
        assert params["with_cursor"] is True and params["trades"] is True
        assert params["limit"] == 50
        if "cursor" not in params:
            return {"error": [], "result": {
                "open": {"stop": {"status": "open", "vol": "1", "descr": {"ordertype": "stop-loss"}}},
                "cursor": {"next": "page-two"},
            }}
        assert params["cursor"] == "page-two"
        return {"error": [], "result": {"open": {"other": {"status": "open"}}}}

    report = api.collect_history(read, account_scope="platform:kraken", include_open_orders=True)
    assert set(report["open_orders"]) == {"stop", "other"}
    assert report["open_orders_observations"] == [
        {"request_started_at": 1000.0, "response_finished_at": 1002.0},
        {"request_started_at": 1003.0, "response_finished_at": 1005.0},
    ]
    assert len([x for x in calls if x[0] == "OpenOrders"]) == 4
    assert report["protective_exit_coverage_verified"] is False
    assert report["trading_authorized"] is False
    envelope = {k: report[k] for k in (
        "account_scope_asserted_by_caller", "history", "open_orders", "open_orders_observations",
    )}
    assert report["evidence_sha256"] == hashlib.sha256(
        json.dumps(envelope, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


@pytest.mark.parametrize("scenario,reason", [
    ("permission", "API failure"), ("missing_error", "API failure"),
    ("malformed", "malformed result"), ("cursor", "invalid cursor"),
    ("repeat_cursor", "repeated cursor"), ("duplicate", "duplicate identifier"),
    ("empty_next", "incomplete empty page"), ("page_limit", "page limit"),
    ("oversized", "oversized page"), ("changed", "changed between"),
    ("nan", "non-JSON record"),
])
def test_open_order_incomplete_or_changing_readback_denies_report(scenario, reason):
    calls = 0

    def read(endpoint, params):
        nonlocal calls
        if endpoint != "OpenOrders":
            field = dict(TradesHistory="trades", ClosedOrders="closed", Ledgers="ledger")[endpoint]
            return {"error": [], "result": {"count": 0, field: {}}}
        calls += 1
        row = {"error": [], "result": {"open": {"stop": {"vol": "1"}}}}
        if scenario == "permission":
            row["error"] = ["private-upstream-canary"]
        elif scenario == "missing_error":
            del row["error"]
        elif scenario == "malformed":
            row["result"] = {}
        elif scenario == "cursor":
            row["result"]["cursor"] = {"next": False}
        elif scenario in {"repeat_cursor", "duplicate", "page_limit", "empty_next"}:
            row["result"]["cursor"] = {"next": "same"}
            if scenario == "repeat_cursor":
                row["result"]["open"] = {str(calls): {"vol": "1"}}
            elif scenario == "empty_next":
                row["result"]["open"] = {}
        elif scenario == "oversized":
            row["result"]["open"] = {str(i): {} for i in range(51)}
        elif scenario == "changed" and calls == 2:
            row["result"]["open"] = {}
        elif scenario == "nan":
            row["result"]["open"]["stop"]["vol"] = float("nan")
        return row

    with pytest.raises(IncompleteHistory, match=reason) as error:
        collect_history(read, account_scope="platform:kraken", include_open_orders=True,
                        max_pages=1 if scenario == "page_limit" else 2)
    assert "private-upstream-canary" not in str(error.value)


def test_open_order_scope_change_in_existing_broker_aborts():
    broker = SimpleNamespace(broker_type="kraken", account_type="platform", user_id=None)

    def read(endpoint, params, *, category):
        assert category == "monitoring"
        if endpoint == "OpenOrders":
            broker.user_id = "different"
            return {"error": [], "result": {"open": {}}}
        return _reader(endpoint, params)

    broker._kraken_private_call = read
    with pytest.raises(ValueError, match="metadata required"):
        collect_from_existing_broker(broker, account_scope="platform:kraken",
                                     monitoring_category="monitoring", include_open_orders=True)


@pytest.mark.parametrize("clock_values", [
    [100.0, 99.0], [100.0, float("nan")], [100.0, 101.0, 99.0, 102.0],
])
def test_open_order_clock_regression_cannot_refresh_evidence(monkeypatch, clock_values):
    from scripts import nija_kraken_readonly_history_collector_v441 as api
    clock = iter(clock_values)
    monkeypatch.setattr(api.time, "time", lambda: next(clock))

    def read(endpoint, params):
        if endpoint == "OpenOrders":
            return {"error": [], "result": {"open": {}}}
        return _reader(endpoint, params)

    with pytest.raises(IncompleteHistory, match="invalid observation clock"):
        collect_history(read, account_scope="platform:kraken", include_open_orders=True)


def test_v463_readonly_intake_reconciles_no_live_state(tmp_path):
    """Existing recovery CI also runs a real v441 -> v463 integration test."""
    import json
    import sqlite3
    import time

    from scripts.nija_kraken_history_ledger_intake_v463 import inspect_intake

    def read(endpoint, params):
        if endpoint == "Balance":
            return {"error": [], "result": {"ZUSD": "10"}}
        if endpoint == "OpenOrders":
            return {"error": [], "result": {"open": {}, "cursor": {"next": ""}}}
        field = {"TradesHistory": "trades", "ClosedOrders": "closed", "Ledgers": "ledger"}[endpoint]
        records = {
            "trades": {"T1": {"ordertxid": "C1", "vol": "0.01", "fee": "0.01"}},
            "closed": {"C1": {"status": "closed"}},
            "ledger": {"L1": {"refid": "T1"}},
        }
        return {"error": [], "result": {"count": 1, field: records[field]}}

    started = time.time()
    evidence = collect_history(
        read, account_scope="platform:kraken", include_balance=True, include_open_orders=True,
    )
    receipt = tmp_path / "receipt.json"
    row = {
        "request_id": "a" * 32, "collection_succeeded": True,
        "collection_started_at": started, "collection_finished_at": time.time(),
        "evidence": evidence, "trading_authorized": False,
    }
    receipt.write_text(json.dumps(row), encoding="utf-8")
    receipt.chmod(0o600)
    database = tmp_path / "ledger.db"
    with sqlite3.connect(database) as db:
        for name in ("trade_ledger", "open_positions", "completed_trades"):
            db.execute('CREATE TABLE "' + name + '" (id INTEGER PRIMARY KEY)')
        db.execute("CREATE TABLE pending_kraken_closes "
                   "(broker TEXT, account_scope TEXT, order_id TEXT, state TEXT)")
        db.execute("INSERT INTO pending_kraken_closes VALUES (?,?,?,?)",
                   ("kraken", "platform:kraken", "C1", "pending"))
    report = inspect_intake(receipt, database, "platform:kraken")
    assert report["status"] == "READ_ONLY_INTAKE_COMPLETE"
    assert report["both_order_and_trade_ids_present"] == 1
    assert report["pending_closes_still_unresolved"] == 1
    assert report["execution_ready"] is False
    assert report["execution_authority"] is False
    assert report["authorizes_orders"] is False
    row["evidence"]["history"]["closed"]["C1"]["status"] = "tampered"
    receipt.write_text(json.dumps(row), encoding="utf-8")
    receipt.chmod(0o600)
    invalid = inspect_intake(receipt, database, "platform:kraken")
    assert invalid["failure_code"] == "receipt_digest_mismatch"
    assert invalid["authorizes_orders"] is False
