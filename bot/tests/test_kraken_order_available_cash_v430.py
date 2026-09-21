import time

from bot.broker_manager import KrakenBroker


def _broker() -> KrakenBroker:
    broker = KrakenBroker.__new__(KrakenBroker)
    broker.account_identifier = "PLATFORM"
    broker._kraken_balance_cache_ttl = 55
    broker._last_known_available_cash = None
    broker._available_cash_last_updated = None
    return broker


def test_authenticated_available_cash_records_zero_and_positive_values():
    broker = _broker()
    assert broker._record_authenticated_available_cash(0.0, 0.0) == 0.0
    cached = broker._fresh_authenticated_available_cash()
    assert cached is not None
    assert cached[0] == 0.0

    assert broker._record_authenticated_available_cash(25.5, 4.5) == 30.0
    cached = broker._fresh_authenticated_available_cash()
    assert cached is not None
    assert cached[0] == 30.0
    assert cached[1] >= 0.0


def test_order_balance_snapshot_reuses_fresh_authenticated_cash_without_broker_io():
    broker = _broker()
    broker._last_known_available_cash = 63.17
    broker._available_cash_last_updated = time.time() - 2.0

    called = {"detailed": 0}

    def detailed():
        called["detailed"] += 1
        raise AssertionError("fresh authenticated cash must avoid redundant private Balance/TradeBalance calls")

    broker.get_account_balance_detailed = detailed
    result = broker._get_order_balance_snapshot()

    assert result["error"] is False
    assert result["trading_balance"] == 63.17
    assert result["source"] == "authenticated_available_cash_cache_v430"
    assert called["detailed"] == 0


def test_order_balance_snapshot_falls_back_when_authenticated_cash_is_stale():
    broker = _broker()
    broker._last_known_available_cash = 63.17
    broker._available_cash_last_updated = time.time() - 56.0
    expected = {"trading_balance": 61.0, "error": False, "crypto": {"ETH": 0.01}}
    broker.get_account_balance_detailed = lambda: expected

    assert broker._fresh_authenticated_available_cash() is None
    assert broker._get_order_balance_snapshot() is expected


def test_order_balance_snapshot_never_uses_total_equity_cache_as_spendable_cash():
    broker = _broker()
    broker._last_known_balance = 999.0
    broker.balance_cache = {"kraken": 999.0}
    expected = {"trading_balance": 0.0, "error": False}
    broker.get_account_balance_detailed = lambda: expected

    assert broker._fresh_authenticated_available_cash() is None
    assert broker._get_order_balance_snapshot() is expected
