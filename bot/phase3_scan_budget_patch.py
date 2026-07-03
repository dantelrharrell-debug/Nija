"""Bound Phase 3 scan breadth and expose terminal admission blockers.

The live scanner can load 1,100+ markets. A blind alphabetical budget reaches
execution quickly, but may spend the first cycles on low-liquidity long-tail
pairs. This patch keeps the fast budget while prioritizing liquid majors first,
then rotates through the rest of the universe across cycles.

It also repairs the operator-facing telemetry for the case where a pair is
ranked/selected but no order is submitted. In that case NIJA now emits a
PHASE3_TERMINAL_BLOCKER line instead of reporting top_veto=none/top_reject=none.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.phase3_scan_budget")
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_PATCHED = False
_COUNTER = 0
_COUNTER_LOCK = threading.Lock()

_PRIORITY_BASES = (
    "BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "LINK", "LTC", "BCH",
    "AVAX", "DOT", "ATOM", "HBAR", "NEAR", "AAVE", "UNI", "ETC", "XLM",
    "FIL", "ICP", "INJ", "OP", "ARB", "SEI", "SUI", "APT", "MATIC", "POL",
)
_PRIORITY_SYMBOLS = tuple(
    f"{base}-{quote}"
    for base in _PRIORITY_BASES
    for quote in ("USD", "USDT", "USDC")
)


def _int_env(name: str, default: int) -> int:
    try:
        value = int(float(os.environ.get(name, str(default)) or default))
        return max(1, value)
    except Exception:
        return int(default)


def _budget_for(symbol_count: int, available_slots: int) -> int:
    default_budget = max(4, min(8, max(available_slots, 1)))
    budget = _int_env("NIJA_PHASE3_MAX_SYMBOLS_PER_CYCLE", default_budget)
    minimum = _int_env("NIJA_PHASE3_MIN_SYMBOLS_PER_CYCLE", min(4, default_budget))
    budget = max(minimum, budget)
    return min(max(1, int(symbol_count)), budget)


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").upper().replace("/", "-").replace(":", "-")


def _priority_rank(symbol: str) -> int:
    norm = _normalize_symbol(symbol)
    try:
        return _PRIORITY_SYMBOLS.index(norm)
    except ValueError:
        return len(_PRIORITY_SYMBOLS) + 1


def _prioritize_symbols(symbols: list[str]) -> tuple[list[str], int]:
    if not symbols:
        return symbols, 0
    priority = [s for s in symbols if _priority_rank(s) < len(_PRIORITY_SYMBOLS)]
    priority.sort(key=_priority_rank)
    seen: set[str] = set()
    ordered: list[str] = []
    for s in priority + symbols:
        norm = _normalize_symbol(s)
        if norm in seen:
            continue
        seen.add(norm)
        ordered.append(s)
    return ordered, len(priority)


def _rotate_symbols(symbols: list[str], budget: int) -> tuple[list[str], int, int]:
    global _COUNTER
    count = len(symbols)
    if count <= budget:
        return symbols, 0, 0
    ordered, priority_count = _prioritize_symbols(symbols)
    priority_slice = ordered[: min(priority_count, max(1, min(budget, 3)))]
    remainder = ordered[priority_count:] if priority_count else ordered
    remaining_budget = max(0, budget - len(priority_slice))
    if remaining_budget <= 0 or not remainder:
        return priority_slice[:budget], 0, priority_count
    with _COUNTER_LOCK:
        offset = (_COUNTER * remaining_budget) % len(remainder)
        _COUNTER += 1
    window = remainder[offset:offset + remaining_budget]
    if len(window) < remaining_budget:
        window.extend(remainder[:remaining_budget - len(window)])
    return (priority_slice + window)[:budget], offset, priority_count


def _count(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _top_reason(mapping: Any) -> str:
    if not isinstance(mapping, dict) or not mapping:
        return "none"
    best_key = "none"
    best_count = 0
    for key, value in mapping.items():
        count = _count(value)
        if count > best_count:
            best_key = str(key)
            best_count = count
    return best_key if best_count > 0 else "none"


def _emit_terminal_blocker(self: Any, result: Any, elapsed_ms: float) -> None:
    try:
        if not isinstance(result, tuple) or len(result) < 4:
            return
        entries, blocked, scored, gate_rejections = result[:4]
        entries_i = _count(entries)
        blocked_i = _count(blocked)
        scored_i = _count(scored)
        if entries_i > 0 or blocked_i <= 0:
            return
        gate_top = _top_reason(gate_rejections)
        reject_top = _top_reason(getattr(self, "reject_reason_counts", {}))
        veto_top = _top_reason(getattr(self, "veto_reason_counts", {}))
        if gate_top == "none" and reject_top == "none" and veto_top == "none":
            terminal = "submit_suppressed_after_selection"
            detail = "candidate selected but no terminal submit/reject reason was recorded"
        elif gate_top != "none":
            terminal = gate_top
            detail = "gate_rejection_counter"
        elif reject_top != "none":
            terminal = reject_top
            detail = "reject_histogram"
        else:
            terminal = veto_top
            detail = "veto_histogram"
        try:
            record_reject = getattr(self, "_record_reject", None)
            if callable(record_reject):
                record_reject(terminal)
        except Exception:
            pass
        logger.critical(
            "PHASE3_TERMINAL_BLOCKER status=ENTRY_BLOCKED scored=%d entered=%d blocked=%d terminal_reason=%s detail=%s gate_top=%s top_reject=%s top_veto=%s elapsed_ms=%.0f",
            scored_i,
            entries_i,
            blocked_i,
            terminal,
            detail,
            gate_top,
            reject_top,
            veto_top,
            elapsed_ms,
        )
        print(
            f"[NIJA-PRINT] PHASE3_TERMINAL_BLOCKER | scored={scored_i} entered={entries_i} blocked={blocked_i} reason={terminal} detail={detail}",
            flush=True,
        )
    except Exception as exc:
        logger.warning("PHASE3_TERMINAL_BLOCKER_FAILED err=%s", exc)


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
        priority_count = 0
        if original_count > budget:
            symbols, offset, priority_count = _rotate_symbols(list(symbols), budget)
            logger.critical(
                "PHASE3_SCAN_BUDGET_APPLIED original_symbols=%d budget=%d slots=%d offset=%d priority_matches=%d symbols=%s cycle_id=%s",
                original_count,
                budget,
                available_slots,
                offset,
                priority_count,
                ",".join(str(s) for s in symbols),
                getattr(snapshot, "cycle_id", ""),
            )
            print(
                f"[NIJA-PRINT] PHASE3_SCAN_BUDGET_APPLIED | original={original_count} "
                f"budget={budget} slots={available_slots} offset={offset} "
                f"priority_matches={priority_count} symbols={','.join(str(s) for s in symbols)}",
                flush=True,
            )
        started = time.monotonic()
        result = original(
            self,
            broker=broker,
            snapshot=snapshot,
            symbols=symbols,
            available_slots=available_slots,
            zero_signal_streak=zero_signal_streak,
        )
        _emit_terminal_blocker(self, result, (time.monotonic() - started) * 1000.0)
        return result

    setattr(_patched_phase3_scan_and_enter, "_nija_phase3_scan_budget_wrapped", True)
    setattr(cls, "_phase3_scan_and_enter", _patched_phase3_scan_and_enter)
    _PATCHED = True
    logger.warning("PHASE3_SCAN_BUDGET_PATCHED module=%s", getattr(module, "__name__", "<unknown>"))
    logger.warning("PHASE3_TERMINAL_BLOCKER_TRACE_PATCHED module=%s", getattr(module, "__name__", "<unknown>"))
    print("[NIJA-PRINT] PHASE3_TERMINAL_BLOCKER_TRACE_PATCHED", flush=True)
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
