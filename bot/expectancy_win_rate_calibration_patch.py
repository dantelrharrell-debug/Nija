from __future__ import annotations

import builtins
import logging
import os
import sys
from functools import wraps
from types import ModuleType
from typing import Any, Optional

logger = logging.getLogger("nija.expectancy_win_rate_calibration")
_MARKER = "20260709m"
_EXEC_ACTION_ATTR = "_nija_expectancy_win_rate_execute_action_v20260709m"
_RESOLVER_ATTR = "_nija_expectancy_win_rate_resolver_v20260709m"
_TRUTHY = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in _TRUTHY


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        amount = float(value)
        if amount != amount:
            return default
        return amount
    except Exception:
        return default


def _prob(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        p = float(value)
        if p > 1.0:
            p /= 100.0
        if p <= 0.0:
            return None
        return max(0.01, min(0.99, p))
    except Exception:
        return None


def _score(payload: dict[str, Any]) -> tuple[float, str]:
    for key in ("composite_score", "signal_score", "entry_score", "score", "phase3_score", "ai_score"):
        if key not in payload:
            continue
        raw = _f(payload.get(key), 0.0)
        if raw > 1.0:
            return raw, key
        # score/confidence can sometimes arrive normalized to 0..1. Treat only
        # explicitly named score fields as a 0..100 source, not confidence.
        if raw > 0 and key in {"composite_score", "signal_score", "entry_score", "score", "phase3_score", "ai_score"}:
            return raw * 100.0, f"{key}_normalized"
    return 0.0, "missing"


def _confidence(payload: dict[str, Any]) -> float:
    for key in ("confidence", "ai_confidence", "gate_confidence"):
        c = _prob(payload.get(key))
        if c is not None:
            return c
    return -1.0


def _regime(payload: dict[str, Any]) -> str:
    return str(payload.get("regime") or payload.get("market_regime") or payload.get("regime_family") or "").strip().lower()


def _calibrated_from_payload(payload: dict[str, Any]) -> tuple[Optional[float], str]:
    score, score_key = _score(payload)
    if score <= 0.0:
        return None, "missing_score"

    # Conservative score-to-win-rate curve. This is intentionally bounded: it
    # can rescue strong approved signals that were stamped with a flat 50% fallback,
    # but it cannot manufacture >68% win rates or bypass negative-EV math.
    if score >= 75.0:
        p = 0.65
    elif score >= 60.0:
        p = 0.60
    elif score >= 50.0:
        p = 0.57
    elif score >= 40.0:
        p = 0.55
    elif score >= 35.0:
        p = 0.535
    else:
        return None, f"score_below_calibration_floor:{score:.2f}"

    adj = 0.0
    c = _confidence(payload)
    if c >= 0.80:
        adj += 0.015
    elif c >= 0.65:
        adj += 0.0075
    elif 0 <= c < 0.40:
        adj -= 0.015

    adx = _f(payload.get("adx"), 0.0)
    if adx >= 45:
        adj += 0.015
    elif adx >= 30:
        adj += 0.0075
    elif 0 < adx < 15:
        adj -= 0.010

    regime = _regime(payload)
    if any(token in regime for token in ("strong_trend", "trending", "uptrend", "momentum", "bull")):
        adj += 0.010
    elif any(token in regime for token in ("chop", "sideways", "ranging", "dead", "low_vol")):
        adj -= 0.020
    elif any(token in regime for token in ("volatile", "high_vol")):
        adj += 0.005

    spread = _f(payload.get("spread_pct"), -1.0)
    slippage = _f(payload.get("slippage_pct"), -1.0)
    # payloads may use decimal rates (0.001) or percentages (0.1). Normalize only for penalty checks.
    spread_rate = spread / 100.0 if spread > 1.0 else spread
    slippage_rate = slippage / 100.0 if slippage > 1.0 else slippage
    if spread_rate >= 0.004 or slippage_rate >= 0.004:
        adj -= 0.015

    calibrated = max(0.515, min(0.68, p + adj))
    return calibrated, f"score_calibrated:{score_key}={score:.2f} adj={adj:+.4f} marker={_MARKER}"


def calibrate_payload(payload: Any) -> Any:
    if not isinstance(payload, dict) or not _truthy("NIJA_EXPECTANCY_WIN_RATE_CALIBRATION", True):
        return payload

    explicit = None
    explicit_key = ""
    for key in ("expected_win_rate", "win_probability", "prob_win"):
        if key in payload:
            explicit = _prob(payload.get(key))
            explicit_key = key
            break

    # Only override the known bad case: a flat/uninformative 50% estimate. If a
    # signal carries a real model win probability above 51%, keep it.
    if explicit is not None and explicit > 0.510:
        return payload

    calibrated, source = _calibrated_from_payload(payload)
    if calibrated is None:
        return payload

    old_value = explicit if explicit is not None else None
    payload["expected_win_rate"] = calibrated
    payload["expected_win_rate_source"] = source
    payload["expected_win_rate_calibrated"] = True
    payload["expected_win_rate_previous"] = old_value
    payload["expected_win_rate_previous_key"] = explicit_key
    tp = payload.get("take_profit")
    if isinstance(tp, dict):
        tp["expected_win_rate"] = calibrated
        tp["expected_win_rate_source"] = source
    elif isinstance(tp, list):
        for item in tp:
            if isinstance(item, dict):
                item["expected_win_rate"] = calibrated
                item["expected_win_rate_source"] = source

    logger.critical(
        "EXPECTANCY_WIN_RATE_CALIBRATED marker=%s symbol=%s old=%s new=%.4f source=%s",
        _MARKER,
        payload.get("symbol") or payload.get("pair") or "",
        "missing" if old_value is None else f"{old_value:.4f}",
        calibrated,
        source,
    )
    print(
        f"[NIJA-PRINT] EXPECTANCY_WIN_RATE_CALIBRATED marker={_MARKER} symbol={payload.get('symbol') or payload.get('pair') or ''} old={'missing' if old_value is None else f'{old_value:.4f}'} new={calibrated:.4f}",
        flush=True,
    )
    return payload


def _patch_strategy_module(module: ModuleType) -> bool:
    patched = False
    for cls in list(vars(module).values()):
        if not isinstance(cls, type):
            continue
        original = getattr(cls, "execute_action", None)
        if not callable(original) or getattr(original, _EXEC_ACTION_ATTR, False):
            continue
        base = getattr(original, "__wrapped__", original)

        @wraps(base)
        def execute_action(self: Any, analysis: Any, symbol: str, *args: Any, __orig=base, **kwargs: Any) -> Any:
            if isinstance(analysis, dict):
                analysis.setdefault("symbol", symbol)
                analysis = calibrate_payload(analysis)
            return __orig(self, analysis, symbol, *args, **kwargs)

        setattr(execute_action, _EXEC_ACTION_ATTR, True)
        setattr(execute_action, "__wrapped__", base)
        setattr(cls, "execute_action", execute_action)
        patched = True
        logger.warning("EXPECTANCY_WIN_RATE_EXECUTE_ACTION_PATCHED marker=%s class=%s", _MARKER, getattr(cls, "__name__", cls))
    return patched


def _patch_execution_engine_module(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionEngine", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_resolve_expected_win_rate", None)
    if not callable(original) or getattr(original, _RESOLVER_ATTR, False):
        return bool(getattr(original, _RESOLVER_ATTR, False))
    base = getattr(original, "__wrapped__", original)

    @wraps(base)
    def _resolve_expected_win_rate(self: Any, take_profit_levels: dict[str, Any]) -> tuple[Any, str]:
        payload = take_profit_levels if isinstance(take_profit_levels, dict) else {}
        # If a previous surface already calibrated, preserve the richer source label.
        if payload.get("expected_win_rate_calibrated"):
            p = _prob(payload.get("expected_win_rate"))
            if p is not None:
                return p, str(payload.get("expected_win_rate_source") or f"calibrated:{_MARKER}")
        p, source = base(self, take_profit_levels)
        if p is not None and float(p) > 0.510:
            return p, source
        calibrated_payload = dict(payload)
        calibrated_payload.setdefault("expected_win_rate", p if p is not None else payload.get("expected_win_rate"))
        calibrated_payload = calibrate_payload(calibrated_payload)
        p2 = _prob(calibrated_payload.get("expected_win_rate"))
        if p2 is not None and (p is None or p2 > float(p)):
            return p2, str(calibrated_payload.get("expected_win_rate_source") or f"resolver_calibrated:{_MARKER}")
        return p, source

    setattr(_resolve_expected_win_rate, _RESOLVER_ATTR, True)
    setattr(_resolve_expected_win_rate, "__wrapped__", base)
    setattr(cls, "_resolve_expected_win_rate", _resolve_expected_win_rate)
    logger.warning("EXPECTANCY_WIN_RATE_RESOLVER_PATCHED marker=%s", _MARKER)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    try:
        modules = list(sys.modules.items())
    except RuntimeError:
        modules = list(dict(sys.modules).items())
    for name, module in modules:
        if not isinstance(module, ModuleType):
            continue
        try:
            if name.endswith(("nija_apex_strategy_v71", "trading_strategy", "apex_strategy")):
                patched = _patch_strategy_module(module) or patched
            if name.endswith("execution_engine"):
                patched = _patch_execution_engine_module(module) or patched
        except Exception as exc:
            logger.warning("EXPECTANCY_WIN_RATE_PATCH_FAILED marker=%s module=%s err=%s", _MARKER, name, exc)
    return patched


def install_import_hook() -> None:
    _try_patch_loaded()
    if getattr(builtins, "_NIJA_EXPECTANCY_WIN_RATE_CALIBRATION_HOOK_V20260709M", False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if any(token in str(name) for token in ("nija_apex_strategy_v71", "trading_strategy", "apex_strategy", "execution_engine")):
                _try_patch_loaded()
        except Exception as exc:
            logger.warning("EXPECTANCY_WIN_RATE_IMPORT_HOOK_FAILED marker=%s name=%s err=%s", _MARKER, name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_EXPECTANCY_WIN_RATE_CALIBRATION_HOOK_V20260709M", True)
    logger.warning("EXPECTANCY_WIN_RATE_CALIBRATION_IMPORT_HOOK marker=%s", _MARKER)


def install() -> None:
    install_import_hook()
