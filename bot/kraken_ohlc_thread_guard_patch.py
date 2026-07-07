from __future__ import annotations

import builtins
import json
import logging
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
from functools import wraps
from types import ModuleType
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.kraken_ohlc_thread_guard")
_MARKER = "KRAKEN_OHLC_THREAD_GUARD_PATCHED marker=20260707c mode=direct_rest_no_pykraken_threads"
_PATCHED_ATTR = "_nija_kraken_ohlc_thread_guard_20260707c"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}

# Shared lock prevents concurrent callers from racing into Kraken market-data calls.
# The patched path below no longer calls pykrakenapi.get_ohlc_data(), because that
# library path creates internal _fetch_ohlc threads and caused Railway to hit
# "can't start new thread".  We call Kraken's public OHLC REST endpoint directly.
_OHLC_GATE = threading.BoundedSemaphore(value=1)
_GLOBAL_COOLDOWN_UNTIL = 0.0
_LAST_SUCCESS_TS = 0.0

# Process-wide singleton guard for known NIJA background workers.  Several runtime
# patch modules can be imported more than once under different module names; module
# globals are not enough in that case, so this guard patches threading.Thread.start
# once and checks currently alive thread names before allowing duplicates.
_THREAD_START_PATCH_ATTR = "_NIJA_BACKGROUND_WORKER_THREAD_START_GUARD_20260707C"
_SINGLETON_WORKER_NAMES = {
    "authority-heartbeat-monitor",
    "startup-position-sync-retry",
    "nija.pre_halt_watchdog",
    "nija-trailing-stop",
    "nija-breakeven-stop",
    "nija-combo-be-trailing",
    "nija-trailing-take-profit",
    "nija-combined-trailing-tp-sl",
    "nija-auto-exit-sl-tp",
}


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUE


def _int_env(name: str, default: int) -> int:
    try:
        return int(float(os.environ.get(name, default)))
    except Exception:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except Exception:
        return default


def _csv_env(name: str, default: str) -> set[str]:
    raw = os.environ.get(name, default)
    return {item.strip() for item in str(raw).split(",") if item.strip()}


def _active_ohlc_threads() -> int:
    count = 0
    for thread in threading.enumerate():
        try:
            name = str(getattr(thread, "name", ""))
            target = str(getattr(thread, "_target", ""))
            if "_fetch_ohlc" in name or "_fetch_ohlc" in target:
                count += 1
        except Exception:
            continue
    return count


def _active_thread_named(name: str) -> bool:
    for thread in threading.enumerate():
        try:
            if thread is threading.current_thread():
                continue
            if str(getattr(thread, "name", "")) == name and thread.is_alive():
                return True
        except Exception:
            continue
    return False


def _install_background_worker_thread_guard() -> None:
    if getattr(threading.Thread, _THREAD_START_PATCH_ATTR, False):
        return

    original_start = threading.Thread.start

    @wraps(original_start)
    def guarded_start(self: threading.Thread, *args: Any, **kwargs: Any):
        worker_names = _csv_env(
            "NIJA_SINGLETON_BACKGROUND_WORKERS",
            ",".join(sorted(_SINGLETON_WORKER_NAMES)),
        )
        name = str(getattr(self, "name", "") or "")
        if name in worker_names and _active_thread_named(name):
            logger.warning(
                "WORKER_ALREADY_RUNNING worker=%s action=skip_duplicate_thread_start source=thread_start_guard marker=20260707c",
                name,
            )
            print(
                f"[NIJA-PRINT] WORKER_ALREADY_RUNNING worker={name} source=thread_start_guard marker=20260707c",
                flush=True,
            )
            return None
        return original_start(self, *args, **kwargs)

    threading.Thread.start = guarded_start  # type: ignore[assignment]
    setattr(threading.Thread, _THREAD_START_PATCH_ATTR, True)
    logger.warning("BACKGROUND_WORKER_THREAD_START_GUARD_INSTALLED marker=20260707c workers=%s", ",".join(sorted(_SINGLETON_WORKER_NAMES)))


