from __future__ import annotations

import builtins
import logging
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.okx_final_order_submission_bridge")
_MARKER = "20260709a"
_ORDER_WRAP_ATTR = "_nija_okx_final_order_submission_bridge_order_v20260709a"
_ROUTER_PATCH_ATTR = "_nija_okx_final_order_submission_bridge_router_v20260709a"
_INSTALL_LOCK = threading.Lock()
_PATCHED_ORDER_CLASSES: set[str] = set()
_ROUTER_PATCHED = False
_MONITOR_STARTED = False


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _clean_symbol(symbol: Any) -> str:
    text = str(symbol or "").upper().strip().replace("/", "-").replace("_", "-").replace(":", "-")
    while "--" in text:
        text = text.replace("--", "-")
    return "".join(ch for ch in text if ch.isalnum() or ch == "-")


def _normalize_inst_id(symbol: Any) -> str:
    raw = _clean_symbol(symbol)
    if not raw:
        return raw
    if raw.endswith("-USDTT"):
        raw = raw[:-6] + "-USDT"
    elif raw.endswith("-USDTC"):
        raw = raw[:-6] + "-USDC"
    elif raw.endswith("USDTT") and "-" not in raw:
        raw = raw[:-5] + "USDT"
    elif raw.endswith("USDTC") and "-" not in raw:
        raw = raw[:-5] + "USDC"

    if "-" in raw:
        base, quote = raw.rsplit("-", 1)
        if not base:
            return raw
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


def _looks_like_okx_order_class(cls: type) -> bool:
    name = str(getattr(cls, "__name__", "")).lower()
    module = str(getattr(cls, "__module__", "")).lower()
    label = str(getattr(cls, "NAME", "") or getattr(cls, "name", "")).lower()
    return "okx" in name or "okx" in module or "okx" in label


def _looks_like_okx_broker_obj(obj: Any) -> bool:
    candidates = (
        getattr(getattr(obj, "broker_type", None), "value", None),
        getattr(obj, "broker_type", None),
        getattr(obj, "NAME", None),
        getattr(obj, "name", None),
        obj.__class__.__name__,
        obj.__class__.__module__,
    )
    return any("okx" in str(candidate or "").lower() for candidate in candidates)


def _extract_payload_order(payload: dict[str, Any]) -> tuple[Any, Any, Any]:
    symbol = payload.get("symbol") or payload.get("instId") or payload.get("instrument_id")
    side = payload.get("side") or payload.get("action")
    quantity = (
        payload.get("quantity")
        or payload.get("qty")
        or payload.get("sz")
        or payload.get("size")
        or payload.get("size_usd")
        or payload.get("notional")
        or payload.get("notional_usd")
        or payload.get("order_notional")
        or payload.get("amount")
    )
    return symbol, side, quantity


