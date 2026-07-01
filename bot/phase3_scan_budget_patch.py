"""Bound Phase 3 scan breadth so live cycles reach ranking/execution promptly.

The live scanner can load 1,100+ markets. A blind alphabetical budget reaches
execution quickly, but may spend the first cycles on low-liquidity long-tail
pairs. This patch keeps the fast budget while prioritizing liquid majors first,
then rotates through the rest of the universe across cycles.

It does not loosen signal thresholds, bypass liquidity/risk/order gates, force
orders, or change exchange validation. It only chooses a better per-cycle symbol
window before delegating to the existing _phase3_scan_and_enter implementation.
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

# High-liquidity USD symbols first. Keep both common exchange formats because
# Kraken/Coinbase/OKX adapters may expose either USD or USDT quote symbols.
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
    # Runtime evidence showed selected candidates could be reached in a small
    # 5-symbol pass. Keep default compact; operators can raise it with
    # NIJA_PHASE3_MAX_SYMBOLS_PER_CYCLE.
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
    priority = [s for s in symbols if _priority_rank(s) <= len(_PRIORITY_SYMBOLS)]
    # Preserve priority ordering by the curated list, then original order for the
    # remaining long tail. De-dupe without losing original symbol spelling.
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
    # Always keep at least one liquid priority symbol in the first cycles when
    # available, then rotate the remainder so the full universe is still covered.
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
        return original(
            self,
            broker=broker,
            snapshot=snapshot,
            symbols=symbols,
            available_slots=available_slots,
            zero_signal_streak=zero_signal_streak,
        )

    setattr(_patched_phase3_scan_and_enter, "_nija_phase3_scan_budget_wrapped", True)
    setattr(cls, "_phase3_scan_and_enter", _patched_phase3_scan_budget_wrapped if False else _patched_phase3_scan_and_enter)
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
