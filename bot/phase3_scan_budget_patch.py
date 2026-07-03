"""Bound Phase 3 scan breadth and expose terminal admission blockers.

The live scanner can load 1,100+ markets. A blind alphabetical budget reaches
execution quickly, but may spend the first cycles on low-liquidity long-tail
pairs. This patch keeps the fast budget while prioritizing liquid majors first,
then rotates through the rest of the universe across cycles.

It also repairs the operator-facing telemetry for the case where a pair is
ranked/selected but no order is submitted. In that case NIJA now emits a
PHASE3_TERMINAL_BLOCKER line instead of reporting top_veto=none/top_reject=none.

2026-07-03f: add broker-aware scan filtering. When OKX is selected, do not feed
it the merged Kraken/Coinbase universe. Convert USD-style majors to OKX USDT
pairs and keep only symbols known to be listed on OKX, preventing repeated
51001/data_insufficient cycles on non-OKX markets.

2026-07-03i: add safe execution-candidate over-selection. The expectancy gate
must remain intact, but one negative-expectancy candidate should not end a cycle
when more ranked candidates and open position slots are available. The patch
lets rank_and_select return more attempts, capped by real available slots.

2026-07-03m: canonicalize Phase 3 patching to bot.* modules only. This prevents
duplicate wrappers when Python also exposes the same file as a top-level module.
"""

from __future__ import annotations

import importlib
import logging
import os
import re
import sys
import threading
import time
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.phase3_scan_budget")

_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_PATCHED = False
_AI_PATCHED = False
_COUNTER = 0
_COUNTER_LOCK = threading.Lock()
_INSTALL_LOCK = threading.Lock()

_DEPLOY_MARKER = "PHASE3_TERMINAL_BLOCKER_TRACE_PATCHED marker=20260703i"
_SCAN_ATTR = "_nija_phase3_scan_budget_wrapped_v20260703i"
_AI_SELECT_ATTR = "_nija_phase3_overselect_wrapped_v20260703i"
_CANONICAL_CORE_LOOP_MODULE = "bot.nija_core_loop"
_CANONICAL_AI_ENGINE_MODULE = "bot.nija_ai_engine"

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
_OKX_CORE_USDT = {
    "BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT", "ADA-USDT",
    "LINK-USDT", "LTC-USDT", "BCH-USDT", "AVAX-USDT", "DOT-USDT", "ATOM-USDT",
    "HBAR-USDT", "NEAR-USDT", "AAVE-USDT", "UNI-USDT", "ETC-USDT", "XLM-USDT",
    "FIL-USDT", "ICP-USDT", "INJ-USDT", "OP-USDT", "ARB-USDT", "SUI-USDT",
    "APT-USDT", "PEPE-USDT", "SHIB-USDT", "TRX-USDT", "TON-USDT", "BNB-USDT",
    "MKR-USDT", "COMP-USDT", "CRV-USDT", "SAND-USDT", "MANA-USDT", "GALA-USDT",
}


def _int_env(name: str, default: int) -> int:
    try:
        value = int(float(os.environ.get(name, str(default)) or default))
        return max(1, value)
    except Exception:
        return int(default)


def _is_named_file_module(module: ModuleType, canonical_name: str, filename: str) -> bool:
    if str(getattr(module, "__name__", "")) != canonical_name:
        return False
    module_file = str(getattr(module, "__file__", "") or "")
    return not module_file or Path(module_file).name == filename


def _is_core_loop_module(module: ModuleType) -> bool:
    return _is_named_file_module(module, _CANONICAL_CORE_LOOP_MODULE, "nija_core_loop.py")


def _is_ai_engine_module(module: ModuleType) -> bool:
    return _is_named_file_module(module, _CANONICAL_AI_ENGINE_MODULE, "nija_ai_engine.py")