def _parse_order_call(args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple[Any, Any, Any, Optional[dict[str, Any]], tuple[Any, ...], dict[str, Any], str]:
    """Return symbol, side, quantity, optional payload, remaining args, kwargs, shape."""
    kw = dict(kwargs or {})
    if args and isinstance(args[0], dict):
        payload = dict(args[0])
        symbol, side, quantity = _extract_payload_order(payload)
        symbol = symbol or kw.get("symbol") or kw.get("instId")
        side = side or kw.get("side")
        quantity = quantity or kw.get("quantity") or kw.get("qty") or kw.get("sz")
        return symbol, side, quantity, payload, tuple(args[1:]), kw, "payload"

    symbol = args[0] if len(args) >= 1 else (kw.get("symbol") or kw.get("instId") or kw.get("instrument_id"))
    side = args[1] if len(args) >= 2 else (kw.get("side") or kw.get("action"))
    quantity = args[2] if len(args) >= 3 else (
        kw.get("quantity")
        or kw.get("qty")
        or kw.get("sz")
        or kw.get("size")
        or kw.get("size_usd")
        or kw.get("notional")
        or kw.get("notional_usd")
        or kw.get("order_notional")
        or kw.get("amount")
    )
    remaining = tuple(args[3:]) if len(args) >= 3 else tuple(args[1:] if len(args) == 1 else ())
    return symbol, side, quantity, None, remaining, kw, "expanded"


def _without_order_keys(kwargs: dict[str, Any]) -> dict[str, Any]:
    blocked = {
        "symbol",
        "instId",
        "instrument_id",
        "side",
        "action",
        "quantity",
        "qty",
        "sz",
        "size",
        "size_usd",
        "notional",
        "notional_usd",
        "order_notional",
        "amount",
    }
    return {k: v for k, v in dict(kwargs or {}).items() if k not in blocked}


def _call_with_fallbacks(
    fn: Callable[..., Any],
    self_obj: Any,
    *,
    symbol: str,
    side: Any,
    quantity: Any,
    payload: Optional[dict[str, Any]],
    remaining: tuple[Any, ...],
    kwargs: dict[str, Any],
    method_name: str,
) -> Any:
    clean_kwargs = _without_order_keys(kwargs)
    if payload is not None:
        payload["instId"] = symbol
        if "symbol" in payload:
            payload["symbol"] = symbol
        if side is not None:
            payload["side"] = side
        if quantity is not None:
            if "sz" in payload or "quantity" not in payload:
                payload["sz"] = quantity
            else:
                payload["quantity"] = quantity
        try:
            return fn(self_obj, payload, *remaining, **clean_kwargs)
        except TypeError as payload_exc:
            logger.warning(
                "OKX_PAYLOAD_STYLE_SUBMIT_RETRY marker=%s method=%s instId=%s error=%s",
                _MARKER,
                method_name,
                symbol,
                payload_exc,
            )

    attempts = (
        lambda: fn(self_obj, symbol, side, quantity, *remaining, **clean_kwargs),
        lambda: fn(self_obj, symbol=symbol, side=side, quantity=quantity, **clean_kwargs),
        lambda: fn(self_obj, instId=symbol, side=side, sz=quantity, **clean_kwargs),
    )
    last_exc: Optional[BaseException] = None
    for attempt in attempts:
        try:
            return attempt()
        except TypeError as exc:
            last_exc = exc
            continue
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("OKX_CALLSHAPE_BLOCK no submit attempt executed")


def _class_key(cls: type, method_name: str) -> str:
    return f"{getattr(cls, '__module__', '')}.{getattr(cls, '__name__', '')}.{method_name}"


def _wrap_order_class(okx_cls: type, module_name: str) -> bool:
    patched = False
    for method_name in ("place_market_order", "execute_order", "place_order"):
        current = getattr(okx_cls, method_name, None)
        if not callable(current) or getattr(current, _ORDER_WRAP_ATTR, False):
            continue
        base = getattr(current, "__wrapped__", current)
        if not callable(base):
            continue

        @wraps(base)
        def _patched_order(self: Any, *args: Any, __fn: Callable[..., Any] = base, __method: str = method_name, **kwargs: Any) -> Any:
            symbol, side, quantity, payload, remaining, parsed_kwargs, shape = _parse_order_call(args, kwargs)
            normalized_symbol = _normalize_inst_id(symbol)
            normalized_side = str(side or "").lower().strip()
            order_qty = _f(quantity, 0.0)
            if not normalized_symbol or not normalized_side or order_qty <= 0:
                reason = (
                    f"OKX_CALLSHAPE_BLOCK missing_or_invalid_order_fields "
                    f"method={__method} symbol={symbol!r} side={side!r} quantity={quantity!r} shape={shape}"
                )
                logger.critical("%s marker=%s", reason, _MARKER)
                print(f"[NIJA-PRINT] {reason} marker={_MARKER}", flush=True)
                return {
                    "status": "error",
                    "error": reason,
                    "error_code": "OKX_CALLSHAPE_BLOCK",
                    "symbol": normalized_symbol or str(symbol or ""),
                    "side": normalized_side,
                    "quantity": quantity,
                }

            logger.critical(
                "FINAL_OKX_SUBMIT_CALL marker=%s method=%s symbol=%s side=%s quantity=%s shape=%s order_type=%s client_order_id=%s",
                _MARKER,
                __method,
                normalized_symbol,
                normalized_side,
                order_qty,
                shape,
                parsed_kwargs.get("order_type") or parsed_kwargs.get("ordType") or parsed_kwargs.get("type") or "market",
                parsed_kwargs.get("client_order_id") or parsed_kwargs.get("clOrdId") or parsed_kwargs.get("clientOrderId") or "",
            )
            print(
                f"[NIJA-PRINT] FINAL_OKX_SUBMIT_CALL marker={_MARKER} "
                f"method={__method} symbol={normalized_symbol} side={normalized_side} quantity={order_qty}",
                flush=True,
            )
            try:
                result = _call_with_fallbacks(
                    __fn,
                    self,
                    symbol=normalized_symbol,
                    side=normalized_side,
                    quantity=order_qty,
                    payload=payload,
                    remaining=remaining,
                    kwargs=parsed_kwargs,
                    method_name=__method,
                )
            except TypeError as exc:
                message = str(exc)
                if "symbol" in message and "quantity" in message:
                    reason = f"OKX_CALLSHAPE_BLOCK wrapper_rejected_order method={__method} error={message}"
                    logger.critical("%s marker=%s symbol=%s side=%s", reason, _MARKER, normalized_symbol, normalized_side)
                    return {
                        "status": "error",
                        "error": reason,
                        "error_code": "OKX_CALLSHAPE_BLOCK",
                        "symbol": normalized_symbol,
                        "side": normalized_side,
                        "quantity": order_qty,
                    }
                raise
            return result

        setattr(_patched_order, _ORDER_WRAP_ATTR, True)
        setattr(_patched_order, "__wrapped__", base)
        setattr(okx_cls, method_name, _patched_order)
        key = _class_key(okx_cls, method_name)
        _PATCHED_ORDER_CLASSES.add(key)
        logger.warning(
            "OKX_FINAL_ORDER_METHOD_PATCHED marker=%s module=%s class=%s method=%s",
            _MARKER,
            module_name,
            getattr(okx_cls, "__name__", "<unknown>"),
            method_name,
        )
        patched = True
    return patched


def _candidate_order_classes(module: ModuleType) -> list[type]:
    found: list[type] = []
    for attr in ("OKXBroker", "OkxBroker", "OKXBrokerAdapter", "OkxBrokerAdapter", "Okx"):
        explicit = getattr(module, attr, None)
        if isinstance(explicit, type) and explicit not in found:
            found.append(explicit)
    for obj in vars(module).values():
        if not isinstance(obj, type) or obj in found:
            continue
        if not _looks_like_okx_order_class(obj):
            continue
        if any(callable(getattr(obj, method, None)) for method in ("place_market_order", "execute_order", "place_order")):
            found.append(obj)
    return found


def _extract_order_id(response: Any) -> Any:
    if not isinstance(response, dict):
        return None
    direct = response.get("order_id") or response.get("id") or response.get("exchange_order_id") or response.get("ordId")
    if direct:
        return direct
    data = response.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0].get("ordId") or data[0].get("order_id") or data[0].get("id")
    return None


