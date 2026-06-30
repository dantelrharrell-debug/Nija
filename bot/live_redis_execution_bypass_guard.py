"""Live Redis execution-bypass guard.

Some legacy execution paths still include local-writer fallback or force-trade
flags as bypass signals. In live mode with Redis configured, those flags must
never expand execution authority. This module removes them immediately before
execution-engine gate methods run and while bot modules import.
"""

from __future__ import annotations

import builtins
import logging
import os
from functools import wraps
from typing import Any

logger = logging.getLogger("nija.live_redis_execution_bypass_guard")
_PATCHED_ATTR = "__nija_live_redis_execution_bypass_guard__"
_TRUTHY = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in _TRUTHY


def _redis_configured() -> bool:
    return bool(
        str(os.environ.get("NIJA_REDIS_URL", "")).strip()
        or str(os.environ.get("REDIS_URL", "")).strip()
        or str(os.environ.get("REDIS_PRIVATE_URL", "")).strip()
        or str(os.environ.get("REDIS_PUBLIC_URL", "")).strip()
    )


def _live_mode() -> bool:
    return not _truthy("DRY_RUN_MODE") and not _truthy("PAPER_MODE")


def _env_name(*parts: str) -> str:
    return "_".join(parts)


def sanitize(label: str) -> None:
    if not (_live_mode() and _redis_configured()):
        return
    cleared = []
    for key in (
        "FORCE_TRADE",
        "FORCE_TRADE_MODE",
        "FORCE_LIVE_TRANSITION",
        "NIJA_FORCE_ACTIVATION",
        "NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK",
        "NIJA_ALLOW_LOCAL_WRITER_LOCK_FALLBACK",
        "NIJA_ALLOW_DEGRADED_WRITER_AUTHORITY",
        "NIJA_ALLOW_REDIS_DEGRADED",
        "NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK",
        "NIJA_DISABLE_WRITER_LOCK",
        "NIJA_CONFIRM_BYPASS_RISKS",
    ):
        if _truthy(key):
            os.environ[key] = "false"
            cleared.append(key)
    os.environ[_env_name("NIJA", "REQUIRE", "DISTRIBUTED", "LOCK")] = "true"
    os.environ[_env_name("NIJA", "STRICT", "REDIS", "LEASE")] = "1"
    os.environ[_env_name("NIJA", "STRICT", "WRITER", "LOCK")] = "true"
    os.environ[_env_name("NIJA", "RUNTIME", "DEGRADED", "MODE")] = "false"
    if cleared:
        logger.critical("LIVE_REDIS_EXECUTION_BYPASS_GUARD label=%s cleared=%s", label, ",".join(cleared))


def _wrap_class(cls: type) -> bool:
    patched = False
    for method_name in (
        "execute_entry",
        "execute_action",
        "can_execute_trade",
        "can_execute",
        "submit_order",
        "_apply_startup_state_override",
        "commit_activation",
        "maybe_auto_activate",
        "transition_to",
    ):
        original = getattr(cls, method_name, None)
        if not callable(original) or getattr(original, _PATCHED_ATTR, False):
            continue

        @wraps(original)
        def wrapper(self: Any, *args: Any, __original=original, __method_name=method_name, **kwargs: Any):
            sanitize(f"{cls.__name__}.{__method_name}")
            return __original(self, *args, **kwargs)

        setattr(wrapper, _PATCHED_ATTR, True)
        setattr(cls, method_name, wrapper)
        patched = True
    if patched:
        logger.warning("LIVE_REDIS_EXECUTION_BYPASS_GUARD_PATCHED class=%s", cls.__name__)
    return patched


def _patch_module(module: Any) -> None:
    for name in dir(module):
        obj = getattr(module, name, None)
        if isinstance(obj, type) and any(
            token in name.lower()
            for token in ("engine", "pipeline", "submitter", "execution", "tradingstatemachine", "statemachine")
        ):
            _wrap_class(obj)


def install_import_hook() -> None:
    sanitize("install")
    import sys
    for name, module in list(sys.modules.items()):
        if name.startswith("bot.") or name in {"trading_state_machine", "execution_pipeline", "execution_engine"}:
            try:
                _patch_module(module)
            except Exception:
                pass
    if getattr(builtins, "_NIJA_LIVE_REDIS_EXEC_BYPASS_GUARD_INSTALLED", False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        sanitize(f"import:{name}")
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if name.startswith("bot") or name in {"trading_state_machine", "execution_pipeline", "execution_engine"}:
                _patch_module(module)
        except Exception:
            pass
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_LIVE_REDIS_EXEC_BYPASS_GUARD_INSTALLED", True)
    logger.warning("LIVE_REDIS_EXECUTION_BYPASS_GUARD_INSTALL_COMPLETE")