def _budget_for(symbol_count: int, available_slots: int) -> int:
    # Scan enough markets to produce replacement candidates when top-ranked
    # symbols fail expectancy/edge gates, but still keep the loop bounded.
    default_budget = max(8, min(24, max(available_slots * 3, 8)))
    budget = _int_env("NIJA_PHASE3_MAX_SYMBOLS_PER_CYCLE", default_budget)
    minimum = _int_env("NIJA_PHASE3_MIN_SYMBOLS_PER_CYCLE", min(8, default_budget))
    budget = max(minimum, budget)
    return min(max(1, int(symbol_count)), budget)


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").upper().replace("/", "-").replace(":", "-").replace("_", "-")


def _okx_inst_id(symbol: Any) -> str:
    raw = _normalize_symbol(str(symbol or ""))
    raw = re.sub(r"[^A-Z0-9\-]", "", raw)
    while "--" in raw:
        raw = raw.replace("--", "-")
    if raw.endswith("-USDTT"):
        raw = raw[:-6] + "-USDT"
    if "-" in raw:
        base, quote = raw.rsplit("-", 1)
        if quote == "USD":
            return f"{base}-USDT"
        if quote in {"USDT", "USDC"}:
            return f"{base}-{quote}"
        return raw
    for quote in ("USDT", "USDC", "USD"):
        if raw.endswith(quote) and len(raw) > len(quote):
            base = raw[: -len(quote)]
            return f"{base}-USDT" if quote == "USD" else f"{base}-{quote}"
    return raw


def _broker_name(broker: Any) -> str:
    try:
        text = " ".join(
            str(getattr(broker, attr, "") or "")
            for attr in ("broker_type", "broker_name", "name", "exchange", "exchange_name")
        ).lower()
        cls = type(broker).__name__.lower()
        text = f"{text} {cls}"
        for name in ("okx", "kraken", "coinbase", "alpaca", "binance"):
            if name in text:
                return name
    except Exception:
        pass
    return "unknown"


def _load_okx_products(broker: Any) -> set[str]:
    products: set[str] = set()
    for attr in (
        "_nija_okx_listed_symbols",
        "_okx_listed_symbols",
        "listed_symbols",
        "symbols",
        "available_symbols",
        "markets",
        "products",
    ):
        try:
            value = getattr(broker, attr, None)
            if callable(value):
                continue
            if isinstance(value, dict):
                iterable = value.keys()
            elif isinstance(value, (list, tuple, set, frozenset)):
                iterable = value
            else:
                continue
            for item in iterable:
                inst = _okx_inst_id(item)
                if inst.endswith("-USDT") or inst.endswith("-USDC"):
                    products.add(inst)
        except Exception:
            continue

    for method_name in ("get_all_products", "get_products", "get_available_markets", "get_tradeable_pairs", "get_tradable_pairs"):
        try:
            method = getattr(broker, method_name, None)
            if not callable(method):
                continue
            value = method()
            iterable = value.keys() if isinstance(value, dict) else value
            if isinstance(iterable, (list, tuple, set, frozenset)):
                for item in iterable:
                    inst = _okx_inst_id(item)
                    if inst.endswith("-USDT") or inst.endswith("-USDC"):
                        products.add(inst)
        except Exception as exc:
            logger.debug("OKX product lookup via %s failed: %s", method_name, exc)

    products.update(_OKX_CORE_USDT)
    return products


