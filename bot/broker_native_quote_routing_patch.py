from __future__ import annotations

import builtins
import logging
import sys
from dataclasses import replace
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.broker_native_quote_routing_patch")
_MARKER = "BROKER_NATIVE_QUOTE_ROUTING_PATCHED marker=20260705i"
_PATCHED_ATTR = "_nija_broker_native_quote_routing_20260705i"


def _norm_broker(value: Any) -> str:
    text = str(value or "").strip().lower()
    if ":" in text:
        text = text.split(":")[-1]
    return text


def _norm_symbol(value: Any) -> str:
    text = str(value or "").strip().upper().replace("/", "-").replace("_", "-")
    while "--" in text:
        text = text.replace("--", "-")
    if text.endswith("-USDTT"):
        text = text[:-6] + "-USDT"
    return text


def _native_symbol(symbol: str, broker: str) -> str:
    symbol = _norm_symbol(symbol)
    broker = _norm_broker(broker)
    if not symbol or "-" not in symbol:
        return symbol
    base, quote = symbol.rsplit("-", 1)
    if not base:
        return symbol
    if broker in {"coinbase", "kraken"} and quote == "USDT":
        return f"{base}-USD"
    if broker == "okx" and quote == "USD":
        return f"{base}-USDT"
    return symbol


def _replace_request(req: Any, **changes: Any) -> Any:
    try:
        return replace(req, **changes)
    except Exception:
        for key, value in changes.items():
            try:
                setattr(req, key, value)
            except Exception:
                pass
        return req


def _patch_pipeline(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionPipeline", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "execute", None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return bool(getattr(original, _PATCHED_ATTR, False))

    @wraps(original)
    def execute(self: Any, request: Any, *args: Any, **kwargs: Any):
        broker = _norm_broker(getattr(request, "preferred_broker", ""))
        symbol = _norm_symbol(getattr(request, "symbol", ""))
        side = str(getattr(request, "side", "") or "").strip().lower()
        native = _native_symbol(symbol, broker)
        if broker in {"coinbase", "kraken", "okx"} and native and native != symbol:
            logger.critical(
                "BROKER_NATIVE_QUOTE_ROUTING_REPAIRED marker=20260705i broker=%s side=%s old_symbol=%s new_symbol=%s",
                broker,
                side,
                symbol,
                native,
            )
            print(
                f"[NIJA-PRINT] BROKER_NATIVE_QUOTE_ROUTING_REPAIRED marker=20260705i broker={broker} old_symbol={symbol} new_symbol={native}",
                flush=True,
            )
            request = _replace_request(request, symbol=native)
        return original(self, request, *args, **kwargs)

    setattr(execute, _PATCHED_ATTR, True)
    setattr(cls, "execute", execute)
    logger.warning("%s class=ExecutionPipeline", _MARKER)
    print("[NIJA-PRINT] BROKER_NATIVE_QUOTE_ROUTING_PATCHED marker=20260705i", flush=True)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.execution_pipeline", "execution_pipeline"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_pipeline(module) or patched
    return patched


def install_import_hook() -> None:
    _try_patch_loaded()
    if getattr(builtins, "_NIJA_BROKER_NATIVE_QUOTE_ROUTING_HOOK", False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if name.endswith("execution_pipeline"):
                _try_patch_loaded()
            else:
                _try_patch_loaded()
        except Exception as exc:
            logger.warning("BROKER_NATIVE_QUOTE_ROUTING hook failed name=%s error=%s", name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_BROKER_NATIVE_QUOTE_ROUTING_HOOK", True)
    logger.warning("BROKER_NATIVE_QUOTE_ROUTING_IMPORT_HOOK marker=20260705i")


def install() -> None:
    install_import_hook()
