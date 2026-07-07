from __future__ import annotations

import builtins
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.kraken_ohlc_thread_guard")
_MARKER = "KRAKEN_OHLC_THREAD_GUARD_PATCHED marker=20260707b"
_PATCHED_ATTR = "_nija_kraken_ohlc_thread_guard_20260707b"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}

# Shared lock prevents concurrent callers from racing into the old pykrakenapi
# path and creating hundreds of daemon _fetch_ohlc threads.
_OHLC_GATE = threading.BoundedSemaphore(value=1)
_GLOBAL_COOLDOWN_UNTIL = 0.0


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


def _patch_module(module: ModuleType) -> bool:
    cls = getattr(module, "KrakenBrokerAdapter", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "get_market_data", None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return bool(getattr(original, _PATCHED_ATTR, False))

    @wraps(original)
    def get_market_data(self: Any, symbol: str, timeframe: str = "5m", limit: int = 100):
        global _GLOBAL_COOLDOWN_UNTIL

        if not _truthy("NIJA_KRAKEN_OHLC_THREAD_GUARD_ENABLED", "true"):
            return original(self, symbol, timeframe, limit)

        active = _active_ohlc_threads()
        max_active = max(1, _int_env("NIJA_KRAKEN_OHLC_MAX_ACTIVE_THREADS", 4))
        cooldown_s = max(10.0, _float_env("NIJA_KRAKEN_OHLC_SATURATION_COOLDOWN_S", 180.0))
        now = time.time()

        if now < _GLOBAL_COOLDOWN_UNTIL:
            logger.warning(
                "KRAKEN_OHLC_THREAD_GUARD_SKIP marker=20260707b symbol=%s active_threads=%d max_active=%d cooldown_remaining=%.1fs reason=global_ohlc_saturation",
                symbol,
                active,
                max_active,
                _GLOBAL_COOLDOWN_UNTIL - now,
            )
            return None

        if active >= max_active:
            _GLOBAL_COOLDOWN_UNTIL = now + cooldown_s
            logger.critical(
                "KRAKEN_OHLC_THREAD_GUARD_SATURATED marker=20260707b symbol=%s active_threads=%d max_active=%d cooldown_s=%.1f action=skip_kraken_ohlc",
                symbol,
                active,
                max_active,
                cooldown_s,
            )
            print(
                f"[NIJA-PRINT] KRAKEN_OHLC_THREAD_GUARD_SATURATED marker=20260707b active_threads={active} max_active={max_active} symbol={symbol}",
                flush=True,
            )
            return None

        # Non-blocking gate: if another Kraken OHLC call is already executing,
        # skip this symbol rather than creating another _fetch_ohlc thread.
        if not _OHLC_GATE.acquire(blocking=False):
            logger.warning(
                "KRAKEN_OHLC_THREAD_GUARD_BACKPRESSURE marker=20260707b symbol=%s active_threads=%d reason=single_flight_busy",
                symbol,
                active,
            )
            return None

        try:
            return original(self, symbol, timeframe, limit)
        except RuntimeError as exc:
            if "can't start new thread" in str(exc).lower():
                _GLOBAL_COOLDOWN_UNTIL = time.time() + cooldown_s
                logger.critical(
                    "KRAKEN_OHLC_THREAD_GUARD_THREAD_START_BLOCKED marker=20260707b symbol=%s cooldown_s=%.1f err=%s",
                    symbol,
                    cooldown_s,
                    exc,
                )
                return None
            raise
        finally:
            try:
                _OHLC_GATE.release()
            except Exception:
                pass

    setattr(get_market_data, _PATCHED_ATTR, True)
    setattr(cls, "get_market_data", get_market_data)
    logger.warning("%s class=KrakenBrokerAdapter", _MARKER)
    print("[NIJA-PRINT] KRAKEN_OHLC_THREAD_GUARD_PATCHED marker=20260707b", flush=True)
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
    os.environ.setdefault("NIJA_KRAKEN_OHLC_MAX_ACTIVE_THREADS", "4")
    os.environ.setdefault("NIJA_KRAKEN_OHLC_SATURATION_COOLDOWN_S", "180")
    _try_patch_loaded()
    if getattr(builtins, "_NIJA_KRAKEN_OHLC_THREAD_GUARD_HOOK_20260707B", False):
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
    setattr(builtins, "_NIJA_KRAKEN_OHLC_THREAD_GUARD_HOOK_20260707B", True)
    logger.warning("KRAKEN_OHLC_THREAD_GUARD_IMPORT_HOOK marker=20260707b")


def install() -> None:
    install_import_hook()
