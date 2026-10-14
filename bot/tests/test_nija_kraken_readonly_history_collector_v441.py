"""Fail-closed tests for read-only, account-scoped Kraken evidence pagination."""
import pytest

from scripts.nija_kraken_readonly_history_collector_v441 import (
    IncompleteHistory, collect_history,
)


def _reader(endpoint, params):
    field = {"TradesHistory": "trades", "ClosedOrders": "closed"}[endpoint]
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
    assert len(calls) == 4
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
            field = "trades" if endpoint == "TradesHistory" else "closed"
            result["result"][field] = {"0": {"vol": "1"}}
        return result
    with pytest.raises(IncompleteHistory, match="duplicate"):
        collect_history(overlapping, account_scope="platform:kraken")
