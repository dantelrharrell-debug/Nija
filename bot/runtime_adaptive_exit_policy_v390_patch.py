"""Research-informed adaptive exit convergence for NIJA (v390).

This layer makes NIJA's live four-way protection consistent with the strategy's
volatility-aware risk design without weakening an already-explicit live stop.

Policy
------
* ATR(14) is the preferred volatility input when a position row exposes it.
* Missing/adopted-position hard stops remain bounded by NIJA's existing hard
  fallback; v390 may tighten that fallback in quiet markets but never widens it.
* Missing take-profit targets use a fee-floor-aware 2R / 3R / 4R ladder with
  established NIJA minimum targets of 1.5% / 2.5% / 4.0%.
* Trailing stop-loss arms only after enough favorable movement to cover its
  trail distance; default distance is 1.25 ATR.
* Trailing take-profit/profit-lock arms later (roughly 1.5R / >=2 ATR) and uses
  a 1.0 ATR callback.
* Existing explicit broker/user TP and SL levels are preserved.

The policy is deliberately conservative during migration: it improves missing
or synthesized protection and the strategy's trailing calculation, but it does
not move an already-explicit hard stop farther from price. Profit is never
guaranteed and all existing writer/nonce/risk/capital/kill-switch/fill gates
remain authoritative.
"""
from __future__ import annotations

import importlib
import logging
import math
import os
from collections.abc import Mapping
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_adaptive_exit_policy_v390")
MARKER = "20260906-adaptive-exit-policy-v390"
_READY_FLAG = "NIJA_RUNTIME_ADAPTIVE_EXIT_POLICY_V390_READY"
_PATCH_ATTR = "_nija_adaptive_exit_policy_v390"
_EPS = 1e-12


