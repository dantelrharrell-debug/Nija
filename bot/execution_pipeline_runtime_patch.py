"""Runtime telemetry and ECEL route hardening for ExecutionPipeline."""

from __future__ import annotations

import builtins
import logging
import time
from dataclasses import replace
from functools import wraps
from typing import Any

logger = logging.getLogger("nija.execution_pipeline_runtime_patch")
_PATCHED_ATTR = "__nija_execution_pipeline_deny_patch__"
_ROUTE_PATCHED_ATTR = "__nija_execution_pipeline_route_patch__"


def _norm_symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper().replace("/", "-").replace("_", "-")
    # Defensive repair for the observed ALLO-USDT -> ALLO-USDTT mutation.
    # Never let an internally-mutated USDTT symbol reach ECEL or broker dispatch.
    if symbol.endswith("-USDTT"):
        symbol = symbol[:-1]
    return symbol


def _is_usdt(symbol: Any) -> bool:
    return _norm_symbol(symbol).endswith("-USDT")


def _norm_broker(value: Any) -> str:
    return str(value or "").strip().lower()


def _replace_req(req: Any, **changes: Any) -> Any:
    try:
        return replace(req, **changes)
    except Exception:
        for key, value in changes.items():
            try:
                setattr(req, key, value)
            except Exception:
                pass
        return req


def _schema_rule(schema: Any, broker: str, symbol: str) -> Any:
    try:
        return schema.get_rule(_norm_broker(broker), _norm_symbol(symbol))
    except Exception:
        return None


def _broker_search_order(symbol: str, preferred: str = "") -> list[str]:
    preferred_broker = _norm_broker(preferred)
    usdt = _is_usdt(symbol)
    if usdt:
        # Venue integrity rule: USDT spot selected for OKX must stay on OKX.
        # Do not silently repair OKX/auto/Coinbase USDT orders to Kraken.
        if preferred_broker == "kraken":
            return ["kraken"]
        if preferred_broker == "okx":
            return ["okx"]
        if preferred_broker == "coinbase":
            return ["coinbase", "okx"]
        return ["okx", "coinbase"]

    brokers: list[str] = []
    if preferred_broker:
        brokers.append(preferred_broker)
    for broker in ("kraken", "coinbase", "okx"):
        if broker not in brokers:
            brokers.append(broker)
    return brokers


def _resolve_rule(schema: Any, symbol: str, preferred: str = "") -> Any:
    symbol = _norm_symbol(symbol)
    for broker in _broker_search_order(symbol, preferred):
        rule = _schema_rule(schema, broker, symbol)
        if rule is not None:
            return rule
    return None


def _refresh_schema(schema: Any, symbol: str, preferred: str = "") -> None:
    try:
        refresh = getattr(schema, "refresh_from_public_endpoints", None)
        if callable(refresh):
            target = _norm_broker(preferred) or None
            if _is_usdt(symbol) and target not in {"okx", "coinbase", "kraken"}:
                target = "okx"
            stats = refresh(target_broker=target)
            logger.warning("ECEL_ROUTE_REFRESH symbol=%s target_broker=%s stats=%s", _norm_symbol(symbol), target or "all", stats)
    except Exception as exc:
        logger.warning("ECEL_ROUTE_REFRESH_FAILED symbol=%s err=%s", _norm_symbol(symbol), exc)


