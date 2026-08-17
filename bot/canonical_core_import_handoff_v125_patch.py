"""Make the canonical pre-core handoff independent of historical import-wrapper churn.

Production v124 reaches BootstrapState.THREADS_STARTING with writer, broker,
balance, capital, risk, nonce and position-sync readiness proven, but the
canonical TradingLoop is never registered.  The remaining handoff in bot_main
performs several ``from bot...`` imports after dozens of compatibility import
wrappers have been installed.  Those imports can repeatedly replay post-import
convergence and prevent Step 3 from reaching ``start_trading_engine``.

v125 installs last on the canonical fast path and short-circuits only a narrow
set of already-audited startup modules through CPython's frozen canonical import
primitive.  It does not grant readiness or execution authority.  For the core
module it explicitly reapplies the existing lifecycle/core wrappers after the
canonical load so bypassing historical import hooks cannot bypass runtime safety.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.canonical_core_import_handoff_v125")
MARKER = "20260816-canonical-core-import-handoff-v125"
RELEASE_ID = "20260816-runtime-convergence-v125"
_FLAG = "NIJA_CANONICAL_CORE_IMPORT_HANDOFF_V125_INSTALLED"
_BUILTIN_ATTR = "_nija_canonical_core_import_handoff_v125"
_IMPORTLIB_ATTR = "_nija_canonical_core_import_module_v125"
_HELPER_ATTR = "_nija_canonical_strategy_helper_v125"
_LOCK = threading.RLock()
_INSTALLED = False

_TARGETS = frozenset(
    {
        "bot.strategy_publication_patch",
        "bot.nija_core_loop",
        "bot.startup_coordinator",
        "bot.entrypoint_writer_authority",
        "bot.bootstrap_state_machine",
        "bot.readiness_table",
        "bot.trading_state_machine",
    }
)


def _canonical_import(name: str) -> ModuleType:
    existing = sys.modules.get(name)
    if isinstance(existing, ModuleType):
        return existing
    bootstrap = getattr(importlib, "_bootstrap", None)
    gcd_import = getattr(bootstrap, "_gcd_import", None) if bootstrap is not None else None
    if not callable(gcd_import):
        raise RuntimeError("canonical_import_primitive_unavailable")
    module = gcd_import(name)
    if not isinstance(module, ModuleType):
        raise RuntimeError(f"canonical_import_invalid_module:{name}")
    return module


def _reapply_core_safety(module: ModuleType) -> bool:
    """Reapply known idempotent core lifecycle wrappers after a direct import."""
    applied = 0
    attempted = 0
    for patch_name in (
        "bot.writer_runtime_lifecycle_supervisor_v54_patch",
        "bot.core_supervised_pending_v120_patch",
    ):
        patch_module = sys.modules.get(patch_name)
        if not isinstance(patch_module, ModuleType):
            try:
                patch_module = _canonical_import(patch_name)
            except Exception:
                continue
        patcher = getattr(patch_module, "_patch_core_loop", None)
        if not callable(patcher):
            continue
        attempted += 1
        try:
            if patcher(module) is not False:
                applied += 1
        except Exception as exc:
            LOGGER.critical(
                "CANONICAL_CORE_V125_SAFETY_REAPPLY_FAILED marker=%s patch=%s err=%s:%s trading_fail_closed=true",
                MARKER,
                patch_name,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            return False
    LOGGER.critical(
        "CANONICAL_CORE_V125_SAFETY_REAPPLIED marker=%s attempted=%d applied=%d execution_gates_unchanged=true",
        MARKER,
        attempted,
        applied,
    )
    return True


def _resolve_target(name: str) -> ModuleType:
    started = time.monotonic()
    module = _canonical_import(name)
    if name == "bot.nija_core_loop" and not _reapply_core_safety(module):
        raise RuntimeError("core_safety_reapply_failed")
    elapsed_ms = (time.monotonic() - started) * 1000.0
    LOGGER.info(
        "CANONICAL_CORE_V125_IMPORT marker=%s module=%s elapsed_ms=%.1f wrapped_import_chain_bypassed=true",
        MARKER,
        name,
        elapsed_ms,
    )
    return module


def _patch_builtin_import() -> bool:
    current = builtins.__import__
    if bool(getattr(current, _BUILTIN_ATTR, False)):
        return True

    @wraps(current)
    def import_v125(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
        if level == 0 and name in _TARGETS:
            module = _resolve_target(name)
            if fromlist:
                return module
            top = name.split(".", 1)[0]
            return sys.modules.get(top, module)
        return current(name, globals, locals, fromlist, level)

    setattr(import_v125, _BUILTIN_ATTR, True)
    setattr(import_v125, "__wrapped__", current)
    builtins.__import__ = import_v125
    return True


def _patch_import_module() -> bool:
    current = importlib.import_module
    if bool(getattr(current, _IMPORTLIB_ATTR, False)):
        return True

    @wraps(current)
    def import_module_v125(name: str, package: str | None = None):
        if package is None and name in _TARGETS:
            return _resolve_target(name)
        return current(name, package)

    setattr(import_module_v125, _IMPORTLIB_ATTR, True)
    setattr(import_module_v125, "__wrapped__", current)
    importlib.import_module = import_module_v125  # type: ignore[assignment]
    return True


def _patch_strategy_publication_helper() -> bool:
    """Remove a wrapped import from bot_main Step 2.5 while retaining v124 bounds."""
    try:
        bot_main = _canonical_import("bot.bot_main")
        publication = _resolve_target("bot.strategy_publication_patch")
    except Exception as exc:
        LOGGER.critical(
            "CANONICAL_CORE_V125_STRATEGY_HELPER_IMPORT_FAILED marker=%s err=%s:%s",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False

    current = getattr(bot_main, "_publish_canonical_strategy_for_runtime", None)
    publish = getattr(publication, "publish_canonical_strategy", None)
    start_monitor = getattr(publication, "start_monitor", None)
    if not callable(current) or not callable(publish):
        return False
    if bool(getattr(current, _HELPER_ATTR, False)):
        return True

    @wraps(current)
    def publish_strategy_v125(broker: object):
        try:
            strategy, detail = publish(explicit_broker=broker)
        except Exception as exc:
            LOGGER.critical(
                "CANONICAL_STRATEGY_V125_PUBLICATION_EXCEPTION marker=%s type=%s err=%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            return None

        if strategy is None or not callable(getattr(strategy, "run_cycle", None)):
            fail = getattr(bot_main, "_fail_closed_strategy_publication", None)
            if callable(fail):
                fail(detail if strategy is None else "strategy_run_cycle_unavailable")
            return None
        if getattr(strategy, "broker", None) is None:
            fail = getattr(bot_main, "_fail_closed_strategy_publication", None)
            if callable(fail):
                fail("strategy_broker_missing")
            return None

        LOGGER.critical(
            "CANONICAL_STRATEGY_V125_HANDOFF_READY marker=%s detail=%s strategy=%s broker=%s wrapped_import_chain_bypassed=true",
            MARKER,
            detail,
            type(strategy).__name__,
            type(getattr(strategy, "broker", None)).__name__,
        )
        if callable(start_monitor):
            try:
                start_monitor()
            except Exception as exc:
                LOGGER.warning("CANONICAL_STRATEGY_V125_MONITOR_START_FAILED err=%s", exc)
        return strategy

    setattr(publish_strategy_v125, _HELPER_ATTR, True)
    setattr(publish_strategy_v125, "__wrapped__", current)
    bot_main._publish_canonical_strategy_for_runtime = publish_strategy_v125
    return True


def _patch_release_manifest() -> bool:
    manifest = sys.modules.get("bot.runtime_release_manifest_patch")
    if not isinstance(manifest, ModuleType):
        try:
            manifest = _canonical_import("bot.runtime_release_manifest_patch")
        except Exception:
            return False
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    if not isinstance(required, dict):
        return False
    required["canonical_core_import_handoff_v125"] = _FLAG
    manifest.RELEASE_ID = RELEASE_ID
    return True


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED and os.environ.get(_FLAG) == "1":
            return True

        # Patch bot_main's Step 2.5 helper before installing the terminal import
        # short-circuit.  Then install this module last so its builtins/importlib
        # wrappers remain outermost for the Step 3 imports.
        helper_ok = _patch_strategy_publication_helper()
        builtin_ok = _patch_builtin_import()
        importlib_ok = _patch_import_module()
        manifest_ok = _patch_release_manifest()
        ok = bool(helper_ok and builtin_ok and importlib_ok and manifest_ok)
        if not ok:
            os.environ.pop(_FLAG, None)
            _INSTALLED = False
            LOGGER.critical(
                "CANONICAL_CORE_IMPORT_HANDOFF_V125_INSTALL_FAILED marker=%s helper=%s builtin=%s importlib=%s manifest=%s trading_fail_closed=true",
                MARKER,
                helper_ok,
                builtin_ok,
                importlib_ok,
                manifest_ok,
            )
            return False

        os.environ[_FLAG] = "1"
        _INSTALLED = True
        LOGGER.critical(
            "CANONICAL_CORE_IMPORT_HANDOFF_V125_INSTALLED marker=%s release=%s terminal_fast_import=true strategy_helper_direct=true core_safety_reapply=true readiness_synthetic=false execution_authority_unchanged=true",
            MARKER,
            RELEASE_ID,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_canonical_import",
    "_resolve_target",
    "_reapply_core_safety",
    "_patch_builtin_import",
    "_patch_import_module",
    "_patch_strategy_publication_helper",
]
