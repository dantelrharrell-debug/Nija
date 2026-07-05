"""Broker-aware ECEL contract route repair."""

from __future__ import annotations

import importlib
import logging
import sys
import threading
import time
from dataclasses import replace
from types import ModuleType
from typing import Any, Callable, Optional

log = logging.getLogger("nija.ecel_contract_route_repair")
_ORIG_IMPORT: Optional[Callable[..., Any]] = None
_STARTED = False
_LOCK = threading.Lock()
_BROKERS = ("kraken", "coinbase", "okx")


def _sym(v: Any) -> str:
    symbol = str(v or "").strip().upper().replace("/", "-").replace("_", "-")
    if symbol.endswith("-USDTT"):
        symbol = symbol[:-1]
    return symbol


def _is_usdt(symbol: Any) -> bool:
    return _sym(symbol).endswith("-USDT")


def _br(v: Any) -> str:
    return str(v or "").strip().lower()


def _replace(obj: Any, **changes: Any) -> Any:
    try:
        return replace(obj, **changes)
    except Exception:
        for key, value in changes.items():
            try:
                setattr(obj, key, value)
            except Exception:
                pass
        return obj


def _rule(schema: Any, broker: str, symbol: str) -> Any:
    try:
        return schema.get_rule(_br(broker), _sym(symbol))
    except Exception:
        return None


def _refresh(schema: Any, symbol: str, requested: str = "") -> None:
    try:
        fn = getattr(schema, "refresh_from_public_endpoints", None)
        if callable(fn):
            target = _br(requested) or None
            if _is_usdt(symbol) and target not in {"okx", "coinbase", "kraken"}:
                target = "okx"
            log.warning("ECEL_ROUTE_REFRESH symbol=%s target_broker=%s stats=%s", _sym(symbol), target or "all", fn(target_broker=target))
    except Exception as exc:
        log.warning("ECEL_ROUTE_REFRESH_FAILED symbol=%s err=%s", _sym(symbol), exc)


def _order(symbol: str, requested: str = "") -> list[str]:
    requested_broker = _br(requested)
    if _is_usdt(symbol):
        if requested_broker == "kraken":
            return ["kraken"]
        if requested_broker == "okx":
            return ["okx"]
        if requested_broker == "coinbase":
            return ["coinbase", "okx"]
        return ["okx", "coinbase"]
    order: list[str] = []
    if requested_broker:
        order.append(requested_broker)
    for broker in _BROKERS:
        if broker not in order:
            order.append(broker)
    return order


def _find(schema: Any, symbol: str, requested: str = "") -> Any:
    symbol = _sym(symbol)
    for broker in _order(symbol, requested):
        found = _rule(schema, broker, symbol)
        if found is not None:
            return found
    return None


def _patch_ecel(module: ModuleType) -> bool:
    cls = getattr(module, "ECELExecutionCompiler", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "compile", None)
    if not callable(original) or getattr(original, "_nija_route_fix", False):
        return True

    def compile_fixed(self: Any, req: Any, *args: Any, **kwargs: Any) -> Any:
        raw_symbol = str(getattr(req, "symbol", "") or "")
        symbol = _sym(raw_symbol)
        if symbol and symbol != raw_symbol:
            log.warning("ECEL_SYMBOL_NORMALIZED raw=%s normalized=%s", raw_symbol, symbol)
            req = _replace(req, symbol=symbol)
        out = original(self, req, *args, **kwargs)
        if bool(getattr(out, "accepted", False)) or str(getattr(out, "reason", "")) != "NO_CONTRACT_RULE":
            return out
        schema = getattr(self, "schema", None)
        requested = _br(getattr(req, "broker", "") or getattr(out, "broker", ""))
        if schema is None or not symbol:
            return out
        _refresh(schema, symbol, requested)
        found = _find(schema, symbol, requested)
        broker = _br(getattr(found, "broker", "")) if found is not None else ""
        if not broker or broker == requested:
            return out
        if _is_usdt(symbol) and broker == "kraken" and requested != "kraken":
            log.critical("ECEL_CONTRACT_ROUTE_REPAIR_BLOCKED_USDT_TO_KRAKEN symbol=%s requested_broker=%s repaired_broker=%s", symbol, requested or "auto", broker)
            return out
        repaired_req = _replace(req, broker=broker, symbol=symbol)
        retry = original(self, repaired_req, *args, **kwargs)
        if bool(getattr(retry, "accepted", False)):
            log.critical("ECEL_CONTRACT_ROUTE_REPAIRED symbol=%s requested_broker=%s repaired_broker=%s", symbol, requested or "auto", broker)
            print(f"[NIJA-PRINT] ECEL_CONTRACT_ROUTE_REPAIRED symbol={symbol} requested_broker={requested or 'auto'} repaired_broker={broker}", flush=True)
        return retry

    setattr(compile_fixed, "_nija_route_fix", True)
    setattr(cls, "compile", compile_fixed)
    log.warning("ECEL_CONTRACT_ROUTE_REPAIR_PATCHED module=%s", getattr(module, "__name__", "?"))
    print("[NIJA-PRINT] ECEL_CONTRACT_ROUTE_REPAIR_PATCHED", flush=True)
    return True


