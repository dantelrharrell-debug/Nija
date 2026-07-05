from __future__ import annotations

import builtins
import json
import logging
import os
import re
import sys
import threading
import time
from types import ModuleType
from typing import Any, Optional

logger = logging.getLogger("nija.okx_order_instid_payload_repair")
_MARKER = "20260705e"
_PATCHED = False
_MONITOR_STARTED = False
_INSTALL_LOCK = threading.Lock()
_REST_WRAP_ATTR = "_nija_okx_order_instid_payload_repair_rest_v20260705e"
_ORDER_WRAP_ATTR = "_nija_okx_order_instid_payload_repair_order_v20260705e"
_VALID_QUOTES = ("USDT", "USDC", "USD")
_PRODUCT_CACHE: dict[str, Any] = {"loaded_at": 0.0, "symbols": set()}


def _clean_symbol(symbol: Any) -> str:
    raw = str(symbol or "").upper().strip().replace("/", "-").replace("_", "-").replace(":", "-")
    raw = re.sub(r"[^A-Z0-9\-]", "", raw)
    while "--" in raw:
        raw = raw.replace("--", "-")
    return raw


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

    for quote in sorted(_VALID_QUOTES, key=len, reverse=True):
        if raw.endswith(quote) and len(raw) > len(quote):
            base = raw[: -len(quote)]
            return f"{base}-USDT" if quote == "USD" else f"{base}-{quote}"
    return raw


def _extract_symbols(payload: Any) -> set[str]:
    symbols: set[str] = set()
    if isinstance(payload, dict):
        if "data" in payload:
            symbols.update(_extract_symbols(payload.get("data")))
        inst = payload.get("instId") or payload.get("symbol") or payload.get("id")
        if inst:
            norm = _normalize_inst_id(inst)
            if norm.endswith(("-USDT", "-USDC")):
                symbols.add(norm)
        for value in payload.values():
            if isinstance(value, (dict, list, tuple, set, frozenset)):
                symbols.update(_extract_symbols(value))
    elif isinstance(payload, (list, tuple, set, frozenset)):
        for item in payload:
            symbols.update(_extract_symbols(item))
    return symbols


def _product_cache(rest: Any, original_request: Any) -> set[str]:
    now = time.time()
    cached = _PRODUCT_CACHE.get("symbols")
    if isinstance(cached, set) and cached and now - float(_PRODUCT_CACHE.get("loaded_at", 0.0) or 0.0) < 1800:
        return set(cached)
    try:
        result = original_request(rest, "GET", "/api/v5/public/instruments", params={"instType": "SPOT"}, payload=None, private=False)
        if isinstance(result, dict) and str(result.get("code", "")) == "0":
            symbols = _extract_symbols(result.get("data", []))
            if symbols:
                _PRODUCT_CACHE["loaded_at"] = now
                _PRODUCT_CACHE["symbols"] = set(symbols)
                logger.warning("OKX_ORDER_PRODUCT_CACHE_LOADED marker=%s count=%d", _MARKER, len(symbols))
                return symbols
    except Exception as exc:
        logger.debug("OKX order product cache load skipped: %s", exc)
    return set(cached) if isinstance(cached, set) else set()


def _choose_listed_inst(inst: str, products: set[str]) -> str:
    if not products or inst in products:
        return inst
    if "-" not in inst:
        return inst
    base, quote = inst.rsplit("-", 1)
    alternates = []
    if quote == "USDT":
        alternates = [f"{base}-USDC"]
    elif quote == "USDC":
        alternates = [f"{base}-USDT"]
    elif quote == "USD":
        alternates = [f"{base}-USDT", f"{base}-USDC"]
    for alt in alternates:
        if alt in products:
            logger.critical("OKX_ORDER_INSTID_LISTED_ALTERNATE marker=%s before=%s after=%s", _MARKER, inst, alt)
            return alt
    return inst


def _nested_scode(payload: Any) -> tuple[str, str]:
    try:
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict):
                return str(first.get("sCode") or ""), str(first.get("sMsg") or "")
    except Exception:
        pass
    return "", ""


