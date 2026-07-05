"""Venue route guard for USDT spot execution.

Prevents the legacy USDT repair from blindly rewriting USDT orders to Kraken.
Kraken is allowed only when the request is already targeting Kraken, the pair is
known by the Kraken validator, and the notional is above the effective live floor.
"""

from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.venue_route_guard")

_ORIGINAL_IMPORT: Optional[Callable[..., Any]] = None
_PATCHED_USDT_MODULES: set[int] = set()
_PATCHED_PIPELINES: set[int] = set()
_PATCHED_ECEL: set[int] = set()
_MONITOR_STARTED = False
_LOCK = threading.Lock()
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUE


def _float_env(name: str, default: float = 0.0) -> float:
    try:
        return float(os.environ.get(name, default))
    except Exception:
        return default


def _is_usdt(symbol: Any) -> bool:
    return str(symbol or "").strip().upper().replace("/", "-").endswith("-USDT")


def _broker(value: Any) -> str:
    return str(value or "").strip().lower()


def _symbol_text(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-").replace("_", "-")


def _kraken_pair_key(symbol: Any) -> str:
    text = _symbol_text(symbol)
    base = text.split("-", 1)[0] if "-" in text else text.replace("USDT", "")
    if base in {"BTC", "XBT"}:
        return "XXBTZUSDT"
    if base in {"ETH", "XETH"}:
        return "XETHZUSDT"
    return f"{base}USDT"


def _configured_kraken_floor() -> float:
    return max(
        23.0,
        _float_env("KRAKEN_MIN_NOTIONAL_USD", 0.0),
        _float_env("NIJA_KRAKEN_MIN_NOTIONAL_USD", 0.0),
        _float_env("NIJA_KRAKEN_EFFECTIVE_MIN_NOTIONAL_USD", 0.0),
        _float_env("NIJA_KRAKEN_FINAL_MIN_NOTIONAL_USD", 0.0),
    )


def _notional_from(obj: Any) -> float:
    for name in ("notional_usd", "size_usd", "quote_amount", "amount_usd"):
        if hasattr(obj, name):
            value = _float_env("__missing__", 0.0)
            try:
                value = float(getattr(obj, name) or 0.0)
            except Exception:
                value = 0.0
            if value > 0:
                return value
    if isinstance(obj, dict):
        for name in ("notional_usd", "size_usd", "quote_amount", "amount_usd"):
            try:
                value = float(obj.get(name) or 0.0)
            except Exception:
                value = 0.0
            if value > 0:
                return value
    return 0.0


def _kraken_pair_validation(symbol: Any, notional: float) -> tuple[bool, str, float, str]:
    pair = _kraken_pair_key(symbol)
    floor = _configured_kraken_floor()
    try:
        try:
            validator = importlib.import_module("bot.kraken_order_validator")
        except Exception:
            validator = importlib.import_module("kraken_order_validator")
        minimums = getattr(validator, "KRAKEN_MINIMUMS", {})
        if not isinstance(minimums, dict) or pair not in minimums:
            return False, pair, floor, "pair_not_in_kraken_validator"
        safe_fn = getattr(validator, "get_pair_safe_minimums", None)
        if callable(safe_fn):
            data = safe_fn(pair)
            floor = max(floor, float(data.get("min_quote", floor)))
    except Exception as exc:
        return False, pair, floor, f"validator_unavailable:{exc}"
    if float(notional or 0.0) + 1e-9 < floor:
        return False, pair, floor, f"notional_below_kraken_floor:${float(notional or 0.0):.2f}<${floor:.2f}"
    return True, pair, floor, "ok"


def _patch_usdt_repair_module(module: ModuleType) -> bool:
    module_id = id(module)
    if module_id in _PATCHED_USDT_MODULES:
        return True

    def _safe_install_on_pipeline(pipeline_module: ModuleType) -> bool:
        cls = getattr(pipeline_module, "ExecutionPipeline", None)
        result_cls = getattr(pipeline_module, "PipelineResult", None)
        if not isinstance(cls, type):
            return False
        original = getattr(cls, "execute", None)
        if not callable(original) or getattr(original, "_venue_route_guard", False):
            return True
        if id(cls) in _PATCHED_PIPELINES:
            return True

        def execute(self: Any, request: Any, *args: Any, **kwargs: Any):
            try:
                symbol = getattr(request, "symbol", "")
                broker = _broker(getattr(request, "preferred_broker", ""))
                notional = _notional_from(request)
                if _is_usdt(symbol):
                    if broker == "okx":
                        logger.critical("USDT_ROUTE_GUARD_KEEP_SELECTED symbol=%s broker=okx notional=$%.2f", symbol, notional)
                    elif broker == "kraken":
                        ok, pair, floor, reason = _kraken_pair_validation(symbol, notional)
                        if not ok:
                            logger.critical(
                                "USDT_ROUTE_GUARD_BLOCK_KRAKEN symbol=%s broker=kraken pair=%s notional=$%.2f floor=$%.2f reason=%s",
                                symbol, pair, notional, floor, reason,
                            )
                            if isinstance(result_cls, type):
                                return result_cls(
                                    success=False,
                                    symbol=str(symbol),
                                    side=str(getattr(request, "side", "buy")),
                                    size_usd=float(notional or getattr(request, "size_usd", 0.0) or 0.0),
                                    broker="kraken",
                                    error=f"KRAKEN_USDT_ROUTE_BLOCKED:{reason}",
                                )
                        else:
                            logger.critical("USDT_ROUTE_GUARD_ALLOW_KRAKEN symbol=%s pair=%s notional=$%.2f floor=$%.2f", symbol, pair, notional, floor)
                    elif broker in {"", "auto", "coinbase"}:
                        logger.critical("USDT_ROUTE_GUARD_NO_BLIND_KRAKEN_ROUTE symbol=%s selected_broker=%s notional=$%.2f", symbol, broker or "unset", notional)
            except Exception as exc:
                logger.warning("USDT_ROUTE_GUARD_PIPELINE_CHECK_FAILED err=%s", exc)
            return original(self, request, *args, **kwargs)

        setattr(execute, "_venue_route_guard", True)
        setattr(execute, "__wrapped__", original)
        setattr(cls, "execute", execute)
        _PATCHED_PIPELINES.add(id(cls))
        logger.warning("VENUE_ROUTE_GUARD_PIPELINE_PATCHED module=%s", getattr(pipeline_module, "__name__", "?"))
        return True

    def _safe_install_on_ecel(ecel_module: ModuleType) -> bool:
        schema_cls = getattr(ecel_module, "ContractSchemaMap", None)
        compiler_cls = getattr(ecel_module, "ECELExecutionCompiler", None)
        if not isinstance(compiler_cls, type):
            return False
        original_compile = getattr(compiler_cls, "compile", None)
        if not callable(original_compile) or getattr(original_compile, "_venue_route_guard", False):
            return True
        if id(compiler_cls) in _PATCHED_ECEL:
            return True

        def compile(self: Any, req: Any):
            broker = _broker(getattr(req, "broker", ""))
            symbol = getattr(req, "symbol", "")
            notional = _notional_from(req)
            if _is_usdt(symbol):
                if broker == "okx":
                    logger.critical("USDT_ECEL_ROUTE_GUARD_KEEP_SELECTED symbol=%s broker=okx notional=$%.2f", symbol, notional)
                elif broker == "kraken":
                    ok, pair, floor, reason = _kraken_pair_validation(symbol, notional)
                    if not ok:
                        logger.critical("USDT_ECEL_ROUTE_GUARD_BLOCK_KRAKEN symbol=%s pair=%s notional=$%.2f floor=$%.2f reason=%s", symbol, pair, notional, floor, reason)
                        raise ValueError(f"KRAKEN_USDT_ROUTE_BLOCKED:{reason}")
                    logger.critical("USDT_ECEL_ROUTE_GUARD_ALLOW_KRAKEN symbol=%s pair=%s notional=$%.2f floor=$%.2f", symbol, pair, notional, floor)
                elif broker in {"", "auto", "coinbase"}:
                    logger.critical("USDT_ECEL_ROUTE_GUARD_NO_BLIND_KRAKEN_ROUTE symbol=%s broker=%s notional=$%.2f", symbol, broker or "unset", notional)
            return original_compile(self, req)

        setattr(compile, "_venue_route_guard", True)
        setattr(compile, "__wrapped__", original_compile)
        setattr(compiler_cls, "compile", compile)
        _PATCHED_ECEL.add(id(compiler_cls))
        logger.warning("VENUE_ROUTE_GUARD_ECEL_PATCHED module=%s schema_present=%s", getattr(ecel_module, "__name__", "?"), isinstance(schema_cls, type))
        return True

    setattr(module, "_install_on_pipeline", _safe_install_on_pipeline)
    setattr(module, "_install_on_ecel", _safe_install_on_ecel)
    _PATCHED_USDT_MODULES.add(module_id)
    logger.warning("VENUE_ROUTE_GUARD_PATCHED_USDT_REPAIR module=%s", getattr(module, "__name__", "?"))
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.usdt_kraken_ecel_routing_repair_patch", "usdt_kraken_ecel_routing_repair_patch"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_usdt_repair_module(module) or patched
    return patched


def _start_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def monitor() -> None:
        deadline = time.time() + _float_env("NIJA_PATCH_MONITOR_SECONDS", 240.0)
        while time.time() < deadline:
            if _try_patch_loaded():
                return
            time.sleep(0.25)
        logger.warning("VENUE_ROUTE_GUARD_MONITOR_EXPIRED patched_modules=%d", len(_PATCHED_USDT_MODULES))

    threading.Thread(target=monitor, name="venue-route-guard-monitor", daemon=True).start()
    logger.warning("VENUE_ROUTE_GUARD_MONITOR_STARTED")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT
    with _LOCK:
        _try_patch_loaded()
        _start_monitor()
        if _ORIGINAL_IMPORT is not None:
            return
        _ORIGINAL_IMPORT = builtins.__import__

        def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
            module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)
            try:
                _try_patch_loaded()
                if str(getattr(module, "__name__", "")) in {"bot.usdt_kraken_ecel_routing_repair_patch", "usdt_kraken_ecel_routing_repair_patch"}:
                    _patch_usdt_repair_module(module)
            except Exception as exc:
                logger.debug("Venue route guard import check skipped: %s", exc)
            return module

        builtins.__import__ = importing
        logger.warning("VENUE_ROUTE_GUARD_INSTALLED marker=20260704h")
