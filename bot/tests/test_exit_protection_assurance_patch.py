import importlib
import os


def test_short_trailing_profit_is_symmetric(monkeypatch):
    monkeypatch.setenv("NIJA_PROFIT_LOCK_ACTIVATION_PCT", "0.008")
    monkeypatch.setenv("NIJA_PROFIT_LOCK_CALLBACK_PCT", "0.0035")

    auto_exit = importlib.import_module("bot.auto_exit_sl_tp_runtime_patch")
    assurance = importlib.import_module("exit_protection_assurance_patch")
    assert assurance._patch(auto_exit)

    position = {
        "position_id": "short-1",
        "account_id": "platform",
        "symbol": "BTC-USD",
        "side": "short",
        "entry_price": 100.0,
        "quantity": 1.0,
    }

    assert auto_exit._trigger(position, 98.0)[0] is False
    hit, reason, trigger = auto_exit._trigger(position, 98.5)
    assert hit is True
    assert reason == "profit_lock_trailing_exit"
    assert trigger > 98.0


def test_protection_defaults_are_enabled(monkeypatch):
    for key in (
        "NIJA_AUTO_EXIT_SL_TP_ENABLED",
        "NIJA_PROFIT_TAKE_ENABLED",
        "NIJA_TRAILING_TP_ENABLED",
        "NIJA_TRAILING_STOP_ENABLED",
        "NIJA_COMBINED_TRAILING_TP_SL_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)

    assurance = importlib.import_module("exit_protection_assurance_patch")
    assurance._configure()

    assert os.environ["NIJA_AUTO_EXIT_SL_TP_ENABLED"] == "true"
    assert os.environ["NIJA_PROFIT_TAKE_ENABLED"] == "true"
    assert os.environ["NIJA_TRAILING_TP_ENABLED"] == "true"
    assert os.environ["NIJA_TRAILING_STOP_ENABLED"] == "true"
    assert os.environ["NIJA_COMBINED_TRAILING_TP_SL_ENABLED"] == "true"
