import importlib
from types import SimpleNamespace


broker_manager = importlib.import_module("bot.broker_manager")


def test_user_kraken_balance_cannot_feed_platform_capital(monkeypatch):
    calls = []
    monkeypatch.setattr(
        broker_manager,
        "_feed_capital_authority",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    broker = SimpleNamespace(
        account_type=broker_manager.AccountType.USER,
        account_identifier="USER:test",
    )

    fed = broker_manager._feed_kraken_platform_capital_authority(broker, 106.35)

    assert fed is False
    assert calls == []


def test_platform_kraken_balance_feeds_platform_capital(monkeypatch):
    calls = []
    monkeypatch.setattr(
        broker_manager,
        "_feed_capital_authority",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    broker = SimpleNamespace(
        account_type=broker_manager.AccountType.PLATFORM,
        account_identifier="PLATFORM",
    )

    fed = broker_manager._feed_kraken_platform_capital_authority(broker, 300.25)

    assert fed is True
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[0] == "kraken"
    assert args[1] == 300.25
    assert kwargs.get("timestamp") is None
