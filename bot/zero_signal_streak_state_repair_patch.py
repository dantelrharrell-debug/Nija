"""Repair stale and unbounded NijaCoreLoop zero-signal streak state.

The core loop passes ``self._zero_signal_streak`` into Phase 3 and increments the
instance field after every no-entry cycle. A stale sentinel such as 999 therefore
becomes 1000, 1001, ... forever. Parameter-only clamping does not repair the source
state and leaves dead-zone bypass permanently active.

Phase 3 is intentionally wrapped by several late runtime repairs. Those repairs
can replace ``_phase3_scan_and_enter`` after this module first attaches. The
monitor therefore remains active for the process lifetime and reattaches this
required state repair whenever a later replacement removes it.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.zero_signal_streak_state_repair")
_MARKER = "20260714-zero-signal-state-v1"
_ATTR = "_nija_zero_signal_state_repair_v1"
_LOCK = threading.RLock()
_STARTED = False


def _int_env(name: str, default: int) -> int:
    try:
        return int(float(os.environ.get(name, str(default)) or default))
    except Exception:
        return default


def _chain_contains(func: Any) -> tuple[bool, bool, int]:
    current = func
    seen: set[int] = set()
    depth = 0
    while callable(current):
        ident = id(current)
        if ident in seen:
            return False, True, depth
        seen.add(ident)
        if bool(getattr(current, _ATTR, False)):
            return True, False, depth
        current = getattr(current, "__wrapped__", None)
        if not callable(current):
            return False, False, depth
        depth += 1
        if depth >= 4096:
            return False, True, depth
    return False, False, depth


def _repair_value(raw: int, cap: int, stale_threshold: int) -> tuple[int, str]:
    raw = max(0, int(raw))
    cap = max(2, min(int(cap), 12))
    stale_threshold = max(cap + 1, int(stale_threshold))
    if raw >= stale_threshold:
        return 0, "stale_sentinel_reset"
    if raw > cap:
        return cap, "bounded"
    return raw, "unchanged"


def _install_on_core_loop(module: ModuleType) -> bool:
    cls = getattr(module, "NijaCoreLoop", None)
    current = getattr(cls, "_phase3_scan_and_enter", None) if isinstance(cls, type) else None
    if not callable(current):
        return False
    found, cycle, depth = _chain_contains(current)
    if cycle:
        os.environ["NIJA_ZERO_SIGNAL_STREAK_STATE_READY"] = "0"
        logger.critical(
            "ZERO_SIGNAL_STREAK_WRAPPER_CYCLE marker=%s module=%s depth=%d",
            _MARKER,
            module.__name__,
            depth,
        )
        return False
    if found:
        os.environ["NIJA_ZERO_SIGNAL_STREAK_STATE_READY"] = "1"
        return True

    @wraps(current)
    def phase3(
        self: Any,
        broker: Any,
        snapshot: Any,
        symbols: Any,
        available_slots: Any,
        zero_signal_streak: int = 0,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        cap = max(2, min(_int_env("NIJA_ZERO_SIGNAL_STREAK_CAP", 12), 12))
        stale_threshold = max(
            cap + 1,
            _int_env("NIJA_ZERO_SIGNAL_STREAK_STALE_THRESHOLD", 100),
        )
        try:
            state_raw = int(getattr(self, "_zero_signal_streak", zero_signal_streak) or 0)
        except Exception:
            state_raw = int(zero_signal_streak or 0)
        incoming = int(zero_signal_streak or 0)
        authoritative_raw = max(state_raw, incoming)
        repaired, reason = _repair_value(authoritative_raw, cap, stale_threshold)
        if repaired != state_raw:
            setattr(self, "_zero_signal_streak", repaired)
        if reason != "unchanged" or incoming != repaired:
            log = logger.critical if reason == "stale_sentinel_reset" else logger.warning
            log(
                "ZERO_SIGNAL_STREAK_STATE_REPAIRED marker=%s raw_state=%d incoming=%d repaired=%d cap=%d stale_threshold=%d reason=%s dead_zone_rearmed=%s",
                _MARKER,
                state_raw,
                incoming,
                repaired,
                cap,
                stale_threshold,
                reason,
                str(reason == "stale_sentinel_reset").lower(),
            )
        return current(
            self,
            broker,
            snapshot,
            symbols,
            available_slots,
            repaired,
            *args,
            **kwargs,
        )

    setattr(phase3, _ATTR, True)
    phase3.__wrapped__ = current
    cls._phase3_scan_and_enter = phase3
    os.environ["NIJA_ZERO_SIGNAL_STREAK_STATE_READY"] = "1"
    logger.critical(
        "ZERO_SIGNAL_STREAK_STATE_REPAIR_INSTALLED marker=%s module=%s cap_env=%s stale_threshold_env=%s persistent=true",
        _MARKER,
        module.__name__,
        os.environ.get("NIJA_ZERO_SIGNAL_STREAK_CAP", "12"),
        os.environ.get("NIJA_ZERO_SIGNAL_STREAK_STALE_THRESHOLD", "100"),
    )
    return True


def _try_loaded() -> bool:
    patched = False
    seen: set[int] = set()
    for name in ("bot.nija_core_loop", "nija_core_loop"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            patched = _install_on_core_loop(module) or patched
    return patched


def _monitor_interval() -> float:
    try:
        return max(
            0.25,
            float(os.environ.get("NIJA_ZERO_SIGNAL_STATE_MONITOR_S", "1.0") or 1.0),
        )
    except Exception:
        return 1.0


def _watchdog() -> None:
    last_ready: bool | None = None
    while True:
        try:
            ready = _try_loaded()
            os.environ["NIJA_ZERO_SIGNAL_STREAK_STATE_READY"] = "1" if ready else "0"
            if ready != last_ready:
                logger.log(
                    logging.INFO if ready else logging.WARNING,
                    "ZERO_SIGNAL_STREAK_STATE_MONITOR marker=%s ready=%s persistent=true",
                    _MARKER,
                    str(ready).lower(),
                )
                last_ready = ready
        except Exception:
            os.environ["NIJA_ZERO_SIGNAL_STREAK_STATE_READY"] = "0"
            logger.exception("ZERO_SIGNAL_STREAK_STATE_REPAIR_RETRY marker=%s", _MARKER)
        time.sleep(_monitor_interval())


def install_import_hook() -> None:
    global _STARTED
    with _LOCK:
        ready = _try_loaded()
        os.environ["NIJA_ZERO_SIGNAL_STREAK_STATE_READY"] = "1" if ready else "0"
        if not _STARTED:
            _STARTED = True
            threading.Thread(
                target=_watchdog,
                name="ZeroSignalStreakStateRepair",
                daemon=True,
            ).start()
        os.environ["NIJA_ZERO_SIGNAL_STREAK_STATE_REPAIR_INSTALLED"] = "1"


def install() -> None:
    install_import_hook()


__all__ = [
    "install",
    "install_import_hook",
    "_install_on_core_loop",
    "_repair_value",
    "_chain_contains",
    "_try_loaded",
    "_monitor_interval",
]
