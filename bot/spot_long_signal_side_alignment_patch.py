from __future__ import annotations

import builtins
import logging
import math
import os
import sys
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.spot_long_signal_side_alignment")
_PATCHED_ATTR = "_nija_spot_long_signal_side_alignment_20260708c"
_HOOK_ATTR = "_NIJA_SPOT_LONG_SIGNAL_SIDE_ALIGNMENT_HOOK_20260708C"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}

_UNSUPPORTED_SHORT_TOKENS = (
    "does not support shorting",
    "spot market - long-only",
    "short_unsupported",
    "shorting for",
)
_TERMINAL_RISK_TOKENS = (
    "terminal_risk_hard_block",
    "portfolio exposure limit reached",
    "position blocked by risk engine",
    "hard sector limit",
    "daily loss",
    "weekly loss",
    "drawdown",
    "emergency_stop",
)


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUE


def _reason_text(result: Any) -> str:
    if isinstance(result, dict):
        return str(result.get("reason") or result.get("reason_code") or "")
    return str(result or "")


def _is_unsupported_spot_short_hold(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    if str(result.get("action") or "hold").lower() not in {"", "hold", "none"}:
        return False
    reason = _reason_text(result).lower()
    if any(token in reason for token in _TERMINAL_RISK_TOKENS):
        return False
    return any(token in reason for token in _UNSUPPORTED_SHORT_TOKENS)


def _last_float_from_df(df: Any, column: str, default: float = 0.0) -> float:
    try:
        series = df[column]
        if hasattr(series, "iloc") and len(series) > 0:
            value = float(series.iloc[-1])
            if math.isfinite(value) and value > 0:
                return value
    except Exception:
        pass
    return default


def _recent_atr_pct(df: Any, price: float) -> float:
    try:
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)
        prev_close = close.shift(1)
        tr = (high - low).abs().combine((high - prev_close).abs(), max).combine((low - prev_close).abs(), max)
        atr = float(tr.tail(14).mean())
        if price > 0 and math.isfinite(atr) and atr > 0:
            return max(0.0035, min(0.025, atr / price))
    except Exception:
        pass
    return 0.008


def _safe_balance(self_obj: Any, account_balance: Any) -> float:
    try:
        bal = float(account_balance or 0.0)
        if bal > 0:
            return bal
    except Exception:
        pass
    for attr in ("account_balance", "balance", "capital"):
        try:
            bal = float(getattr(self_obj, attr, 0.0) or 0.0)
            if bal > 0:
                return bal
        except Exception:
            pass
    return 0.0


def _build_conservative_long_payload(self_obj: Any, df: Any, symbol: str, account_balance: Any, original: dict[str, Any]) -> dict[str, Any]:
    price = _last_float_from_df(df, "close", 0.0)
    if price <= 0:
        return original
    bal = _safe_balance(self_obj, account_balance)
    # Conservative live-capital size.  Respect common venue floors without making
    # this patch aggressive: it only repairs direction mismatch, not risk sizing.
    min_order = 10.0
    try:
        broker_name = ""
        if callable(getattr(self_obj, "_get_broker_name", None)):
            broker_name = str(self_obj._get_broker_name() or "").lower()
        if broker_name == "coinbase":
            min_order = float(os.getenv("COINBASE_MIN_ORDER_USD", "1.0") or 1.0)
        elif broker_name == "kraken":
            min_order = float(os.getenv("KRAKEN_MIN_NOTIONAL_USD", os.getenv("MIN_TRADE_USD", "23.10")) or 23.10)
        elif broker_name == "okx":
            min_order = float(os.getenv("OKX_MIN_ORDER_USD", "10") or 10.0)
    except Exception:
        pass
    cap_pct = 0.05
    try:
        cap_pct = max(0.005, min(0.10, float(os.getenv("NIJA_SPOT_LONG_ALIGNMENT_SIZE_PCT", "0.05") or 0.05)))
    except Exception:
        cap_pct = 0.05
    size = max(min_order, bal * cap_pct) if bal > 0 else min_order
    if bal > 0:
        size = min(size, bal * 0.15)
    atr_pct = _recent_atr_pct(df, price)
    stop_loss = price * (1.0 - max(0.006, atr_pct * 1.2))
    take_profit = [
        price * 1.010,
        price * 1.016,
        price * 1.024,
    ]
    payload = dict(original)
    payload.update({
        "action": "enter_long",
        "entry_price": price,
        "position_size": float(size),
        "stop_loss": float(stop_loss),
        "take_profit": take_profit,
        "trailing_stop_pct": float(os.getenv("NIJA_SPOT_LONG_ALIGNMENT_TRAILING_PCT", "0.75") or 0.75),
        "confidence": float(payload.get("confidence") or 0.50),
        "fallback_entry": True,
        "side_alignment_repair": True,
        "reason": (
            "SPOT_LONG_SIGNAL_SIDE_ALIGNMENT: selected long signal preserved after "
            f"strategy-side short veto; original_reason={_reason_text(original)}"
        ),
    })
    return payload


