from __future__ import annotations

import pytest

from bot import auto_exit_sl_tp_runtime_patch as auto_exit
from bot import runtime_universal_sl_tp_policy_v375_patch as v375


@pytest.fixture(autouse=True)
def _four_way_env(monkeypatch):
    monkeypatch.setenv("NIJA_HARD_STOP_LOSS_PCT", "0.015")
    monkeypatch.setenv("NIJA_MAX_POSITION_LOSS_USD", "2.00")
    monkeypatch.setenv("NIJA_PROFIT_TARGET_TP1_PCT", "0.005")
    monkeypatch.setenv("NIJA_PROFIT_TARGET_TP2_PCT", "0.010")
    monkeypatch.setenv("NIJA_PROFIT_TARGET_TP3_PCT", "0.020")
    monkeypatch.setenv("NIJA_TRAILING_STOP_ENABLED", "true")
    monkeypatch.setenv("NIJA_TRAILING_STOP_ACTIVATION_PCT", "0.008")
    monkeypatch.setenv("NIJA_TRAILING_STOP_PCT", "0.0035")
    monkeypatch.setenv("NIJA_TRAILING_TP_ENABLED", "true")
    monkeypatch.setenv("NIJA_TRAILING_TP_ACTIVATION_PCT", "0.008")
    monkeypatch.setenv("NIJA_TRAILING_TP_CALLBACK_PCT", "0.0035")
    auto_exit._HIGH_WATER.clear()


def _position(**overrides):
    row = {
        "account_id": "platform",
        "position_id": "P1",
        "symbol": "ETH-USD",
        "side": "long",
        "entry_price": 100.0,
        "quantity": 1.0,
    }
    row.update(overrides)
    return row


def test_policy_row_requires_all_four_protection_legs():
    row = v375._policy_row(_position())

    assert row["stop_loss"] > 0.0
    assert row["take_profit_1"] == pytest.approx(100.5)
    assert row["take_profit_2"] == pytest.approx(101.0)
    assert row["take_profit_3"] == pytest.approx(102.0)
    assert row["software_trailing_stop_available"] is True
    assert row["software_trailing_take_profit_available"] is True
    assert row["universal_sl_tp_policy_complete"] is True
    assert row["universal_four_way_policy_complete"] is True


def test_long_trailing_stop_loss_is_evaluated_independently(monkeypatch):
    monkeypatch.setenv("NIJA_TRAILING_TP_CALLBACK_PCT", "0.010")
    pos = _position(
        take_profit_1=110.0,
        take_profit_2=120.0,
        take_profit_3=130.0,
    )

    assert v375._four_way_trigger(pos, 102.0)[0] is False
    hit, reason, threshold = v375._four_way_trigger(pos, 101.5)

    assert hit is True
    assert reason == "trailing_stop_loss"
    assert threshold == pytest.approx(102.0 * (1.0 - 0.0035))


def test_short_trailing_take_profit_is_symmetric(monkeypatch):
    monkeypatch.setenv("NIJA_TRAILING_STOP_PCT", "0.010")
    pos = _position(
        position_id="P2",
        side="short",
        take_profit_1=90.0,
        take_profit_2=80.0,
        take_profit_3=70.0,
    )

    assert v375._four_way_trigger(pos, 98.0)[0] is False
    hit, reason, threshold = v375._four_way_trigger(pos, 98.5)

    assert hit is True
    assert reason == "profit_lock_trailing_exit"
    assert threshold == pytest.approx(98.0 * (1.0 + 0.0035))


def test_disabling_any_trailing_leg_makes_four_way_policy_incomplete(monkeypatch):
    monkeypatch.setenv("NIJA_TRAILING_TP_ENABLED", "false")
    row = v375._policy_row(_position())

    assert row["universal_sl_tp_policy_complete"] is True
    assert row["software_trailing_stop_available"] is True
    assert row["software_trailing_take_profit_available"] is False
    assert row["universal_four_way_policy_complete"] is False