def _timeframe_to_interval(timeframe: str) -> int:
    interval_map = {
        "1m": 1,
        "5m": 5,
        "15m": 15,
        "30m": 30,
        "1h": 60,
        "4h": 240,
        "1d": 1440,
    }
    return interval_map.get(str(timeframe or "5m").strip().lower(), 5)


def _convert_symbol(adapter: Any, symbol: str) -> str:
    converter = getattr(adapter, "_convert_to_kraken_symbol", None)
    if callable(converter):
        try:
            converted = str(converter(symbol) or "").strip().upper()
            if converted:
                return converted
        except Exception:
            pass
    return str(symbol or "").replace("-", "").replace("/", "").upper()


def _public_ohlc_rest(symbol: str, interval: int, timeout_s: float) -> Optional[Dict[str, Any]]:
    params = urllib.parse.urlencode({"pair": symbol, "interval": interval})
    url = f"https://api.kraken.com/0/public/OHLC?{params}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "NIJA-AI-Trading/ohlc-thread-guard-20260707c",
            "Accept": "application/json",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # nosec: public market-data endpoint
        raw = resp.read()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("unexpected Kraken OHLC response type")
    errors = payload.get("error") or []
    if errors:
        raise RuntimeError("Kraken OHLC public API error: " + ", ".join(map(str, errors)))
    result = payload.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("missing Kraken OHLC result")
    pair_key = next((key for key in result.keys() if key != "last"), None)
    if not pair_key:
        raise RuntimeError("missing Kraken OHLC pair payload")
    rows = result.get(pair_key) or []
    if not isinstance(rows, list):
        raise RuntimeError("unexpected Kraken OHLC rows type")
    return {"pair_key": pair_key, "rows": rows, "last": result.get("last")}


def _rows_to_candles(rows: List[Any], limit: int) -> List[Dict[str, float]]:
    candles: List[Dict[str, float]] = []
    for row in rows[-max(1, int(limit)) :]:
        try:
            candles.append(
                {
                    "timestamp": int(float(row[0])),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[6]),
                }
            )
        except Exception:
            continue
    return candles