def _okx_response_error(response: dict[str, Any]) -> str:
    data = response.get("data")
    nested = ""
    if isinstance(data, list) and data and isinstance(data[0], dict):
        nested = str(data[0].get("sMsg") or data[0].get("sCode") or "")
    return str(
        response.get("error")
        or response.get("message")
        or response.get("msg")
        or nested
        or response.get("code")
        or "unknown_okx_order_error"
    )


def _patch_router_module(module: ModuleType) -> bool:
    global _ROUTER_PATCHED
    cls = getattr(module, "MultiBrokerExecutionRouter", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "_dispatch_direct_broker_market_order", None)
    if not callable(current) or getattr(current, _ROUTER_PATCH_ATTR, False):
        return False
    original = getattr(current, "__wrapped__", current)

    @staticmethod
    @wraps(original)
    def _patched_dispatch_direct_broker_market_order(
        broker: Any,
        *,
        symbol: str,
        side: str,
        size_usd: float,
        metadata: dict[str, Any],
    ) -> tuple[float, float]:
        if not _looks_like_okx_broker_obj(broker):
            return original(broker, symbol=symbol, side=side, size_usd=size_usd, metadata=metadata)

        submit = getattr(broker, "place_market_order", None)
        if not callable(submit):
            submit = getattr(broker, "execute_order", None)
        if not callable(submit):
            submit = getattr(broker, "place_order", None)
        if not callable(submit):
            raise RuntimeError(f"OKX_CALLSHAPE_BLOCK broker {broker!r} has no submit method")

        normalized_symbol = _normalize_inst_id(symbol)
        normalized_side = str(side or "").lower().strip()
        order_notional = float(size_usd or 0.0)
        logger.critical(
            "FINAL_OKX_SUBMIT_CALL marker=%s source=router symbol=%s side=%s quantity=%s order_notional=%.2f order_type=market client_order_id=%s min_notional=%s",
            _MARKER,
            normalized_symbol,
            normalized_side,
            order_notional,
            order_notional,
            str((metadata or {}).get("client_order_id") or ""),
            str((metadata or {}).get("min_notional") or (metadata or {}).get("min_notional_usd") or ""),
        )
        try:
            result = submit(normalized_symbol, normalized_side, order_notional, size_type="quote")
        except TypeError as first_exc:
            try:
                result = submit(symbol=normalized_symbol, side=normalized_side, quantity=order_notional, size_type="quote")
            except TypeError as second_exc:
                message = f"first={first_exc}; second={second_exc}"
                if "symbol" in message and "quantity" in message:
                    raise RuntimeError(f"OKX_CALLSHAPE_BLOCK final_submit_missing_symbol_quantity {message}") from second_exc
                try:
                    result = submit(normalized_symbol, normalized_side, order_notional)
                except TypeError as third_exc:
                    raise RuntimeError(f"OKX_CALLSHAPE_BLOCK final_submit_type_error {third_exc}") from third_exc

        if isinstance(result, tuple) and len(result) >= 2:
            return float(result[0] or 0.0), float(result[1] or order_notional)
        if not isinstance(result, dict):
            raise RuntimeError(f"Unsupported OKX order response: {result!r}")

        status = str(result.get("status") or result.get("state") or "").strip().lower()
        code = str(result.get("code") or "")
        order_id = _extract_order_id(result)
        if status in {"error", "failed", "rejected", "canceled", "cancelled"} or (code and code != "0"):
            raise RuntimeError(
                f"OKX_ORDER_REJECTED code={code or result.get('error_code') or 'unknown'} "
                f"message={_okx_response_error(result)} raw={result!r}"
            )

        fill_price = _f(
            result.get("filled_price")
            or result.get("average_filled_price")
            or result.get("average_fill_price")
            or result.get("avg_price")
            or result.get("price")
            or (metadata or {}).get("price_hint_usd"),
            0.0,
        )
        filled_usd = _f(
            result.get("filled_size_usd")
            or result.get("filled_value")
            or result.get("notional_usd")
            or result.get("size_usd"),
            order_notional,
        )
        if fill_price <= 0 and order_id:
            fill_price = _f((metadata or {}).get("price_hint_usd"), 0.0)
        if fill_price <= 0:
            raise RuntimeError(f"OKX broker acknowledged without fill price/order id: {result!r}")
        logger.critical(
            "OKX_BROKER_ACK_RECEIVED marker=%s symbol=%s side=%s order_id=%s fill_price=%s filled_usd=%s",
            _MARKER,
            normalized_symbol,
            normalized_side,
            order_id or "",
            fill_price,
            filled_usd,
        )
        return fill_price, filled_usd

    setattr(_patched_dispatch_direct_broker_market_order, _ROUTER_PATCH_ATTR, True)
    setattr(_patched_dispatch_direct_broker_market_order, "__wrapped__", original)
    setattr(cls, "_dispatch_direct_broker_market_order", _patched_dispatch_direct_broker_market_order)
    _ROUTER_PATCHED = True
    logger.warning("OKX_FINAL_ORDER_ROUTER_PATCHED marker=%s module=%s", _MARKER, getattr(module, "__name__", "<unknown>"))
    return True


