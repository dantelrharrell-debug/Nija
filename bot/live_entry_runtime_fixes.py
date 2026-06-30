"""Runtime fixes for live entry visibility, quote filtering, and pair quarantine.

This module is intentionally defensive: it patches the live core loop only when
those classes are imported and leaves trade admission logic unchanged except for
skipping pairs that cannot be funded by the broker's available quote balance or
that the venue has already reported as unknown.
"""

from __future__ import annotations

import builtins
import logging
import os
import re
import time
from functools import wraps
from typing import Any, Iterable, Mapping, MutableMapping, Optional, Sequence

logger = logging.getLogger("nija.live_entry_runtime_fixes")
_PATCHED_ATTR = "__nija_live_entry_runtime_fixes__"
_UNKNOWN_PAIRS: set[tuple[str, str]] = set()

_STABLE_QUOTES = ("USDT", "USDC", "USD", "EUR", "GBP", "BTC", "ETH")
_BALANCE_ATTRS = (
    "balance_cache",
    "_balance_cache",
    "balances",
    "_balances",
    "last_balance",
    "_last_balance",
    "last_balance_snapshot",
    "_last_balance_snapshot",
    "_last_known_balance_payload",
    "_last_raw_balances",
    "raw_balances",
    "_raw_balances",
)


def _truthy(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "y", "enabled"}


def _broker_name(broker: Any, fallback: str = "unknown") -> str:
    for attr in ("name", "broker_name", "exchange", "exchange_name", "broker_type"):
        try:
            value = getattr(broker, attr, None)
            if value is None:
                continue
            raw = getattr(value, "value", value)
            if str(raw).strip():
                return str(raw).strip().lower()
        except Exception:
            continue
    try:
        cls_name = type(broker).__name__.lower()
        for key in ("kraken", "coinbase", "okx", "binance", "alpaca"):
            if key in cls_name:
                return key
    except Exception:
        pass
    return fallback


def _quote_asset(symbol: Any) -> str:
    raw = str(symbol or "").upper().strip()
    if not raw:
        return ""
    normalized = raw.replace("/", "-").replace("_", "-").replace(":", "-")
    if "-" in normalized:
        tail = normalized.rsplit("-", 1)[-1]
        return re.sub(r"[^A-Z0-9]", "", tail)
    compact = re.sub(r"[^A-Z0-9]", "", normalized)
    for quote in sorted(_STABLE_QUOTES, key=len, reverse=True):
        if compact.endswith(quote) and len(compact) > len(quote):
            return quote
    return ""


def _flatten_balances(payload: Any, out: MutableMapping[str, float]) -> None:
    if payload is None:
        return
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            key_text = str(key).strip().lower()
            try:
                if isinstance(value, Mapping):
                    # Coinbase/OKX often nest available/total values under each currency.
                    for sub_key in ("available", "free", "balance", "total", "amount", "value"):
                        if sub_key in value:
                            out[key_text] = max(out.get(key_text, 0.0), float(value.get(sub_key) or 0.0))
                            break
                    _flatten_balances(value, out)
                elif isinstance(value, (int, float, str)):
                    numeric = float(value or 0.0)
                    out[key_text] = max(out.get(key_text, 0.0), numeric)
            except (TypeError, ValueError):
                continue
    elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        for item in payload:
            _flatten_balances(item, out)


def _quote_balances_from_broker(broker: Any) -> dict[str, float]:
    balances: dict[str, float] = {}
    for attr in _BALANCE_ATTRS:
        try:
            _flatten_balances(getattr(broker, attr, None), balances)
        except Exception:
            continue
    # Common scalar attributes used by bootstrap/capital hydration.
    scalar_attrs = {
        "usd": ("usd", "available_usd", "usd_balance", "_usd_balance"),
        "usdt": ("usdt", "available_usdt", "usdt_balance", "_usdt_balance"),
        "usdc": ("usdc", "available_usdc", "usdc_balance", "_usdc_balance"),
    }
    for quote, attrs in scalar_attrs.items():
        for attr in attrs:
            try:
                value = getattr(broker, attr, None)
                if value is not None:
                    balances[quote] = max(balances.get(quote, 0.0), float(value or 0.0))
            except (TypeError, ValueError):
                continue
    return balances


def _should_skip_for_quote(broker_name: str, symbol: str, quote: str, balances: Mapping[str, float]) -> tuple[bool, str]:
    if not quote or not balances:
        return False, ""
    quote_key = quote.lower()
    quote_available = float(balances.get(quote_key, 0.0) or 0.0)
    # Only enforce the strict mismatch guard on OKX. Other brokers can expose
    # their buying power through generic USD/trading_balance fields while still
    # accepting USD pairs; over-filtering those venues would suppress trades.
    if broker_name == "okx" and quote in {"USDT", "USDC"} and quote_available <= 0.0:
        usd_available = float(balances.get("usd", 0.0) or balances.get("available_usd", 0.0) or 0.0)
        if usd_available > 0.0:
            return True, f"okx_quote_mismatch:{quote}_balance=0 usd_available={usd_available:.2f}"
    return False, ""