def _filter_symbols_for_broker(broker: Any, symbols: list[str]) -> tuple[list[str], int, str]:
    if _broker_name(broker) != "okx":
        return symbols, 0, "not_okx"
    products = _load_okx_products(broker)
    seen: set[str] = set()
    filtered: list[str] = []
    for symbol in symbols or []:
        inst = _okx_inst_id(symbol)
        if inst in seen:
            continue
        if products and inst not in products:
            continue
        seen.add(inst)
        filtered.append(inst)
    if not filtered:
        filtered = [s for s in ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT") if not products or s in products]
    dropped = max(0, len(symbols or []) - len(filtered))
    return filtered, dropped, "okx_listed_only"


def _priority_rank(symbol: str) -> int:
    norm = _normalize_symbol(symbol)
    try:
        return _PRIORITY_SYMBOLS.index(norm)
    except ValueError:
        try:
            return _PRIORITY_SYMBOLS.index(norm.replace("-USDT", "-USD"))
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
    priority_slice = ordered[: min(priority_count, max(1, min(budget, 6)))]
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


def _patch_ai_engine_module(module: ModuleType) -> bool:
    global _AI_PATCHED
    if not _is_ai_engine_module(module):
        return False
    cls = getattr(module, "NijaAIEngine", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "rank_and_select", None)
    if not callable(original):
        return False
    if getattr(original, _AI_SELECT_ATTR, False):
        _AI_PATCHED = True
        return True

    def _rank_and_select_more_attempts(self: Any, candidates: list[Any], available_slots: int, regime: Any = None) -> list[Any]:
        selected = list(original(self, candidates, available_slots, regime) or [])
        try:
            slots = max(0, int(available_slots or 0))
            if not candidates or slots <= 0:
                return selected
            # Never return more successful-entry capacity than open slots; this
            # only gives the execution loop replacement attempts when earlier
            # candidates are rejected by expectancy/edge/exchange gates.
            max_attempts = min(slots, _int_env("NIJA_PHASE3_MAX_EXECUTION_ATTEMPTS", 8))
            if len(selected) >= max_attempts:
                return selected
            ranked = sorted(candidates, key=lambda s: float(getattr(s, "composite_score", 0.0) or 0.0), reverse=True)
            seen = {str(getattr(s, "symbol", "")) + ":" + str(getattr(s, "side", "")) for s in selected}
            threshold = float(getattr(selected[0], "threshold_used", 0.0) if selected else 0.0)
            for sig in ranked:
                if len(selected) >= max_attempts:
                    break
                key = str(getattr(sig, "symbol", "")) + ":" + str(getattr(sig, "side", ""))
                if key in seen:
                    continue
                try:
                    score = float(getattr(sig, "composite_score", 0.0) or 0.0)
                except Exception:
                    score = 0.0
                if score <= 0:
                    continue
                try:
                    setattr(sig, "threshold_used", threshold or getattr(sig, "threshold_used", 0.0))
                    if hasattr(self, "_position_multiplier"):
                        sig.position_multiplier = self._position_multiplier(score)
                    metadata = getattr(sig, "metadata", None)
                    if isinstance(metadata, dict):
                        metadata["selection_reason"] = "replacement_attempt_after_prior_gate_reject"
                except Exception:
                    pass
                selected.append(sig)
                seen.add(key)
            if selected:
                logger.critical(
                    "PHASE3_OVERSELECT_APPLIED marker=20260703i candidates=%d selected=%d available_slots=%d max_attempts=%d symbols=%s",
                    len(candidates),
                    len(selected),
                    slots,
                    max_attempts,
                    ",".join(str(getattr(s, "symbol", "?")) for s in selected),
                )
                print(
                    f"[NIJA-PRINT] PHASE3_OVERSELECT_APPLIED marker=20260703i selected={len(selected)} slots={slots} symbols={','.join(str(getattr(s, 'symbol', '?')) for s in selected)}",
                    flush=True,
                )
        except Exception as exc:
            logger.warning("PHASE3_OVERSELECT_FAILED marker=20260703i err=%s", exc)
        return selected

    setattr(_rank_and_select_more_attempts, _AI_SELECT_ATTR, True)
    setattr(cls, "rank_and_select", _rank_and_select_more_attempts)
    _AI_PATCHED = True
    logger.warning("PHASE3_OVERSELECT_PATCHED marker=20260703i module=%s", getattr(module, "__name__", "<unknown>"))
    print("[NIJA-PRINT] PHASE3_OVERSELECT_PATCHED marker=20260703i", flush=True)
    return True


def _install_on_module(module: ModuleType) -> bool:
    global _PATCHED
    if not _is_core_loop_module(module):
        return False
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_phase3_scan_and_enter", None)
    if not callable(original):
        return False
    if getattr(original, _SCAN_ATTR, False):
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
        symbols, dropped, filter_reason = _filter_symbols_for_broker(broker, list(symbols or []))
        filtered_count = len(symbols or [])
        if dropped:
            logger.critical(
                "BROKER_AWARE_SCAN_FILTER_APPLIED marker=20260703i broker=%s original_symbols=%d filtered_symbols=%d dropped=%d reason=%s sample=%s",
                _broker_name(broker),
                original_count,
                filtered_count,
                dropped,
                filter_reason,
                ",".join(str(s) for s in symbols[:12]),
            )
            print(
                f"[NIJA-PRINT] BROKER_AWARE_SCAN_FILTER_APPLIED marker=20260703i broker={_broker_name(broker)} original={original_count} filtered={filtered_count} dropped={dropped}",
                flush=True,
            )
        budget = _budget_for(filtered_count, int(available_slots or 0))
        offset = 0
        priority_count = 0
        if filtered_count > budget:
            symbols, offset, priority_count = _rotate_symbols(list(symbols), budget)
            logger.critical(
                "PHASE3_SCAN_BUDGET_APPLIED marker=20260703i original_symbols=%d filtered_symbols=%d budget=%d slots=%d offset=%d priority_matches=%d symbols=%s cycle_id=%s",
                original_count,
                filtered_count,
                budget,
                available_slots,
                offset,
                priority_count,
                ",".join(str(s) for s in symbols),
                getattr(snapshot, "cycle_id", ""),
            )
            print(
                f"[NIJA-PRINT] PHASE3_SCAN_BUDGET_APPLIED marker=20260703i | original={original_count} filtered={filtered_count} budget={budget} slots={available_slots} offset={offset} priority_matches={priority_count} symbols={','.join(str(s) for s in symbols)}",
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
    setattr(_patched_phase3_scan_and_enter, _SCAN_ATTR, True)
    setattr(_patched_phase3_scan_and_enter, "__wrapped__", original)
    setattr(cls, "_phase3_scan_and_enter", _patched_phase3_scan_and_enter)
    _PATCHED = True
    logger.warning(
        "PHASE3_SCAN_BUDGET_PATCHED marker=20260703i module=%s canonical_module=%s",
        getattr(module, "__name__", "<unknown>"),
        _CANONICAL_CORE_LOOP_MODULE,
    )
    logger.warning("%s module=%s canonical_module=%s", _DEPLOY_MARKER, getattr(module, "__name__", "<unknown>"), _CANONICAL_CORE_LOOP_MODULE)
    print("[NIJA-PRINT] PHASE3_TERMINAL_BLOCKER_TRACE_PATCHED marker=20260703i", flush=True)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    module = sys.modules.get(_CANONICAL_CORE_LOOP_MODULE)
    if isinstance(module, ModuleType):
        patched = _install_on_module(module) or patched
    ai_module = sys.modules.get(_CANONICAL_AI_ENGINE_MODULE)
    if isinstance(ai_module, ModuleType):
        patched = _patch_ai_engine_module(ai_module) or patched
    return patched


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _INSTALL_LOCK:
        if _ORIGINAL_IMPORT_MODULE is not None:
            _try_patch_loaded()
            logger.debug(
                "PHASE3_SCAN_BUDGET_INSTALL_COMPLETE marker=20260703i already_installed=True patched=%s ai_patched=%s",
                _PATCHED,
                _AI_PATCHED,
            )
            return

        logger.warning("%s install_start=True canonical_module=%s", _DEPLOY_MARKER, _CANONICAL_CORE_LOOP_MODULE)
        print("[NIJA-PRINT] PHASE3_TERMINAL_BLOCKER_TRACE_PATCHED marker=20260703i install_start", flush=True)
        _try_patch_loaded()

        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name == _CANONICAL_CORE_LOOP_MODULE:
                _install_on_module(module)
            elif name == _CANONICAL_AI_ENGINE_MODULE:
                _patch_ai_engine_module(module)
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
        logger.warning(
            "PHASE3_SCAN_BUDGET_INSTALL_COMPLETE marker=20260703i patched=%s ai_patched=%s canonical_module=%s",
            _PATCHED,
            _AI_PATCHED,
            _CANONICAL_CORE_LOOP_MODULE,
        )
