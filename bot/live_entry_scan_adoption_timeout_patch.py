from __future__ import annotations

import builtins
import logging
import os
import queue
import threading
import time
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.live_entry_scan_adoption_timeout")
_PATCHED_ATTR = "_NIJA_SCAN_ADOPTION_TIMEOUT_PATCHED"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.getenv(name, default)).strip().lower() in _TRUE


def _timeout_s() -> float:
    try:
        return max(0.05, float(os.getenv("NIJA_SCAN_POSITION_ADOPTION_TIMEOUT_S", "0.75") or 0.75))
    except Exception:
        return 0.75


def _already_synced() -> bool:
    for name in (
        "NIJA_EXCHANGE_POSITION_SYNC_COMPLETE",
        "NIJA_STARTUP_POSITION_SYNC_COMPLETE",
        "NIJA_HELD_POSITION_SYNC_COMPLETE",
    ):
        if _truthy(name, "false"):
            return True
    return False


def _patch_module(module: ModuleType) -> bool:
    if getattr(module, _PATCHED_ATTR, False):
        return True
    original = getattr(module, "_adopt_exchange_held_positions", None)
    if not callable(original):
        return False

    def _bounded_adopt_exchange_held_positions(core_loop: Any, broker: Any, open_positions_count: int = 0) -> int:
        if not _truthy("NIJA_SCAN_POSITION_ADOPTION_ENABLED", "true"):
            return int(open_positions_count or 0)

        # Startup/runtime position sync already adopts held exchange positions in a
        # background-safe path.  Do not let per-cycle scan startup block on broker
        # position APIs before Phase 3 can score markets.
        if _already_synced() or getattr(core_loop, "_nija_scan_adoption_bypassed_once", False):
            return max(
                int(open_positions_count or 0),
                int(getattr(core_loop, "_adopted_held_position_count", 0) or 0),
            )

        timeout = _timeout_s()
        result_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue(maxsize=1)

        def _runner() -> None:
            try:
                result_queue.put(("ok", original(core_loop, broker, open_positions_count)))
            except Exception as exc:  # noqa: BLE001
                result_queue.put(("err", exc))

        worker = threading.Thread(target=_runner, name="scan-position-adoption", daemon=True)
        worker.start()
        try:
            kind, payload = result_queue.get(timeout=timeout)
        except queue.Empty:
            setattr(core_loop, "_nija_scan_adoption_bypassed_once", True)
            logger.warning(
                "SCAN_POSITION_ADOPTION_TIMEOUT_BYPASS timeout_s=%.2f broker=%s open_positions=%s elapsed_wall=%.2f",
                timeout,
                type(broker).__name__ if broker is not None else "None",
                open_positions_count,
                timeout,
            )
            return int(open_positions_count or 0)

        if kind == "err":
            logger.warning("SCAN_POSITION_ADOPTION_ERROR_BYPASS err=%s", payload)
            return int(open_positions_count or 0)
        try:
            return int(payload or 0)
        except Exception:
            return int(open_positions_count or 0)

    setattr(module, "_adopt_exchange_held_positions", _bounded_adopt_exchange_held_positions)
    setattr(module, _PATCHED_ATTR, True)
    logger.warning("SCAN_POSITION_ADOPTION_TIMEOUT_PATCHED module=%s timeout_s=%.2f", module.__name__, _timeout_s())
    return True


def _patch_loaded() -> None:
    import sys

    for name in ("bot.live_entry_runtime_fixes", "live_entry_runtime_fixes"):
        mod = sys.modules.get(name)
        if isinstance(mod, ModuleType):
            try:
                _patch_module(mod)
            except Exception as exc:  # noqa: BLE001
                logger.warning("SCAN_POSITION_ADOPTION_TIMEOUT_PATCH_FAILED module=%s err=%s", name, exc)


def install_import_hook() -> None:
    _patch_loaded()
    if getattr(builtins, "_NIJA_SCAN_ADOPTION_TIMEOUT_IMPORT_HOOK_INSTALLED", False):
        return

    original_import = builtins.__import__

    def guarded_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
        module = original_import(name, globals, locals, fromlist, level)
        if name in {"bot.live_entry_runtime_fixes", "live_entry_runtime_fixes"} or str(name).endswith("live_entry_runtime_fixes"):
            _patch_loaded()
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_SCAN_ADOPTION_TIMEOUT_IMPORT_HOOK_INSTALLED", True)
    logger.warning("SCAN_POSITION_ADOPTION_TIMEOUT_INSTALL_COMPLETE")


def install() -> None:
    install_import_hook()