def _filter_symbols_for_quote_balance(broker: Any, symbols: Iterable[Any]) -> list[Any]:
    symbols_list = list(symbols or [])
    broker_name = _broker_name(broker)
    balances = _quote_balances_from_broker(broker)
    kept: list[Any] = []
    skipped_quote = 0
    skipped_unknown = 0
    for symbol in symbols_list:
        sym_text = str(symbol)
        quote = _quote_asset(sym_text)
        if (broker_name, sym_text.upper()) in _UNKNOWN_PAIRS:
            skipped_unknown += 1
            logger.info("PAIR_SKIPPED_UNKNOWN broker=%s pair=%s reason=session_quarantine", broker_name, sym_text)
            continue
        skip, reason = _should_skip_for_quote(broker_name, sym_text, quote, balances)
        if skip:
            skipped_quote += 1
            logger.info(
                "PAIR_SKIPPED_QUOTE_MISMATCH broker=%s pair=%s quote=%s reason=%s balances=%s",
                broker_name,
                sym_text,
                quote,
                reason,
                {k: round(v, 8) for k, v in balances.items() if k in {"usd", "usdt", "usdc", "available_usd"}},
            )
            continue
        kept.append(symbol)
    if skipped_quote or skipped_unknown:
        logger.warning(
            "SYMBOL_FILTER_SUMMARY broker=%s input=%d kept=%d skipped_quote=%d skipped_unknown=%d",
            broker_name,
            len(symbols_list),
            len(kept),
            skipped_quote,
            skipped_unknown,
        )
    return kept


def _mark_unknown_pair(broker: Any, symbol: Any, error: Any) -> None:
    msg = str(error or "")
    if "Unknown asset pair" not in msg and "EQuery:Unknown asset pair" not in msg:
        return
    broker_name = _broker_name(broker)
    sym_text = str(symbol or "").upper()
    if not sym_text:
        return
    _UNKNOWN_PAIRS.add((broker_name, sym_text))
    logger.warning("PAIR_QUARANTINED_UNKNOWN broker=%s pair=%s error=%s", broker_name, sym_text, msg[:240])


