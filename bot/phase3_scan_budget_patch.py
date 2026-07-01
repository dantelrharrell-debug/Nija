"""Bound Phase 3 scan breadth so live cycles reach ranking/execution promptly.

Latest live logs show the system now enters NijaCoreLoop.run_scan_phase(), loads a
large 1,181-symbol universe, and produces SIGNAL_PASSED candidates, but still has
zero execute attempts because the scan spends minutes traversing the large symbol
universe before reaching the rank/submit section.

This patch does not loosen signal thresholds, bypass risk/order gates, or force
orders. It applies a rotating per-cycle symbol budget before delegating to the
existing _phase3_scan_and_enter implementation so each live cycle reaches the
existing ranking and execute_action path promptly while still covering different
parts of the universe across cycles.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.phase3_scan_budget")
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_PATCHED = False
_COUNTER = 0
_COUNTER_LOCK = threading.Lock()


def _int_env(name: str, default: int) -> int:
    try:
        value = int(float(os.environ.get(name, str(default)) or default))
        return max(1, value)
    except Exception:
        return int(default)


def _budget_for(symbol_count: int, available_slots: int) -> int:
    # Runtime evidence showed ~10 symbols in ~48s. A default budget of 8 lets the
    # cycle reach ranking/execution in one short pass instead of spending minutes
    # on 80+ symbols. Operators can raise it with NIJA_PHASE3_MAX_SYMBOLS_PER_CYCLE.
    default_budget = max(4, min(8, max(available_slots, 1)))
    budget = _int_env("NIJA_PHASE3_MAX_SYMBOLS_PER_CYCLE", default_budget)
    minimum = _int_env("NIJA_PHASE3_MIN_SYMBOLS_PER_CYCLE", min(4, default_budget))
    budget = max(minimum, budget)
    return min(max(1, int(symbol_count)), budget)


def _rotate_symbols(symbols: list[str], budget: int) -> tuple[list[str], int]:
    global _COUNTER
    count = len(symbols)
    if count <= budget:
        return symbols, 0
    with _COUNTER_LOCK:
        offset = (_COUNTER * budget) % count
        _COUNTER += 1
    window = symbols[offset:offset + budget]
    if len(window) < budget:
        window.extend(symbols[:budget - len(window)])
    return window, offset


def _install_on_module(module: ModuleType) -> bool:
    global _PATCHED
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False

    original = getattr(cls, "_phase3_scan_and_enter", None)
    if not callable(original):
        return False
    if getattr(original, "_nija_phase3_scan_budget_wrapped", False):
        _PATCHED = True
        return True

    def _patched_phase3_scan_and_enter(
        self: Any,
        broker: Any,
        snapshot: Any,
        symbols: list[str],
        available_slots: int,
        zero_signal_streak: int = 0,
    ):
        original_count = len(symbols or [])
        budget = _budget_for(original_count, int(available_slots or 0))
        offset = 0
        if original_count > budget:
            symbols, offset = _rotate_symbols(list(symbols), budget)
            logger.critical(
                "PHASE3_SCAN_BUDGET_APPLIED original_symbols=%d budget=%d slots=%d offset=%d cycle_id=%s",
                original_count,
                budget,
                available_slots,
                offset,
                getattr(snapshot, "cycle_id", ""),
            )
            print(
                f"[NIJA-PRINT] PHASE3_SCAN_BUDGET_APPLIED | original={original_count} "
                f"budget={budget} slots={available_slots} offset={offset}",
                flush=True,
            )
        return original(
            self,
            broker=broker,
            snapshot=snapshot,
            symbols=symbols,
            available_slots=available_slots,
            zero_signal_streak=zero_signal_streak,
        )

    setattr(_patched_phase3_scan_and_enter, "_nija_phase3_scan_budget_wrapped", True)
    setattr(cls, "_phase3_scan_and_enter", _patched_phase3_scan_and_enter)
    _PATCHED = True
    logger.warning("PHASE3_SCAN_BUDGET_PATCHED module=%s", getattr(module, "__name__", "<unknown>"))
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.nija_core_loop", "nija_core_loop"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _install_on_module(module) or patched
    return patched


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    _try_patch_loaded()
    if _ORIGINAL_IMPORT_MODULE is not None:
        logger.warning("PHASE3_SCAN_BUDGET_INSTALL_COMPLETE already_installed=True patched=%s", _PATCHED)
        return

    _ORIGINAL_IMPORT_MODULE = importlib.import_module

    def _wrapped_import_module(name: str, package: str | None = None):
        module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
        if name in {"bot.nija_core_loop", "nija_core_loop"}:
            _install_on_module(module)
        return module

    importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
    logger.warning("PHASE3_SCAN_BUDGET_INSTALL_COMPLETE patched=%s", _PATCHED)
