"""Research-grounded adaptive exit policy v388.

This patch converges NIJA's live four-way protection on a volatility/risk-unit
policy instead of fixed magic percentages.

Policy:
- Hard stop fallback: max(1.5%, 1.5 x ATR), capped at 3.0%.
- New-entry stops preserve dollar risk by shrinking size when stop distance widens.
- Universal fallback TPs: 1.5R / 2R / 3R (existing explicit targets preserved).
- Strategy exit config keeps documented partial ladder geometry at 1R / 2R / 3R.
- Trailing SL: arm at +1R, trail by max(1R, 1.5 x ATR).
  This places the first trailing boundary near breakeven and ratchets thereafter.
- Trailing TP / profit lock: arm at +2R, callback max(0.75R, 1.0 x ATR).

R is the actual stop distance from verified entry. If ATR is unavailable, the
stop-derived R remains authoritative. If neither is available, conservative
fallbacks are used. Existing tighter dollar-loss caps are never widened.

Research basis (parameter-region guidance, not a claim of universal optimality):
- Fidelity ATR guidance: volatility-aware stops; 1.5 x ATR example.
- Dai et al., International Review of Finance (2021), doi:10.1111/irfi.12328.
- Kaminski & Lo, Journal of Financial Markets (2014), stop-loss value is regime-dependent.
- Glynn & Iglehart, Management Science (1995), doi:10.1287/mnsc.41.6.1096.
- NIJA SECURITY_MODEL.md: R-multiple targets and ATR(14) x 1.5 trailing after TP1.

Profit is not guaranteed. This module changes exit geometry only; it does not
bypass writer, nonce, capital, broker-health, kill-switch, fill, or order gates.
"""
from __future__ import annotations

import importlib
import logging
import math
import os
from collections.abc import Mapping
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_research_adaptive_exit_v388")
MARKER = "20260906-research-adaptive-exit-v388"
_READY_FLAG = "NIJA_RESEARCH_ADAPTIVE_EXIT_V388_READY"
_PATCH_ATTR = "_nija_research_adaptive_exit_v388"
_EPS = 1e-12

_BASE_STOP_PCT = 0.015
_MIN_STOP_PCT = 0.010
_MAX_STOP_PCT = 0.030
_ATR_STOP_MULT = 1.50
_FALLBACK_TP_R = (1.50, 2.00, 3.00)
_STRATEGY_TP_R = (1.00, 2.00, 3.00)
_TRAIL_SL_ARM_R = 1.00
_TRAIL_SL_ATR_MULT = 1.50
_TRAIL_TP_ARM_R = 2.00
_TRAIL_TP_CALLBACK_R = 0.75
_TRAIL_TP_ATR_MULT = 1.00


