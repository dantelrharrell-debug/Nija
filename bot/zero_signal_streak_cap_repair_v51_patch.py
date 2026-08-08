"""Persistently restore the NijaCoreLoop zero-signal streak cap guard.

The legacy runtime-convergence hardening layer installs
``_nija_zero_streak_cap_e`` on ``NijaCoreLoop._phase3_scan_and_enter`` but its
watchdog is intentionally time-bounded. Production can load a later Phase-3
wrapper after that watchdog exits, leaving the process-lifetime zero-signal
state repair present while the parameter cap guard disappears. The module
identity guard correctly treats that state as unsafe and blocks live trading.

v51 makes only the cap layer persistent. It never grants execution authority,
changes writer/nonce state, touches broker connectivity, or weakens the module
identity gate. If the wrapper chain is cyclic or the core loop is unavailable,
readiness stays fail-closed until a safe chain can be proven.
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

LOGGER = logging.getLogger("nija.zero_signal_streak_cap_v51")
MARKER = "20260808-zero-signal-cap-repair-v51"

_ATTR = "_nija_zero_streak_cap_e"
_STATE_ATTR = "_nija_zero_signal_state_repair_v1"
_LOCK = threading.RLock()
_STARTED = False


def _int_env(name: str, default: int) -> int:
    try:
        return int(float(os.environ.get(name, str(default)) or default))
    except Exception:
        return default


def _cap_value() -> int:
    return max(2, min(_int_env("NIJA_ZERO_SIGNAL_STREAK_CAP", 12), 12))


def _chain_contains(func: Any, attr: str = _ATTR) -> tuple[bool, bool, int]:
    current = func
    seen: set[int] = set()
    depth = 0
    while callable(current):
        ident = id(current)
        if ident in seen:
            return False, True, depth
        seen.add(ident)
        if bool(getattr(current, attr, False)):
            return True, False, depth
        current = getattr(current, "__wrapped__", None)
        if not callable(current):
            return False, False, depth
        depth += 1
        if depth >= 4096:
            return False, True, depth
    return False, False, depth


def _install_on_core_loop(module: ModuleType) -> bool:
    cls = getattr(module, "NijaCoreLoop", None)
    current = getattr(cls, "_phase3_scan_and_enter", None) if isinstance(cls, type) else None
    if not callable(current):
        return False

    found, cycle, depth = _chain_contains(current)
    if cycle:
        os.environ["NIJA_ZERO_SIGNAL_STREAK_CAP_READY"] = "0"
        LOGGER.critical(
            "ZERO_SIGNAL_CAP_V51_WRAPPER_CYCLE marker=%s module=%s depth=%d fail_closed=true",
            MARKER,
            module.__name__,
            depth,
        )
        return False
    if found:
        os.environ["NIJA_ZERO_SIGNAL_STREAK_CAP_READY"] = "1"
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
        cap = _cap_value()
        try:
            raw = int(zero_signal_streak or 0)
        except Exception:
            raw = 0
        bounded = min(max(raw, 0), cap)
        if bounded != raw:
            LOGGER.warning(
                "ZERO_SIGNAL_CAP_V51_REPAIRED marker=%s raw=%d bounded=%d cap=%d",
                MARKER,
                raw,
                bounded,
                cap,
            )
        return current(
            self,
            broker,
            snapshot,
            symbols,
            available_slots,
            bounded,
            *args,
            **kwargs,
        )

    setattr(phase3, _ATTR, True)
    phase3.__wrapped__ = current
    cls._phase3_scan_and_enter = phase3
    os.environ["NIJA_ZERO_SIGNAL_STREAK_CAP_READY"] = "1"
    LOGGER.critical(
        "ZERO_SIGNAL_CAP_V51_INSTALLED marker=%s module=%s persistent=true state_guard_present=%s cap=%d",
        MARKER,
        module.__name__,
        str(_chain_contains(phase3, _STATE_ATTR)[0]).lower(),
        _cap_value(),
    )
    return True


def _try_loaded() -> bool:
    ready = False
    seen: set[int] = set()
    for name in ("bot.nija_core_loop", "nija_core_loop"):
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType) or id(module) in seen:
            continue
        seen.add(id(module))
        ready = _install_on_core_loop(module) or ready
    return ready


def _monitor_interval() -> float:
    try:
        return max(
            0.25,
            float(os.environ.get("NIJA_ZERO_SIGNAL_CAP_V51_MONITOR_S", "1.0") or 1.0),
        )
    except Exception:
        return 1.0


def _watchdog() -> None:
    last_ready: bool | None = None
    while True:
        try:
            ready = _try_loaded()
            os.environ["NIJA_ZERO_SIGNAL_STREAK_CAP_READY"] = "1" if ready else "0"
            if ready != last_ready:
                LOGGER.log(
                    logging.INFO if ready else logging.WARNING,
                    "ZERO_SIGNAL_CAP_V51_MONITOR marker=%s ready=%s persistent=true",
                    MARKER,
                    str(ready).lower(),
                )
                last_ready = ready
        except Exception:
            os.environ["NIJA_ZERO_SIGNAL_STREAK_CAP_READY"] = "0"
            LOGGER.exception("ZERO_SIGNAL_CAP_V51_RETRY marker=%s fail_closed=true", MARKER)
        time.sleep(_monitor_interval())


def install_import_hook() -> bool:
    global _STARTED
    with _LOCK:
        ready = _try_loaded()
        os.environ["NIJA_ZERO_SIGNAL_STREAK_CAP_READY"] = "1" if ready else "0"
        if not _STARTED:
            _STARTED = True
            threading.Thread(
                target=_watchdog,
                name="ZeroSignalStreakCapV51",
                daemon=True,
            ).start()
        os.environ["NIJA_ZERO_SIGNAL_STREAK_CAP_V51_INSTALLED"] = "1"
        LOGGER.critical(
            "ZERO_SIGNAL_CAP_V51_GUARD_ARMED marker=%s ready_now=%s persistent=true fail_closed=true",
            MARKER,
            str(ready).lower(),
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_cap_value",
    "_chain_contains",
    "_install_on_core_loop",
    "_try_loaded",
    "_monitor_interval",
]