def _interesting_module(name: str) -> bool:
    lowered = str(name or "").lower()
    return (
        lowered in {
            "bot.broker_manager",
            "broker_manager",
            "bot.broker_integration",
            "broker_integration",
            "bot.multi_account_broker_manager",
            "multi_account_broker_manager",
            "bot.multi_broker_execution_router",
            "multi_broker_execution_router",
        }
        or "okx" in lowered
        or "broker" in lowered
    )


def _patch_module(module: ModuleType) -> bool:
    patched = False
    for cls in _candidate_order_classes(module):
        try:
            patched = _wrap_order_class(cls, getattr(module, "__name__", "<unknown>")) or patched
        except Exception as exc:
            logger.warning("OKX_FINAL_ORDER_CLASS_PATCH_FAILED marker=%s module=%s class=%s err=%s", _MARKER, getattr(module, "__name__", "<unknown>"), getattr(cls, "__name__", "<unknown>"), exc)
    try:
        patched = _patch_router_module(module) or patched
    except Exception as exc:
        logger.warning("OKX_FINAL_ORDER_ROUTER_PATCH_FAILED marker=%s module=%s err=%s", _MARKER, getattr(module, "__name__", "<unknown>"), exc)
    return patched


def _try_patch_loaded() -> bool:
    patched = False
    for name, module in list(sys.modules.items()):
        if not isinstance(module, ModuleType) or not _interesting_module(name):
            continue
        patched = _patch_module(module) or patched
    return patched