def _patch_module(module: ModuleType) -> bool:
    cls = getattr(module, "KrakenBrokerAdapter", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "get_market_data", None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return bool(getattr(original, _PATCHED_ATTR, False))

    @wraps(original)
    def get_market_data(self: Any, symbol: str, timeframe: str = "5m", limit: int = 100):
        global _GLOBAL_COOLDOWN_UNTIL, _LAST_SUCCESS_TS

        if not _truthy("NIJA_KRAKEN_OHLC_THREAD_GUARD_ENABLED", "true"):
            return original(self, symbol, timeframe, limit)

        active = _active_ohlc_threads()
        max_active = max(0, _int_env("NIJA_KRAKEN_OHLC_MAX_ACTIVE_THREADS", 0))
        cooldown_s = max(10.0, _float_env("NIJA_KRAKEN_OHLC_SATURATION_COOLDOWN_S", 180.0))
        timeout_s = max(2.0, _float_env("NIJA_KRAKEN_OHLC_REST_TIMEOUT_S", _float_env("NIJA_OHLC_TIMEOUT_SECONDS", 8.0)))
        now = time.time()

        if now < _GLOBAL_COOLDOWN_UNTIL:
            logger.warning(
                "KRAKEN_OHLC_THREAD_GUARD_SKIP marker=20260707c symbol=%s active_threads=%d max_active=%d cooldown_remaining=%.1fs reason=global_ohlc_saturation",
                symbol,
                active,
                max_active,
                _GLOBAL_COOLDOWN_UNTIL - now,
            )
            return None

        if max_active >= 0 and active > max_active:
            _GLOBAL_COOLDOWN_UNTIL = now + cooldown_s
            logger.critical(
                "KRAKEN_OHLC_THREAD_GUARD_SATURATED marker=20260707c symbol=%s active_threads=%d max_active=%d cooldown_s=%.1f action=skip_kraken_ohlc",
                symbol,
                active,
                max_active,
                cooldown_s,
            )
            print(
                f"[NIJA-PRINT] KRAKEN_OHLC_THREAD_GUARD_SATURATED marker=20260707c active_threads={active} max_active={max_active} symbol={symbol}",
                flush=True,
            )
            return None

        if not _OHLC_GATE.acquire(blocking=False):
            logger.warning(
                "KRAKEN_OHLC_THREAD_GUARD_BACKPRESSURE marker=20260707c symbol=%s active_threads=%d reason=single_flight_busy",
                symbol,
                active,
            )
            return None

        try:
            kraken_symbol = _convert_symbol(self, symbol)
            interval = _timeframe_to_interval(timeframe)
            payload = _public_ohlc_rest(kraken_symbol, interval, timeout_s)
            if payload is None:
                return None
            candles = _rows_to_candles(payload.get("rows") or [], limit)
            if not candles:
                logger.warning(
                    "KRAKEN_OHLC_DIRECT_REST_EMPTY marker=20260707c symbol=%s kraken_symbol=%s interval=%s",
                    symbol,
                    kraken_symbol,
                    interval,
                )
                return None
            _LAST_SUCCESS_TS = time.time()
            logger.info(
                "KRAKEN_OHLC_DIRECT_REST_OK marker=20260707c symbol=%s kraken_symbol=%s candles=%d active_pykraken_threads=%d",
                symbol,
                kraken_symbol,
                len(candles),
                _active_ohlc_threads(),
            )
            return {"symbol": kraken_symbol, "timeframe": timeframe, "candles": candles}
        except Exception as exc:
            message = str(exc)
            if "can't start new thread" in message.lower():
                _GLOBAL_COOLDOWN_UNTIL = time.time() + cooldown_s
                logger.critical(
                    "KRAKEN_OHLC_THREAD_START_BLOCKED_AFTER_DIRECT_REST marker=20260707c symbol=%s cooldown_s=%.1f err=%s",
                    symbol,
                    cooldown_s,
                    exc,
                )
                return None
            logger.warning(
                "KRAKEN_OHLC_DIRECT_REST_FAILED marker=20260707c symbol=%s err=%s legacy_fallback=%s",
                symbol,
                exc,
                _truthy("NIJA_KRAKEN_OHLC_ALLOW_LEGACY_FALLBACK", "false"),
            )
            if _truthy("NIJA_KRAKEN_OHLC_ALLOW_LEGACY_FALLBACK", "false"):
                return original(self, symbol, timeframe, limit)
            return None
        finally:
            try:
                _OHLC_GATE.release()
            except Exception:
                pass

    setattr(get_market_data, _PATCHED_ATTR, True)
    setattr(cls, "get_market_data", get_market_data)
    logger.warning("%s class=KrakenBrokerAdapter", _MARKER)
    print("[NIJA-PRINT] KRAKEN_OHLC_THREAD_GUARD_PATCHED marker=20260707c mode=direct_rest_no_pykraken_threads", flush=True)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.broker_integration", "broker_integration"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_module(module) or patched
    return patched


def install_import_hook() -> None:
    os.environ.setdefault("NIJA_KRAKEN_OHLC_THREAD_GUARD_ENABLED", "true")
    os.environ.setdefault("NIJA_KRAKEN_OHLC_MAX_ACTIVE_THREADS", "0")
    os.environ.setdefault("NIJA_KRAKEN_OHLC_SATURATION_COOLDOWN_S", "180")
    os.environ.setdefault("NIJA_KRAKEN_OHLC_REST_TIMEOUT_S", os.environ.get("NIJA_OHLC_TIMEOUT_SECONDS", "8"))
    os.environ.setdefault("NIJA_KRAKEN_OHLC_ALLOW_LEGACY_FALLBACK", "false")
    _install_background_worker_thread_guard()
    _try_patch_loaded()
    if getattr(builtins, "_NIJA_KRAKEN_OHLC_THREAD_GUARD_HOOK_20260707C", False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if name.endswith("broker_integration") or "broker_integration" in str(name):
                _try_patch_loaded()
        except Exception as exc:
            logger.warning("KRAKEN_OHLC_THREAD_GUARD hook failed name=%s error=%s", name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_KRAKEN_OHLC_THREAD_GUARD_HOOK_20260707C", True)
    logger.warning("KRAKEN_OHLC_THREAD_GUARD_IMPORT_HOOK marker=20260707c")


def install() -> None:
    install_import_hook()