def _patch_ecel_compiler(ecel: Any) -> bool:
    if ecel is None:
        return False
    cls = ecel.__class__
    original = getattr(cls, "compile", None)
    if not callable(original):
        return False
    if getattr(original, "__nija_ecel_route_compile_patch__", False):
        return True

    @wraps(original)
    def compile_with_route_repair(self: Any, req: Any, *args: Any, **kwargs: Any):
        raw_symbol = str(getattr(req, "symbol", "") or "")
        symbol = _norm_symbol(raw_symbol)
        if symbol and symbol != raw_symbol:
            logger.warning("ECEL_SYMBOL_NORMALIZED raw=%s normalized=%s", raw_symbol, symbol)
            req = _replace_req(req, symbol=symbol)

        result = original(self, req, *args, **kwargs)
        if bool(getattr(result, "accepted", False)):
            return result
        if str(getattr(result, "reason", "") or "") != "NO_CONTRACT_RULE":
            return result

        schema = getattr(self, "schema", None)
        requested = _norm_broker(getattr(req, "broker", "") or getattr(result, "broker", ""))
        if schema is None or not symbol:
            return result

        _refresh_schema(schema, symbol, requested)
        rule = _resolve_rule(schema, symbol, requested)
        repaired = _norm_broker(getattr(rule, "broker", "")) if rule is not None else ""
        if not repaired or repaired == requested:
            logger.error("ECEL_ROUTE_REPAIR_UNRESOLVED symbol=%s requested_broker=%s", symbol, requested or "auto")
            return result
        if _is_usdt(symbol) and repaired == "kraken" and requested != "kraken":
            logger.critical(
                "ECEL_ROUTE_REPAIR_BLOCKED_USDT_TO_KRAKEN symbol=%s requested_broker=%s repaired_broker=%s",
                symbol,
                requested or "auto",
                repaired,
            )
            return result

        fixed_req = _replace_req(req, broker=repaired, symbol=symbol)
        retry = original(self, fixed_req, *args, **kwargs)
        if bool(getattr(retry, "accepted", False)):
            logger.critical("ECEL_CONTRACT_ROUTE_REPAIRED symbol=%s requested_broker=%s repaired_broker=%s", symbol, requested or "auto", repaired)
            print(f"[NIJA-PRINT] ECEL_CONTRACT_ROUTE_REPAIRED symbol={symbol} requested_broker={requested or 'auto'} repaired_broker={repaired}", flush=True)
        return retry

    setattr(compile_with_route_repair, "__nija_ecel_route_compile_patch__", True)
    setattr(cls, "compile", compile_with_route_repair)
    logger.warning("ECEL_CONTRACT_ROUTE_COMPILE_PATCHED class=%s", cls.__name__)
    print("[NIJA-PRINT] ECEL_CONTRACT_ROUTE_COMPILE_PATCHED", flush=True)
    return True


