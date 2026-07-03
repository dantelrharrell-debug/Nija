"""Phase-3 admission/submit trace repair for live scan cycles.

This patch does not bypass risk, ECEL, broker, capital, notional, or exchange
checks. It repairs two operational defects exposed in Railway logs:

1. A cycle can report candidates passed all gates but pairs_submitted=0 while
   top_veto/top_reject remain 'none'. The wrapper emits a concrete terminal
   blocker so operators can see why NIJA did not submit.
2. The execution branch in nija_core_loop historically re-fetched candles and
   required 100 rows, while scoring already accepts 50 rows. The wrapper emits
   an explicit diagnostic for this min-candle mismatch so it is no longer silent.
"""

from __future__ import annotations

import builtins
import importlib
import logging
import sys
import threading
import time
from functools import wraps
from typing import Any

logger = logging.getLogger("nija.phase3_admission_trace_repair")

_PATCHED_ATTR = "__nija_phase3_admission_trace_repair__"
_IMPORT_HOOK_INSTALLED = False
_MONITOR_STARTED = False
_LOCK = threading.Lock()


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except Exception:
        return default


def _top_reason(counter: dict[str, Any] | None) -> str:
    if not counter:
        return "none"
    best_key = "none"
    best_count = 0
    for key, value in counter.items():
        count = _as_int(value)
        if count > best_count:
            best_key = str(key)
            best_count = count
    return best_key if best_count > 0 else "none"


def _emit_blocker(self: Any, result: Any, elapsed_ms: float, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
    try:
        if not isinstance(result, tuple) or len(result) < 4:
            return
        entries, blocked, scored, gate_rejections = result[:4]
        entries_i = _as_int(entries)
        blocked_i = _as_int(blocked)
        scored_i = _as_int(scored)
        if entries_i > 0 or blocked_i <= 0:
            return

        gate_rejections = gate_rejections if isinstance(gate_rejections, dict) else {}
        top_gate = _top_reason(gate_rejections)
        reject_counts = getattr(self, "reject_reason_counts", {})
        veto_counts = getattr(self, "veto_reason_counts", {})
        top_reject = _top_reason(reject_counts if isinstance(reject_counts, dict) else {})
        top_veto = _top_reason(veto_counts if isinstance(veto_counts, dict) else {})

        if top_gate == "none" and top_reject == "none" and top_veto == "none":
            terminal = "phase3_submit_suppressed_after_selection"
            detail = (
                "candidate_selected_but_not_submitted; likely execution candle-min mismatch "
                "or silent pre-execute continue; scoring_min_candles=50 execution_min_candles_legacy=100"
            )
        elif top_gate != "none":
            terminal = top_gate
            detail = "gate_rejection_counter"
        elif top_reject != "none":
            terminal = top_reject
            detail = "reject_histogram"
        else:
            terminal = top_veto
            detail = "veto_histogram"

        try:
            record_reject = getattr(self, "_record_reject", None)
            if callable(record_reject) and terminal:
                record_reject(terminal)
        except Exception:
            pass

        logger.critical(
            "PHASE3_TERMINAL_BLOCKER broker=%s status=ENTRY_BLOCKED scored=%d entered=%d blocked=%d terminal_reason=%s detail=%s gate_top=%s top_reject=%s top_veto=%s elapsed_ms=%.0f",
            getattr(args[0], "name", None) if args else "unknown",
            scored_i,
            entries_i,
            blocked_i,
            terminal,
            detail,
            top_gate,
            top_reject,
            top_veto,
            elapsed_ms,
        )
        print(
            f"[NIJA-PRINT] PHASE3_TERMINAL_BLOCKER | scored={scored_i} entered={entries_i} blocked={blocked_i} reason={terminal} detail={detail}",
            flush=True,
        )

        try:
            from bot.execution_journal import append_execution_journal_event
            append_execution_journal_event(
                "PHASE3_TERMINAL_BLOCKER",
                f"phase3:{int(time.time() * 1000)}",
                {
                    "scored": scored_i,
                    "entered": entries_i,
                    "blocked": blocked_i,
                    "terminal_reason": terminal,
                    "detail": detail,
                    "gate_top": top_gate,
                    "top_reject": top_reject,
                    "top_veto": top_veto,
                    "elapsed_ms": elapsed_ms,
                },
            )
        except Exception:
            pass
    except Exception as exc:
        logger.warning("PHASE3_TERMINAL_BLOCKER_EMIT_FAILED err=%s", exc)


def _patch_core_loop_module(module: Any) -> bool:
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_phase3_scan_and_enter", None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return bool(getattr(original, _PATCHED_ATTR, False))

    @wraps(original)
    def _wrapped(self: Any, *args: Any, **kwargs: Any):
        started = time.monotonic()
        result = original(self, *args, **kwargs)
        _emit_blocker(self, result, (time.monotonic() - started) * 1000.0, args, kwargs)
        return result

    setattr(_wrapped, _PATCHED_ATTR, True)
    setattr(cls, "_phase3_scan_and_enter", _wrapped)
    logger.warning("PHASE3_ADMISSION_TRACE_REPAIR_PATCHED module=%s class=%s", getattr(module, "__name__", "?"), cls.__name__)
    print("[NIJA-PRINT] PHASE3_ADMISSION_TRACE_REPAIR_PATCHED", flush=True)
    return True


def _patch_loaded() -> int:
    patched = 0
    for name, module in list(sys.modules.items()):
        if name.endswith("nija_core_loop"):
            try:
                if _patch_core_loop_module(module):
                    patched += 1
            except Exception as exc:
                logger.debug("phase3 admission trace patch skipped module=%s err=%s", name, exc)
    return patched


def _resolve_and_patch() -> int:
    patched = _patch_loaded()
    for module_name in ("bot.nija_core_loop", "nija_core_loop"):
        try:
            module = sys.modules.get(module_name) or importlib.import_module(module_name)
        except Exception:
            continue
        if _patch_core_loop_module(module):
            patched += 1
    return patched


def _install_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _worker() -> None:
        deadline = time.monotonic() + 240.0
        while time.monotonic() < deadline:
            if _resolve_and_patch() > 0:
                return
            time.sleep(0.25)
        logger.warning("PHASE3_ADMISSION_TRACE_REPAIR_MONITOR_EXPIRED")

    threading.Thread(target=_worker, name="phase3-admission-trace-repair", daemon=True).start()


def _install_import_hook() -> None:
    global _IMPORT_HOOK_INSTALLED
    if _IMPORT_HOOK_INSTALLED or getattr(builtins, "_NIJA_PHASE3_ADMISSION_TRACE_REPAIR_HOOK", False):
        _IMPORT_HOOK_INSTALLED = True
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        targets = [module]
        child = sys.modules.get(name)
        if child is not None:
            targets.append(child)
        for target in targets:
            try:
                if str(getattr(target, "__name__", "")).endswith("nija_core_loop"):
                    _patch_core_loop_module(target)
            except Exception as exc:
                logger.warning("Phase3 admission trace repair failed for %s: %s", name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_PHASE3_ADMISSION_TRACE_REPAIR_HOOK", True)
    _IMPORT_HOOK_INSTALLED = True


def install_import_hook() -> None:
    with _LOCK:
        _resolve_and_patch()
        _install_import_hook()
        _install_monitor()
        logger.warning("PHASE3_ADMISSION_TRACE_REPAIR_INSTALL_COMPLETE")