def _wrap_run_scan_phase(cls: type) -> None:
    original = getattr(cls, "run_scan_phase", None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return

    @wraps(original)
    def _wrapped(self: Any, broker: Any = None, balance: float = 0.0, symbols: Optional[list[str]] = None, *args: Any, **kwargs: Any):
        broker_obj = broker if broker is not None else getattr(getattr(self, "apex", None), "broker_client", None)
        broker_name = _broker_name(broker_obj)
        symbols_count = len(symbols or []) if symbols is not None else 0
        cycle_id = f"runtime-{int(time.time() * 1000)}"
        logger.info(
            "SCAN_CYCLE_START cycle_id=%s broker=%s symbols=%d balance=%.2f open_positions=%s user_mode=%s",
            cycle_id,
            broker_name,
            symbols_count,
            float(balance or 0.0),
            kwargs.get("open_positions_count", args[0] if args else "unknown"),
            kwargs.get("user_mode", False),
        )
        result = original(self, broker, balance, symbols, *args, **kwargs)
        logger.info(
            "SCAN_CYCLE_END cycle_id=%s broker=%s symbols_scored=%s entries_taken=%s entries_blocked=%s exits_taken=%s next_interval=%s errors=%s",
            cycle_id,
            broker_name,
            getattr(result, "symbols_scored", None),
            getattr(result, "entries_taken", None),
            getattr(result, "entries_blocked", None),
            getattr(result, "exits_taken", None),
            getattr(result, "next_interval", None),
            getattr(result, "errors", None),
        )
        return result

    setattr(_wrapped, _PATCHED_ATTR, True)
    setattr(cls, "run_scan_phase", _wrapped)
    logger.warning("LIVE_ENTRY_FIXES_RUN_SCAN_WIRED class=%s", cls.__name__)


def _wrap_phase3(cls: type) -> None:
    original = getattr(cls, "_phase3_scan_and_enter", None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return

    @wraps(original)
    def _wrapped(self: Any, broker: Any, snapshot: Any, symbols: list[str], available_slots: int, *args: Any, **kwargs: Any):
        filtered_symbols = _filter_symbols_for_quote_balance(broker, symbols)
        logger.info(
            "ENTRY_SCAN_START broker=%s cycle_id=%s symbols_in=%d symbols_after_filter=%d available_slots=%d balance=%.2f",
            _broker_name(broker),
            getattr(snapshot, "cycle_id", "n/a"),
            len(symbols or []),
            len(filtered_symbols),
            int(available_slots or 0),
            float(getattr(snapshot, "balance", 0.0) or 0.0),
        )
        return original(self, broker, snapshot, filtered_symbols, available_slots, *args, **kwargs)

    setattr(_wrapped, _PATCHED_ATTR, True)
    setattr(cls, "_phase3_scan_and_enter", _wrapped)
    logger.warning("LIVE_ENTRY_FIXES_PHASE3_WIRED class=%s", cls.__name__)


def _wrap_fetch_df(cls: type) -> None:
    original = getattr(cls, "_fetch_df", None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return

    @wraps(original)
    def _wrapped(self: Any, broker: Any, symbol: Any, *args: Any, **kwargs: Any):
        try:
            return original(self, broker, symbol, *args, **kwargs)
        except Exception as exc:
            _mark_unknown_pair(broker, symbol, exc)
            raise

    setattr(_wrapped, _PATCHED_ATTR, True)
    setattr(cls, "_fetch_df", _wrapped)
    logger.warning("LIVE_ENTRY_FIXES_FETCH_DF_WIRED class=%s", cls.__name__)


def _wrap_execute_action(cls: type) -> None:
    original = getattr(cls, "execute_action", None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return

    @wraps(original)
    def _wrapped(self: Any, analysis: Any, symbol: str, *args: Any, **kwargs: Any):
        action = analysis.get("action") if isinstance(analysis, Mapping) else None
        size = analysis.get("position_size") if isinstance(analysis, Mapping) else None
        price = analysis.get("entry_price") if isinstance(analysis, Mapping) else None
        logger.info(
            "ORDER_SUBMIT_ATTEMPT broker=%s pair=%s action=%s usd_size=%s entry_price=%s",
            _broker_name(getattr(self, "broker_client", None)),
            symbol,
            action,
            size,
            price,
        )
        result = original(self, analysis, symbol, *args, **kwargs)
        logger.info(
            "ORDER_SUBMIT_RESULT broker=%s pair=%s action=%s success=%s",
            _broker_name(getattr(self, "broker_client", None)),
            symbol,
            action,
            bool(result),
        )
        return result

    setattr(_wrapped, _PATCHED_ATTR, True)
    setattr(cls, "execute_action", _wrapped)
    logger.warning("LIVE_ENTRY_FIXES_EXECUTE_WIRED class=%s", cls.__name__)


def _patch_module(module: Any) -> bool:
    if module is None:
        return False
    patched = False
    try:
        core_cls = getattr(module, "NijaCoreLoop", None)
        if isinstance(core_cls, type):
            _wrap_run_scan_phase(core_cls)
            _wrap_phase3(core_cls)
            _wrap_fetch_df(core_cls)
            patched = True
    except Exception as exc:
        logger.warning("Live entry core-loop patch failed for %s: %s", getattr(module, "__name__", module), exc)
    try:
        apex_cls = getattr(module, "NIJAApexStrategyV71", None)
        if isinstance(apex_cls, type):
            _wrap_execute_action(apex_cls)
            patched = True
    except Exception as exc:
        logger.warning("Live entry apex patch failed for %s: %s", getattr(module, "__name__", module), exc)
    return patched


def install_import_hook() -> None:
    if not _truthy("NIJA_LIVE_ENTRY_RUNTIME_FIXES", True):
        logger.warning("LIVE_ENTRY_FIXES_DISABLED env=NIJA_LIVE_ENTRY_RUNTIME_FIXES")
        return

    import sys

    for name, module in list(sys.modules.items()):
        if name.endswith(("nija_core_loop", "nija_apex_strategy_v71")):
            _patch_module(module)

    if getattr(builtins, "_NIJA_LIVE_ENTRY_RUNTIME_FIXES_HOOK_INSTALLED", False):
        return

    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        targets = ("nija_core_loop", "nija_apex_strategy_v71")
        try:
            if name.endswith(targets):
                _patch_module(module)
            # When importing from a package with fromlist, Python returns the package;
            # patch submodules if they are already loaded.
            for loaded_name, loaded_module in list(sys.modules.items()):
                if loaded_name.endswith(targets):
                    _patch_module(loaded_module)
        except Exception as exc:
            logger.warning("Live entry runtime fixes import hook failed for %s: %s", name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_LIVE_ENTRY_RUNTIME_FIXES_HOOK_INSTALLED", True)
    logger.warning("LIVE_ENTRY_FIXES_INSTALL_COMPLETE")
