"""Sanitize scan symbols before expensive OHLC retrieval.

Removes malformed repeated-quote pairs such as APXUSD-USD and APXUSD-USDC,
deduplicates aliases, and preserves normal exchange-native symbols.
"""
from __future__ import annotations

import logging
import os
import re
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.scan_symbol_sanitizer")
_MARKER = "20260720-scan-symbol-sanitizer-v1"
_PATCH_ATTR = "_nija_scan_symbol_sanitizer_v1"
_QUOTES = ("USD", "USDT", "USDC", "EUR", "GBP", "BTC", "ETH")
_LOCK = threading.RLock()
_STARTED = False


def _normalize(symbol: Any) -> str:
    return str(symbol or "").strip().upper().replace("/", "-").replace("_", "-")


def _valid(symbol: str) -> bool:
    if not symbol or len(symbol) > 32:
        return False
    if not re.fullmatch(r"[A-Z0-9]+(?:-[A-Z0-9]+)?", symbol):
        return False
    parts = symbol.split("-")
    if len(parts) != 2:
        return False
    base, quote = parts
    if quote not in _QUOTES or not base:
        return False
    # A base already ending in a quote token indicates an accidental repeated quote.
    if any(base.endswith(q) for q in _QUOTES):
        return False
    return True


def sanitize_symbols(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        return values
    output: list[str] = []
    seen: set[str] = set()
    dropped: list[str] = []
    for value in values:
        symbol = _normalize(value)
        if not _valid(symbol):
            dropped.append(symbol or str(value))
            continue
        if symbol in seen:
            continue
        seen.add(symbol)
        output.append(symbol)
    if dropped:
        logger.warning(
            "SCAN_SYMBOLS_SANITIZED marker=%s input=%d output=%d dropped=%d examples=%s",
            _MARKER, len(values), len(output), len(dropped), ",".join(dropped[:8]),
        )
    return output


def _patch_class(cls: type) -> bool:
    changed = False
    for method_name in ("run_scan_phase", "_phase3_scan_and_enter"):
        current = getattr(cls, method_name, None)
        if not callable(current) or getattr(current, _PATCH_ATTR, False):
            continue

        @wraps(current)
        def wrapped(self: Any, *args: Any, __current=current, __name=method_name, **kwargs: Any):
            args_list = list(args)
            for idx, value in enumerate(args_list):
                if isinstance(value, (list, tuple, set)) and value and all(isinstance(x, str) for x in value):
                    args_list[idx] = sanitize_symbols(value)
                    break
            for key in ("symbols", "symbol_list", "markets", "pairs"):
                value = kwargs.get(key)
                if isinstance(value, (list, tuple, set)):
                    kwargs[key] = sanitize_symbols(value)
                    break
            return __current(self, *tuple(args_list), **kwargs)

        setattr(wrapped, _PATCH_ATTR, True)
        setattr(wrapped, "__wrapped__", current)
        setattr(cls, method_name, wrapped)
        logger.critical("SCAN_SYMBOL_SANITIZER_SURFACE_PATCHED marker=%s module=%s class=%s method=%s", _MARKER, cls.__module__, cls.__name__, method_name)
        changed = True
    return changed


def _patch_loaded() -> bool:
    changed = False
    for name in ("bot.nija_core_loop", "nija_core_loop"):
        module = sys.modules.get(name)
        cls = getattr(module, "NijaCoreLoop", None) if isinstance(module, ModuleType) else None
        if isinstance(cls, type):
            changed = _patch_class(cls) or changed
    return changed


def _watchdog() -> None:
    while True:
        try:
            _patch_loaded()
        except Exception as exc:
            logger.debug("SCAN_SYMBOL_SANITIZER_RETRY marker=%s error=%s", _MARKER, exc)
        time.sleep(1.0)


def install() -> bool:
    global _STARTED
    with _LOCK:
        _patch_loaded()
        if not _STARTED:
            _STARTED = True
            threading.Thread(target=_watchdog, name="ScanSymbolSanitizer", daemon=True).start()
        os.environ["NIJA_SCAN_SYMBOL_SANITIZER_INSTALLED"] = "1"
        logger.critical("SCAN_SYMBOL_SANITIZER_INSTALLED marker=%s", _MARKER)
        return True


install()

__all__ = ["install", "sanitize_symbols"]
