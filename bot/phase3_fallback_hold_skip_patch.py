from __future__ import annotations

import importlib
import inspect
import logging
import sys
import textwrap
import threading
import time
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.phase3_fallback_hold_skip")

_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_PATCHED = False
_MONITOR_STARTED = False
_INSTALL_LOCK = threading.Lock()
_WRAP_ATTR = "_nija_phase3_fallback_hold_skip_wrapped_v20260703u"
_MARKER = "PHASE3_FALLBACK_HOLD_SKIP_PATCHED marker=20260703u"

_SKIP_BLOCK = '''
                        if isinstance(fallback_payload, dict) and fallback_payload.get("blocked_before_execute_action"):
                            action = analysis.get("action", action)
                            blocked += 1
                            _skip_reason = str(fallback_payload.get("reason") or "fallback_skip_before_execute")
                            _skip_stage = str(fallback_payload.get("filter_stage") or "fallback_prefilter")
                            _funnel["profitability"] = ("FAIL", _skip_reason)
                            logger.critical(
                                "PHASE3_FALLBACK_HOLD_SKIP_APPLIED marker=20260703u symbol=%s stage=%s reason=%s action=%s order_submit=false",
                                sig.symbol,
                                _skip_stage,
                                _skip_reason,
                                action,
                            )
                            print(
                                f"[NIJA-PRINT] PHASE3_FALLBACK_HOLD_SKIP_APPLIED marker=20260703u symbol={sig.symbol} stage={_skip_stage} reason={_skip_reason}",
                                flush=True,
                            )
                            continue
                        action = analysis.get("action", action)
'''


def _install_on_module(module: ModuleType) -> bool:
    global _PATCHED
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_phase3_scan_and_enter", None)
    if not callable(original):
        return False
    if getattr(original, _WRAP_ATTR, False):
        _PATCHED = True
        return True

    try:
        source = inspect.getsource(original)
        source = textwrap.dedent(source)
    except Exception as exc:
        logger.warning("PHASE3_FALLBACK_HOLD_SKIP_SOURCE_UNAVAILABLE marker=20260703u err=%s", exc)
        return False

    needle = "                        analysis.update(fallback_payload)\n"
    count = source.count(needle)
    if count <= 0:
        logger.warning("PHASE3_FALLBACK_HOLD_SKIP_NEEDLE_MISSING marker=20260703u")
        return False

    patched_source = source.replace(needle, needle + _SKIP_BLOCK)
    namespace = dict(getattr(original, "__globals__", {}))
    try:
        exec(compile(patched_source, "<phase3_fallback_hold_skip_patch>", "exec"), namespace)
        patched = namespace.get("_phase3_scan_and_enter")
        if not callable(patched):
            raise RuntimeError("patched _phase3_scan_and_enter not produced")
    except Exception as exc:
        logger.warning("PHASE3_FALLBACK_HOLD_SKIP_COMPILE_FAILED marker=20260703u err=%s", exc)
        return False

    setattr(patched, _WRAP_ATTR, True)
    setattr(patched, "__wrapped__", original)
    setattr(cls, "_phase3_scan_and_enter", patched)
    _PATCHED = True
    logger.warning("%s module=%s replacements=%d", _MARKER, getattr(module, "__name__", "<unknown>"), count)
    print(f"[NIJA-PRINT] PHASE3_FALLBACK_HOLD_SKIP_PATCHED marker=20260703u | module={getattr(module, '__name__', '<unknown>')} replacements={count}", flush=True)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name, module in list(sys.modules.items()):
        if not isinstance(module, ModuleType):
            continue
        if name in {"bot.nija_core_loop", "nija_core_loop"} or hasattr(module, "NijaCoreLoop"):
            patched = _install_on_module(module) or patched
    return patched


def _start_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + 300.0
        patched_any = False
        while time.time() < deadline:
            patched_any = _try_patch_loaded() or patched_any
            if _PATCHED:
                break
            time.sleep(1.0)
        logger.warning("PHASE3_FALLBACK_HOLD_SKIP_MONITOR_COMPLETE marker=20260703u patched=%s patched_any=%s", _PATCHED, patched_any)

    threading.Thread(target=_monitor, name="phase3-fallback-hold-skip-monitor", daemon=True).start()
    logger.warning("PHASE3_FALLBACK_HOLD_SKIP_MONITOR_STARTED marker=20260703u")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _INSTALL_LOCK:
        _try_patch_loaded()
        _start_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            logger.warning("PHASE3_FALLBACK_HOLD_SKIP_INSTALL_COMPLETE marker=20260703u already_installed=True patched=%s", _PATCHED)
            return
        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name in {"bot.nija_core_loop", "nija_core_loop"} or hasattr(module, "NijaCoreLoop"):
                _install_on_module(module)
            _try_patch_loaded()
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
        logger.warning("PHASE3_FALLBACK_HOLD_SKIP_INSTALL_COMPLETE marker=20260703u patched=%s", _PATCHED)
