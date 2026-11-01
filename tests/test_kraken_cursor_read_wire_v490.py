"""Offline parameter normalization tests; no exchange credentials, sockets or orders."""
from types import SimpleNamespace

import pytest

from bot.kraken_cursor_read_wire_v490 import cursor_read_params
from scripts.nija_kraken_readonly_history_collector_v441 import collect_from_existing_broker


@pytest.mark.parametrize("endpoint", ["TradesHistory", "ClosedOrders", "Ledgers", "OpenOrders"])
def test_direct_cursor_read_has_lowercase_form_fields(endpoint):
    direct = SimpleNamespace(_gateway_url="", _gateway_only_mode=False)
    original = {"with_cursor": True, "cursor": "opaque"}
    if endpoint == "OpenOrders":
        original["trades"] = True
        original["limit"] = 50
    result = cursor_read_params(direct, endpoint, original)
    assert original["with_cursor"] is True
    assert result["with_cursor"] == "true"
    assert result["cursor"] == "opaque"
    if endpoint == "OpenOrders":
        assert result["trades"] == "true"


@pytest.mark.parametrize("mode", [
    SimpleNamespace(_gateway_url="https://gateway.example", _gateway_only_mode=True),
    SimpleNamespace(_gateway_url="https://gateway.example", _gateway_only_mode=False),
    SimpleNamespace(_gateway_url=None, _gateway_only_mode=False),
    SimpleNamespace(_gateway_url="", _gateway_only_mode=True),
    SimpleNamespace(),
])
def test_gateway_or_unknown_broker_keeps_original_json_boolean_types(mode):
    params = {"with_cursor": True, "trades": True, "limit": 50}
    result = cursor_read_params(mode, "OpenOrders", params)
    assert result == params
    assert result is not params
    assert result["with_cursor"] is True
    assert result["trades"] is True


@pytest.mark.parametrize("endpoint", ["AddOrder", "CancelOrder", "Balance"])
def test_mutating_and_non_cursor_reads_are_never_transformed(endpoint):
    direct = SimpleNamespace(_gateway_url="", _gateway_only_mode=False)
    params = {"with_cursor": True, "trades": True, "nonce": 7}
    assert cursor_read_params(direct, endpoint, params) == params
    assert cursor_read_params(direct, "TradesHistory", {"ofs": 50}) == {"ofs": 50}


def test_existing_authenticated_direct_history_reader_keeps_nonce_and_pagination_state():
    calls = []

    def read(endpoint, params, *, category):
        assert category == "monitoring"
        assert params["with_cursor"] == "true"
        assert "nonce" not in params
        calls.append((endpoint, dict(params)))
        if endpoint == "OpenOrders":
            assert params["trades"] == "true"
            return {"error": [], "result": {"open": {}, "cursor": {}}}
        return {"error": [], "result": {
            {"TradesHistory": "trades", "ClosedOrders": "closed", "Ledgers": "ledger"}[endpoint]: {},
            "cursor": {},
        }}

    direct = SimpleNamespace(
        broker_type="kraken", account_type="platform", user_id=None,
        _gateway_url="", _gateway_only_mode=False, _kraken_private_call=read,
    )
    evidence = collect_from_existing_broker(
        direct, account_scope="platform:kraken", monitoring_category="monitoring",
        max_pages=2, use_cursor=True, include_open_orders=True,
    )
    assert len(calls) == 8
    assert evidence["trading_authorized"] is False
    assert evidence["authenticated_identity_independently_verified"] is False
    assert evidence["protective_exit_coverage_verified"] is False


@pytest.mark.parametrize("mode, expected_cursor, expected_trades", [
    (SimpleNamespace(_gateway_url="", _gateway_only_mode=False), "true", "true"),
    (SimpleNamespace(_gateway_url="https://gateway.example", _gateway_only_mode=True), True, True),
])
def test_openorders_documented_cursor_contract_preserves_nonce_ownership(mode, expected_cursor, expected_trades):
    """Official OpenOrders supports with_cursor, limit, trades and cursor.

    Regression for the production invalid_arguments receipt: keep the supported
    parameters and verify transport-specific wire types. This is offline only.
    """
    original = {"with_cursor": True, "limit": 50, "trades": True, "cursor": "opaque"}
    result = cursor_read_params(mode, "OpenOrders", original)
    assert result == {"with_cursor": expected_cursor, "limit": 50,
                      "trades": expected_trades, "cursor": "opaque"}
    assert original == {"with_cursor": True, "limit": 50,
                        "trades": True, "cursor": "opaque"}
    assert "nonce" not in result


def test_openorders_invalid_arguments_does_not_retry_or_fallback_to_another_mode():
    """A rejected authenticated OpenOrders read cannot certify a partial snapshot."""
    from scripts.nija_kraken_readonly_history_collector_v441 import IncompleteHistory, collect_history

    calls = []

    def read(endpoint, params):
        calls.append((endpoint, dict(params)))
        if endpoint == "OpenOrders":
            return {"error": ["EGeneral:Invalid arguments"], "result": {}}
        field = {"TradesHistory": "trades", "ClosedOrders": "closed", "Ledgers": "ledger"}[endpoint]
        return {"error": [], "result": {field: {}, "cursor": {}}}

    with pytest.raises(IncompleteHistory):
        collect_history(read, account_scope="platform:kraken",
                        include_open_orders=True, use_cursor=True, max_pages=2)
    open_calls = [(endpoint, params) for endpoint, params in calls if endpoint == "OpenOrders"]
    assert len(open_calls) == 1
    assert open_calls[0][1] == {"with_cursor": True, "limit": 50, "trades": True}
    assert not any("ofs" in params for _, params in calls)
