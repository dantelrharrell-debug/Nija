"""Read-only regression: retain individual fill identifiers for reconciliation."""
from types import SimpleNamespace

import pytest

from bot.kraken_cursor_read_wire_v490 import cursor_read_params
from scripts.nija_kraken_readonly_history_collector_v441 import (
    IncompleteHistory, collect_from_existing_broker, collect_history,
)


@pytest.mark.parametrize('cursor', [False, True])
def test_history_explicitly_requests_individual_fills_in_both_verification_passes(cursor):
    calls = []

    def read(endpoint, params):
        calls.append((endpoint, dict(params)))
        field = {'TradesHistory': 'trades', 'ClosedOrders': 'closed', 'Ledgers': 'ledger'}[endpoint]
        rows = {}
        if endpoint == 'TradesHistory':
            # A default-consolidated response can conceal individual execution IDs.
            # This fixture models only the documented choice, not real account data.
            rows = {'fill-a': {'ordertxid': 'order-1', 'time': 1000},
                    'fill-b': {'ordertxid': 'order-1', 'time': 1001}} if params.get('consolidate_taker') is False else {
                        'combined': {'ordertxid': 'order-1', 'time': 1001}}
        return {'error': [], 'result': {field: rows, 'count': len(rows), 'cursor': {}}}

    result = collect_history(read, account_scope='platform:kraken', use_cursor=cursor)
    assert set(result['history']['trades']) == {'fill-a', 'fill-b'}
    trade_calls = [params for endpoint, params in calls if endpoint == 'TradesHistory']
    assert len(trade_calls) == 2
    assert all(params['consolidate_taker'] is False for params in trade_calls)
    assert all('consolidate_taker' not in params for endpoint, params in calls
               if endpoint not in {'TradesHistory', 'ClosedOrders'})
    assert result['history']['trades']['fill-a']['time'] == 1000
    assert result['trading_authorized'] is False
    assert result['entry_exit_reconciliation_verified'] is False


@pytest.mark.parametrize('cursor', [False, True])
@pytest.mark.parametrize('direct', [False, True])
def test_existing_nonce_owner_gets_transport_specific_flags_without_extra_calls(cursor, direct):
    calls = []

    def read(endpoint, params, *, category):
        assert category == 'monitoring'
        assert 'nonce' not in params
        calls.append((endpoint, dict(params)))
        if endpoint in {'TradesHistory', 'ClosedOrders'}:
            assert params['consolidate_taker'] == ('false' if direct else False)
        else:
            assert 'consolidate_taker' not in params
        # Model nonce mutation at the existing signing boundary.
        params['nonce'] = len(calls)
        field = {'TradesHistory': 'trades', 'ClosedOrders': 'closed', 'Ledgers': 'ledger'}[endpoint]
        return {'error': [], 'result': {field: {}, 'count': 0, 'cursor': {}}}

    broker = SimpleNamespace(
        broker_type='kraken', account_type='platform', user_id=None,
        _gateway_url='' if direct else 'https://gateway.example', _gateway_only_mode=not direct,
        _kraken_private_call=read,
    )
    report = collect_from_existing_broker(broker, account_scope='platform:kraken',
        monitoring_category='monitoring', use_cursor=cursor)
    assert len(calls) == 6
    assert report['trading_authorized'] is False
    assert report['authenticated_identity_independently_verified'] is False


def test_only_history_flags_are_serialized_without_mutating_input():
    direct = SimpleNamespace(_gateway_url='', _gateway_only_mode=False)
    params = {'ofs': 0, 'consolidate_taker': False}
    assert cursor_read_params(direct, 'TradesHistory', params) == {'ofs': 0, 'consolidate_taker': 'false'}
    assert params['consolidate_taker'] is False
    assert cursor_read_params(direct, 'ClosedOrders', params) == {'ofs': 0, 'consolidate_taker': 'false'}
    for endpoint in ['AddOrder', 'CancelOrder', 'Ledgers']:
        assert cursor_read_params(direct, endpoint, params) == params


def test_no_automatic_retry_when_unconsolidated_history_is_rejected():
    calls = []
    def rejected(endpoint, params):
        calls.append(endpoint)
        return {'error': ['EGeneral:Invalid arguments']}
    with pytest.raises(IncompleteHistory):
        collect_history(rejected, account_scope='platform:kraken')
    assert calls == ['TradesHistory']


@pytest.mark.parametrize("cursor", [False, True])
def test_individual_fill_flag_is_preserved_on_subsequent_pages(cursor):
    trade_calls = []
    def read(endpoint, params):
        field = {"TradesHistory": "trades", "ClosedOrders": "closed", "Ledgers": "ledger"}[endpoint]
        if endpoint != "TradesHistory":
            return {"error": [], "result": {field: {}, "count": 0, "cursor": {}}}
        trade_calls.append(dict(params))
        assert params["consolidate_taker"] is False
        second = "cursor" in params if cursor else params["ofs"] > 0
        rows = {"fill-" + str(i): {"time": 1000 + i} for i in (range(50, 51) if second else range(50))}
        return {"error": [], "result": {field: rows, "count": 51,
            "cursor": {"next": None if second else "opaque-next"}}}
    evidence = collect_history(read, account_scope="platform:kraken", use_cursor=cursor, max_pages=2)
    assert len(evidence["history"]["trades"]) == 51
    assert len(trade_calls) == 4
    assert evidence["trading_authorized"] is False