def _f(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _entry(row: Mapping[str, Any]) -> float:
    for key in ("entry_price", "avg_entry_price", "average_price", "cost_basis_price", "avg_price"):
        value = _f(row.get(key))
        if value > _EPS:
            return value
    return 0.0


def _qty(row: Mapping[str, Any]) -> float:
    for key in ("quantity", "qty", "size", "amount", "units", "balance"):
        value = abs(_f(row.get(key)))
        if value > _EPS:
            return value
    return 0.0


def _short(row: Mapping[str, Any]) -> bool:
    return str(row.get("side") or "").strip().lower() in {"short", "sell"}


def _atr_pct(row: Mapping[str, Any], entry: float | None = None) -> float:
    entry = _f(entry, 0.0) if entry is not None else _entry(row)
    for key in ("atr_pct", "atr_14_pct", "atr14_pct", "volatility_atr_pct"):
        value = _f(row.get(key))
        if value > 0.0:
            # Accept either fractional or percentage representation.
            if value > 1.0:
                value /= 100.0
            return _clamp(value, 0.0025, 0.04)
    if entry > _EPS:
        for key in ("atr", "atr_14", "atr14", "average_true_range"):
            value = _f(row.get(key))
            if value > 0.0:
                return _clamp(value / entry, 0.0025, 0.04)

    asset = str(row.get("asset_class") or row.get("market_type") or "").lower()
    broker = str(row.get("broker") or row.get("venue") or "").lower()
    # Runtime fallback only. Real entry calculations should supply ATR(14).
    if any(token in asset for token in ("equity", "stock")) or broker == "alpaca":
        return _clamp(_f(os.environ.get("NIJA_ADAPTIVE_ATR_FALLBACK_EQUITY_PCT"), 0.006), 0.0025, 0.04)
    return _clamp(_f(os.environ.get("NIJA_ADAPTIVE_ATR_FALLBACK_CRYPTO_PCT"), 0.010), 0.0025, 0.04)


def _stop_multiplier(row: Mapping[str, Any]) -> float:
    regime = str(row.get("market_regime") or row.get("regime") or row.get("trend_regime") or "").upper()
    if "VOLAT" in regime:
        return 1.75
    if "TREND" in regime:
        return 1.50
    if "RANG" in regime or "CHOP" in regime:
        return 1.25
    return 1.50


def _risk_pct(row: Mapping[str, Any]) -> float:
    entry = _entry(row)
    stop = _f(row.get("stop_loss"))
    if entry > _EPS and stop > _EPS:
        return _clamp(abs(entry - stop) / entry, 0.0005, 0.03)
    return _clamp(_atr_pct(row, entry) * _stop_multiplier(row), 0.004, 0.03)


def _target_pcts(row: Mapping[str, Any]) -> tuple[float, float, float]:
    risk = _risk_pct(row)
    tp1 = max(_f(os.environ.get("NIJA_ADAPTIVE_TP1_MIN_PCT"), 0.015), 2.0 * risk)
    tp2 = max(_f(os.environ.get("NIJA_ADAPTIVE_TP2_MIN_PCT"), 0.025), 3.0 * risk, tp1)
    tp3 = max(_f(os.environ.get("NIJA_ADAPTIVE_TP3_MIN_PCT"), 0.040), 4.0 * risk, tp2)
    return (_clamp(tp1, 0.005, 0.12), _clamp(tp2, 0.010, 0.15), _clamp(tp3, 0.020, 0.20))


def _trailing_settings(row: Mapping[str, Any]) -> dict[str, float | bool | str]:
    entry = _entry(row)
    atr = _atr_pct(row, entry)
    risk = _risk_pct(row)
    sl_distance = _clamp(1.25 * atr, 0.0035, 0.025)
    # Arm only when a full reversal of the trail cannot turn the protected move
    # into a larger loss than the original hard-risk geometry.
    sl_activation = _clamp(max(risk, sl_distance), 0.004, 0.08)
    tp_callback = _clamp(1.00 * atr, 0.0035, 0.020)
    tp_activation = _clamp(max(1.5 * risk, 2.0 * atr, sl_activation), 0.008, 0.10)
    return {
        "trailing_stop_loss_enabled": True,
        "trailing_stop_activation_pct": sl_activation,
        "trailing_stop_distance_pct": sl_distance,
        "trailing_take_profit_enabled": True,
        "trailing_take_profit_activation_pct": tp_activation,
        "trailing_take_profit_callback_pct": tp_callback,
        "adaptive_atr_pct": atr,
        "adaptive_risk_pct": risk,
        "adaptive_exit_policy": "atr14_2r3r4r_progressive_trailing_v390",
    }


def _bounded_failsafe_stop_pct(original_pct: float, row: Mapping[str, Any]) -> float:
    """Adaptive runtime fallback that never widens the pre-v390 hard fallback."""
    original_pct = _clamp(original_pct, 0.0005, 0.03)
    desired = _clamp(_atr_pct(row) * _stop_multiplier(row), 0.004, 0.03)
    return min(original_pct, desired)


def _patch_auto_exit_failsafe() -> bool:
    module = importlib.import_module("bot.auto_exit_sl_tp_runtime_patch")
    current = getattr(module, "_effective_stop", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def effective_stop_v390(pos: dict[str, Any], price: float):
        # Explicit strategy/broker stops are authoritative and never moved here.
        if _f(pos.get("stop_loss")) > _EPS:
            return current(pos, price)
        stop, source = current(pos, price)
        entry = _entry(pos)
        if entry <= _EPS or _f(stop) <= _EPS:
            return stop, source
        original_pct = abs(entry - _f(stop)) / entry
        pct = _bounded_failsafe_stop_pct(original_pct, pos)
        candidate = entry * (1.0 + pct if _short(pos) else 1.0 - pct)
        return candidate, f"adaptive_atr_bounded:{source or 'existing_hard_fallback'}"

    setattr(effective_stop_v390, _PATCH_ATTR, True)
    setattr(effective_stop_v390, "__wrapped__", current)
    module._effective_stop = effective_stop_v390
    return True


def _patch_profit_targets() -> bool:
    module = importlib.import_module("bot.runtime_all_account_profit_targets_v239_patch")
    current = getattr(module, "_with_profit_targets", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def with_targets_v390(raw: Any):
        if not isinstance(raw, dict):
            return current(raw)
        explicit = {key: _f(raw.get(key)) > _EPS for key in ("take_profit_1", "take_profit_2", "take_profit_3")}
        pos = current(raw)
        if not isinstance(pos, dict) or _entry(pos) <= _EPS or _qty(pos) <= _EPS:
            return pos
        entry = _entry(pos)
        pcts = _target_pcts(pos)
        short = _short(pos)
        adjusted: list[str] = []
        for key, pct in zip(("take_profit_1", "take_profit_2", "take_profit_3"), pcts):
            if explicit[key]:
                continue
            pos[key] = entry * (1.0 - pct if short else 1.0 + pct)
            adjusted.append(key)
        pos.update({"adaptive_tp1_pct": pcts[0], "adaptive_tp2_pct": pcts[1], "adaptive_tp3_pct": pcts[2]})
        if adjusted:
            LOGGER.info(
                "ADAPTIVE_TP_V390 marker=%s account=%s symbol=%s risk_pct=%.6f atr_pct=%.6f "
                "tp1=%.6f tp2=%.6f tp3=%.6f adjusted=%s explicit_preserved=true",
                MARKER,
                str(pos.get("account_id") or pos.get("user_id") or pos.get("account") or "platform"),
                str(pos.get("symbol") or "unknown"),
                _risk_pct(pos), _atr_pct(pos), pcts[0], pcts[1], pcts[2], ",".join(adjusted),
            )
        return pos

    setattr(with_targets_v390, _PATCH_ATTR, True)
    setattr(with_targets_v390, "__wrapped__", current)
    module._with_profit_targets = with_targets_v390
    return True


def _patch_universal_policy() -> bool:
    module = importlib.import_module("bot.runtime_universal_sl_tp_policy_v375_patch")
    current = getattr(module, "_policy_row", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def policy_row_v390(raw: Any):
        row = current(raw)
        if not isinstance(row, Mapping) or _entry(row) <= _EPS or _qty(row) <= _EPS:
            return row
        output = dict(row)
        output.update(_trailing_settings(output))
        output["adaptive_exit_policy_v390"] = True
        output["universal_four_way_policy_complete"] = bool(
            _f(output.get("stop_loss")) > _EPS
            and any(_f(output.get(k)) > _EPS for k in ("take_profit_1", "take_profit_2", "take_profit_3"))
            and output.get("trailing_stop_loss_enabled") is True
            and output.get("trailing_take_profit_enabled") is True
        )
        return output

    setattr(policy_row_v390, _PATCH_ATTR, True)
    setattr(policy_row_v390, "__wrapped__", current)
    module._policy_row = policy_row_v390
    return True


def _patch_kraken_margin_policy() -> bool:
    module = importlib.import_module("bot.runtime_kraken_margin_full_protection_v371_patch")
    current = getattr(module, "_trailing_policy", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def trailing_policy_v390(row: dict[str, Any]) -> None:
        current(row)
        row.update(_trailing_settings(row))

    setattr(trailing_policy_v390, _PATCH_ATTR, True)
    setattr(trailing_policy_v390, "__wrapped__", current)
    module._trailing_policy = trailing_policy_v390
    return True


def _patch_strategy_risk_manager() -> bool:
    module = importlib.import_module("bot.risk_manager")
    # Research-informed ATR baseline while preserving NIJA's existing 3% hard cap.
    module._ATR_MULT_TRENDING = 1.50
    module._ATR_MULT_VOLATILE = 1.75
    module._ATR_MULT_RANGING = 1.25
    module._ATR_MULT_DEFAULT = 1.50
    module.TP_ATR_MULTIPLIER = 2.0
    cls = getattr(module, "AdaptiveRiskManager", None)
    current = getattr(cls, "calculate_trailing_stop", None) if isinstance(cls, type) else None
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def calculate_trailing_stop_v390(self, current_price: float, entry_price: float, side: str, atr: float, breakeven_mode: bool = False) -> float:
        if entry_price <= 0 or atr <= 0:
            return current(self, current_price, entry_price, side, atr, breakeven_mode)
        long_side = str(side or "").lower() in {"long", "buy"}
        favorable = (current_price - entry_price) / entry_price if long_side else (entry_price - current_price) / entry_price
        if favorable >= 0.060:
            mult = 0.80
        elif favorable >= 0.040:
            mult = 1.00
        elif favorable >= 0.025:
            mult = 1.20
        else:
            mult = 1.50
        distance = max(atr * mult, entry_price * 0.0035)
        stop = current_price - distance if long_side else current_price + distance
        if breakeven_mode:
            stop = max(stop, entry_price) if long_side else min(stop, entry_price)
        return stop

    setattr(calculate_trailing_stop_v390, _PATCH_ATTR, True)
    setattr(calculate_trailing_stop_v390, "__wrapped__", current)
    cls.calculate_trailing_stop = calculate_trailing_stop_v390
    return True


def _set_backup_defaults() -> None:
    # Canonical row-level policy is adaptive. These values only harden legacy or
    # backup workers that can consume process-wide percentages.
    os.environ["NIJA_TRAILING_STOP_ENABLED"] = "true"
    os.environ["NIJA_TRAILING_TP_ENABLED"] = "true"
    os.environ["NIJA_TRAILING_STOP_ACTIVATION_PCT"] = str(_f(os.environ.get("NIJA_ADAPTIVE_BACKUP_TRAIL_ACTIVATION_PCT"), 0.015))
    os.environ["NIJA_TRAILING_STOP_PCT"] = str(_f(os.environ.get("NIJA_ADAPTIVE_BACKUP_TRAIL_DISTANCE_PCT"), 0.0125))
    os.environ["NIJA_TRAILING_TP_ACTIVATION_PCT"] = str(_f(os.environ.get("NIJA_ADAPTIVE_BACKUP_TRAILING_TP_ACTIVATION_PCT"), 0.0225))
    os.environ["NIJA_TRAILING_TP_CALLBACK_PCT"] = str(_f(os.environ.get("NIJA_ADAPTIVE_BACKUP_TRAILING_TP_CALLBACK_PCT"), 0.010))
    os.environ["NIJA_PROFIT_LOCK_ACTIVATION_PCT"] = os.environ["NIJA_TRAILING_TP_ACTIVATION_PCT"]
    os.environ["NIJA_PROFIT_LOCK_CALLBACK_PCT"] = os.environ["NIJA_TRAILING_TP_CALLBACK_PCT"]


def install_import_hook() -> bool:
    _set_backup_defaults()
    outcomes = {
        "auto_exit_failsafe": _patch_auto_exit_failsafe(),
        "profit_targets": _patch_profit_targets(),
        "universal_policy": _patch_universal_policy(),
        "kraken_margin": _patch_kraken_margin_policy(),
        "strategy_risk_manager": _patch_strategy_risk_manager(),
    }
    ready = all(outcomes.values())
    os.environ[_READY_FLAG] = "1" if ready else "0"
    LOGGER.critical(
        "RUNTIME_ADAPTIVE_EXIT_POLICY_V390_%s marker=%s ready=%s outcomes=%s "
        "atr_period=14 stop_baseline_atr=1.25-1.75 tp_ladder=2R/3R/4R "
        "trailing_sl_distance_atr=1.25 trailing_tp_callback_atr=1.0 "
        "existing_explicit_stops_preserved=true missing_stop_never_widened=true "
        "existing_explicit_take_profit_preserved=true all_four_legs_required=true "
        "safety_gates_bypassed=false profit_guaranteed=false",
        "READY" if ready else "NOT_READY",
        MARKER, str(ready).lower(), outcomes,
    )
    return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER", "install", "install_import_hook", "_atr_pct", "_risk_pct",
    "_target_pcts", "_trailing_settings", "_bounded_failsafe_stop_pct",
]