def _patch_strategy_module(module: ModuleType) -> bool:
    cls = getattr(module, "NIJAApexStrategyV71", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "analyze_market", None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return bool(getattr(original, _PATCHED_ATTR, False))

    @wraps(original)
    def analyze_market(self: Any, df: Any, symbol: str, account_balance: Any = None, *args: Any, **kwargs: Any):
        result = original(self, df, symbol, account_balance, *args, **kwargs)
        try:
            if not _truthy("NIJA_SPOT_LONG_SIGNAL_SIDE_ALIGNMENT_ENABLED", "true"):
                return result
            if not _is_unsupported_spot_short_hold(result):
                return result
            repaired = _build_conservative_long_payload(self, df, str(symbol or ""), account_balance, result)
            if repaired is result or repaired.get("action") != "enter_long":
                return result
            logger.critical(
                "SPOT_LONG_SIGNAL_SIDE_ALIGNMENT_APPLIED marker=20260708c symbol=%s original_reason=%s action=enter_long size=$%.2f price=%.8f",
                symbol,
                _reason_text(result),
                float(repaired.get("position_size", 0.0) or 0.0),
                float(repaired.get("entry_price", 0.0) or 0.0),
            )
            return repaired
        except Exception as exc:
            logger.warning("SPOT_LONG_SIGNAL_SIDE_ALIGNMENT_ERROR marker=20260708c symbol=%s error=%s", symbol, exc)
            return result

    setattr(analyze_market, _PATCHED_ATTR, True)
    setattr(cls, "analyze_market", analyze_market)
    logger.warning("SPOT_LONG_SIGNAL_SIDE_ALIGNMENT_PATCHED marker=20260708c module=%s", getattr(module, "__name__", "unknown"))
    print("[NIJA-PRINT] SPOT_LONG_SIGNAL_SIDE_ALIGNMENT_PATCHED marker=20260708c", flush=True)
    return True


def _try_patch_loaded() -> None:
    for name in ("bot.nija_apex_strategy_v71", "nija_apex_strategy_v71"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                _patch_strategy_module(module)
            except Exception as exc:
                logger.warning("SPOT_LONG_SIGNAL_SIDE_ALIGNMENT_PATCH_FAILED marker=20260708c module=%s error=%s", name, exc)


def install_import_hook() -> None:
    os.environ.setdefault("NIJA_SPOT_LONG_SIGNAL_SIDE_ALIGNMENT_ENABLED", "true")
    _try_patch_loaded()
    if getattr(builtins, _HOOK_ATTR, False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if name.endswith("nija_apex_strategy_v71") or name in {"bot.nija_apex_strategy_v71", "nija_apex_strategy_v71"}:
                _try_patch_loaded()
            else:
                _try_patch_loaded()
        except Exception as exc:
            logger.warning("SPOT_LONG_SIGNAL_SIDE_ALIGNMENT_HOOK_ERROR marker=20260708c name=%s error=%s", name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, _HOOK_ATTR, True)
    logger.warning("SPOT_LONG_SIGNAL_SIDE_ALIGNMENT_IMPORT_HOOK marker=20260708c")


def install() -> None:
    install_import_hook()
