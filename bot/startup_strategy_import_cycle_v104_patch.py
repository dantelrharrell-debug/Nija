"""Break the canonical TradingStrategy startup import cycle without bypassing safety.

Production on 2026-08-16 showed ``bot.trading_strategy`` remaining
``__spec__._initializing=True`` for the full v102/v103 observation window.  The
module eagerly imports APEX and the core loop before defining TradingStrategy,
while APEX also imports the core loop.  Those dependencies are optional in
``trading_strategy`` and are already designed to degrade on ImportError.

v104 installs a very narrow builtins import guard before TradingStrategy wiring:
when (and only when) trading_strategy itself is actively initializing, imports of
APEX or the core loop requested by that module fail immediately with ImportError.
That allows TradingStrategy to finish defining.  Once initialization completes,
the guard becomes transparent and the existing APEX/core-loop wiring may hydrate
those dependencies normally.

No broker, balance, readiness, authority, nonce, position, risk, kill-switch, or
execution state is synthesized or bypassed.
"""
from __future__ import annotations

import builtins
import logging
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.startup_strategy_import_cycle_v104")
MARKER = "20260816-startup-strategy-import-cycle-v104"
_LOCK = threading.RLock()
_HOOK_FLAG = "_NIJA_STARTUP_STRATEGY_IMPORT_CYCLE_V104"
_ORIGINAL_ATTR = "_NIJA_STARTUP_STRATEGY_IMPORT_CYCLE_V104_ORIGINAL"

_BLOCKED = {
    "bot.nija_apex_strategy_v71",
    "nija_apex_strategy_v71",
    "bot.nija_core_loop",
    "nija_core_loop",
}
_CALLERS = {"bot.trading_strategy", "trading_strategy"}


def _initializing(module: ModuleType | None) -> bool:
    return bool(
        isinstance(module, ModuleType)
        and getattr(getattr(module, "__spec__", None), "_initializing", False)
    )


def _caller_is_initializing(globals_dict: Any) -> bool:
    if not isinstance(globals_dict, dict):
        return False
    caller = str(globals_dict.get("__name__", "") or "")
    if caller not in _CALLERS:
        return False
    return _initializing(sys.modules.get(caller))


def install() -> bool:
    with _LOCK:
        if getattr(builtins, _HOOK_FLAG, False):
            return True

        original_import = builtins.__import__

        @wraps(original_import)
        def importing(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
            requested = str(name or "")
            if requested in _BLOCKED and _caller_is_initializing(globals):
                LOGGER.warning(
                    "STARTUP_STRATEGY_IMPORT_V104_DEFERRED marker=%s caller=%s dependency=%s "
                    "reason=canonical_strategy_initializing fail_closed=true",
                    MARKER,
                    globals.get("__name__", "unknown") if isinstance(globals, dict) else "unknown",
                    requested,
                )
                raise ImportError(
                    f"{requested} deferred while canonical TradingStrategy is initializing"
                )
            return original_import(name, globals, locals, fromlist, level)

        setattr(builtins, _ORIGINAL_ATTR, original_import)
        builtins.__import__ = importing
        setattr(builtins, _HOOK_FLAG, True)

    LOGGER.critical(
        "STARTUP_STRATEGY_IMPORT_CYCLE_V104_INSTALLED marker=%s "
        "scope=trading_strategy_initialization_only safety_gates_unchanged=true",
        MARKER,
    )
    return True


def install_import_hook() -> bool:
    return install()


__all__ = ["MARKER", "install", "install_import_hook"]
