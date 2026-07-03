"""Preserve multiple Phase 3 candidates when FORCE_NEXT_CYCLE is active.

Observed runtime behavior after the 20260703j overselect repair:
- rank_and_select correctly returns 8 candidates.
- NijaCoreLoop then hits its FORCE_NEXT_CYCLE block and replaces the selected
  list with only [top_candidate].
- The cycle attempts one order, receives a safety rejection, and ends without
  trying the remaining ranked candidates.

This patch keeps the intent of FORCE_NEXT_CYCLE—make the cycle executable and
force fallback_active=True—but prevents it from collapsing an already ranked
multi-candidate list down to a singleton.

Safety contract:
- Does not bypass expectancy, risk, kill switch, writer authority, TPE, ECEL, or
  exchange constraints.
- Does not increase max successful entries. The original execution loop still
  stops at MAX_ENTRIES_PER_CYCLE / available slots.
- Only changes selection preservation: multiple already-ranked candidates remain
  available as replacement attempts after prior downstream rejections.
"""

from __future__ import annotations

import builtins
import importlib
import inspect
import logging
import sys
import textwrap
import threading
import time
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.phase3_force_next_preserve_selection")

_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_ORIGINAL_BUILTINS_IMPORT: Optional[Callable[..., Any]] = None
_PATCHED = False
_MONITOR_STARTED = False
_LOCK = threading.Lock()
_MARKER = "PHASE3_FORCE_NEXT_PRESERVE_SELECTION_PATCHED marker=20260703k"
_ATTR = "_nija_force_next_preserve_selection_v20260703k"

_OLD_BLOCK = '''        if _force_this_cycle and candidates:
            top_candidate = max(candidates, key=lambda s: s.composite_score)
            top_candidate.metadata["bypass_quality_filter"] = True
            top_candidate.metadata["hard_bypass_streak"] = zero_signal_streak
            for c in candidates:
                logger.info(
                    "🔹 Candidate: %s | Score: %.1f",
                    getattr(c, "symbol", "UNKNOWN"),
                    c.composite_score,
                )
            logger.warning(
                "🚀 FORCE_NEXT_CYCLE active — forcing entry on top candidate "
                "%s (score=%.1f, streak=%d)",
                top_candidate.symbol,
                top_candidate.composite_score,
                zero_signal_streak,
            )
            selected = [top_candidate]
            fallback_active = True  # ensure the execution block forces the action
'''

_NEW_BLOCK = '''        if _force_this_cycle and candidates:
            top_candidate = max(candidates, key=lambda s: s.composite_score)
            top_candidate.metadata["bypass_quality_filter"] = True
            top_candidate.metadata["hard_bypass_streak"] = zero_signal_streak
            for c in candidates:
                logger.info(
                    "🔹 Candidate: %s | Score: %.1f",
                    getattr(c, "symbol", "UNKNOWN"),
                    c.composite_score,
                )
            if len(selected) > 1:
                for _sig in selected:
                    try:
                        _sig.metadata["bypass_quality_filter"] = True
                        _sig.metadata["hard_bypass_streak"] = zero_signal_streak
                        _sig.metadata["force_next_preserved_selection"] = True
                    except Exception:
                        pass
                logger.warning(
                    "🚀 FORCE_NEXT_CYCLE active — preserving %d ranked candidates instead of collapsing to top candidate %s (score=%.1f, streak=%d)",
                    len(selected),
                    top_candidate.symbol,
                    top_candidate.composite_score,
                    zero_signal_streak,
                )
                print(
                    f"[NIJA-PRINT] PHASE3_FORCE_NEXT_PRESERVED_SELECTION marker=20260703k selected={len(selected)} top={top_candidate.symbol}",
                    flush=True,
                )
            else:
                logger.warning(
                    "🚀 FORCE_NEXT_CYCLE active — forcing entry on top candidate "
                    "%s (score=%.1f, streak=%d)",
                    top_candidate.symbol,
                    top_candidate.composite_score,
                    zero_signal_streak,
                )
                selected = [top_candidate]
            fallback_active = True  # ensure the execution block forces the action
'''


