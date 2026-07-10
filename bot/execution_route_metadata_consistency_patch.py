from __future__ import annotations

import builtins
import logging
import os
import sys
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.execution_route_metadata_consistency")
_MARKER = "20260709ar"
_HOOK_FLAG = "_NIJA_EXECUTION_ROUTE_METADATA_CONSISTENCY_HOOK_20260709AR"
_PATCH_ATTR = "_nija_execution_route_metadata_consistency_20260709ar"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_FALSE = {"0", "false", "no", "off", "disabled", "n"}


def _csv_env(name: str, default: str = "") -> list[str]:
    raw = os.environ.get(name, default) or ""
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


def _norm_broker(value: Any) -> str:
    text = str(getattr(value, "value", value) or "").strip().lower()
    if ":" in text:
        text = text.split(":")[-1]
    compact = text.replace("_", "").replace("-", "").replace(" ", "")
    aliases = {
        "coinbasebrokeradapter": "coinbase",
        "coinbasebroker": "coinbase",
        "coinbase": "coinbase",
        "krakenbrokeradapter": "kraken",
        "krakenbroker": "kraken",
        "kraken": "kraken",
        "okxbrokeradapter": "okx",
        "okxbroker": "okx",
        "okx": "okx",
        "alpacabroker": "alpaca",
        "alpaca": "alpaca",
    }
    return aliases.get(compact, text)


