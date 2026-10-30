"""Offline cursor recovery tests; these do not certify a brokerage account."""
import json
from types import SimpleNamespace

import pytest

from bot.kraken_live_history_recovery import collect_requested_history
from scripts.nija_kraken_readonly_history_collector_v441 import (
    IncompleteHistory, collect_from_existing_broker, collect_history,
)

FIELDS = {"TradesHistory": "trades", "ClosedOrders": "closed", "Ledgers": "ledger"}


def page(endpoint, params):
    final = "cursor" in params
    return {"error": [], "result": {
        FIELDS[endpoint]: {"second" if final else "first": {"fee": "1"}},
        "count": None if endpoint == "Ledgers" else 0,
        "cursor": {} if final else {"next": "opaque-token"},
    }}


def test_cursor_exhaustion_ignores_placeholder_counts_and_keeps_nonce_owner():
    calls = []

    def read(endpoint, params, *, category):
        assert category == "monitoring"
        assert "nonce" not in params and "ofs" not in params
        calls.append((endpoint, dict(params)))
        result = page(endpoint, params)
        params["nonce"] = len(calls)  # Real transport mutates its argument.
        return result

    broker = SimpleNamespace(broker_type="kraken", account_type="platform", user_id=None,
                             _kraken_private_call=read)
    report = collect_from_existing_broker(
        broker, account_scope="platform:kraken", monitoring_category="monitoring",
        use_cursor=True, max_pages=2,
    )
    assert len(calls) == 12
    assert all(set(rows) == {"first", "second"} for rows in report["history"].values())
    assert report["history_pagination"] == "cursor"
    assert report["trading_authorized"] is False
    assert report["authenticated_identity_independently_verified"] is False
    assert report["atomic_broker_snapshot_verified"] is False


@pytest.mark.parametrize("case", [
    "missing_cursor", "wrong_cursor", "whitespace", "repeated", "duplicate",
    "empty_nonterminal", "oversized", "api_error", "non_json", "changed_pass",
])
def test_cursor_failures_never_return_partial_evidence(case):
    calls = 0

    def read(endpoint, params):
        nonlocal calls
        calls += 1
        result = page(endpoint, params)
        row = result["result"]
        if case == "missing_cursor":
            del row["cursor"]
        elif case == "wrong_cursor":
            row["cursor"] = []
        elif case == "whitespace":
            row["cursor"] = {"next": " "}
        elif case == "repeated":
            row["cursor"] = {"next": "opaque-token"}
        elif case == "duplicate":
            row[FIELDS[endpoint]] = {"first": {}}
        elif case == "empty_nonterminal":
            row[FIELDS[endpoint]] = {}
        elif case == "oversized":
            row[FIELDS[endpoint]] = {str(i): {} for i in range(51)}
        elif case == "api_error":
            result["error"] = ["upstream private text"]
        elif case == "non_json":
            row[FIELDS[endpoint]] = {"first": {"fee": float("nan")}}
        elif case == "changed_pass" and calls > 6:
            row[FIELDS[endpoint]] = {"changed": {}}
        return result

    with pytest.raises(IncompleteHistory) as exc:
        collect_history(read, account_scope="platform:kraken", use_cursor=True, max_pages=2)
    assert "upstream private text" not in str(exc.value)


def test_cursor_budget_never_falls_back_to_offset():
    calls = []

    def read(endpoint, params):
        calls.append(params)
        return page(endpoint, params)

    with pytest.raises(IncompleteHistory, match="page limit"):
        collect_history(read, account_scope="platform:kraken", use_cursor=True, max_pages=1)
    assert calls == [{"with_cursor": True}]


@pytest.mark.parametrize("cursor", [True, False, "true", 1])
def test_private_request_selects_cursor_explicitly_without_replay(tmp_path, cursor):
    tmp_path.chmod(0o700)
    identity = "b" * 32
    request = tmp_path / "request.json"
    request.write_text(json.dumps(dict(request_id=identity, account_scope="platform:kraken",
                                       created_at=1000, max_pages=2, use_cursor=cursor)))
    request.chmod(0o600)
    calls = []

    def read(endpoint, params, *, category):
        calls.append((endpoint, dict(params)))
        if endpoint == "Balance":
            return {"error": [], "result": {"ZUSD": "100"}}
        if endpoint == "OpenOrders":
            return {"error": [], "result": {"open": {}}}
        if cursor is True:
            return page(endpoint, params)
        assert set(params) == {"ofs"}
        return {"error": [], "result": {FIELDS[endpoint]: {}, "count": 0}}

    broker = SimpleNamespace(broker_type="kraken", account_type="platform", user_id=None,
                             connected=True, _kraken_private_call=read)
    if type(cursor) is not bool:
        with pytest.raises(ValueError, match="cursor_invalid"):
            collect_requested_history(tmp_path, [broker], monitoring_category="monitoring", now=1000)
        assert not calls
        return
    assert collect_requested_history(tmp_path, [broker], monitoring_category="monitoring", now=1000)
    report = json.loads((tmp_path / (identity + ".evidence.json")).read_text())
    assert report["collection_succeeded"] is True
    assert report["trading_authorized"] is False
    assert not collect_requested_history(tmp_path, [broker], monitoring_category="monitoring", now=1000)


def test_open_orders_rejects_unknown_cursor_fields_instead_of_claiming_completion():
    """An unrecognized cursor object cannot silently certify an incomplete order set."""
    calls = []

    def read(endpoint, params):
        calls.append((endpoint, dict(params)))
        if endpoint == "OpenOrders":
            return {"error": [], "result": {
                "open": {"open-order-a": {"vol": "1"}},
                "cursor": {"previous": "opaque-but-not-next"},
            }}
        field = FIELDS[endpoint]
        return {"error": [], "result": {field: {}, "count": 0}}

    with pytest.raises(IncompleteHistory, match="OpenOrders: invalid cursor"):
        collect_history(read, account_scope="platform:kraken",
                        include_open_orders=True, max_pages=2)
    assert [ep for ep, _ in calls].count("OpenOrders") == 1


def test_direct_open_order_reader_isolates_transport_nonce_between_cursor_pages():
    """The raw reader may mutate its input exactly as krakenex does."""
    calls = []

    def read(endpoint, params):
        assert "nonce" not in params
        calls.append((endpoint, dict(params)))
        if endpoint != "OpenOrders":
            field = FIELDS[endpoint]
            return {"error": [], "result": {field: {}, "count": 0}}
        page_two = "cursor" in params
        params["nonce"] = len(calls)
        if not page_two:
            return {"error": [], "result": {
                "open": {"order-a": {"vol": "1"}},
                "cursor": {"next": "page-two"},
            }}
        assert params["cursor"] == "page-two"
        return {"error": [], "result": {
            "open": {"order-b": {"vol": "2"}},
            "cursor": {},
        }}

    evidence = collect_history(read, account_scope="platform:kraken",
                               include_open_orders=True, max_pages=2)
    assert set(evidence["open_orders"]) == {"order-a", "order-b"}
    assert [ep for ep, _ in calls].count("OpenOrders") == 4
    assert evidence["trading_authorized"] is False
    assert evidence["protective_exit_coverage_verified"] is False
