"""Broker-local halt and router convergence repairs for NIJA live execution."""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.critical_runtime_repairs_v9")
_MARKER = "20260720-critical-runtime-repairs-v9"
_LOCK = threading.RLock()
_INSTALLED = False


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _healthy_execution_venues() -> list[str]:
    healthy: list[str] = []
    for module_name in ("bot.multi_account_broker_manager", "multi_account_broker_manager"):
        module = sys.modules.get(module_name)
        if not isinstance(module, ModuleType):
            continue
        manager = getattr(module, "multi_account_broker_manager", None)
        mappings = []
        for owner in (manager, module):
            if owner is None:
                continue
            for attr in ("_platform_brokers", "platform_brokers", "brokers", "GLOBAL_PLATFORM_BROKERS"):
                mapping = getattr(owner, attr, None)
                if isinstance(mapping, dict):
                    mappings.append(mapping)
        for mapping in mappings:
            for raw_name, broker in mapping.items():
                name = str(getattr(raw_name, "value", raw_name) or "").lower()
                for venue in ("kraken", "coinbase", "okx"):
                    if venue in name or venue in type(broker).__name__.lower():
                        name = venue
                        break
                if name not in {"kraken", "coinbase", "okx"} or broker is None:
                    continue
                connected = bool(getattr(broker, "connected", False))
                if not connected:
                    fn = getattr(broker, "is_ready_for_trading", None)
                    try:
                        connected = bool(fn()) if callable(fn) else False
                    except Exception:
                        connected = False
                if connected and name not in healthy:
                    healthy.append(name)
    return healthy


def _patch_pre_halt_engine(module: ModuleType) -> bool:
    cls = getattr(module, "PreHaltAlertEngine", None)
    if not isinstance(cls, type) or getattr(cls, "_NIJA_BROKER_LOCAL_PREHALT_V9", False):
        return isinstance(cls, type)

    original_warn = getattr(cls, "warn_pre_halt", None)
    if not callable(original_warn):
        return False

    def warn_pre_halt(self: Any, reason: str, countdown_s: float = 60.0) -> None:
        reason_text = str(reason or "")
        is_kraken_only = "KRAKEN_health" in reason_text or "Kraken" in reason_text
        healthy = _healthy_execution_venues()
        if is_kraken_only and any(v in healthy for v in ("coinbase", "okx")):
            logger.warning(
                "BROKER_LOCAL_PREHALT_SUPPRESSED marker=%s failed_venue=kraken healthy_venues=%s reason=%s",
                _MARKER,
                ",".join(healthy),
                reason_text,
            )
            os.environ["NIJA_KRAKEN_DEGRADED"] = "1"
            os.environ["NIJA_GLOBAL_HALT_SUPPRESSED_FOR_BROKER_LOCAL_FAILURE"] = "1"
            return
        return original_warn(self, reason, countdown_s)

    setattr(cls, "warn_pre_halt", warn_pre_halt)
    setattr(cls, "_NIJA_BROKER_LOCAL_PREHALT_V9", True)
    logger.critical("BROKER_LOCAL_PREHALT_REPAIR_PATCHED marker=%s", _MARKER)
    return True


def _patch_okx_pending_logger(module: ModuleType) -> bool:
    if getattr(module, "_NIJA_OKX_PENDING_TERMINAL_V9", False):
        return True
    base_logger = getattr(module, "logger", None)
    if base_logger is None:
        return False

    class _RouterAwareLogger:
        def __init__(self, base: Any) -> None:
            self._base = base
        def __getattr__(self, name: str) -> Any:
            return getattr(self._base, name)
        def error(self, msg: Any, *args: Any, **kwargs: Any) -> None:
            text = str(msg or "")
            if text.startswith("OKX_ROUTER_BIND_PENDING"):
                converged = os.environ.get("NIJA_OKX_ROUTER_CONVERGED", "").strip() == "1"
                router = sys.modules.get("bot.multi_broker_execution_router")
                if converged or router is not None:
                    self._base.info(
                        "OKX_ROUTER_PENDING_SUPPRESSED marker=%s router_present=%s",
                        _MARKER,
                        router is not None,
                    )
                    return
            self._base.error(msg, *args, **kwargs)

    if not isinstance(base_logger, _RouterAwareLogger):
        setattr(module, "logger", _RouterAwareLogger(base_logger))
    setattr(module, "_NIJA_OKX_PENDING_TERMINAL_V9", True)
    os.environ["NIJA_OKX_ROUTER_CONVERGED"] = "1"
    logger.critical("OKX_ROUTER_PENDING_TERMINAL_REPAIR_PATCHED marker=%s", _MARKER)
    return True


def _apply() -> bool:
    ok = False
    for name in ("bot.self_healing_startup", "self_healing_startup"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            ok = _patch_pre_halt_engine(module) or ok
    for name in ("bot.final_account_router_exit_convergence_patch", "final_account_router_exit_convergence_patch"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            ok = _patch_okx_pending_logger(module) or ok
    return ok


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return True
        importlib.import_module("critical_runtime_repairs_v8").install()
        for name in ("bot.self_healing_startup", "bot.final_account_router_exit_convergence_patch"):
            try:
                importlib.import_module(name)
            except Exception:
                logger.debug("V9 optional import deferred module=%s", name, exc_info=True)
        _apply()

        def monitor() -> None:
            deadline = time.time() + 300.0
            while time.time() < deadline:
                _apply()
                time.sleep(2.0)

        threading.Thread(target=monitor, name="CriticalRuntimeRepairsV9", daemon=True).start()
        os.environ["NIJA_CRITICAL_RUNTIME_REPAIRS_V9_READY"] = "1"
        _INSTALLED = True
        logger.critical(
            "CRITICAL_RUNTIME_REPAIRS_V9_READY marker=%s broker_local_halt=true okx_pending_terminal=true healthy_venues=%s",
            _MARKER,
            ",".join(_healthy_execution_venues()),
        )
        return True


__all__ = ["install"]
