from __future__ import annotations

import bot.broker_manager as broker_manager


def test_local_kraken_read_contention_does_not_mutate_health():
    broker = broker_manager.KrakenBroker.__new__(broker_manager.KrakenBroker)
    broker.api = object()
    broker._gateway_url = ""
    broker._last_known_balance = 154.49
    broker._balance_last_updated = None
    broker._kraken_balance_cache_ttl = 0.0
    broker.balance_cache = {"kraken": 154.49}
    broker._balance_fetch_errors = 44
    broker._is_available = True
    broker.exit_only_mode = False
    broker.kraken_health = "OK"
    broker.account_identifier = "PLATFORM"

    def busy(*_args, **_kwargs):
        raise RuntimeError("Kraken read lock busy (local_read_lock_timeout)")

    broker._kraken_private_call = busy

    assert broker_manager.KrakenBroker.get_account_balance(broker, verbose=False) == 154.49
    assert broker._balance_fetch_errors == 44
    assert broker._is_available is True
    assert broker.exit_only_mode is False
    assert broker.kraken_health == "OK"


def test_local_kraken_read_contention_without_cache_returns_zero_without_health_mutation():
    broker = broker_manager.KrakenBroker.__new__(broker_manager.KrakenBroker)
    broker.api = object()
    broker._gateway_url = ""
    broker._last_known_balance = None
    broker._balance_last_updated = None
    broker._kraken_balance_cache_ttl = 0.0
    broker.balance_cache = {}
    broker._balance_fetch_errors = 2
    broker._is_available = True
    broker.exit_only_mode = False
    broker.kraken_health = "OK"
    broker.account_identifier = "PLATFORM"
    broker._kraken_private_call = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RuntimeError("KrakenReadLockBusy")
    )

    assert broker_manager.KrakenBroker.get_account_balance(broker, verbose=False) == 0.0
    assert broker._balance_fetch_errors == 2
    assert broker._is_available is True
    assert broker.exit_only_mode is False
    assert broker.kraken_health == "OK"
