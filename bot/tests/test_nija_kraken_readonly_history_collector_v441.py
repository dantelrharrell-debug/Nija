"""Fail-closed tests for read-only, account-scoped Kraken evidence pagination."""
import pytest

from scripts.nija_kraken_readonly_history_collector_v441 import (
    IncompleteHistory, collect_history,
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
    from scripts.nija_kraken_readonly_history_collector_v441 import collect_from_existing_broker
    class Broker:
        def _kraken_private_call(self, endpoint, params, *, category):
            assert category == "monitoring"
            assert set(params) == {"ofs"}
            assert endpoint in {"TradesHistory", "ClosedOrders", "Ledgers"}
            field = {"TradesHistory": "trades", "ClosedOrders": "closed", "Ledgers": "ledger"}[endpoint]
            return {"error": [], "result": {"count": 0, field: {}}}
    report = collect_from_existing_broker(Broker(), account_scope="platform:kraken", monitoring_category="monitoring")
    assert report["trading_authorized"] is False
    assert report["ledger_links_verified"] is False


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