def _patch_pipeline(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionPipeline", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_dispatch", None)
    if not callable(original) or getattr(original, "_nija_route_fix", False):
        return True

    def dispatch_fixed(self: Any, request: Any, t_start: float, *args: Any, **kwargs: Any) -> Any:
        try:
            schema = getattr(getattr(self, "_ecel", None), "schema", None)
            raw_symbol = str(getattr(request, "symbol", "") or "")
            symbol = _sym(raw_symbol)
            current = _br(getattr(request, "preferred_broker", ""))
            if symbol and symbol != raw_symbol:
                log.warning("ECEL_PRE_DISPATCH_SYMBOL_NORMALIZED raw=%s normalized=%s", raw_symbol, symbol)
                request = _replace(request, symbol=symbol)
            if schema is not None and symbol and _rule(schema, current, symbol) is None:
                found = _find(schema, symbol, current)
                if found is None:
                    _refresh(schema, symbol, current)
                    found = _find(schema, symbol, current)
                broker = _br(getattr(found, "broker", "")) if found is not None else ""
                if broker and broker != current:
                    if _is_usdt(symbol) and broker == "kraken" and current != "kraken":
                        log.critical("ECEL_PRE_DISPATCH_ROUTE_REPAIR_BLOCKED_USDT_TO_KRAKEN symbol=%s old_broker=%s repaired_broker=%s", symbol, current or "blank", broker)
                    else:
                        log.critical("ECEL_PRE_DISPATCH_BROKER_ROUTE_REPAIRED symbol=%s old_broker=%s repaired_broker=%s", symbol, current or "blank", broker)
                        print(f"[NIJA-PRINT] ECEL_PRE_DISPATCH_BROKER_ROUTE_REPAIRED symbol={symbol} old_broker={current or 'blank'} repaired_broker={broker}", flush=True)
                        request = _replace(request, preferred_broker=broker, symbol=symbol)
        except Exception as exc:
            log.warning("ECEL_PRE_DISPATCH_BROKER_ROUTE_REPAIR_FAILED err=%s", exc)
        return original(self, request, t_start, *args, **kwargs)

    setattr(dispatch_fixed, "_nija_route_fix", True)
    setattr(cls, "_dispatch", dispatch_fixed)
    log.warning("ECEL_CONTRACT_ROUTE_PIPELINE_PATCHED module=%s", getattr(module, "__name__", "?"))
    return True


def _patch_loaded() -> bool:
    ok = False
    for name in ("bot.ecel_execution_compiler", "ecel_execution_compiler"):
        mod = sys.modules.get(name)
        if isinstance(mod, ModuleType):
            ok = _patch_ecel(mod) or ok
    for name in ("bot.execution_pipeline", "execution_pipeline"):
        mod = sys.modules.get(name)
        if isinstance(mod, ModuleType):
            ok = _patch_pipeline(mod) or ok
    return ok


def _monitor() -> None:
    deadline = time.time() + 240.0
    while time.time() < deadline:
        if _patch_loaded():
            return
        time.sleep(0.25)
    log.warning("ECEL_CONTRACT_ROUTE_REPAIR_MONITOR_EXPIRED")


def install_import_hook() -> None:
    global _ORIG_IMPORT, _STARTED
    with _LOCK:
        _patch_loaded()
        if not _STARTED:
            _STARTED = True
            threading.Thread(target=_monitor, name="ecel-contract-route-repair", daemon=True).start()
        if _ORIG_IMPORT is not None:
            return
        _ORIG_IMPORT = importlib.import_module

        def import_module_fixed(name: str, package: str | None = None):
            mod = _ORIG_IMPORT(name, package)  # type: ignore[misc]
            if name in {"bot.ecel_execution_compiler", "ecel_execution_compiler"}:
                _patch_ecel(mod)
            if name in {"bot.execution_pipeline", "execution_pipeline"}:
                _patch_pipeline(mod)
            return mod

        importlib.import_module = import_module_fixed  # type: ignore[assignment]
        log.warning("ECEL_CONTRACT_ROUTE_REPAIR_INSTALL_COMPLETE")
        print("[NIJA-PRINT] ECEL_CONTRACT_ROUTE_REPAIR_INSTALL_COMPLETE", flush=True)