def _start_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + float(__import__("os").environ.get("NIJA_PATCH_MONITOR_SECONDS", "240") or "240")
        while time.time() < deadline:
            if _try_patch_loaded():
                if _ROUTER_PATCHED and _PATCHED_ORDER_CLASSES:
                    return
            time.sleep(0.25)
        logger.warning(
            "OKX_FINAL_ORDER_SUBMISSION_BRIDGE_MONITOR_EXPIRED marker=%s router_patched=%s order_classes=%s",
            _MARKER,
            _ROUTER_PATCHED,
            sorted(_PATCHED_ORDER_CLASSES),
        )

    threading.Thread(target=_monitor, name="okx-final-order-submission-bridge-monitor", daemon=True).start()
    logger.warning("OKX_FINAL_ORDER_SUBMISSION_BRIDGE_MONITOR_STARTED marker=%s", _MARKER)


def install_import_hook() -> None:
    with _INSTALL_LOCK:
        _try_patch_loaded()
        _start_monitor()
        if getattr(builtins, "_NIJA_OKX_FINAL_ORDER_SUBMISSION_BRIDGE_HOOK_V20260709A", False):
            logger.warning(
                "OKX_FINAL_ORDER_SUBMISSION_BRIDGE_INSTALL_COMPLETE marker=%s already_installed=True router_patched=%s order_classes=%s",
                _MARKER,
                _ROUTER_PATCHED,
                sorted(_PATCHED_ORDER_CLASSES),
            )
            return
        original_import = builtins.__import__

        def guarded_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
            module = original_import(name, globals, locals, fromlist, level)
            if _interesting_module(name):
                _try_patch_loaded()
            return module

        builtins.__import__ = guarded_import
        setattr(builtins, "_NIJA_OKX_FINAL_ORDER_SUBMISSION_BRIDGE_HOOK_V20260709A", True)
        logger.warning(
            "OKX_FINAL_ORDER_SUBMISSION_BRIDGE_INSTALL_COMPLETE marker=%s router_patched=%s order_classes=%s",
            _MARKER,
            _ROUTER_PATCHED,
            sorted(_PATCHED_ORDER_CLASSES),
        )


def install() -> None:
    install_import_hook()