def _patch_module(module: ModuleType) -> bool:
    global _PATCHED
    rest_cls = getattr(module, "_OKXRestClient", None)
    okx_cls = getattr(module, "OKXBroker", None) or getattr(module, "OKXBrokerAdapter", None)
    patched = False

    if isinstance(rest_cls, type):
        original_request = getattr(rest_cls, "_request", None)
        if callable(original_request) and not getattr(original_request, _REST_WRAP_ATTR, False):
            def _patched_request(self: Any, method: str, path: str, *, params: Optional[dict[str, Any]] = None, payload: Optional[dict[str, Any]] = None, private: bool = False) -> dict[str, Any]:
                clean_payload = dict(payload or {}) if isinstance(payload, dict) else payload
                order_path = str(path or "") == "/api/v5/trade/order"
                if isinstance(clean_payload, dict) and "instId" in clean_payload:
                    before = str(clean_payload.get("instId") or "")
                    after = _normalize_inst_id(before)
                    if order_path:
                        products = _product_cache(self, original_request)
                        after2 = _choose_listed_inst(after, products)
                        if after2 != after:
                            after = after2
                    if after != before:
                        logger.critical("OKX_ORDER_INSTID_PAYLOAD_NORMALIZED marker=%s before=%s after=%s path=%s", _MARKER, before, after, path)
                        print(f"[NIJA-PRINT] OKX_ORDER_INSTID_PAYLOAD_NORMALIZED marker={_MARKER} before={before} after={after}", flush=True)
                    clean_payload["instId"] = after
                    if order_path:
                        logger.critical(
                            "OKX_ORDER_PAYLOAD_READY marker=%s instId=%s side=%s tdMode=%s ordType=%s sz=%s",
                            _MARKER,
                            after,
                            clean_payload.get("side"),
                            clean_payload.get("tdMode"),
                            clean_payload.get("ordType"),
                            clean_payload.get("sz"),
                        )
                result = original_request(self, method, path, params=params, payload=clean_payload, private=private)
                if order_path and isinstance(result, dict):
                    scode, smsg = _nested_scode(result)
                    if scode == "51001":
                        inst = ""
                        if isinstance(clean_payload, dict):
                            inst = str(clean_payload.get("instId") or "")
                        msg = f"OKX_51001_INVALID_INSTRUMENT instId={inst} detail={smsg or 'Instrument ID does not exist'}"
                        result["msg"] = msg
                        result["nija_error_code"] = "OKX_INVALID_INSTRUMENT"
                        result["nija_inst_id"] = inst
                        logger.critical("OKX_ORDER_51001_CLASSIFIED marker=%s instId=%s detail=%s", _MARKER, inst, smsg)
                        print(f"[NIJA-PRINT] OKX_ORDER_51001_CLASSIFIED marker={_MARKER} instId={inst} detail={smsg}", flush=True)
                return result

            setattr(_patched_request, _REST_WRAP_ATTR, True)
            setattr(_patched_request, "__wrapped__", original_request)
            setattr(rest_cls, "_request", _patched_request)
            logger.warning("OKX_ORDER_INSTID_REST_PATCHED marker=%s module=%s", _MARKER, getattr(module, "__name__", "<unknown>"))
            patched = True

    if isinstance(okx_cls, type):
        for method_name in ("place_market_order", "execute_order", "place_order"):
            original = getattr(okx_cls, method_name, None)
            if not callable(original) or getattr(original, _ORDER_WRAP_ATTR, False):
                continue

            def _make_wrapper(fn: Any, name: str):
                def _patched_order(self: Any, symbol: Any, side: Any, quantity: Any, *args: Any, **kwargs: Any) -> Any:
                    before = str(symbol or "")
                    after = _normalize_inst_id(before)
                    if after != before:
                        logger.critical("OKX_ORDER_SYMBOL_NORMALIZED marker=%s method=%s before=%s after=%s", _MARKER, name, before, after)
                        print(f"[NIJA-PRINT] OKX_ORDER_SYMBOL_NORMALIZED marker={_MARKER} before={before} after={after}", flush=True)
                    return fn(self, after, side, quantity, *args, **kwargs)
                setattr(_patched_order, _ORDER_WRAP_ATTR, True)
                setattr(_patched_order, "__wrapped__", fn)
                return _patched_order

            setattr(okx_cls, method_name, _make_wrapper(original, method_name))
            logger.warning("OKX_ORDER_SYMBOL_METHOD_PATCHED marker=%s module=%s method=%s", _MARKER, getattr(module, "__name__", "<unknown>"), method_name)
            patched = True

    if patched:
        _PATCHED = True
        print(f"[NIJA-PRINT] OKX_ORDER_INSTID_PAYLOAD_REPAIR_PATCHED marker={_MARKER} module={getattr(module, '__name__', '<unknown>')}", flush=True)
    return patched


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.broker_manager", "broker_manager"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                patched = _patch_module(module) or patched
            except Exception as exc:
                logger.warning("OKX_ORDER_INSTID_PAYLOAD_REPAIR_FAILED marker=%s module=%s err=%s", _MARKER, name, exc)
    return patched


def _start_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + float(os.environ.get("NIJA_PATCH_MONITOR_SECONDS", "240") or "240")
        while time.time() < deadline:
            if _try_patch_loaded():
                return
            time.sleep(0.25)
        logger.warning("OKX_ORDER_INSTID_PAYLOAD_REPAIR_MONITOR_EXPIRED marker=%s patched=%s", _MARKER, _PATCHED)

    threading.Thread(target=_monitor, name="okx-order-instid-payload-repair-monitor", daemon=True).start()
    logger.warning("OKX_ORDER_INSTID_PAYLOAD_REPAIR_MONITOR_STARTED marker=%s", _MARKER)


def install_import_hook() -> None:
    with _INSTALL_LOCK:
        _try_patch_loaded()
        _start_monitor()
        if getattr(builtins, "_NIJA_OKX_ORDER_INSTID_PAYLOAD_REPAIR_IMPORT_HOOK", False):
            logger.warning("OKX_ORDER_INSTID_PAYLOAD_REPAIR_INSTALL_COMPLETE marker=%s already_installed=True patched=%s", _MARKER, _PATCHED)
            return
        original_import = builtins.__import__

        def guarded_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
            module = original_import(name, globals, locals, fromlist, level)
            if name in {"bot.broker_manager", "broker_manager"} or str(name).endswith(".broker_manager"):
                _try_patch_loaded()
            return module

        builtins.__import__ = guarded_import
        setattr(builtins, "_NIJA_OKX_ORDER_INSTID_PAYLOAD_REPAIR_IMPORT_HOOK", True)
        logger.warning("OKX_ORDER_INSTID_PAYLOAD_REPAIR_INSTALL_COMPLETE marker=%s patched=%s", _MARKER, _PATCHED)


def install() -> None:
    install_import_hook()