def _truthy_env(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in _TRUE


def _falsey_env(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in _FALSE


def _okx_enabled() -> bool:
    for name in ("NIJA_OKX_EXECUTION_ENABLED", "NIJA_OKX_LIVE_TRADING_ENABLED", "OKX_LIVE_TRADING_ENABLED", "NIJA_ENABLE_OKX_EXECUTION"):
        if _truthy_env(name):
            return True
        if _falsey_env(name):
            return False
    return False


def _disabled_brokers() -> set[str]:
    disabled = set(_csv_env("NIJA_DISABLED_BROKERS", ""))
    if not _okx_enabled():
        disabled.add("okx")
    return {_norm_broker(item) for item in disabled if _norm_broker(item)}


def _allowed_brokers() -> list[str]:
    allowed = _csv_env("NIJA_ALLOWED_EXECUTION_BROKERS", "")
    if not allowed:
        allowed = _csv_env("NIJA_ENTRY_BROKER_PRIORITY", "coinbase,kraken,alpaca")
    disabled = _disabled_brokers()
    out: list[str] = []
    for item in allowed:
        broker = _norm_broker(item)
        if broker and broker not in disabled and broker != "okx" and broker not in out:
            out.append(broker)
    return out


def _fallback_broker() -> str:
    preferred = _csv_env("NIJA_OKX_REROUTE_FALLBACK_BROKERS", "coinbase,kraken,alpaca")
    allowed = _allowed_brokers()
    allowed_set = set(allowed) if allowed else {"coinbase", "kraken", "alpaca"}
    disabled = _disabled_brokers()
    for item in preferred + allowed:
        broker = _norm_broker(item)
        if broker and broker != "okx" and broker not in disabled and broker in allowed_set:
            return broker
    return "coinbase"


def _norm_symbol(value: Any) -> str:
    text = str(value or "").strip().upper().replace("/", "-").replace("_", "-").replace(":", "-")
    while "--" in text:
        text = text.replace("--", "-")
    return text


def _native_symbol(symbol: str, broker: str) -> str:
    symbol = _norm_symbol(symbol)
    broker = _norm_broker(broker)
    if not symbol or "-" not in symbol:
        return symbol
    base, quote = symbol.rsplit("-", 1)
    if broker in {"coinbase", "kraken"} and quote in {"USDT", "USDC"}:
        return f"{base}-USD"
    if broker == "okx" and quote == "USD":
        return f"{base}-USDT"
    return symbol


def _replace_request(module: ModuleType, req: Any, **changes: Any) -> Any:
    replacer = getattr(module, "_replace_request", None)
    if callable(replacer):
        try:
            return replacer(req, **changes)
        except Exception:
            pass
    for key, value in changes.items():
        try:
            setattr(req, key, value)
        except Exception:
            pass
    return req


def _strict_reroute(module: ModuleType, request: Any, symbol: str, reason: str) -> Any:
    fallback = _fallback_broker()
    old_symbol = _norm_symbol(symbol)
    new_symbol = _native_symbol(old_symbol, fallback)
    meta = dict(getattr(request, "metadata", {}) or {})
    original = {
        "preferred_broker": getattr(request, "preferred_broker", None),
        "broker_name": meta.get("broker_name"),
        "selected_broker": meta.get("selected_broker"),
        "execution_broker": meta.get("execution_broker"),
        "dispatch_broker": meta.get("dispatch_broker"),
    }
    for key in ("broker_client", "broker_adapter", "broker", "broker_name", "selected_broker", "execution_broker", "dispatch_broker", "symbol_broker", "balance_broker"):
        meta.pop(key, None)
    meta.update(
        {
            "broker_name": fallback,
            "selected_broker": fallback,
            "execution_broker": fallback,
            "dispatch_broker": fallback,
            "symbol_broker": fallback,
            "balance_broker": fallback,
            "preferred_broker": fallback,
            "okx_quote_reroute_reason": str(reason or "okx_quote_unavailable"),
            "okx_reroute_original_symbol": old_symbol,
            "okx_reroute_symbol": new_symbol,
            "okx_reroute_fallback_broker": fallback,
            "route_consistency_marker": _MARKER,
        }
    )
    logger.critical(
        "EXECUTION_ROUTE_METADATA_CONSISTENCY_APPLIED marker=%s old_broker=okx new_broker=%s old_symbol=%s new_symbol=%s reason=%s original=%s",
        _MARKER,
        fallback,
        old_symbol,
        new_symbol,
        reason,
        original,
    )
    print(
        f"[NIJA-PRINT] EXECUTION_ROUTE_METADATA_CONSISTENCY_APPLIED marker={_MARKER} old_broker=okx new_broker={fallback} old_symbol={old_symbol} new_symbol={new_symbol}",
        flush=True,
    )
    return _replace_request(module, request, symbol=new_symbol, preferred_broker=fallback, metadata=meta)


def _patch_broker_native_quote_module(module: ModuleType) -> bool:
    original = getattr(module, "_reroute_away_from_okx", None)
    if not callable(original):
        return False
    if getattr(original, _PATCH_ATTR, False):
        return True

    def reroute_away_from_okx_strict(request: Any, symbol: str, reason: str) -> Any:
        return _strict_reroute(module, request, symbol, reason)

    setattr(reroute_away_from_okx_strict, _PATCH_ATTR, True)
    setattr(module, "_reroute_away_from_okx", reroute_away_from_okx_strict)
    logger.warning("EXECUTION_ROUTE_METADATA_CONSISTENCY_PATCHED marker=%s module=%s", _MARKER, getattr(module, "__name__", "unknown"))
    print(f"[NIJA-PRINT] EXECUTION_ROUTE_METADATA_CONSISTENCY_PATCHED marker={_MARKER}", flush=True)
    return True


def _patch_loaded() -> None:
    for name in ("bot.broker_native_quote_routing_patch", "broker_native_quote_routing_patch"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                _patch_broker_native_quote_module(module)
            except Exception as exc:
                logger.warning("EXECUTION_ROUTE_METADATA_CONSISTENCY_PATCH_FAILED marker=%s module=%s err=%s", _MARKER, name, exc)


def install_import_hook() -> None:
    _patch_loaded()
    if getattr(builtins, _HOOK_FLAG, False):
        return
    original_import = builtins.__import__

    def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        text = str(name)
        if text.endswith("broker_native_quote_routing_patch") or text in {"bot.broker_native_quote_routing_patch", "broker_native_quote_routing_patch"}:
            _patch_loaded()
        return module

    builtins.__import__ = importing
    setattr(builtins, _HOOK_FLAG, True)
    logger.warning("EXECUTION_ROUTE_METADATA_CONSISTENCY_INSTALL_COMPLETE marker=%s", _MARKER)


def install() -> None:
    install_import_hook()