def _f(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _entry(row: Mapping[str, Any]) -> float:
    for key in ("entry_price", "avg_entry_price", "average_price", "cost_basis_price", "avg_price"):
        value = _f(row.get(key))
        if value > _EPS:
            return value
    return 0.0


def _qty(row: Mapping[str, Any]) -> float:
    for key in ("quantity", "qty", "size", "amount", "units", "balance"):
        if row.get(key) is not None:
            value = abs(_f(row.get(key)))
            if value > _EPS:
                return value
    return 0.0


def _side(row: Mapping[str, Any]) -> str:
    raw = str(row.get("side") or "").strip().lower()
    return "short" if raw in {"short", "sell"} else "long"


def _atr_pct(row: Mapping[str, Any] | None = None, **kwargs: Any) -> float:
    values: list[Any] = []
    if isinstance(row, Mapping):
        values.extend(row.get(key) for key in (
            "atr_pct", "atr_percent", "volatility_pct", "atr_fraction",
        ))
        atr_value = _f(row.get("atr_value") or row.get("atr"))
        entry = _entry(row)
        if atr_value > _EPS and entry > _EPS:
            values.append(atr_value / entry)
    values.extend(kwargs.get(key) for key in ("atr_pct", "atr_percent", "volatility_pct"))
    for raw in values:
        value = _f(raw)
        if value > 1.0:
            value /= 100.0
        if value > _EPS:
            return _clamp(value, 0.0001, 0.25)
    return 0.0


def hard_stop_pct(row: Mapping[str, Any] | None = None, *, atr_pct: float = 0.0) -> float:
    """Return research default stop distance as fraction of entry."""
    atr = atr_pct if atr_pct > 0 else _atr_pct(row)
    desired = max(_BASE_STOP_PCT, atr * _ATR_STOP_MULT if atr > 0 else 0.0)
    return _clamp(desired, _MIN_STOP_PCT, _MAX_STOP_PCT)


def risk_unit_pct(row: Mapping[str, Any]) -> float:
    """R = actual stop distance; otherwise adaptive fallback."""
    entry = _entry(row)
    stop = _f(row.get("stop_loss"))
    if entry > _EPS and stop > _EPS:
        distance = abs(entry - stop) / entry
        if distance > _EPS:
            return _clamp(distance, 0.0005, 0.25)
    explicit = _f(row.get("risk_stop_loss_pct"))
    if explicit > _EPS:
        if explicit > 1.0:
            explicit /= 100.0
        return _clamp(explicit, 0.0005, 0.25)
    return hard_stop_pct(row)


def fallback_tp_pcts(row: Mapping[str, Any]) -> tuple[float, float, float]:
    """Full-exit fallback ladder for universal/adopted positions."""
    r = risk_unit_pct(row)
    atr = _atr_pct(row)
    tp1 = max(_FALLBACK_TP_R[0] * r, 2.0 * atr if atr > 0 else 0.0)
    tp2 = max(_FALLBACK_TP_R[1] * r, 3.0 * atr if atr > 0 else 0.0)
    tp3 = max(_FALLBACK_TP_R[2] * r, 4.0 * atr if atr > 0 else 0.0)
    tp1 = _clamp(tp1, 0.005, 0.25)
    tp2 = _clamp(max(tp1, tp2), tp1, 0.25)
    tp3 = _clamp(max(tp2, tp3), tp2, 0.25)
    return tp1, tp2, tp3


def trailing_pcts(row: Mapping[str, Any]) -> dict[str, float | bool]:
    r = risk_unit_pct(row)
    atr = _atr_pct(row)
    sl_distance = max(r, _TRAIL_SL_ATR_MULT * atr if atr > 0 else 0.0)
    sl_activation = max(_TRAIL_SL_ARM_R * r, sl_distance)
    tp_activation = max(_TRAIL_TP_ARM_R * r, 2.0 * atr if atr > 0 else 0.0)
    tp_callback = max(
        _TRAIL_TP_CALLBACK_R * r,
        _TRAIL_TP_ATR_MULT * atr if atr > 0 else 0.0,
    )
    return {
        "trailing_stop_loss_enabled": True,
        "trailing_stop_activation_pct": _clamp(sl_activation, 0.005, 0.25),
        "trailing_stop_distance_pct": _clamp(sl_distance, 0.005, 0.25),
        "trailing_take_profit_enabled": True,
        "trailing_take_profit_activation_pct": _clamp(tp_activation, 0.005, 0.25),
        "trailing_take_profit_callback_pct": _clamp(tp_callback, 0.003, 0.25),
    }


def _apply_fallback_env() -> None:
    """Align non-row-aware fallback workers with the same R-region."""
    env = {
        "NIJA_HARD_STOP_LOSS_PCT": "0.015",
        "NIJA_GLOBAL_STOP_LOSS_PCT": "0.015",
        "NIJA_PROFIT_FIRST_MIN_STOP_PCT": "0.010",
        "NIJA_PROFIT_FIRST_MAX_STOP_PCT": "0.030",
        "MAX_SL_PCT": "0.030",
        "RISK_SIZER_ATR_MULTIPLIER": "1.5",
        "SL_ATR_MULTIPLIER": "1.5",
        "NIJA_TRAILING_STOP_ACTIVATION_PCT": "0.015",
        "NIJA_TRAILING_STOP_PCT": "0.015",
        "NIJA_TRAILING_TP_ACTIVATION_PCT": "0.030",
        "NIJA_TRAILING_TP_CALLBACK_PCT": "0.01125",
        "NIJA_PROFIT_LOCK_ACTIVATION_PCT": "0.030",
        "NIJA_PROFIT_LOCK_CALLBACK_PCT": "0.01125",
        "NIJA_BREAKEVEN_PROFIT_THRESHOLD_PCT": "0.015",
        "NIJA_BREAKEVEN_STOP_OFFSET_PCT": "0.001",
        "NIJA_COMBO_BREAKEVEN_THRESHOLD_PCT": "0.015",
        "NIJA_COMBO_BREAKEVEN_OFFSET_PCT": "0.001",
        "NIJA_COMBO_TRAILING_SWITCH_PCT": "0.030",
        "NIJA_COMBO_TRAILING_STOP_PCT": "0.015",
        "NIJA_COMBINED_TRAILING_SL_ACTIVATION_PCT": "0.015",
        "NIJA_COMBINED_TRAILING_SL_DISTANCE_PCT": "0.015",
        "NIJA_COMBINED_TRAILING_TP_ACTIVATION_PCT": "0.030",
        "NIJA_COMBINED_TRAILING_TP_CALLBACK_PCT": "0.01125",
        "NIJA_GLOBAL_TRAILING_ACTIVATION_PCT": "0.015",
        "NIJA_GLOBAL_TRAILING_STOP_PCT": "0.015",
        "NIJA_GLOBAL_TRAILING_TP_ACTIVATION_PCT": "0.030",
        "NIJA_GLOBAL_TRAILING_TP_CALLBACK_PCT": "0.01125",
        "NIJA_PROFIT_TARGET_TP1_PCT": "0.0225",
        "NIJA_PROFIT_TARGET_TP2_PCT": "0.0300",
        "NIJA_PROFIT_TARGET_TP3_PCT": "0.0450",
    }
    for key, value in env.items():
        os.environ[key] = value


def _patch_profit_first() -> bool:
    try:
        mod = importlib.import_module("profit_first_loss_prevention_patch")
    except Exception:
        try:
            mod = importlib.import_module("bot.profit_first_loss_prevention_patch")
        except Exception:
            return False

    current_defaults = getattr(mod, "_force_live_defaults", None)
    if callable(current_defaults) and not getattr(current_defaults, _PATCH_ATTR, False):
        @wraps(current_defaults)
        def defaults_v388(*args: Any, **kwargs: Any):
            out = current_defaults(*args, **kwargs)
            _apply_fallback_env()
            return out
        setattr(defaults_v388, _PATCH_ATTR, True)
        mod._force_live_defaults = defaults_v388

    current_geometry = getattr(mod, "_safe_stop_geometry", None)
    if callable(current_geometry) and not getattr(current_geometry, _PATCH_ATTR, False):
        @wraps(current_geometry)
        def geometry_v388(side: str, position_size: float, entry_price: float,
                           stop_loss: float, levels: Any = None, kwargs: Any = None):
            entry = _f(entry_price)
            stop = _f(stop_loss)
            size = _f(position_size)
            if entry <= 0 or stop <= 0 or size <= 0:
                return current_geometry(side, position_size, entry_price, stop_loss, levels, kwargs)
            old_pct = abs(entry - stop) / entry
            context: dict[str, Any] = {}
            if isinstance(levels, Mapping):
                context.update(levels)
            if isinstance(kwargs, Mapping):
                context.update(kwargs)
            desired = hard_stop_pct(context, atr_pct=_atr_pct(context))
            new_pct = min(_MAX_STOP_PCT, max(old_pct, desired))
            if new_pct <= 0:
                return 0.0, stop, old_pct, new_pct
            short = str(side or "").lower() in {"short", "sell"}
            new_stop = entry * (1.0 + new_pct if short else 1.0 - new_pct)
            new_size = size * old_pct / new_pct if new_pct > old_pct > 0 else size
            return max(0.0, new_size), new_stop, old_pct, new_pct
        setattr(geometry_v388, _PATCH_ATTR, True)
        mod._safe_stop_geometry = geometry_v388

    _apply_fallback_env()
    return True


def _patch_v239() -> bool:
    mod = importlib.import_module("bot.runtime_all_account_profit_targets_v239_patch")
    current = getattr(mod, "_with_profit_targets", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def with_targets_v388(raw: Any):
        if not isinstance(raw, dict):
            return raw
        pos = dict(raw)
        entry = _entry(pos)
        qty = _qty(pos)
        if entry <= _EPS or qty <= _EPS:
            return pos
        tp1, tp2, tp3 = fallback_tp_pcts(pos)
        short = _side(pos) == "short"
        synthesized: list[str] = []
        for key, pct in (
            ("take_profit_1", tp1),
            ("take_profit_2", tp2),
            ("take_profit_3", tp3),
        ):
            if _f(pos.get(key)) > _EPS:
                continue
            pos[key] = entry * (1.0 - pct if short else 1.0 + pct)
            synthesized.append(key)
        if synthesized:
            pos["research_exit_policy_marker"] = MARKER
            pos["research_tp_r_multiples"] = _FALLBACK_TP_R
            pos["research_risk_unit_pct"] = risk_unit_pct(pos)
        return pos

    setattr(with_targets_v388, _PATCH_ATTR, True)
    setattr(with_targets_v388, "__wrapped__", current)
    mod._with_profit_targets = with_targets_v388

    def targets_v388() -> tuple[float, float, float]:
        baseline = {"entry_price": 100.0, "stop_loss": 98.5, "quantity": 1.0}
        return fallback_tp_pcts(baseline)
    setattr(targets_v388, _PATCH_ATTR, True)
    mod._targets = targets_v388
    return True


def _patch_v375() -> bool:
    mod = importlib.import_module("bot.runtime_universal_sl_tp_policy_v375_patch")
    current = getattr(mod, "_policy_row", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def policy_row_v388(raw: Any):
        row = current(raw)
        if not isinstance(row, Mapping):
            return row
        out = dict(row)
        if _entry(out) <= _EPS or _qty(out) <= _EPS:
            return out
        out.update(trailing_pcts(out))
        out["research_exit_policy_marker"] = MARKER
        out["research_risk_unit_pct"] = risk_unit_pct(out)
        out["software_trailing_stop_available"] = True
        out["software_trailing_take_profit_available"] = True
        out["universal_four_way_policy_complete"] = bool(
            _f(out.get("stop_loss")) > _EPS
            and any(_f(out.get(k)) > _EPS for k in (
                "take_profit", "take_profit_1", "take_profit_2", "take_profit_3"
            ))
        )
        return out

    setattr(policy_row_v388, _PATCH_ATTR, True)
    setattr(policy_row_v388, "__wrapped__", current)
    mod._policy_row = policy_row_v388
    return True


def _patch_v371() -> bool:
    mod = importlib.import_module("bot.runtime_kraken_margin_full_protection_v371_patch")
    current = getattr(mod, "_ensure_software_targets", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def ensure_v388(raw: Any):
        row = current(raw)
        if not isinstance(row, Mapping):
            return row
        out = dict(row)
        if not (
            out.get("kraken_margin_openpositions") is True
            or out.get("margin_position") is True
        ):
            return out
        if _entry(out) > _EPS and _qty(out) > _EPS:
            out.update(trailing_pcts(out))
            out["research_exit_policy_marker"] = MARKER
            out["research_risk_unit_pct"] = risk_unit_pct(out)
            out["software_trailing_stop_available"] = True
            out["software_trailing_take_profit_available"] = True
            out["software_protection_targets_complete"] = bool(
                out.get("software_protection_identity_verified")
                and _f(out.get("stop_loss")) > _EPS
                and any(_f(out.get(k)) > _EPS for k in (
                    "take_profit", "take_profit_1", "take_profit_2", "take_profit_3"
                ))
            )
        return out

    setattr(ensure_v388, _PATCH_ATTR, True)
    setattr(ensure_v388, "__wrapped__", current)
    mod._ensure_software_targets = ensure_v388
    return True


def _patch_trailing_stop_worker() -> bool:
    mod = importlib.import_module("bot.trailing_stop_loss_runtime_patch")
    current = getattr(mod, "_update_trailing_state", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def update_v388(engine: Any, pos: dict[str, Any], price: float):
        symbol = str(pos.get("symbol") or "").strip().upper().replace("/", "-").replace("_", "-")
        position_id = str(pos.get("position_id") or symbol)
        key = f"{position_id}:{symbol}"
        entry = _entry(pos)
        side = _side(pos)
        settings = trailing_pcts(pos)
        distance = _f(settings["trailing_stop_distance_pct"])
        activation = _f(settings["trailing_stop_activation_pct"])
        st = mod._state(engine)
        row = st.get(key)
        if row is None:
            row = {
                "highest": max(entry, price),
                "lowest": min(entry if entry > 0 else price, price),
                "stop": _f(pos.get("stop_loss")),
                "activated": 0.0,
            }
            st[key] = row
        if side == "long":
            row["highest"] = max(_f(row.get("highest")), price)
            if entry > 0 and row["highest"] >= entry * (1.0 + activation):
                row["activated"] = 1.0
            candidate = row["highest"] * (1.0 - distance)
            if candidate > _f(row.get("stop")):
                row["stop"] = candidate
            hit = bool(row.get("activated")) and _f(row.get("stop")) > 0 and price <= _f(row.get("stop"))
        else:
            row["lowest"] = min(_f(row.get("lowest"), price), price)
            if entry > 0 and row["lowest"] <= entry * (1.0 - activation):
                row["activated"] = 1.0
            candidate = row["lowest"] * (1.0 + distance)
            current_stop = _f(row.get("stop"))
            if current_stop <= 0 or candidate < current_stop:
                row["stop"] = candidate
            hit = bool(row.get("activated")) and _f(row.get("stop")) > 0 and price >= _f(row.get("stop"))
        row["research_exit_policy_marker"] = MARKER
        return hit, row

    setattr(update_v388, _PATCH_ATTR, True)
    setattr(update_v388, "__wrapped__", current)
    mod._update_trailing_state = update_v388
    return True


def _patch_trailing_tp_worker() -> bool:
    mod = importlib.import_module("bot.trailing_take_profit_runtime_patch")
    armed_current = getattr(mod, "_armed", None)
    track_current = getattr(mod, "_track", None)
    if not callable(armed_current) or not callable(track_current):
        return False

    if not getattr(armed_current, _PATCH_ATTR, False):
        @wraps(armed_current)
        def armed_v388(position: dict[str, Any], price: float) -> bool:
            entry = _entry(position)
            if entry <= _EPS:
                return False
            activation = _f(trailing_pcts(position)["trailing_take_profit_activation_pct"])
            return (
                price <= entry * (1.0 - activation)
                if _side(position) == "short"
                else price >= entry * (1.0 + activation)
            )
        setattr(armed_v388, _PATCH_ATTR, True)
        mod._armed = armed_v388

    if not getattr(track_current, _PATCH_ATTR, False):
        @wraps(track_current)
        def track_v388(position: dict[str, Any], row: dict[str, Any], price: float):
            callback = _f(trailing_pcts(position)["trailing_take_profit_callback_pct"])
            if _side(position) == "short":
                best = min(_f(row.get("best"), price), price)
                row["best"] = best
                trigger = best * (1.0 + callback)
                return price >= trigger, best, trigger
            best = max(_f(row.get("best"), price), price)
            row["best"] = best
            trigger = best * (1.0 - callback)
            return price <= trigger, best, trigger
        setattr(track_v388, _PATCH_ATTR, True)
        mod._track = track_v388
    return True


def _patch_execution_exit_config() -> bool:
    try:
        mod = importlib.import_module("bot.execution_exit_config")
    except Exception:
        return False
    cls = getattr(mod, "ExecutionExitConfig", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "get_exit_params", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def get_exit_params_v388(self: Any, regime: Any = None, entry_type: str = "swing",
                              broker: str = "coinbase", trades_per_hour: float = 2.0,
                              atr_pct: float = 0.0):
        params = current(
            self,
            regime=regime,
            entry_type=entry_type,
            broker=broker,
            trades_per_hour=trades_per_hour,
            atr_pct=atr_pct,
        )
        stop = getattr(params, "stop", None)
        tp = getattr(params, "tp", None)
        r = _f(getattr(stop, "hard_sl_pct", 0.0))
        atr = atr_pct if atr_pct > 0 else _f(getattr(stop, "atr_pct", 0.0))
        desired = hard_stop_pct({}, atr_pct=atr)
        new_r = min(_MAX_STOP_PCT, max(r, desired))
        if stop is not None:
            stop.hard_sl_pct = round(new_r, 4)
            stop.atr_sl_applied = bool(atr > 0 and new_r > r + 1e-12)
            stop.trailing_activate_pct = round(new_r, 4)
            stop.trailing_buffer_pct = round(max(new_r, _TRAIL_SL_ATR_MULT * atr if atr > 0 else 0.0), 4)
        if tp is not None and hasattr(tp, "levels"):
            fractions = [0.50, 0.25, 0.25]
            tp.levels = [
                mod.TPLevel(target_pct=round(mult * new_r, 4), exit_fraction=fractions[i])
                for i, mult in enumerate(_STRATEGY_TP_R)
            ]
        return params

    setattr(get_exit_params_v388, _PATCH_ATTR, True)
    setattr(get_exit_params_v388, "__wrapped__", current)
    cls.get_exit_params = get_exit_params_v388
    return True


def _patch_auto_exit_effective_stop() -> bool:
    mod = importlib.import_module("bot.auto_exit_sl_tp_runtime_patch")
    current = getattr(mod, "_effective_stop", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def effective_stop_v388(pos: dict[str, Any], price: float):
        explicit = _f(pos.get("stop_loss"))
        if explicit > _EPS:
            return current(pos, price)
        existing_stop, existing_source = current(pos, price)
        entry = _entry(pos)
        qty = _qty(pos)
        if entry <= _EPS or qty <= _EPS:
            return existing_stop, existing_source
        pct = hard_stop_pct(pos)
        short = _side(pos) == "short"
        adaptive = entry * (1.0 + pct if short else 1.0 - pct)
        if _f(existing_stop) > _EPS:
            chosen = min(existing_stop, adaptive) if short else max(existing_stop, adaptive)
        else:
            chosen = adaptive
        return chosen, "research_atr_stop_capped_by_existing_loss_cap"

    setattr(effective_stop_v388, _PATCH_ATTR, True)
    setattr(effective_stop_v388, "__wrapped__", current)
    mod._effective_stop = effective_stop_v388
    return True


def install_import_hook() -> bool:
    """Patch every live exit owner. Idempotent and safe to reassert."""
    _apply_fallback_env()
    results: dict[str, bool] = {}
    for name, fn in (
        ("profit_first", _patch_profit_first),
        ("v239", _patch_v239),
        ("v375", _patch_v375),
        ("v371", _patch_v371),
        ("trailing_sl_worker", _patch_trailing_stop_worker),
        ("trailing_tp_worker", _patch_trailing_tp_worker),
        ("execution_exit_config", _patch_execution_exit_config),
        ("auto_exit_stop", _patch_auto_exit_effective_stop),
    ):
        try:
            results[name] = bool(fn())
        except Exception as exc:
            results[name] = False
            LOGGER.exception(
                "RESEARCH_ADAPTIVE_EXIT_V388_PATCH_FAILED marker=%s component=%s error=%s:%s",
                MARKER, name, type(exc).__name__, exc,
            )

    required = ("v239", "v375", "trailing_sl_worker", "auto_exit_stop")
    ready = all(results.get(name, False) for name in required)
    os.environ[_READY_FLAG] = "1" if ready else "0"
    if ready:
        LOGGER.critical(
            "RESEARCH_ADAPTIVE_EXIT_V388_READY marker=%s hard_stop=ATRx%.2f cap=%.4f "
            "fallback_tp_R=%s strategy_tp_R=%s trailing_sl=arm_%.2fR_distance_max_R_ATRx%.2f "
            "trailing_tp=arm_%.2fR_callback_max_%.2fR_ATRx%.2f "
            "explicit_targets_preserved=true dollar_loss_caps_preserved=true "
            "profit_not_guaranteed=true safety_gates_bypassed=false components=%s",
            MARKER, _ATR_STOP_MULT, _MAX_STOP_PCT,
            _FALLBACK_TP_R, _STRATEGY_TP_R,
            _TRAIL_SL_ARM_R, _TRAIL_SL_ATR_MULT,
            _TRAIL_TP_ARM_R, _TRAIL_TP_CALLBACK_R, _TRAIL_TP_ATR_MULT,
            results,
        )
    else:
        LOGGER.error(
            "RESEARCH_ADAPTIVE_EXIT_V388_NOT_READY marker=%s results=%s "
            "new_entries_should_remain_fail_closed=true existing_exits_preserved=true",
            MARKER, results,
        )
    return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER", "install", "install_import_hook", "hard_stop_pct", "risk_unit_pct",
    "fallback_tp_pcts", "trailing_pcts",
]
