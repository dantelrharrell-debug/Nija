"""Adaptive, fee-safe profit exit authority v74.

The existing v68 net-profit floor is the economic floor for a winning exit.  In
strong favorable regimes, however, treating that floor as an immediate fixed TP
can truncate extended trends.  v74 converts that floor into a trailing
*activation* threshold only when all of the following are proven:

* the exit is a normal profit exit (never a protective stop/emergency exit);
* the market has already crossed the v68 fee/slippage-adjusted net-profit floor;
* the current regime is favorable to the position and confidence is sufficient;
* a scoped high-water mark can be maintained for account + broker + position.

The giveback distance is volatility/regime adaptive using ATR when available and
is bounded.  If the regime weakens after arming, NIJA banks the already-proven
net profit rather than waiting for a wider trend trail.

Learning is conservative and account/broker/regime scoped.  Confirmed closed
trades update realized outcome statistics.  Automatic trail adaptation is
sample-gated and bounded to +/-10%; hard risk limits, writer authority, broker
state, and entry rules are never learned away.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import math
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any, Mapping

from bot import universal_net_profit_exit_floor_v68_patch as v68

LOGGER = logging.getLogger("nija.adaptive_profit_exit_v74")
MARKER = "20260809-adaptive-profit-exit-v74"
_PATCH_ATTR = "_nija_adaptive_profit_exit_v74"
_LOCK = threading.RLock()
_STATE_KEY = "_NIJA_ADAPTIVE_PROFIT_EXIT_V74_STATE"
if not hasattr(builtins, _STATE_KEY):
    setattr(builtins, _STATE_KEY, {"positions": {}, "stats": {}})
_STATE: dict[str, Any] = getattr(builtins, _STATE_KEY)
_POSITIONS: dict[str, dict[str, Any]] = _STATE["positions"]
_STATS: dict[str, dict[str, float]] = _STATE["stats"]


def _f(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value or 0.0)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if math.isfinite(result) else default


def _account(universal: ModuleType, broker: Any, pos: Mapping[str, Any]) -> str:
    for value in (
        pos.get("account_id"), pos.get("user_id"), pos.get("account_name"),
        getattr(broker, "account_id", None), getattr(broker, "user_id", None),
        getattr(broker, "account_name", None),
    ):
        text = str(value or "").strip().lower()
        if text:
            return text
    return "platform"


def _position_key(universal: ModuleType, broker: Any, pos: Mapping[str, Any]) -> str:
    venue = v68._broker_label(universal, broker)
    account = _account(universal, broker, pos)
    symbol = universal.auto_exit._sym(pos.get("symbol"))
    pid = str(pos.get("position_id") or pos.get("id") or symbol).strip()
    return f"{account}:{venue}:{pid}:{symbol}"


def _regime_snapshot(pos: Mapping[str, Any]) -> tuple[str, float]:
    explicit = str(pos.get("market_regime") or pos.get("regime") or "").strip().lower()
    explicit_conf = _f(pos.get("regime_confidence"), 0.0)
    if explicit:
        return explicit, max(0.0, min(1.0, explicit_conf or 0.60))
    try:
        module = importlib.import_module("bot.regime_intelligence")
        engine = module.get_regime_intelligence_engine()
        snap = engine.get_current_regime()
        if snap is not None:
            label = str(getattr(getattr(snap, "regime", ""), "value", getattr(snap, "regime", ""))).strip().lower()
            return label or "unknown", max(0.0, min(1.0, _f(getattr(snap, "confidence", 0.0))))
    except Exception:
        pass
    return "unknown", 0.0


def _atr_pct(pos: Mapping[str, Any], entry: float) -> float:
    direct = max(
        _f(pos.get("atr_pct")),
        _f(pos.get("atr_percent")) / 100.0 if _f(pos.get("atr_percent")) > 1.0 else _f(pos.get("atr_percent")),
        _f(pos.get("volatility_pct")) / 100.0 if _f(pos.get("volatility_pct")) > 1.0 else _f(pos.get("volatility_pct")),
    )
    if direct > 0.0:
        return direct
    atr = max(_f(pos.get("atr")), _f(pos.get("current_atr")), _f(pos.get("entry_atr")))
    if atr > 0.0 and entry > 0.0:
        return atr / entry
    return 0.0


def _baseline_multiplier(regime: str) -> float:
    defaults = {
        "bull_trending": 1.50,
        "bear_trending": 1.50,
        "breakout": 2.00,
        "volatile": 2.00,
        "ranging": 0.90,
        "unknown": 1.20,
    }
    try:
        module = importlib.import_module("bot.regime_intelligence")
        enum_cls = getattr(module, "Regime")
        regime_enum = enum_cls(regime)
        params = module.get_regime_intelligence_engine().get_regime_parameters(regime_enum)
        value = _f(getattr(params, "trailing_stop_atr_multiplier", 0.0))
        if value > 0.0:
            return value
    except Exception:
        pass
    return defaults.get(regime, 1.20)


def _scope_key(universal: ModuleType, broker: Any, pos: Mapping[str, Any], regime: str) -> str:
    return f"{_account(universal, broker, pos)}:{v68._broker_label(universal, broker)}:{regime}"


def _learning_factor(universal: ModuleType, broker: Any, pos: Mapping[str, Any], regime: str) -> float:
    key = _scope_key(universal, broker, pos, regime)
    with _LOCK:
        stats = dict(_STATS.get(key, {}) or {})
    trades = int(stats.get("trades", 0.0) or 0.0)
    if trades < max(20, int(_f(os.environ.get("NIJA_EXIT_LEARNING_MIN_TRADES"), 30.0))):
        return 1.0
    wins = float(stats.get("wins", 0.0) or 0.0)
    pnl = float(stats.get("total_pnl", 0.0) or 0.0)
    win_rate = wins / trades if trades > 0 else 0.0
    avg_pnl = pnl / trades if trades > 0 else 0.0
    # Bounded adaptation only.  A weak realized history tightens giveback;
    # a strong history permits a little more room for trend continuation.
    if avg_pnl <= 0.0 or win_rate < 0.45:
        return 0.90
    if avg_pnl > 0.0 and win_rate >= 0.60:
        return 1.10
    return 1.0


def _trail_pct(universal: ModuleType, broker: Any, pos: Mapping[str, Any], regime: str, entry: float) -> float:
    atr_pct = _atr_pct(pos, entry)
    base = atr_pct * _baseline_multiplier(regime) if atr_pct > 0.0 else _f(
        os.environ.get("NIJA_ADAPTIVE_EXIT_DEFAULT_TRAIL_PCT"), 0.015
    )
    base *= _learning_factor(universal, broker, pos, regime)
    low = max(0.0025, _f(os.environ.get("NIJA_ADAPTIVE_EXIT_MIN_TRAIL_PCT"), 0.0060))
    high = min(0.15, max(low, _f(os.environ.get("NIJA_ADAPTIVE_EXIT_MAX_TRAIL_PCT"), 0.0600)))
    return min(high, max(low, base))


def _favorable_regime(regime: str, confidence: float, short: bool) -> bool:
    minimum = max(0.50, min(0.95, _f(os.environ.get("NIJA_ADAPTIVE_EXIT_MIN_REGIME_CONFIDENCE"), 0.60)))
    if confidence < minimum:
        return False
    if regime == "breakout":
        return True
    if short:
        return regime == "bear_trending"
    return regime == "bull_trending"


def _update_peak(universal: ModuleType, broker: Any, pos: Mapping[str, Any], market: float, short: bool, regime: str) -> dict[str, Any]:
    key = _position_key(universal, broker, pos)
    with _LOCK:
        state = _POSITIONS.setdefault(key, {"peak": market, "trough": market, "armed": False, "regime": regime})
        state["peak"] = max(_f(state.get("peak"), market), market)
        state["trough"] = min(_f(state.get("trough"), market), market)
        state["regime"] = regime
        state["market"] = market
        state["short"] = short
        return dict(state)


def _giveback(state: Mapping[str, Any], market: float, short: bool) -> float:
    if short:
        trough = _f(state.get("trough"), market)
        return max(0.0, (market - trough) / trough) if trough > 0.0 else 0.0
    peak = _f(state.get("peak"), market)
    return max(0.0, (peak - market) / peak) if peak > 0.0 else 0.0


def _arm(universal: ModuleType, broker: Any, pos: Mapping[str, Any]) -> None:
    key = _position_key(universal, broker, pos)
    with _LOCK:
        _POSITIONS.setdefault(key, {})["armed"] = True


def _is_armed(universal: ModuleType, broker: Any, pos: Mapping[str, Any]) -> bool:
    key = _position_key(universal, broker, pos)
    with _LOCK:
        return bool((_POSITIONS.get(key) or {}).get("armed", False))


def _patch_universal(module: ModuleType) -> bool:
    current = getattr(module, "_trigger", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def adaptive_trigger(broker: Any, pos: dict[str, Any], market: float):
        hit, reason, target = current(broker, pos, market)
        kind = v68._reason_kind(reason) if hit else "none"
        if hit and kind == "protective":
            return hit, reason, target

        break_even, net_target, details = v68._floors(module, broker, pos)
        entry = _f(details.get("entry")) if details else module.auto_exit._entry_price(pos)
        if entry <= 0.0 or break_even <= 0.0 or net_target <= 0.0:
            return hit, reason, target
        short = bool(details.get("short"))
        regime, confidence = _regime_snapshot(pos)
        state = _update_peak(module, broker, pos, market, short, regime)
        favorable = _favorable_regime(regime, confidence, short)
        profitable = v68._meets(market, net_target, short)

        # In a strong favorable regime, the v68 net-profit target becomes the
        # activation floor for a volatility-aware trailing exit.
        if profitable and favorable:
            if not _is_armed(module, broker, pos):
                _arm(module, broker, pos)
                LOGGER.critical(
                    "ADAPTIVE_PROFIT_EXIT_V74_ARMED marker=%s venue=%s account=%s symbol=%s "
                    "regime=%s confidence=%.3f market=%.8f net_floor=%.8f",
                    MARKER, v68._broker_label(module, broker), _account(module, broker, pos),
                    module.auto_exit._sym(pos.get("symbol")), regime, confidence, market, net_target,
                )
            state = _update_peak(module, broker, pos, market, short, regime)
            trail = _trail_pct(module, broker, pos, regime, entry)
            giveback = _giveback(state, market, short)
            if giveback >= trail and v68._meets(market, break_even, short):
                LOGGER.critical(
                    "ADAPTIVE_PROFIT_EXIT_V74_TRIGGERED marker=%s venue=%s account=%s symbol=%s "
                    "reason=volatility_trailing_profit regime=%s confidence=%.3f giveback=%.5f trail=%.5f "
                    "market=%.8f break_even=%.8f",
                    MARKER, v68._broker_label(module, broker), _account(module, broker, pos),
                    module.auto_exit._sym(pos.get("symbol")), regime, confidence, giveback, trail,
                    market, break_even,
                )
                return True, "adaptive_volatility_trailing_profit", break_even
            # Suppress a normal fixed TP while a high-confidence favorable trend
            # remains intact.  Existing trailing/protective triggers are not suppressed.
            if kind in {"profit", "other", "none"}:
                return False, "", 0.0

        # Once armed, a regime deterioration is itself a reason to bank the
        # already-proven net profit rather than giving back a former trend.
        if _is_armed(module, broker, pos) and not favorable and v68._meets(market, break_even, short):
            LOGGER.critical(
                "ADAPTIVE_PROFIT_EXIT_V74_REGIME_EXIT marker=%s venue=%s account=%s symbol=%s "
                "regime=%s confidence=%.3f market=%.8f break_even=%.8f",
                MARKER, v68._broker_label(module, broker), _account(module, broker, pos),
                module.auto_exit._sym(pos.get("symbol")), regime, confidence, market, break_even,
            )
            return True, "adaptive_regime_profit_exit", break_even

        return hit, reason, target

    setattr(adaptive_trigger, _PATCH_ATTR, True)
    setattr(adaptive_trigger, "__wrapped__", current)
    module._trigger = adaptive_trigger
    LOGGER.critical(
        "ADAPTIVE_PROFIT_EXIT_V74_PATCHED marker=%s module=%s "
        "net_floor_activation=true volatility_trailing=true protective_exits_unchanged=true",
        MARKER,
        module.__name__,
    )
    return True


def record_confirmed_exit(universal: ModuleType, broker: Any, pos: Mapping[str, Any], fill_price: float, fee: float = 0.0) -> None:
    entry = universal.auto_exit._entry_price(dict(pos))
    qty = universal.auto_exit._quantity(dict(pos))
    if entry <= 0.0 or qty <= 0.0 or fill_price <= 0.0:
        return
    short = universal.auto_exit._side(pos.get("side"), dict(pos)) in {"short", "sell"}
    gross = (entry - fill_price) * qty if short else (fill_price - entry) * qty
    pnl = gross - max(0.0, fee)
    regime, _confidence = _regime_snapshot(pos)
    key = _scope_key(universal, broker, pos, regime)
    with _LOCK:
        stats = _STATS.setdefault(key, {"trades": 0.0, "wins": 0.0, "total_pnl": 0.0})
        stats["trades"] = float(stats.get("trades", 0.0) or 0.0) + 1.0
        if pnl > 0.0:
            stats["wins"] = float(stats.get("wins", 0.0) or 0.0) + 1.0
        stats["total_pnl"] = float(stats.get("total_pnl", 0.0) or 0.0) + pnl
        _POSITIONS.pop(_position_key(universal, broker, pos), None)
    LOGGER.info(
        "ADAPTIVE_PROFIT_EXIT_V74_LEARNED marker=%s scope=%s regime=%s pnl=%+.4f confirmed_fill=true",
        MARKER, key, regime, pnl,
    )


def _patch_mark_closed(module: ModuleType) -> bool:
    current = getattr(module, "_mark_closed", None)
    if not callable(current) or getattr(current, _PATCH_ATTR, False):
        return bool(callable(current))

    @wraps(current)
    def mark_closed_learning(broker: Any, pos: dict[str, Any], order: dict[str, Any], reason: str, market: float):
        result = current(broker, pos, order, reason, market)
        fill = _f(module.auto_exit._get(order, "filled_price", "average_fill_price", "avg_price", "price", default=market), market)
        fee = _f(module.auto_exit._get(order, "fee", "commission", "fees", default=0.0), 0.0)
        record_confirmed_exit(module, broker, pos, fill, fee)
        return result

    setattr(mark_closed_learning, _PATCH_ATTR, True)
    setattr(mark_closed_learning, "__wrapped__", current)
    module._mark_closed = mark_closed_learning
    return True


def _patch_loaded() -> bool:
    changed = False
    for name in ("bot.universal_broker_exit_supervisor_patch", "universal_broker_exit_supervisor_patch"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            changed = _patch_universal(module) or changed
            changed = _patch_mark_closed(module) or changed
    return changed


def install_import_hook() -> bool:
    with _LOCK:
        v68.install_import_hook()
        _patch_loaded()
        flag = "_NIJA_ADAPTIVE_PROFIT_EXIT_V74_IMPORT_HOOK"
        if getattr(builtins, flag, False):
            return True
        original_import = builtins.__import__

        @wraps(original_import)
        def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
            result = original_import(name, globals, locals, fromlist, level)
            if "universal_broker_exit" in str(name):
                _patch_loaded()
            return result

        builtins.__import__ = guarded_import
        setattr(builtins, flag, True)
        os.environ["NIJA_ADAPTIVE_PROFIT_EXIT_V74_INSTALLED"] = "1"
        LOGGER.critical(
            "ADAPTIVE_PROFIT_EXIT_V74_INSTALLED marker=%s sample_gated_learning=true hard_risk_learning=false",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER", "install", "install_import_hook", "record_confirmed_exit",
    "_trail_pct", "_favorable_regime", "_learning_factor", "_POSITIONS", "_STATS",
]
