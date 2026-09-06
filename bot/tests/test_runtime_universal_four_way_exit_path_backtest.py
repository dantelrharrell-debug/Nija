from __future__ import annotations

import pytest

from bot import auto_exit_sl_tp_runtime_patch as auto_exit
from bot import runtime_universal_four_way_scope_v376_patch as v376
from bot import runtime_universal_sl_tp_policy_v375_patch as v375


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("NIJA_HARD_STOP_LOSS_PCT", "0.015")
    monkeypatch.setenv("NIJA_MAX_POSITION_LOSS_USD", "1000.00")
    monkeypatch.setenv("NIJA_TRAILING_STOP_ENABLED", "true")
    monkeypatch.setenv("NIJA_TRAILING_STOP_ACTIVATION_PCT", "0.008")
    monkeypatch.setenv("NIJA_TRAILING_STOP_PCT", "0.0035")
    monkeypatch.setenv("NIJA_TRAILING_TP_ENABLED", "true")
    monkeypatch.setenv("NIJA_TRAILING_TP_ACTIVATION_PCT", "0.008")
    monkeypatch.setenv("NIJA_TRAILING_TP_CALLBACK_PCT", "0.0035")
    monkeypatch.setenv("NIJA_PROFIT_LOCK_ACTIVATION_PCT", "0.008")
    monkeypatch.setenv("NIJA_PROFIT_LOCK_CALLBACK_PCT", "0.0035")
    auto_exit._HIGH_WATER.clear()
    assert v375._patch_auto_exit_trigger() is True
    assert v376._patch_trigger_compatibility() is True


def _first_exit(position, prices):
    for index, price in enumerate(prices):
        hit, reason, target = auto_exit._trigger(position, float(price))
        if hit:
            return index, float(price), reason, float(target)
    return None


def test_backtest_long_fixed_stop_loss_path():
    pos = {
        "account_id": "platform",
        "position_id": "bt-long-sl",
        "symbol": "BTC-USD",
        "side": "long",
        "entry_price": 100.0,
        "quantity": 1.0,
        "take_profit_1": 110.0,
        "take_profit_2": 120.0,
        "take_profit_3": 130.0,
    }

    result = _first_exit(pos, [100.0, 99.4, 99.0, 98.5])

    assert result is not None
    index, price, reason, target = result
    assert index == 3
    assert price == pytest.approx(98.5)
    assert reason.startswith("stop_loss:")
    assert target == pytest.approx(98.5)


def test_backtest_long_fixed_take_profit_path():
    pos = {
        "account_id": "platform",
        "position_id": "bt-long-tp",
        "symbol": "ETH-USD",
        "side": "long",
        "entry_price": 100.0,
        "quantity": 1.0,
        "take_profit_1": 103.0,
        "take_profit_2": 106.0,
        "take_profit_3": 110.0,
    }

    result = _first_exit(pos, [100.0, 101.0, 102.0, 103.0])

    assert result is not None
    index, price, reason, target = result
    assert index == 3
    assert price == pytest.approx(103.0)
    assert reason == "take_profit_1"
    assert target == pytest.approx(103.0)


def test_backtest_long_trailing_profit_reversal_preserves_legacy_sequence():
    pos = {
        "account_id": "user:long",
        "position_id": "bt-long-trail",
        "symbol": "SOL-USD",
        "side": "long",
        "entry_price": 100.0,
        "quantity": 1.0,
        "stop_loss": 95.0,
        "take_profit_1": 110.0,
        "take_profit_2": 120.0,
        "take_profit_3": 130.0,
    }

    result = _first_exit(pos, [100.0, 100.4, 100.9, 101.4, 101.0])

    assert result is not None
    index, price, reason, target = result
    assert index == 4
    assert price == pytest.approx(101.0)
    assert reason in {"profit_lock_trailing_exit", "trailing_stop_loss"}
    assert target > 100.0


def test_backtest_short_trailing_profit_reversal_is_symmetric():
    pos = {
        "account_id": "user:short",
        "position_id": "bt-short-trail",
        "symbol": "BTC-USD",
        "side": "short",
        "entry_price": 100.0,
        "quantity": 1.0,
        "stop_loss": 105.0,
        "take_profit_1": 90.0,
        "take_profit_2": 80.0,
        "take_profit_3": 70.0,
    }

    result = _first_exit(pos, [100.0, 99.6, 99.0, 98.4, 98.8])

    assert result is not None
    index, price, reason, target = result
    assert index == 4
    assert price == pytest.approx(98.8)
    assert reason in {"profit_lock_trailing_exit", "trailing_stop_loss"}
    assert target < 100.0


def test_backtest_no_exit_inside_unarmed_band():
    pos = {
        "account_id": "user:flat",
        "position_id": "bt-no-exit",
        "symbol": "ETH-USD",
        "side": "long",
        "entry_price": 100.0,
        "quantity": 1.0,
        "stop_loss": 95.0,
        "take_profit_1": 110.0,
        "take_profit_2": 120.0,
        "take_profit_3": 130.0,
    }

    result = _first_exit(pos, [100.0, 100.2, 100.4, 100.6, 100.5])

    assert result is None