@pytest.mark.parametrize("cursor", [False, True])
@pytest.mark.parametrize("direct", [False, True])
def test_closed_orders_preserve_individual_fill_links_on_every_page_and_pass(cursor, direct):
    """Model documented defaults that omit or consolidate closed-order fill IDs."""
    calls = []

    def read(endpoint, params, *, category):
        assert category == "monitoring"
        assert "nonce" not in params
        saved = dict(params)
        calls.append((endpoint, saved))
        params["nonce"] = len(calls)
        field = {"TradesHistory": "trades", "ClosedOrders": "closed", "Ledgers": "ledger"}[endpoint]
        second = "cursor" in saved if cursor else saved["ofs"] > 0
        rows = {}
        count = 0
        more = False
        if endpoint == "TradesHistory":
            rows = {name: {"ordertxid": "order-0", "time": 1000+i}
                    for i, name in enumerate(("fill-a", "fill-b"))}
            count = 2
        elif endpoint == "ClosedOrders":
            rows = {"order-"+str(i): {"status": "closed"}
                    for i in (range(50, 51) if second else range(50))}
            count, more = 51, not second
            if not second and saved.get("trades") in (True, "true"):
                rows["order-0"]["trades"] = (
                    ["fill-a", "fill-b"] if saved.get("consolidate_taker") in (False, "false")
                    else ["combined-taker-fill"]
                )
        return {"error": [], "result": {
            field: rows, "count": count,
            "cursor": {"next": "opaque-next" if more else None},
        }}

    broker = SimpleNamespace(
        broker_type="kraken", account_type="platform", user_id=None,
        _gateway_url="" if direct else "https://gateway.example",
        _gateway_only_mode=not direct, _kraken_private_call=read,
    )
    evidence = collect_from_existing_broker(
        broker, account_scope="platform:kraken", monitoring_category="monitoring",
        use_cursor=cursor, max_pages=2,
    )
    assert evidence["history"]["closed"]["order-0"]["trades"] == ["fill-a", "fill-b"]
    assert set(evidence["history"]["trades"]) == {"fill-a", "fill-b"}
    closed = [params for endpoint, params in calls if endpoint == "ClosedOrders"]
    assert len(closed) == 4
    assert sum(("cursor" not in p if cursor else p["ofs"] == 0) for p in closed) == 2
    for params in closed:
        if direct:
            assert params["trades"] == "true"
            assert params["consolidate_taker"] == "false"
        else:
            assert params["trades"] is True
            assert params["consolidate_taker"] is False
    assert all("consolidate_taker" not in p and "trades" not in p
               for endpoint, p in calls if endpoint == "Ledgers")
    assert len(calls) == 8
    assert evidence["trading_authorized"] is False
    assert evidence["entry_exit_reconciliation_verified"] is False


@pytest.mark.parametrize("cursor", [False, True])
@pytest.mark.parametrize("field,value", [
    ("trades", False), ("trades", 1), ("trades", "true"), ("trades", None),
    ("consolidate_taker", True), ("consolidate_taker", 0),
    ("consolidate_taker", "false"), ("consolidate_taker", None),
    ("userref", "unreviewed-filter"), ("nonce", 1),
])
def test_closed_order_boundary_rejects_wrong_flags_filters_and_caller_nonces(cursor, field, value, monkeypatch):
    from unittest.mock import Mock
    from scripts import nija_kraken_readonly_history_collector_v441 as collector

    params = {"with_cursor": True} if cursor else {"ofs": 0}
    params.update(trades=True, consolidate_taker=False)
    if value is None:
        del params[field]
    else:
        params[field] = value
    transport = Mock(side_effect=AssertionError("must not reach the broker"))
    broker = SimpleNamespace(
        broker_type="kraken", account_type="platform", user_id=None,
        _kraken_private_call=transport,
    )
    monkeypatch.setattr(collector, "collect_history", lambda read, **kwargs: read("ClosedOrders", params))
    with pytest.raises(ValueError, match="Non-read-only request rejected"):
        collector.collect_from_existing_broker(
            broker, account_scope="platform:kraken", monitoring_category="monitoring", use_cursor=cursor,
        )
    transport.assert_not_called()


@pytest.mark.parametrize("cursor", [False, True])
def test_rejected_closed_order_flags_never_retry_or_fall_back(cursor):
    calls = []
    def read(endpoint, params):
        calls.append(endpoint)
        if endpoint == "TradesHistory":
            return {"error": [], "result": {"trades": {}, "count": 0, "cursor": {}}}
        assert endpoint == "ClosedOrders"
        assert params["trades"] is True and params["consolidate_taker"] is False
        return {"error": ["EGeneral:Invalid arguments"]}
    with pytest.raises(IncompleteHistory):
        collect_history(read, account_scope="platform:kraken", use_cursor=cursor)
    assert calls == ["TradesHistory", "ClosedOrders"]