def _patch_execution_pipeline(module: Any) -> bool:
    cls = getattr(module, "ExecutionPipeline", None)
    result_cls = getattr(module, "PipelineResult", None)
    if not isinstance(cls, type):
        return False

    patched = False
    original_deny = getattr(cls, "_deny", None)
    if callable(original_deny) and not getattr(cls, _PATCHED_ATTR, False):
        @staticmethod
        @wraps(original_deny)
        def _deny(request: Any, t_start: float, reason: str):
            symbol = _norm_symbol(getattr(request, "symbol", "?") or "?")
            side = str(getattr(request, "side", "?") or "?")
            try:
                size = float(getattr(request, "size_usd", 0.0) or 0.0)
            except Exception:
                size = 0.0
            account_id = str(getattr(request, "account_id", "default") or "default")
            broker = str(getattr(request, "preferred_broker", "") or "")
            latency_ms = (time.monotonic() - float(t_start or time.monotonic())) * 1000.0
            logger.error(
                "EXECUTION_PIPELINE_DENY symbol=%s side=%s size_usd=%.2f account=%s broker=%s reason=%s latency_ms=%.1f",
                symbol,
                side,
                size,
                account_id,
                broker or "auto",
                reason,
                latency_ms,
            )
            try:
                from bot.execution_journal import append_execution_journal_event
                append_execution_journal_event(
                    "EXECUTION_PIPELINE_DENY",
                    f"{account_id}:{broker or 'auto'}:{symbol}:{side}:{int(time.time() * 1000)}",
                    {
                        "symbol": symbol,
                        "side": side,
                        "size_usd": size,
                        "account_id": account_id,
                        "broker": broker or "auto",
                        "reason": str(reason),
                        "latency_ms": latency_ms,
                    },
                )
            except Exception as exc:
                logger.debug("execution deny journal append skipped: %s", exc)
            if result_cls is not None:
                try:
                    return result_cls(success=False, symbol=symbol, side=side, size_usd=size, error=str(reason), latency_ms=latency_ms)
                except Exception:
                    pass
            return original_deny(request, t_start, reason)

        setattr(cls, "_deny", _deny)
        setattr(cls, _PATCHED_ATTR, True)
        logger.warning("EXECUTION_PIPELINE_DENY_TELEMETRY_PATCHED")
        patched = True

    original_load_ecel = getattr(cls, "_load_ecel", None)
    if callable(original_load_ecel) and not getattr(original_load_ecel, "__nija_route_load_patch__", False):
        @wraps(original_load_ecel)
        def _load_ecel(self: Any, *args: Any, **kwargs: Any):
            ecel = original_load_ecel(self, *args, **kwargs)
            _patch_ecel_compiler(ecel)
            return ecel

        setattr(_load_ecel, "__nija_route_load_patch__", True)
        setattr(cls, "_load_ecel", _load_ecel)
        patched = True

    original_dispatch = getattr(cls, "_dispatch", None)
    if callable(original_dispatch) and not getattr(cls, _ROUTE_PATCHED_ATTR, False):
        @wraps(original_dispatch)
        def _dispatch(self: Any, request: Any, t_start: float, *args: Any, **kwargs: Any):
            try:
                schema = getattr(getattr(self, "_ecel", None), "schema", None)
                raw_symbol = str(getattr(request, "symbol", "") or "")
                symbol = _norm_symbol(raw_symbol)
                current = _norm_broker(getattr(request, "preferred_broker", ""))
                if symbol and symbol != raw_symbol:
                    logger.warning("ECEL_PRE_DISPATCH_SYMBOL_NORMALIZED raw=%s normalized=%s", raw_symbol, symbol)
                    request = _replace_req(request, symbol=symbol)
                if schema is not None and symbol and _schema_rule(schema, current, symbol) is None:
                    rule = _resolve_rule(schema, symbol, current)
                    if rule is None:
                        _refresh_schema(schema, symbol, current)
                        rule = _resolve_rule(schema, symbol, current)
                    repaired = _norm_broker(getattr(rule, "broker", "")) if rule is not None else ""
                    if repaired and repaired != current:
                        if _is_usdt(symbol) and repaired == "kraken" and current != "kraken":
                            logger.critical(
                                "ECEL_PRE_DISPATCH_ROUTE_REPAIR_BLOCKED_USDT_TO_KRAKEN symbol=%s old_broker=%s repaired_broker=%s",
                                symbol,
                                current or "auto",
                                repaired,
                            )
                        else:
                            logger.critical("ECEL_PRE_DISPATCH_BROKER_ROUTE_REPAIRED symbol=%s old_broker=%s repaired_broker=%s", symbol, current or "auto", repaired)
                            print(f"[NIJA-PRINT] ECEL_PRE_DISPATCH_BROKER_ROUTE_REPAIRED symbol={symbol} old_broker={current or 'auto'} repaired_broker={repaired}", flush=True)
                            request = _replace_req(request, preferred_broker=repaired, symbol=symbol)
            except Exception as exc:
                logger.warning("ECEL_PRE_DISPATCH_BROKER_ROUTE_REPAIR_FAILED err=%s", exc)
            return original_dispatch(self, request, t_start, *args, **kwargs)

        setattr(cls, "_dispatch", _dispatch)
        setattr(cls, _ROUTE_PATCHED_ATTR, True)
        logger.warning("ECEL_PRE_DISPATCH_BROKER_ROUTE_PATCHED")
        patched = True

    return patched or bool(getattr(cls, _PATCHED_ATTR, False)) or bool(getattr(cls, _ROUTE_PATCHED_ATTR, False))


def install_import_hook() -> None:
    import sys

    for ecel_name in ("bot.ecel_execution_compiler", "ecel_execution_compiler"):
        ecel_module = sys.modules.get(ecel_name)
        if ecel_module is not None:
            try:
                instance_getter = getattr(ecel_module, "get_ecel_execution_compiler", None)
                if callable(instance_getter):
                    _patch_ecel_compiler(instance_getter())
            except Exception as exc:
                logger.warning("ECEL route compile patch failed: %s", exc)

    for name in ("bot.execution_pipeline", "execution_pipeline"):
        module = sys.modules.get(name)
        if module is not None and _patch_execution_pipeline(module):
            return

    if getattr(builtins, "_NIJA_EXECUTION_PIPELINE_PATCH_HOOK_INSTALLED", False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        if name.endswith("ecel_execution_compiler"):
            try:
                getter = getattr(module, "get_ecel_execution_compiler", None)
                if callable(getter):
                    _patch_ecel_compiler(getter())
            except Exception as exc:
                logger.warning("ECEL route compile patch failed: %s", exc)
        if name.endswith("execution_pipeline"):
            try:
                _patch_execution_pipeline(module)
            except Exception as exc:
                logger.warning("execution pipeline runtime patch failed: %s", exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_EXECUTION_PIPELINE_PATCH_HOOK_INSTALLED", True)
