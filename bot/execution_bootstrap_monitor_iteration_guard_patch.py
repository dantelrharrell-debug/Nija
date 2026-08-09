from __future__ import annotations

import builtins
import logging
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.execution_bootstrap_monitor_iteration_guard")
_MARKER = "20260709a"
_WRITER_V61_MARKER = "20260809-writer-scan-deadline-lease-guard-v61"
_INSTALL_LOCK = threading.Lock()
_MONITOR_STARTED = False
_PATCHED_MODULES: set[str] = set()
_WRITER_PATCHED_MODULES: set[str] = set()
_WRITER_PATCH_ATTR = "_nija_scan_deadline_warning_only_v61"


def _is_target_module(name: str, module: Any) -> bool:
    file_name = str(getattr(module, "__file__", "") or "")
    return (
        name in {
            "nija_execution_bootstrap_authority_repair_patch",
            "bot.execution_bootstrap_authority_repair_patch",
            "execution_bootstrap_authority_repair_patch",
        }
        or file_name.endswith("execution_bootstrap_authority_repair_patch.py")
    )


def _is_writer_module(name: str, module: Any) -> bool:
    file_name = str(getattr(module, "__file__", "") or "")
    return (
        name in {"bot.entrypoint_writer_authority", "entrypoint_writer_authority"}
        or file_name.endswith("entrypoint_writer_authority.py")
    )


def _snapshot_modules() -> list[tuple[str, Any]]:
    for _ in range(3):
        try:
            return list(sys.modules.items())
        except RuntimeError:
            time.sleep(0.01)
    try:
        return list(dict(sys.modules).items())
    except Exception:
        return []


def _patch_target_module(module: ModuleType) -> bool:
    original_install = getattr(module, "_install_on_execution_engine", None)
    if not callable(original_install):
        return False
    current = getattr(module, "_try_patch_loaded", None)
    if callable(current) and getattr(current, "_nija_monitor_iteration_guard_v20260709a", False):
        _PATCHED_MODULES.add(str(getattr(module, "__name__", "<unknown>")))
        return True

    def _safe_try_patch_loaded() -> bool:
        patched = False
        for name, loaded_module in _snapshot_modules():
            try:
                if not isinstance(loaded_module, ModuleType):
                    continue
                if name in {"bot.execution_engine", "execution_engine"} or hasattr(loaded_module, "ExecutionEngine"):
                    patched = original_install(loaded_module) or patched
            except RuntimeError as exc:
                if "dictionary changed size" in str(exc):
                    logger.warning(
                        "EXECUTION_BOOTSTRAP_MONITOR_ITERATION_RETRY marker=%s err=%s",
                        _MARKER,
                        exc,
                    )
                    continue
                raise
            except Exception as exc:
                logger.debug(
                    "EXECUTION_BOOTSTRAP_MONITOR_ITERATION_SKIPPED marker=%s module=%s err=%s",
                    _MARKER,
                    name,
                    exc,
                )
        return patched

    setattr(_safe_try_patch_loaded, "_nija_monitor_iteration_guard_v20260709a", True)
    setattr(_safe_try_patch_loaded, "__wrapped__", current)
    setattr(module, "_try_patch_loaded", _safe_try_patch_loaded)
    _PATCHED_MODULES.add(str(getattr(module, "__name__", "<unknown>")))
    logger.warning(
        "EXECUTION_BOOTSTRAP_MONITOR_ITERATION_GUARD_PATCHED marker=%s module=%s",
        _MARKER,
        getattr(module, "__name__", "<unknown>"),
    )
    print(
        f"[NIJA-PRINT] EXECUTION_BOOTSTRAP_MONITOR_ITERATION_GUARD_PATCHED "
        f"marker={_MARKER} module={getattr(module, '__name__', '<unknown>')}",
        flush=True,
    )
    return True


