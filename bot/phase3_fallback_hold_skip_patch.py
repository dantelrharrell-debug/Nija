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
_PATCHED_CLASSES: set[str] = set()
_MONITOR_STARTED = False
_INSTALL_LOCK = threading.Lock()
_PHASE3_WRAP_ATTR = "_nija_phase3_fallback_hold_skip_phase3_wrapped_v20260703x"
_MARKER = "PHASE3_FALLBACK_HOLD_SKIP_PATCHED marker=20260703x"

_SKIP_BLOCK = '''
                if isinstance(analysis, dict):
                    _hold_skip = bool(
                        str(analysis.get("action", "")).strip().lower() == "hold"
                        and (
                            analysis.get("blocked_before_execute_action")
                            or analysis.get("skip_before_execute_action")
                            or analysis.get("order_should_not_submit")
                            or analysis.get("fallback_entry_skipped")
                        )
                    )
                    if _hold_skip:
                        blocked += 1
                        _skip_reason = str(analysis.get("reason") or analysis.get("detail") or "fallback_hold_skip")
                        _skip_stage = str(analysis.get("filter_stage") or "fallback_prefilter")
                        _funnel["profitability"] = ("FAIL", _skip_reason)
                        logger.critical(
                            "PHASE3_FALLBACK_HOLD_SKIP_APPLIED marker=20260703x symbol=%s stage=%s reason=%s action=hold core_loop_skip=true",
                            sig.symbol,
                            _skip_stage,
                            _skip_reason,
                        )
                        print(
                            f"[NIJA-PRINT] PHASE3_FALLBACK_HOLD_SKIP_APPLIED marker=20260703x symbol={sig.symbol} stage={_skip_stage} reason={_skip_reason} core_loop_skip=true",
                            flush=True,
                        )
                        continue
'''


def _iter_chain(fn: Any):
    seen: set[int] = set()
    cur = fn
    depth = 0
    while callable(cur) and id(cur) not in seen:
        seen.add(id(cur))
        yield depth, cur
        cur = getattr(cur, "__wrapped__", None)
        depth += 1


def _find_source_with_submit(fn: Any):
    for depth, candidate in _iter_chain(fn):
        try:
            source = textwrap.dedent(inspect.getsource(candidate))
        except Exception:
            continue
        needle = "success = self.apex.execute_action(analysis, sig.symbol)"
        if needle in source:
            return depth, candidate, source, needle
    return -1, None, "", ""


def _patch_core_loop_phase3(cls: type, *, label: str) -> bool:
    current = getattr(cls, "_phase3_scan_and_enter", None)
    if not callable(current):
        return False
    if getattr(current, _PHASE3_WRAP_ATTR, False):
        _PATCHED_CLASSES.add(f"{label}.{cls.__name__}._phase3_scan_and_enter")
        return True

    depth, target, source, needle = _find_source_with_submit(current)
    if target is None:
        logger.warning("PHASE3_FALLBACK_HOLD_SKIP_PHASE3_NEEDLE_MISSING marker=20260703x chain_checked=true")
        return False

    patched_source = source.replace(needle, _SKIP_BLOCK + "                " + needle, 1)
    namespace = dict(getattr(target, "__globals__", getattr(current, "__globals__", {})))
    try:
        exec(compile(patched_source, "<phase3_fallback_hold_skip_guard>", "exec"), namespace)
        patched = namespace.get("_phase3_scan_and_enter")
        if not callable(patched):
            raise RuntimeError("patched function not produced")
    except Exception as exc:
        logger.warning("PHASE3_FALLBACK_HOLD_SKIP_PHASE3_COMPILE_FAILED marker=20260703x err=%s", exc)
        return False

    setattr(patched, _PHASE3_WRAP_ATTR, True)
    setattr(patched, "__wrapped__", current)
    setattr(cls, "_phase3_scan_and_enter", patched)
    _PATCHED_CLASSES.add(f"{label}.{cls.__name__}._phase3_scan_and_enter")
    logger.warning("%s class=%s source_depth=%s", _MARKER, f"{label}.{cls.__name__}", depth)
    print(f"[NIJA-PRINT] PHASE3_FALLBACK_HOLD_SKIP_PATCHED marker=20260703x | class={label}.{cls.__name__} source_depth={depth}", flush=True)
    return True


def _install_on_module(module: ModuleType) -> bool:
    cls = getattr(module, "NijaCoreLoop", None)
    if isinstance(cls, type):
        return _patch_core_loop_phase3(cls, label=getattr(module, "__name__", "<unknown>"))
    return False


def _try_patch_loaded() -> bool:
    patched = False
    for name, module in list(sys.modules.items()):
        if isinstance(module, ModuleType) and (name in {"bot.nija_core_loop", "nija_core_loop"} or hasattr(module, "NijaCoreLoop")):
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
            if patched_any:
                break
            time.sleep(1.0)
        logger.warning("PHASE3_FALLBACK_HOLD_SKIP_MONITOR_COMPLETE marker=20260703x patched_any=%s patched_classes=%s", patched_any, sorted(_PATCHED_CLASSES))

    threading.Thread(target=_monitor, name="phase3-fallback-hold-skip-monitor", daemon=True).start()
    logger.warning("PHASE3_FALLBACK_HOLD_SKIP_MONITOR_STARTED marker=20260703x")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _INSTALL_LOCK:
        _try_patch_loaded()
        _start_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            logger.warning("PHASE3_FALLBACK_HOLD_SKIP_INSTALL_COMPLETE marker=20260703x already_installed=True patched_classes=%s", sorted(_PATCHED_CLASSES))
            return
        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name in {"bot.nija_core_loop", "nija_core_loop"} or hasattr(module, "NijaCoreLoop"):
                _install_on_module(module)
            _try_patch_loaded()
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
        logger.warning("PHASE3_FALLBACK_HOLD_SKIP_INSTALL_COMPLETE marker=20260703x patched_classes=%s", sorted(_PATCHED_CLASSES))
