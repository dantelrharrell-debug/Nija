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
    assert all('consolidate_taker' not in params for endpoint, params in calls if endpoint != 'TradesHistory')
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
        if endpoint == 'TradesHistory':
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
    for endpoint in ['AddOrder', 'CancelOrder', 'ClosedOrders', 'Ledgers']:
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
