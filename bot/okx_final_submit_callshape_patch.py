from __future__ import annotations

import builtins
import logging
import os
import sys
from functools import wraps
from types import ModuleType
from typing import Any, Dict

logger = logging.getLogger("nija.okx_final_submit_callshape_patch")
_MARKER = "OKX_FINAL_SUBMIT_CALLSHAPE_PATCHED marker=20260705g"
_PATCHED_ATTR = "_nija_okx_final_submit_callshape_20260705g"
_TRUE = {"1", "true", "yes", "on", "enabled"}


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in _TRUE


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return default


def _inst(symbol: Any) -> str:
    text = str(symbol or "").upper().strip().replace("/", "-").replace("_", "-")
    if text.endswith("-USD"):
        return text[:-4] + "-USDT"
    if text.endswith("USD") and "-" not in text and len(text) > 3:
        return text[:-3] + "-USDT"
    return text


def _price(broker: Any, symbol: str) -> float:
    getter = getattr(broker, "get_current_price", None)
    if callable(getter):
        try:
            value = _f(getter(symbol), 0.0)
            if value > 0:
                return value
        except Exception:
            pass
    api = getattr(broker, "market_api", None)
    ticker = getattr(api, "get_ticker", None)
    if callable(ticker):
        try:
            data = (ticker(instId=symbol) or {}).get("data") or []
            if data:
                return _f(data[0].get("last"), 0.0)
        except Exception:
            pass
    return 0.0


def _patch(module: ModuleType) -> bool:
    cls = getattr(module, "OKXBroker", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "place_market_order", None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return bool(getattr(original, _PATCHED_ATTR, False))

    @wraps(original)
    def place_market_order(self: Any, symbol: str, side: str, quantity: float, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        size_type = str(kwargs.get("size_type", args[0] if args else "base") or "base").lower()
        try:
            result = original(self, symbol, side, quantity, *args, **kwargs)
            if not (isinstance(result, dict) and "missing 2 required positional arguments" in str(result.get("error", ""))):
                return result
            logger.warning("OKX_FINAL_SUBMIT_CALLSHAPE_RETRY marker=20260705g reason=result_error symbol=%s", symbol)
        except TypeError as exc:
            if "symbol" not in str(exc) or "quantity" not in str(exc):
                raise
            logger.warning("OKX_FINAL_SUBMIT_CALLSHAPE_RETRY marker=20260705g reason=type_error symbol=%s error=%s", symbol, exc)
        except Exception as exc:
            if "missing 2 required positional arguments" not in str(exc):
                raise
            logger.warning("OKX_FINAL_SUBMIT_CALLSHAPE_RETRY marker=20260705g reason=exception symbol=%s error=%s", symbol, exc)

        if not any(_truthy(flag) for flag in ("NIJA_OKX_EXECUTION_ENABLED", "NIJA_OKX_LIVE_TRADING_ENABLED", "OKX_LIVE_TRADING_ENABLED", "NIJA_ENABLE_OKX_EXECUTION")):
            return {"status": "error", "error": "OKX live execution disabled", "blocked_by": "okx_live_execution_guard"}

        inst_id = _inst(symbol)
        order_side = str(side or "").lower()
        submitted_size = _f(quantity, 0.0)
        price_hint = 0.0
        if order_side == "sell" and size_type == "quote":
            price_hint = _price(self, inst_id)
            if price_hint > 0:
                submitted_size = submitted_size / price_hint
        elif order_side == "buy":
            price_hint = _price(self, inst_id)
        if submitted_size <= 0:
            return {"status": "error", "error": "invalid_okx_order_size", "symbol": inst_id, "side": order_side}

        api = getattr(self, "trade_api", None)
        submit = getattr(api, "place_order", None)
        if not callable(submit):
            return {"status": "error", "error": "OKX trade API missing place_order", "symbol": inst_id, "side": order_side}

        logger.critical(
            "OKX_FINAL_SUBMIT_CALLSHAPE_APPLIED marker=20260705g symbol=%s side=%s quantity=%s size_type=%s",
            inst_id,
            order_side,
            submitted_size,
            size_type,
        )
        print(f"[NIJA-PRINT] OKX_FINAL_SUBMIT_CALLSHAPE_APPLIED marker=20260705g symbol={inst_id} side={order_side}", flush=True)

        response = submit(inst_id, order_side, submitted_size, tdMode="cash", ordType="market", tgtCcy="quote_ccy" if order_side == "buy" else None)
        if response and str(response.get("code", "")) == "0":
            data = response.get("data") or []
            oid = data[0].get("ordId") if data and isinstance(data[0], dict) else None
            return {"status": "filled" if oid else "submitted", "order_id": oid, "symbol": inst_id, "side": order_side, "quantity": submitted_size, "filled_price": price_hint, "raw": response}
        return {"status": "error", "error": str((response or {}).get("msg") or response), "symbol": inst_id, "side": order_side, "raw": response}

    setattr(place_market_order, _PATCHED_ATTR, True)
    setattr(cls, "place_market_order", place_market_order)
    logger.warning("%s class=OKXBroker", _MARKER)
    print("[NIJA-PRINT] OKX_FINAL_SUBMIT_CALLSHAPE_PATCHED marker=20260705g", flush=True)
    return True


def _try() -> bool:
    done = False
    for name in ("bot.broker_manager", "broker_manager"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            done = _patch(module) or done
    return done


def install_import_hook() -> None:
    _try()
    if getattr(builtins, "_NIJA_OKX_FINAL_SUBMIT_CALLSHAPE_HOOK", False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            _try()
        except Exception as exc:
            logger.warning("OKX_FINAL_SUBMIT_CALLSHAPE hook failed: %s", exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_OKX_FINAL_SUBMIT_CALLSHAPE_HOOK", True)
    logger.warning("OKX_FINAL_SUBMIT_CALLSHAPE_IMPORT_HOOK marker=20260705g")


def install() -> None:
    install_import_hook()
