import importlib
import os


def _reset_auto_state(auto_exit):
    auto_exit._HIGH_WATER.clear()


def test_short_trailing_profit_is_symmetric(monkeypatch):
    monkeypatch.setenv("NIJA_PROFIT_TAKE_ENABLED", "false")
    monkeypatch.setenv("NIJA_TRAILING_TP_ENABLED", "true")
    monkeypatch.setenv("NIJA_TRAILING_STOP_ENABLED", "false")
    monkeypatch.setenv("NIJA_TRAILING_TP_ACTIVATION_PCT", "0.008")
    monkeypatch.setenv("NIJA_TRAILING_TP_CALLBACK_PCT", "0.0035")

    auto_exit = importlib.import_module("bot.auto_exit_sl_tp_runtime_patch")
    assurance = importlib.import_module("exit_protection_assurance_patch")
    assert assurance._patch(auto_exit)
    _reset_auto_state(auto_exit)

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


def test_long_trailing_stop_loss_is_present(monkeypatch):
    monkeypatch.setenv("NIJA_PROFIT_TAKE_ENABLED", "false")
    monkeypatch.setenv("NIJA_TRAILING_TP_ENABLED", "false")
    monkeypatch.setenv("NIJA_TRAILING_STOP_ENABLED", "true")
    monkeypatch.setenv("NIJA_TRAILING_STOP_ACTIVATION_PCT", "0.008")
    monkeypatch.setenv("NIJA_TRAILING_STOP_PCT", "0.0035")

    auto_exit = importlib.import_module("bot.auto_exit_sl_tp_runtime_patch")
    assurance = importlib.import_module("exit_protection_assurance_patch")
    assert assurance._patch(auto_exit)
    _reset_auto_state(auto_exit)

    position = {
        "position_id": "long-1",
        "account_id": "platform",
        "symbol": "ETH-USD",
        "side": "long",
        "entry_price": 100.0,
        "quantity": 1.0,
    }

    assert auto_exit._trigger(position, 102.0)[0] is False
    hit, reason, trigger = auto_exit._trigger(position, 101.5)
    assert hit is True
    assert reason == "trailing_stop_loss"
    assert trigger > 101.5


def test_accepted_order_id_is_not_a_fill():
    assurance = importlib.import_module("exit_protection_assurance_patch")

    assert assurance._filled_result({"status": "accepted", "order_id": "OID-1"}) is False
    assert assurance._filled_result({"status": "open", "order_id": "OID-2"}) is False
    assert assurance._filled_result({"status": "filled", "order_id": "OID-3"}) is True
    assert assurance._filled_result({"status": "open", "filled_qty": "0.25"}) is False
    assert assurance._filled_result({"status": "", "filled_qty": "0.25"}) is True


def test_patched_auto_exit_predicate_keeps_real_fills(monkeypatch):
    auto_exit = importlib.import_module("bot.auto_exit_sl_tp_runtime_patch")
    assurance = importlib.import_module("exit_protection_assurance_patch")
    assert assurance._patch(auto_exit)

    assert auto_exit._ok({"status": "accepted", "order_id": "OID-ACK"}) is False
    assert auto_exit._ok({"status": "filled", "order_id": "OID-FILL"}) is True


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
