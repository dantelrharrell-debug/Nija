"""Regression and scenario-backtest tests for adaptive exit policy v390."""
from __future__ import annotations

import math

from bot import runtime_adaptive_exit_policy_v390_patch as v390


def test_atr14_prefers_real_position_volatility() -> None:
    assert math.isclose(v390._atr_pct({"entry_price": 100.0, "atr": 1.2}), 0.012)
    assert math.isclose(v390._atr_pct({"entry_price": 100.0, "atr_pct": 1.4}), 0.014)


def test_2r_3r_4r_targets_with_nija_minimums() -> None:
    # 1.5% risk -> 3.0% / 4.5% / 6.0% targets.
    row = {"entry_price": 100.0, "quantity": 1.0, "stop_loss": 98.5, "atr": 1.0}
    tp1, tp2, tp3 = v390._target_pcts(row)
    assert math.isclose(tp1, 0.030)
    assert math.isclose(tp2, 0.045)
    assert math.isclose(tp3, 0.060)


def test_small_risk_still_obeys_fee_viability_minimum_ladder() -> None:
    # 0.5% risk would imply 1/1.5/2%, but NIJA minimum ladder remains
    # 1.5/2.5/4.0% so micro-profit targets do not dominate the exit plan.
    row = {"entry_price": 100.0, "quantity": 1.0, "stop_loss": 99.5, "atr": 0.4}
    assert v390._target_pcts(row) == (0.015, 0.025, 0.040)


def test_trailing_geometry_uses_atr_and_progressive_activation() -> None:
    row = {"entry_price": 100.0, "quantity": 1.0, "stop_loss": 98.5, "atr": 1.0}
    settings = v390._trailing_settings(row)
    assert math.isclose(settings["adaptive_atr_pct"], 0.01)
    assert math.isclose(settings["adaptive_risk_pct"], 0.015)
    assert math.isclose(settings["trailing_stop_distance_pct"], 0.0125)
    assert math.isclose(settings["trailing_stop_activation_pct"], 0.015)
    assert math.isclose(settings["trailing_take_profit_callback_pct"], 0.010)
    assert math.isclose(settings["trailing_take_profit_activation_pct"], 0.0225)


def test_runtime_missing_stop_is_never_widened() -> None:
    high_vol = {"entry_price": 100.0, "quantity": 1.0, "atr": 3.0, "market_regime": "VOLATILE"}
    # Existing fallback is 1.5%. Adaptive desired stop would be wider, but
    # migration safety keeps the already-established hard fallback at 1.5%.
    assert math.isclose(v390._bounded_failsafe_stop_pct(0.015, high_vol), 0.015)

    quiet = {"entry_price": 100.0, "quantity": 1.0, "atr": 0.3, "market_regime": "RANGING"}
    # In quiet conditions v390 may tighten the missing-position fallback.
    assert v390._bounded_failsafe_stop_pct(0.015, quiet) <= 0.015


def _old_trailing_exit(path: list[float], entry: float = 100.0) -> float | None:
    """Approximate pre-v390 software trail: arm +0.8%, callback 0.35%."""
    high = entry
    armed = False
    for price in path:
        high = max(high, price)
        if high >= entry * 1.008:
            armed = True
        if armed and price <= high * (1.0 - 0.0035):
            return price
    return None


def _adaptive_trailing_exit(path: list[float], entry: float = 100.0, atr: float = 1.0) -> float | None:
    """Scenario implementation of v390 long-side trail geometry."""
    row = {"entry_price": entry, "quantity": 1.0, "stop_loss": 98.5, "atr": atr}
    cfg = v390._trailing_settings(row)
    high = entry
    for price in path:
        high = max(high, price)
        sl_armed = high >= entry * (1.0 + float(cfg["trailing_stop_activation_pct"]))
        tp_armed = high >= entry * (1.0 + float(cfg["trailing_take_profit_activation_pct"]))
        sl_hit = sl_armed and price <= high * (1.0 - float(cfg["trailing_stop_distance_pct"]))
        tp_hit = tp_armed and price <= high * (1.0 - float(cfg["trailing_take_profit_callback_pct"]))
        if sl_hit or tp_hit:
            return price
    return None


def test_scenario_backtest_normal_noise_does_not_trip_new_trail_early() -> None:
    # A +0.9% move followed by ordinary ~0.5% noise can trip the old 0.35%
    # callback. v390 waits for a move that is meaningful relative to ATR/risk.
    path = [100.20, 100.55, 100.90, 100.50, 100.72, 101.10, 101.35]
    assert _old_trailing_exit(path) is not None
    assert _adaptive_trailing_exit(path, atr=1.0) is None


def test_scenario_backtest_trend_reversal_still_locks_positive_move() -> None:
    path = [100.4, 101.0, 101.6, 102.3, 103.1, 102.7, 102.0]
    exit_price = _adaptive_trailing_exit(path, atr=1.0)
    assert exit_price is not None
    assert exit_price > 100.0
