"""Regression/path tests for research adaptive exit policy v388."""
from __future__ import annotations

import pytest

from bot import runtime_research_adaptive_exit_v388_patch as v388


def test_hard_stop_uses_atr_1_5x_with_three_percent_cap():
    assert v388.hard_stop_pct({}, atr_pct=0.005) == pytest.approx(0.015)
    assert v388.hard_stop_pct({}, atr_pct=0.012) == pytest.approx(0.018)
    assert v388.hard_stop_pct({}, atr_pct=0.030) == pytest.approx(0.030)


def test_risk_unit_uses_actual_verified_stop_distance():
    row = {"entry_price": 100.0, "stop_loss": 98.0, "quantity": 1.0}
    assert v388.risk_unit_pct(row) == pytest.approx(0.02)


def test_universal_fallback_targets_are_r_based_and_not_old_micro_targets():
    row = {"entry_price": 100.0, "stop_loss": 98.5, "quantity": 1.0}
    tp1, tp2, tp3 = v388.fallback_tp_pcts(row)
    assert tp1 == pytest.approx(0.0225)
    assert tp2 == pytest.approx(0.0300)
    assert tp3 == pytest.approx(0.0450)
    assert tp1 > 0.005  # old v239 TP1 was 0.5%


def test_atr_aware_targets_do_not_fall_inside_two_atr_first_target():
    row = {
        "entry_price": 100.0,
        "stop_loss": 97.0,
        "quantity": 1.0,
        "atr_pct": 0.02,
    }
    tp1, tp2, tp3 = v388.fallback_tp_pcts(row)
    assert tp1 >= 2.0 * row["atr_pct"]
    assert tp1 < tp2 < tp3


def test_trailing_stop_arms_at_one_r_and_first_boundary_is_near_breakeven():
    row = {"entry_price": 100.0, "stop_loss": 98.5, "quantity": 1.0}
    s = v388.trailing_pcts(row)
    assert s["trailing_stop_activation_pct"] == pytest.approx(0.015)
    assert s["trailing_stop_distance_pct"] == pytest.approx(0.015)
    peak = 100.0 * (1 + s["trailing_stop_activation_pct"])
    boundary = peak * (1 - s["trailing_stop_distance_pct"])
    assert boundary == pytest.approx(99.9775, abs=1e-4)


def test_trailing_take_profit_arms_at_two_r_with_less_than_one_r_callback():
    row = {"entry_price": 100.0, "stop_loss": 98.5, "quantity": 1.0}
    s = v388.trailing_pcts(row)
    assert s["trailing_take_profit_activation_pct"] == pytest.approx(0.030)
    assert s["trailing_take_profit_callback_pct"] == pytest.approx(0.01125)
    assert s["trailing_take_profit_callback_pct"] < v388.risk_unit_pct(row)


def test_v239_patch_preserves_explicit_targets_and_synthesizes_missing_ones():
    from bot import runtime_all_account_profit_targets_v239_patch as v239

    assert v388._patch_v239()
    row = {
        "entry_price": 100.0,
        "stop_loss": 98.5,
        "quantity": 2.0,
        "side": "long",
        "take_profit_1": 105.0,
    }
    out = v239._with_profit_targets(row)
    assert out["take_profit_1"] == pytest.approx(105.0)
    assert out["take_profit_2"] == pytest.approx(103.0)
    assert out["take_profit_3"] == pytest.approx(104.5)
    assert out["research_exit_policy_marker"] == v388.MARKER


def test_v375_policy_row_carries_adaptive_four_way_settings():
    from bot import runtime_universal_sl_tp_policy_v375_patch as v375

    assert v388._patch_v239()
    assert v388._patch_v375()
    row = v375._policy_row({
        "entry_price": 100.0,
        "stop_loss": 98.5,
        "quantity": 1.0,
        "side": "long",
    })
    assert row["universal_four_way_policy_complete"] is True
    assert row["research_exit_policy_marker"] == v388.MARKER
    assert row["trailing_stop_distance_pct"] == pytest.approx(0.015)
    assert row["trailing_take_profit_callback_pct"] == pytest.approx(0.01125)


def _trailing_exit_index(prices: list[float], activation: float, distance: float) -> int | None:
    entry = prices[0]
    high = entry
    armed = False
    for idx, price in enumerate(prices[1:], start=1):
        high = max(high, price)
        if high >= entry * (1 + activation):
            armed = True
        if armed and price <= high * (1 - distance):
            return idx
    return None


def test_path_backtest_adaptive_trail_avoids_old_035pct_noise_whipsaw():
    # Deterministic regression path, not a profitability forecast.
    prices = [100.0, 101.05, 100.60, 101.50, 102.00, 102.30]
    old_exit = _trailing_exit_index(prices, activation=0.010, distance=0.0035)
    row = {"entry_price": 100.0, "stop_loss": 98.5, "quantity": 1.0}
    s = v388.trailing_pcts(row)
    new_exit = _trailing_exit_index(
        prices,
        activation=float(s["trailing_stop_activation_pct"]),
        distance=float(s["trailing_stop_distance_pct"]),
    )
    assert old_exit == 2
    assert new_exit is None
    tp1, _, _ = v388.fallback_tp_pcts(row)
    assert prices[-1] >= 100.0 * (1 + tp1)


def test_execution_exit_config_uses_documented_one_two_three_r_partial_geometry():
    from bot.execution_exit_config import ExecutionExitConfig

    assert v388._patch_execution_exit_config()
    cfg = ExecutionExitConfig()
    params = cfg.get_exit_params(
        regime="weak_trend",
        entry_type="swing",
        broker="kraken",
        atr_pct=0.01,
    )
    r = params.stop.hard_sl_pct
    assert r >= 0.015
    targets = [level.target_pct for level in params.tp.levels]
    fractions = [level.exit_fraction for level in params.tp.levels]
    assert targets == pytest.approx([r, 2 * r, 3 * r], abs=1e-4)
    assert fractions == pytest.approx([0.50, 0.25, 0.25])
