from __future__ import annotations

import builtins
import logging
import os
import sys
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.closed_candle_volume_repair")
_MARKER = "20260709q"
_PATCH_ATTR = "_nija_closed_candle_volume_repair_v20260709q"
_HOOK_FLAG = "_NIJA_CLOSED_CANDLE_VOLUME_REPAIR_HOOK_V20260709Q"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUE


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


def _columns(df: Any) -> set[str]:
    try:
        return {str(c) for c in getattr(df, "columns", [])}
    except Exception:
        return set()


def _ensure_volume_column(df: Any) -> tuple[Any, bool, str]:
    cols = _columns(df)
    if "volume" in cols:
        return df, False, "volume"
    for candidate in ("vol", "Volume", "VOL", "base_volume", "baseVolume", "volume_base", "qty", "quantity"):
        if candidate in cols:
            try:
                df = df.copy()
                df["volume"] = df[candidate]
                return df, True, candidate
            except Exception:
                return df, False, "copy_failed"
    return df, False, "missing"


def _price_action_proxy_allowed(df: Any) -> bool:
    if not _truthy("NIJA_PRICE_ACTION_VOLUME_PROXY", "true"):
        return False
    try:
        if "close" not in df.columns or len(df) < 50:
            return False
        close = df["close"].astype(float).tail(30)
        if len(close) < 10:
            return False
        if float(close.max() or 0.0) <= 0.0:
            return False
        returns = close.pct_change().abs().dropna()
        avg_abs = float(returns.mean() or 0.0) if len(returns) else 0.0
        if avg_abs >= _f(os.environ.get("NIJA_PRICE_ACTION_VOLUME_PROXY_MIN_RETURN"), 0.00001):
            return True
        if {"high", "low"}.issubset(df.columns):
            high = df["high"].astype(float).tail(30)
            low = df["low"].astype(float).tail(30)
            rng = ((high - low).abs() / close.replace(0, float("nan"))).dropna()
            return bool(len(rng) and float(rng.mean() or 0.0) >= _f(os.environ.get("NIJA_PRICE_ACTION_VOLUME_PROXY_MIN_RANGE"), 0.00001))
    except Exception:
        return False
    return False


def repair_dataframe(df: Any, *, symbol: str = "", broker: str = "") -> Any:
    if df is None or not _truthy("NIJA_CLOSED_CANDLE_VOLUME_REPAIR", "true"):
        return df
    try:
        if len(df) < 50:
            return df
        df, copied, source = _ensure_volume_column(df)
        if "volume" not in _columns(df):
            return df
        # Work on a copy only when changing values so callers do not see hidden side effects.
        vol = df["volume"].astype(float)
        last_volume = _f(vol.iloc[-1], 0.0)
        if last_volume > 0.0:
            return df
        prev = vol.iloc[:-1].tail(30)
        positives = prev[prev > 0.0]
        if len(positives) > 0:
            repaired_value = max(_f(positives.iloc[-1], 0.0), _f(positives.median(), 0.0))
            if repaired_value > 0.0:
                out = df.copy()
                out.loc[out.index[-1], "volume"] = repaired_value
                try:
                    out.attrs["nija_volume_repair"] = f"closed_candle_last_positive:{_MARKER}"
                except Exception:
                    pass
                logger.critical(
                    "CLOSED_CANDLE_VOLUME_REPAIRED marker=%s broker=%s symbol=%s source=%s old_last=%.8f new_last=%.8f rows=%d",
                    _MARKER,
                    broker,
                    symbol,
                    source,
                    last_volume,
                    repaired_value,
                    len(out),
                )
                return out
        # Some exchange REST surfaces return full OHLC price rows but zero/missing
        # volume on the open candle. If all recent volume is zero yet price action
        # is real, use a synthetic proxy volume so the current-open candle does not
        # falsely block every symbol before AI scoring. Risk, spread, expectancy,
        # venue-cash and broker ACK gates still run after this.
        if _price_action_proxy_allowed(df):
            out = df.copy()
            proxy_value = max(1.0, _f(os.environ.get("NIJA_PRICE_ACTION_VOLUME_PROXY_VALUE"), 1.0))
            tail_n = min(20, len(out))
            out.loc[out.index[-tail_n:], "volume"] = proxy_value
            try:
                out.attrs["nija_volume_repair"] = f"price_action_proxy:{_MARKER}"
            except Exception:
                pass
            logger.critical(
                "PRICE_ACTION_VOLUME_PROXY_APPLIED marker=%s broker=%s symbol=%s rows=%d proxy_volume=%.4f reason=ohlc_price_action_with_zero_volume",
                _MARKER,
                broker,
                symbol,
                len(out),
                proxy_value,
            )
            print(
                f"[NIJA-PRINT] PRICE_ACTION_VOLUME_PROXY_APPLIED marker={_MARKER} broker={broker} symbol={symbol} rows={len(out)}",
                flush=True,
            )
            return out
        if copied:
            return df
    except Exception as exc:
        logger.debug("CLOSED_CANDLE_VOLUME_REPAIR_SKIPPED marker=%s symbol=%s err=%s", _MARKER, symbol, exc)
    return df


def _broker_name(obj: Any) -> str:
    for attr in ("name", "broker_name", "exchange", "venue"):
        value = str(getattr(obj, attr, "") or "").strip().lower()
        if value:
            return value
    return type(obj).__name__.lower()


def _patch_core_loop_module(module: ModuleType) -> bool:
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_fetch_df", None)
    if not callable(original) or getattr(original, _PATCH_ATTR, False):
        return bool(getattr(original, _PATCH_ATTR, False))

    @wraps(original)
    def _fetch_df(self: Any, broker: Any, symbol: str, *args: Any, **kwargs: Any):
        df = original(self, broker, symbol, *args, **kwargs)
        return repair_dataframe(df, symbol=str(symbol or ""), broker=_broker_name(broker))

    setattr(_fetch_df, _PATCH_ATTR, True)
    setattr(_fetch_df, "__wrapped__", original)
    setattr(cls, "_fetch_df", _fetch_df)
    logger.warning("CLOSED_CANDLE_VOLUME_REPAIR_PATCHED marker=%s module=%s class=NijaCoreLoop", _MARKER, getattr(module, "__name__", ""))
    print(f"[NIJA-PRINT] CLOSED_CANDLE_VOLUME_REPAIR_PATCHED marker={_MARKER}", flush=True)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name, module in list(sys.modules.items()):
        if isinstance(module, ModuleType) and (name.endswith("nija_core_loop") or hasattr(module, "NijaCoreLoop")):
            try:
                patched = _patch_core_loop_module(module) or patched
            except Exception as exc:
                logger.warning("CLOSED_CANDLE_VOLUME_REPAIR_PATCH_FAILED marker=%s module=%s err=%s", _MARKER, name, exc)
    return patched


def install_import_hook() -> None:
    _try_patch_loaded()
    if getattr(builtins, _HOOK_FLAG, False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if "nija_core_loop" in str(name) or "core_loop" in str(name):
                _try_patch_loaded()
        except Exception as exc:
            logger.warning("CLOSED_CANDLE_VOLUME_REPAIR_IMPORT_HOOK_FAILED marker=%s name=%s err=%s", _MARKER, name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, _HOOK_FLAG, True)
    logger.warning("CLOSED_CANDLE_VOLUME_REPAIR_IMPORT_HOOK marker=%s", _MARKER)


def install() -> None:
    install_import_hook()
