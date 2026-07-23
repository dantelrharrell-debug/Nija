from __future__ import annotations

import importlib
import logging
import os
import threading

logger = logging.getLogger("nija.generation_sync_timing_patch")
_INSTALL_LOCK = threading.RLock()
_INSTALLED = False


def _install_runtime_patch_churn_safety() -> None:
    try:
        module = importlib.import_module("bot.runtime_patch_churn_safety_patch")
        installer = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
        if callable(installer):
            installer()
    except Exception as exc:
        logger.warning("runtime patch-churn safety unavailable: %s", exc)


def _install_final_gate_repair() -> None:
    try:
        module = importlib.import_module("bot.live_active_execution_gate_final_patch")
        installer = getattr(module, "install_import_hook", None)
        if callable(installer):
            installer()
            logger.warning("LIVE_ACTIVE_EXECUTION_GATE_FINAL_CHAINED_FROM_GENERATION_SYNC")
            print("[NIJA-PRINT] LIVE_ACTIVE_EXECUTION_GATE_FINAL_CHAINED_FROM_GENERATION_SYNC", flush=True)
    except Exception as exc:
        logger.debug("final gate repair chain deferred: %s", exc)


def _install_dispatch_scope_bridge() -> None:
    try:
        module = importlib.import_module("bot.dispatch_scope_bridge_patch")
        installer = getattr(module, "install_import_hook", None)
        if callable(installer):
            installer()
            logger.warning("DISPATCH_SCOPE_BRIDGE_CHAINED_FROM_GENERATION_SYNC")
            print("[NIJA-PRINT] DISPATCH_SCOPE_BRIDGE_CHAINED_FROM_GENERATION_SYNC", flush=True)
    except Exception as exc:
        logger.debug("dispatch scope bridge chain deferred: %s", exc)


def install_import_hook() -> None:
    global _INSTALLED
    with _INSTALL_LOCK:
        os.environ["NIJA_GENERATION_MISMATCH_RECOVERY_COOLDOWN_S"] = "0"

        # Install the chain-aware safety layer before asking any execution-gate
        # patch to re-evaluate loaded runtime modules.
        _install_runtime_patch_churn_safety()

        if _INSTALLED:
            return
        _INSTALLED = True

        _install_final_gate_repair()
        _install_dispatch_scope_bridge()
        for name in ("bot.writer_generation_tracker", "writer_generation_tracker"):
            try:
                module = importlib.import_module(name)
                old = getattr(module, "_SYNC_RECOVERY_COOLDOWN_S", None)
                setattr(module, "_SYNC_RECOVERY_COOLDOWN_S", 0.0)
                logger.warning(
                    "GENERATION_SYNC_TIMING_PATCH_APPLIED module=%s old=%s new=0.0",
                    name,
                    old,
                )
                print(
                    "[NIJA-PRINT] GENERATION_SYNC_TIMING_PATCH_APPLIED | cooldown_s=0",
                    flush=True,
                )
            except Exception as exc:
                logger.debug("generation sync timing patch deferred for %s: %s", name, exc)
