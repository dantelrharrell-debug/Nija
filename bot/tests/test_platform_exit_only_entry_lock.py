from types import SimpleNamespace

import bot.independent_broker_trader as module


def test_platform_entry_lock_sets_exit_only_and_preserves_connection(monkeypatch):
    monkeypatch.setattr(module, "NIJA_PLATFORM_TRADING_ENABLED", False)
    broker = SimpleNamespace(connected=True, exit_only_mode=False, mode="LIVE")

    enforced = module.IndependentBrokerTrader._enforce_platform_entry_lock(
        broker, "kraken"
    )

    assert enforced is True
    assert broker.connected is True
    assert broker.exit_only_mode is True
    assert broker.mode == "PASSIVE"


def test_platform_entry_lock_does_not_mutate_when_enabled(monkeypatch):
    monkeypatch.setattr(module, "NIJA_PLATFORM_TRADING_ENABLED", True)
    broker = SimpleNamespace(connected=True, exit_only_mode=False, mode="LIVE")

    enforced = module.IndependentBrokerTrader._enforce_platform_entry_lock(
        broker, "kraken"
    )

    assert enforced is False
    assert broker.exit_only_mode is False
    assert broker.mode == "LIVE"
