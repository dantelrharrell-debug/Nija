from __future__ import annotations

import builtins
import logging
import os
import sys
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.exchange_kill_switch_internal_reject_guard")
_MARKER = "EXCHANGE_KILL_SWITCH_INTERNAL_REJECT_GUARD_PATCHED marker=20260706a"
_PATCHED_ATTR = "_nija_exchange_kill_switch_internal_reject_guard_20260706a"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_INTERNAL_REJECT_PATTERNS = (
    "no_execution_venue_available",
    "broker_not_registered",
    "replacement_unavailable",
    "direct_broker_metadata_mismatch",
    "direct_broker_metadata_cleared",
    "routing candidate",
    "internal route",
    "venue registry",
)


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUE


def _internal_reject(*values: Any) -> bool:
    text = " ".join(str(v or "") for v in values).lower()
    return any(pattern in text for pattern in _INTERNAL_REJECT_PATTERNS)


def _patch_module(module: ModuleType) -> bool:
    cls = getattr(module, "ExchangeKillSwitchProtector", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "record_order_result", None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return bool(getattr(original, _PATCHED_ATTR, False))

    @wraps(original)
    def record_order_result(self: Any, order_id: str, accepted: bool, *args: Any, **kwargs: Any):
        if _truthy("NIJA_EXCHANGE_KILL_SWITCH_IGNORE_INTERNAL_ROUTING_REJECTS", "true"):
            if not accepted and _internal_reject(order_id, args, kwargs):
                logger.critical(
                    "EXCHANGE_KILL_SWITCH_INTERNAL_REJECT_IGNORED marker=20260706a order_id=%s reason=internal_router_not_exchange",
                    order_id,
                )
                print(
                    f"[NIJA-PRINT] EXCHANGE_KILL_SWITCH_INTERNAL_REJECT_IGNORED marker=20260706a order_id={order_id}",
                    flush=True,
                )
                return None
        return original(self, order_id, accepted, *args, **kwargs)

    setattr(record_order_result, _PATCHED_ATTR, True)
    setattr(cls, "record_order_result", record_order_result)
    logger.warning("%s class=ExchangeKillSwitchProtector", _MARKER)
    print("[NIJA-PRINT] EXCHANGE_KILL_SWITCH_INTERNAL_REJECT_GUARD_PATCHED marker=20260706a", flush=True)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.exchange_kill_switch", "exchange_kill_switch"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_module(module) or patched
    return patched


def install_import_hook() -> None:
    os.environ.setdefault("NIJA_EXCHANGE_KILL_SWITCH_IGNORE_INTERNAL_ROUTING_REJECTS", "true")
    _try_patch_loaded()
    if getattr(builtins, "_NIJA_EXCHANGE_KILL_SWITCH_INTERNAL_REJECT_GUARD_HOOK", False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if name.endswith("exchange_kill_switch"):
                _try_patch_loaded()
            else:
                _try_patch_loaded()
        except Exception as exc:
            logger.warning("EXCHANGE_KILL_SWITCH_INTERNAL_REJECT_GUARD hook failed name=%s error=%s", name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_EXCHANGE_KILL_SWITCH_INTERNAL_REJECT_GUARD_HOOK", True)
    logger.warning("EXCHANGE_KILL_SWITCH_INTERNAL_REJECT_GUARD_IMPORT_HOOK marker=20260706a")


def install() -> None:
    install_import_hook()