def _patch_writer_module(module: ModuleType) -> bool:
    """Keep the scan-start deadline diagnostic-only while startup is still running.

    The canonical writer module already documents SCAN_STARTED_DEADLINE_EXCEEDED
    as a warning that must not release the writer lease.  Production showed a
    contradictory branch in ``_validate_core_thread_liveness``: when no core
    thread had been registered yet, the scan deadline flag returned False and
    the heartbeat then called ``_release_owned_lock_for_reelection``.  That
    intentionally deleted a healthy Redis lock during slow broker/capital
    bootstrap and caused the exact ``redis_lock_missing`` / fencing cascade.

    v61 changes only that pre-core-thread case.  Once a core thread has actually
    been registered, the original liveness method remains authoritative and a
    dead thread still fails closed and releases writer authority as designed.
    """
    cls = getattr(module, "EntrypointWriterAuthority", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_validate_core_thread_liveness", None)
    if not callable(original):
        return False
    if getattr(original, _WRITER_PATCH_ATTR, False):
        _WRITER_PATCHED_MODULES.add(str(getattr(module, "__name__", "<unknown>")))
        return True

    @wraps(original)
    def _warning_only_scan_deadline(self: Any) -> tuple[bool, str]:
        thread = getattr(self, "_core_thread", None)
        scan_started = float(getattr(self, "_scan_started_at", 0.0) or 0.0)
        scan_deadline_exceeded = bool(getattr(self, "_scan_deadline_exceeded", False))
        if thread is None and scan_deadline_exceeded and scan_started <= 0.0:
            logger.critical(
                "WRITER_V61_SCAN_DEADLINE_WARNING_ONLY marker=%s "
                "core_thread_registered=false scan_started=false action=keep_renewing_writer "
                "lease_release=false fail_closed_execution=true",
                _WRITER_V61_MARKER,
            )
            return True, "scan_start_deadline_warning_only"
        return original(self)

    setattr(_warning_only_scan_deadline, _WRITER_PATCH_ATTR, True)
    setattr(_warning_only_scan_deadline, "__wrapped__", original)
    setattr(cls, "_validate_core_thread_liveness", _warning_only_scan_deadline)
    _WRITER_PATCHED_MODULES.add(str(getattr(module, "__name__", "<unknown>")))
    logger.critical(
        "WRITER_V61_SCAN_DEADLINE_LEASE_GUARD_PATCHED marker=%s module=%s "
        "pre_core_deadline_releases_lease=false registered_dead_core_still_fail_closed=true",
        _WRITER_V61_MARKER,
        getattr(module, "__name__", "<unknown>"),
    )
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name, module in _snapshot_modules():
        if not isinstance(module, ModuleType):
            continue
        if _is_target_module(name, module):
            try:
                patched = _patch_target_module(module) or patched
            except Exception as exc:
                logger.warning(
                    "EXECUTION_BOOTSTRAP_MONITOR_ITERATION_GUARD_FAILED marker=%s module=%s err=%s",
                    _MARKER,
                    name,
                    exc,
                )
        if _is_writer_module(name, module):
            try:
                patched = _patch_writer_module(module) or patched
            except Exception as exc:
                logger.warning(
                    "WRITER_V61_SCAN_DEADLINE_LEASE_GUARD_FAILED marker=%s module=%s err=%s",
                    _WRITER_V61_MARKER,
                    name,
                    exc,
                )
    return patched


def _start_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + float(
            __import__("os").environ.get("NIJA_PATCH_MONITOR_SECONDS", "300") or "300"
        )
        while time.time() < deadline:
            _try_patch_loaded()
            # Do not exit merely because the bootstrap-repair module was patched:
            # entrypoint_writer_authority may load later in the startup sequence.
            if _WRITER_PATCHED_MODULES:
                return
            time.sleep(0.25)
        logger.warning(
            "EXECUTION_BOOTSTRAP_MONITOR_ITERATION_GUARD_MONITOR_EXPIRED marker=%s "
            "patched_modules=%s writer_patched_modules=%s",
            _MARKER,
            sorted(_PATCHED_MODULES),
            sorted(_WRITER_PATCHED_MODULES),
        )

    threading.Thread(
        target=_monitor,
        name="execution-bootstrap-monitor-iteration-guard",
        daemon=True,
    ).start()
    logger.warning(
        "EXECUTION_BOOTSTRAP_MONITOR_ITERATION_GUARD_MONITOR_STARTED marker=%s",
        _MARKER,
    )


def install_import_hook() -> None:
    with _INSTALL_LOCK:
        _try_patch_loaded()
        _start_monitor()
        if getattr(
            builtins,
            "_NIJA_EXECUTION_BOOTSTRAP_MONITOR_ITERATION_GUARD_V20260709A",
            False,
        ):
            logger.warning(
                "EXECUTION_BOOTSTRAP_MONITOR_ITERATION_GUARD_INSTALL_COMPLETE marker=%s "
                "already_installed=True patched_modules=%s writer_patched_modules=%s",
                _MARKER,
                sorted(_PATCHED_MODULES),
                sorted(_WRITER_PATCHED_MODULES),
            )
            return
        original_import = builtins.__import__

        def guarded_import(
            name: str,
            globals: Any = None,
            locals: Any = None,
            fromlist: Any = (),
            level: int = 0,
        ) -> Any:
            module = original_import(name, globals, locals, fromlist, level)
            text = str(name)
            if (
                "execution_bootstrap_authority_repair_patch" in text
                or "entrypoint_writer_authority" in text
            ):
                _try_patch_loaded()
            return module

        builtins.__import__ = guarded_import
        setattr(
            builtins,
            "_NIJA_EXECUTION_BOOTSTRAP_MONITOR_ITERATION_GUARD_V20260709A",
            True,
        )
        logger.warning(
            "EXECUTION_BOOTSTRAP_MONITOR_ITERATION_GUARD_INSTALL_COMPLETE marker=%s "
            "patched_modules=%s writer_patched_modules=%s",
            _MARKER,
            sorted(_PATCHED_MODULES),
            sorted(_WRITER_PATCHED_MODULES),
        )


def install() -> None:
    install_import_hook()
