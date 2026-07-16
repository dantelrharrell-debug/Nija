from bot.broker_health_exit_continuity_patch import install_import_hook
from bot.broker_failure_manager import BrokerFailureManager


def _manager():
    install_import_hook()
    return BrokerFailureManager(failure_threshold=2)


def test_transient_market_data_failures_do_not_mark_broker_dead():
    manager = _manager()
    manager.register_broker("kraken")

    assert manager.record_error("kraken", "OHLC market data timeout") is False
    assert manager.record_error("kraken", "volume data timeout") is False
    assert manager.is_dead("kraken") is False


def test_successful_private_read_revives_nonterminal_dead_state():
    manager = _manager()
    manager.register_broker("kraken")

    # Simulate stale state left by an older runtime generation.
    state = manager._states["kraken"]
    state.is_dead = True
    state.last_error_reason = "network timeout"
    state.consecutive_errors = 6

    assert manager.is_dead("kraken") is False
    assert manager.record_success("kraken") is True
    assert manager.is_dead("kraken") is False


def test_terminal_authentication_failures_still_fail_closed():
    manager = _manager()
    manager.register_broker("kraken")

    assert manager.record_error("kraken", "authentication failed: invalid API key") is False
    assert manager.record_error("kraken", "authentication failed: invalid API key") is True
    assert manager.is_dead("kraken") is True