def _patch_core_loop_module(module: ModuleType) -> bool:
    global _PATCHED
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_phase3_scan_and_enter", None)
    if not callable(original):
        return False
    if getattr(original, _ATTR, False):
        _PATCHED = True
        return True
    try:
        source = inspect.getsource(original)
        dedented = textwrap.dedent(source)
        if _OLD_BLOCK not in source and textwrap.dedent(_OLD_BLOCK) not in dedented:
            logger.warning("PHASE3_FORCE_NEXT_PRESERVE_SELECTION_SOURCE_MISS marker=20260703k module=%s", getattr(module, "__name__", "<unknown>"))
            return False
        if _OLD_BLOCK in source:
            patched_source = source.replace(_OLD_BLOCK, _NEW_BLOCK)
        else:
            patched_source = dedented.replace(textwrap.dedent(_OLD_BLOCK), textwrap.dedent(_NEW_BLOCK))
        namespace = dict(original.__globals__)
        exec(compile(patched_source, getattr(original, "__code__", None).co_filename if getattr(original, "__code__", None) else "<phase3_force_next_patch>", "exec"), namespace)
        replacement = namespace.get(original.__name__)
        if not callable(replacement):
            raise RuntimeError("patched function was not created")
        setattr(replacement, _ATTR, True)
        setattr(cls, "_phase3_scan_and_enter", replacement)
        _PATCHED = True
        logger.warning("%s module=%s", _MARKER, getattr(module, "__name__", "<unknown>"))
        print("[NIJA-PRINT] PHASE3_FORCE_NEXT_PRESERVE_SELECTION_PATCHED marker=20260703k", flush=True)
        return True
    except Exception as exc:
        logger.warning("PHASE3_FORCE_NEXT_PRESERVE_SELECTION_FAILED marker=20260703k module=%s err=%s", getattr(module, "__name__", "<unknown>"), exc)
        return False


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.nija_core_loop", "nija_core_loop"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_core_loop_module(module) or patched
    return patched


def _start_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + 240.0
        while time.time() < deadline:
            if _try_patch_loaded():
                return
            time.sleep(0.25)
        logger.warning("PHASE3_FORCE_NEXT_PRESERVE_SELECTION_MONITOR_EXPIRED patched=%s", _PATCHED)

    threading.Thread(target=_monitor, name="phase3-force-next-preserve-selection", daemon=True).start()
    logger.warning("PHASE3_FORCE_NEXT_PRESERVE_SELECTION_MONITOR_STARTED marker=20260703k")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE, _ORIGINAL_BUILTINS_IMPORT
    with _LOCK:
        logger.warning("PHASE3_FORCE_NEXT_PRESERVE_SELECTION_INSTALL_START marker=20260703k")
        print("[NIJA-PRINT] PHASE3_FORCE_NEXT_PRESERVE_SELECTION_INSTALL_START marker=20260703k", flush=True)
        _try_patch_loaded()
        _start_monitor()

        if _ORIGINAL_IMPORT_MODULE is None:
            _ORIGINAL_IMPORT_MODULE = importlib.import_module

            def _wrapped_import_module(name: str, package: str | None = None):
                module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
                if name in {"bot.nija_core_loop", "nija_core_loop"}:
                    _patch_core_loop_module(module)
                return module

            importlib.import_module = _wrapped_import_module  # type: ignore[assignment]

        if _ORIGINAL_BUILTINS_IMPORT is None:
            _ORIGINAL_BUILTINS_IMPORT = builtins.__import__

            def _wrapped_builtin_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
                module = _ORIGINAL_BUILTINS_IMPORT(name, globals, locals, fromlist, level)  # type: ignore[misc]
                try:
                    if name in {"bot.nija_core_loop", "nija_core_loop"} or name.endswith(".nija_core_loop"):
                        target = sys.modules.get("bot.nija_core_loop") or sys.modules.get("nija_core_loop") or module
                        if isinstance(target, ModuleType):
                            _patch_core_loop_module(target)
                    else:
                        _try_patch_loaded()
                except Exception as exc:
                    logger.debug("Phase3 force-next preserve import hook skipped: %s", exc)
                return module

            builtins.__import__ = _wrapped_builtin_import

        logger.warning("PHASE3_FORCE_NEXT_PRESERVE_SELECTION_INSTALL_COMPLETE marker=20260703k patched=%s", _PATCHED)
