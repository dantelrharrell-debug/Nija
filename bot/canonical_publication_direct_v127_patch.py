"""Bypass blocking broker discovery on the canonical pre-core strategy handoff.

v127 builds the canonical strategy only from already-loaded connected brokers.
Validation intentionally uses the publication module's canonical entry-ready
predicate because production broker wrappers may expose connection truth through
that boundary even when a local attribute-only duplicate predicate disagrees.
No readiness, authority, nonce, capital, risk, or execution proof is fabricated.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.canonical_publication_direct_v127")
MARKER = "20260816-canonical-publication-direct-v127"
RELEASE_ID = "20260816-runtime-convergence-v127"
_FLAG = "NIJA_CANONICAL_PUBLICATION_DIRECT_V127_INSTALLED"
_HELPER_ATTR = "_nija_canonical_publication_direct_v127"
_LOCK = threading.RLock()
_INSTALLED = False


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


def _connected_entry_broker(broker: Any) -> bool:
    return bool(
        broker is not None
        and bool(getattr(broker, "connected", False))
        and not bool(getattr(broker, "exit_only_mode", False))
    )


def _broker_key(broker: Any, fallback: str) -> str:
    btype = getattr(broker, "broker_type", None)
    raw = getattr(btype, "value", btype)
    if raw:
        return str(raw).strip().lower()
    name = getattr(broker, "NAME", None)
    if name:
        return str(name).strip().lower()
    cls = type(broker).__name__.replace("Broker", "").strip().lower()
    return cls or fallback


def _add_loaded(results: dict[str, dict[str, Any]], broker: Any, source: str) -> None:
    if not _connected_entry_broker(broker):
        return
    key = _broker_key(broker, source)
    results.setdefault(key, {"broker": broker, "connected": True, "ready_for_capital": True, "entry_ready": True, "source": source})


def _loaded_connected_brokers(explicit_broker: Any = None) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    _add_loaded(results, explicit_broker, "canonical_runtime_handoff")
    for module_name in ("bot.multi_account_broker_manager", "multi_account_broker_manager", "bot.broker_manager", "broker_manager"):
        module = sys.modules.get(module_name)
        if not isinstance(module, ModuleType):
            continue
        for manager_name in ("multi_account_broker_manager", "broker_manager"):
            manager = getattr(module, manager_name, None)
            if manager is None:
                continue
            for attr in ("platform_brokers", "_platform_brokers", "brokers", "broker_map"):
                mapping = getattr(manager, attr, None)
                if isinstance(mapping, dict):
                    for broker in mapping.values():
                        _add_loaded(results, broker, f"{module_name}.{manager_name}.{attr}")
        for attr in ("_PLATFORM_BROKER_INSTANCES", "platform_brokers", "brokers"):
            mapping = getattr(module, attr, None)
            if isinstance(mapping, dict):
                for broker in mapping.values():
                    _add_loaded(results, broker, f"{module_name}.{attr}")
    return results


def _patch_bot_main_helper() -> bool:
    bot_main = _canonical_import("bot.bot_main")
    publication = _canonical_import("bot.strategy_publication_patch")
    strategy_module = _canonical_import("bot.trading_strategy")
    current = getattr(bot_main, "_publish_canonical_strategy_for_runtime", None)
    build = getattr(publication, "_build_strategy", None)
    publish = getattr(publication, "_publish", None)
    entry_ready = getattr(publication, "_entry_ready_broker", None)
    cls = getattr(strategy_module, "TradingStrategy", None)
    start_monitor = getattr(publication, "start_monitor", None)
    if not callable(current) or not callable(build) or not callable(publish) or not callable(entry_ready) or not isinstance(cls, type):
        return False
    if bool(getattr(current, _HELPER_ATTR, False)):
        return True

    @wraps(current)
    def _publish_direct_v127(explicit_broker: Any):
        brokers = _loaded_connected_brokers(explicit_broker)
        if not brokers:
            fail = getattr(bot_main, "_fail_closed_strategy_publication", None)
            if callable(fail): fail("v127_no_loaded_connected_broker")
            LOGGER.critical("CANONICAL_STRATEGY_V127_DIRECT_BLOCKED marker=%s reason=no_loaded_connected_broker trading_fail_closed=true", MARKER)
            return None
        LOGGER.critical("CANONICAL_STRATEGY_V127_DIRECT_BEGIN marker=%s broker_keys=%s blocking_global_discovery=false", MARKER, sorted(brokers.keys()))
        try:
            strategy = build(cls, brokers)
        except Exception as exc:
            fail = getattr(bot_main, "_fail_closed_strategy_publication", None)
            if callable(fail): fail(f"v127_build_error:{type(exc).__name__}")
            LOGGER.critical("CANONICAL_STRATEGY_V127_DIRECT_BUILD_FAILED marker=%s err=%s:%s trading_fail_closed=true", MARKER, type(exc).__name__, exc, exc_info=True)
            return None

        broker = getattr(strategy, "broker", None)
        broker_ok = bool(entry_ready(broker))
        run_cycle_ok = callable(getattr(strategy, "run_cycle", None))
        if not broker_ok or not run_cycle_ok:
            fail = getattr(bot_main, "_fail_closed_strategy_publication", None)
            if callable(fail): fail("v127_strategy_validation_failed")
            LOGGER.critical(
                "CANONICAL_STRATEGY_V127_VALIDATION_FAILED marker=%s strategy=%s broker=%s broker_connected=%s exit_only=%s canonical_entry_ready=%s run_cycle=%s trading_fail_closed=true",
                MARKER, type(strategy).__name__, type(broker).__name__ if broker is not None else "none",
                bool(getattr(broker, "connected", False)) if broker is not None else False,
                bool(getattr(broker, "exit_only_mode", False)) if broker is not None else False,
                broker_ok, run_cycle_ok,
            )
            return None

        publish(strategy)
        LOGGER.critical("CANONICAL_STRATEGY_V127_DIRECT_READY marker=%s strategy=%s broker=%s blocking_global_discovery=false execution_authority_unchanged=true", MARKER, type(strategy).__name__, type(broker).__name__)
        if callable(start_monitor):
            try: start_monitor()
            except Exception as exc: LOGGER.warning("CANONICAL_STRATEGY_V127_MONITOR_START_FAILED err=%s", exc)
        return strategy

    setattr(_publish_direct_v127, _HELPER_ATTR, True)
    setattr(_publish_direct_v127, "__wrapped__", current)
    bot_main._publish_canonical_strategy_for_runtime = _publish_direct_v127
    return True


def _patch_release_manifest() -> bool:
    manifest = _canonical_import("bot.runtime_release_manifest_patch")
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    if not isinstance(required, dict): return False
    required["canonical_publication_direct_v127"] = _FLAG
    manifest.RELEASE_ID = RELEASE_ID
    return True


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED and os.environ.get(_FLAG) == "1": return True
        try:
            helper_ok = _patch_bot_main_helper(); manifest_ok = _patch_release_manifest()
        except Exception as exc:
            helper_ok = manifest_ok = False
            LOGGER.critical("CANONICAL_PUBLICATION_DIRECT_V127_INSTALL_FAILED marker=%s err=%s:%s trading_fail_closed=true", MARKER, type(exc).__name__, exc, exc_info=True)
        if not (helper_ok and manifest_ok):
            os.environ.pop(_FLAG, None); _INSTALLED = False; return False
        os.environ[_FLAG] = "1"; _INSTALLED = True
        LOGGER.critical("CANONICAL_PUBLICATION_DIRECT_V127_INSTALLED marker=%s release=%s bot_main_helper_direct=true global_broker_scan_precore=false connected_broker_required=true canonical_entry_ready_validation=true readiness_synthetic=false execution_authority_unchanged=true", MARKER, RELEASE_ID)
        return True


def install_import_hook() -> bool:
    return install()


__all__ = ["MARKER", "RELEASE_ID", "install", "install_import_hook", "_connected_entry_broker", "_loaded_connected_brokers", "_patch_bot_main_helper"]
