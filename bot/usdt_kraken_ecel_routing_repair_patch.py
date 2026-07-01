from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from dataclasses import replace
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.usdt_kraken_ecel_routing_repair")
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_PATCHED_PIPELINE = False
_PATCHED_ECEL = False
_MONITOR_STARTED = False
_INSTALL_LOCK = threading.Lock()


def _is_usdt_spot(symbol: str) -> bool:
    return str(symbol or "").strip().upper().replace("/", "-").endswith("-USDT")


def _kraken_usdt_rule(module: ModuleType, symbol: str) -> Any:
    ContractRule = getattr(module, "ContractRule")
    s = str(symbol or "").strip().upper().replace("/", "-")
    base = s.split("-", 1)[0]
    kraken_base = "XBT" if base == "BTC" else base
    canonical_symbol = f"{kraken_base}-USDT"
    min_base = 0.00000001
    base_step = 0.00000001
    price_step = 0.01
    price_precision = 2
    if kraken_base in {"XBT", "BTC"}:
        min_base = 0.00001
        base_step = 0.00000001
        price_step = 0.1
        price_precision = 1
    return ContractRule(
        broker="kraken",
        symbol=canonical_symbol,
        base_asset=kraken_base,
        quote_asset="USDT",
        min_notional_usd=10.0,
        min_base_size=min_base,
        base_step_size=base_step,
        price_step_size=price_step,
        base_precision=8,
        price_precision=price_precision,
    )


def _install_on_ecel(module: ModuleType) -> bool:
    global _PATCHED_ECEL
    schema_cls = getattr(module, "ContractSchemaMap", None)
    compiler_cls = getattr(module, "ECELExecutionCompiler", None)
    if not isinstance(schema_cls, type) or not isinstance(compiler_cls, type):
        return False

    original_get_rule = getattr(schema_cls, "get_rule", None)
    if callable(original_get_rule) and not getattr(original_get_rule, "_nija_usdt_kraken_get_rule_wrapped", False):
        def _patched_get_rule(self: Any, broker: str, symbol: str):
            rule = original_get_rule(self, broker, symbol)
            if rule is not None:
                return rule
            if str(broker or "").strip().lower() == "kraken" and _is_usdt_spot(symbol):
                rule = _kraken_usdt_rule(module, symbol)
                try:
                    self.upsert_rule(rule)
                except Exception:
                    pass
                logger.critical("USDT_KRAKEN_ECEL_RULE_REPAIR_APPLIED broker=kraken symbol=%s canonical=%s", symbol, rule.symbol)
                return rule
            return None
        setattr(_patched_get_rule, "_nija_usdt_kraken_get_rule_wrapped", True)
        setattr(schema_cls, "get_rule", _patched_get_rule)

    original_compile = getattr(compiler_cls, "compile", None)
    if callable(original_compile) and not getattr(original_compile, "_nija_usdt_kraken_compile_wrapped", False):
        def _patched_compile(self: Any, req: Any):
            broker = str(getattr(req, "broker", "") or "").strip().lower()
            symbol = str(getattr(req, "symbol", "") or "")
            if broker in {"", "coinbase", "auto"} and _is_usdt_spot(symbol):
                try:
                    req = replace(req, broker="kraken")
                except Exception:
                    setattr(req, "broker", "kraken")
                logger.critical("USDT_KRAKEN_ECEL_ROUTING_REPAIR_APPLIED raw_broker=%s symbol=%s broker=kraken", broker or "unset", symbol)
                print(f"[NIJA-PRINT] USDT_KRAKEN_ECEL_ROUTING_REPAIR_APPLIED | symbol={symbol} broker=kraken", flush=True)
            return original_compile(self, req)
        setattr(_patched_compile, "_nija_usdt_kraken_compile_wrapped", True)
        setattr(compiler_cls, "compile", _patched_compile)

    _PATCHED_ECEL = True
    logger.warning("USDT_KRAKEN_ECEL_REPAIR_PATCHED module=%s", getattr(module, "__name__", "<unknown>"))
    return True


def _install_on_pipeline(module: ModuleType) -> bool:
    global _PATCHED_PIPELINE
    cls = getattr(module, "ExecutionPipeline", None)
    if not isinstance(cls, type):
        return False
    original_execute = getattr(cls, "execute", None)
    if not callable(original_execute):
        return False
    if getattr(original_execute, "_nija_usdt_kraken_pipeline_routing_wrapped", False):
        _PATCHED_PIPELINE = True
        return True

    def _patched_execute(self: Any, request: Any, *args: Any, **kwargs: Any):
        try:
            symbol = str(getattr(request, "symbol", "") or "")
            broker = str(getattr(request, "preferred_broker", "") or "").strip().lower()
            if _is_usdt_spot(symbol) and broker in {"", "auto", "coinbase"}:
                request = replace(request, preferred_broker="kraken")
                logger.critical("USDT_KRAKEN_PIPELINE_ROUTING_REPAIR_APPLIED symbol=%s raw_broker=%s broker=kraken", symbol, broker or "unset")
                print(f"[NIJA-PRINT] USDT_KRAKEN_PIPELINE_ROUTING_REPAIR_APPLIED | symbol={symbol} broker=kraken", flush=True)
        except Exception as exc:
            logger.warning("USDT_KRAKEN_PIPELINE_ROUTING_REPAIR skipped err=%s", exc)
        return original_execute(self, request, *args, **kwargs)

    setattr(_patched_execute, "_nija_usdt_kraken_pipeline_routing_wrapped", True)
    setattr(cls, "execute", _patched_execute)
    _PATCHED_PIPELINE = True
    logger.warning("USDT_KRAKEN_PIPELINE_ROUTING_REPAIR_PATCHED module=%s", getattr(module, "__name__", "<unknown>"))
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.ecel_execution_compiler", "ecel_execution_compiler"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _install_on_ecel(module) or patched
    for name in ("bot.execution_pipeline", "execution_pipeline"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _install_on_pipeline(module) or patched
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
        logger.warning("USDT_KRAKEN_ECEL_ROUTING_REPAIR_MONITOR_EXPIRED pipeline=%s ecel=%s", _PATCHED_PIPELINE, _PATCHED_ECEL)

    threading.Thread(target=_monitor, name="usdt-kraken-ecel-routing-repair-monitor", daemon=True).start()
    logger.warning("USDT_KRAKEN_ECEL_ROUTING_REPAIR_MONITOR_STARTED")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _INSTALL_LOCK:
        _try_patch_loaded()
        _start_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            logger.warning("USDT_KRAKEN_ECEL_ROUTING_REPAIR_INSTALL_COMPLETE already_installed=True pipeline=%s ecel=%s", _PATCHED_PIPELINE, _PATCHED_ECEL)
            return
        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name in {"bot.ecel_execution_compiler", "ecel_execution_compiler"}:
                _install_on_ecel(module)
            if name in {"bot.execution_pipeline", "execution_pipeline"}:
                _install_on_pipeline(module)
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
        logger.warning("USDT_KRAKEN_ECEL_ROUTING_REPAIR_INSTALL_COMPLETE pipeline=%s ecel=%s", _PATCHED_PIPELINE, _PATCHED_ECEL)
