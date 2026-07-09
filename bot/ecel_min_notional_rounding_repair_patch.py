from __future__ import annotations

import builtins
import dataclasses
import logging
import os
import sys
import threading
import time
from decimal import Decimal, ROUND_UP
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.ecel_min_notional_rounding_repair")
_MARKER = "20260709c"
_WRAP_ATTR = "_nija_ecel_min_notional_rounding_repair_v20260709c"
_INSTALL_LOCK = threading.Lock()
_MONITOR_STARTED = False
_PATCHED_MODULES: set[str] = set()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _buffered_notional(rule: Any, requested: float) -> float:
    min_notional = Decimal(str(max(_f(getattr(rule, "min_notional_usd", 0.0), 0.0), 0.0)))
    current = Decimal(str(max(requested, 0.0)))
    if min_notional <= 0:
        return float(current)
    buffer_pct = Decimal(str(max(_f(os.environ.get("ECEL_MIN_NOTIONAL_BUFFER_PCT"), 0.012), 0.0)))
    fixed_buffer = Decimal(str(max(_f(os.environ.get("ECEL_MIN_NOTIONAL_BUFFER_USD"), 0.05), 0.0)))
    target = max(current, min_notional * (Decimal("1") + buffer_pct), min_notional + fixed_buffer)
    return float(target.quantize(Decimal("0.00000001"), rounding=ROUND_UP))


def _clone_request(req: Any, desired_notional_usd: float) -> Any:
    if dataclasses.is_dataclass(req):
        return dataclasses.replace(req, desired_notional_usd=desired_notional_usd)
    try:
        data = dict(getattr(req, "__dict__", {}) or {})
        data["desired_notional_usd"] = desired_notional_usd
        return req.__class__(**data)
    except Exception:
        setattr(req, "desired_notional_usd", desired_notional_usd)
        return req


def _result_accepted(result: Any) -> bool:
    return bool(getattr(result, "accepted", False) or getattr(result, "status", "") in {"accepted", "ACCEPTED"})


def _result_reason(result: Any) -> str:
    return str(getattr(result, "reason", "") or getattr(result, "error", "") or "")


def _patch_ecel_module(module: ModuleType) -> bool:
    cls = getattr(module, "ECELExecutionCompiler", None)
    compile_request = getattr(module, "CompileRequest", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "compile", None)
    if not callable(original) or getattr(original, _WRAP_ATTR, False):
        return False

    def _patched_compile(self: Any, req: Any, *args: Any, **kwargs: Any) -> Any:
        result = original(self, req, *args, **kwargs)
        broker = str(getattr(req, "broker", "") or "").strip().lower()
        reason = _result_reason(result).upper()
        if _result_accepted(result) or "BELOW_MIN_NOTIONAL" not in reason:
            return result
        if broker not in {"okx", "coinbase", "kraken"}:
            return result
        symbol = str(getattr(req, "symbol", "") or getattr(result, "symbol", "") or "")
        rule = getattr(result, "rule", None)
        if rule is None:
            try:
                normalized = self._normalize_symbol(symbol, broker)
                rule = self.schema.get_rule(broker, normalized)
            except Exception:
                rule = None
        if rule is None:
            return result
        requested = _f(getattr(req, "desired_notional_usd", 0.0), 0.0)
        retry_notional = _buffered_notional(rule, requested)
        if retry_notional <= requested:
            return result
        retry_req = _clone_request(req, retry_notional)
        retry_result = original(self, retry_req, *args, **kwargs)
        if _result_accepted(retry_result):
            logger.critical(
                "ECEL_MIN_NOTIONAL_ROUNDING_REPAIR_APPLIED marker=%s broker=%s symbol=%s requested=%.8f retry_notional=%.8f min_notional=%.8f reason=%s",
                _MARKER,
                broker,
                symbol,
                requested,
                retry_notional,
                _f(getattr(rule, "min_notional_usd", 0.0), 0.0),
                reason,
            )
            print(
                f"[NIJA-PRINT] ECEL_MIN_NOTIONAL_ROUNDING_REPAIR_APPLIED marker={_MARKER} broker={broker} symbol={symbol} requested={requested:.8f} retry_notional={retry_notional:.8f}",
                flush=True,
            )
            return retry_result
        logger.warning(
            "ECEL_MIN_NOTIONAL_ROUNDING_REPAIR_RETRY_REJECTED marker=%s broker=%s symbol=%s requested=%.8f retry_notional=%.8f retry_reason=%s",
            _MARKER,
            broker,
            symbol,
            requested,
            retry_notional,
            _result_reason(retry_result),
        )
        return retry_result

    setattr(_patched_compile, _WRAP_ATTR, True)
    setattr(_patched_compile, "__wrapped__", original)
    setattr(cls, "compile", _patched_compile)
    _PATCHED_MODULES.add(str(getattr(module, "__name__", "<unknown>")))
    logger.warning("ECEL_MIN_NOTIONAL_ROUNDING_REPAIR_PATCHED marker=%s module=%s", _MARKER, getattr(module, "__name__", "<unknown>"))
    return True


def _interesting(name: str) -> bool:
    lowered = str(name or "").lower()
    return lowered in {"bot.ecel_execution_compiler", "ecel_execution_compiler"} or "ecel_execution_compiler" in lowered


def _try_patch_loaded() -> bool:
    patched = False
    try:
        modules = list(sys.modules.items())
    except RuntimeError:
        modules = list(dict(sys.modules).items())
    for name, module in modules:
        if isinstance(module, ModuleType) and _interesting(name):
            try:
                patched = _patch_ecel_module(module) or patched
            except Exception as exc:
                logger.warning("ECEL_MIN_NOTIONAL_ROUNDING_REPAIR_PATCH_FAILED marker=%s module=%s err=%s", _MARKER, name, exc)
    return patched


def _start_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + float(os.environ.get("NIJA_PATCH_MONITOR_SECONDS", "300") or "300")
        while time.time() < deadline:
            if _try_patch_loaded():
                return
            time.sleep(0.25)
        logger.warning("ECEL_MIN_NOTIONAL_ROUNDING_REPAIR_MONITOR_EXPIRED marker=%s patched_modules=%s", _MARKER, sorted(_PATCHED_MODULES))

    threading.Thread(target=_monitor, name="ecel-min-notional-rounding-repair", daemon=True).start()
    logger.warning("ECEL_MIN_NOTIONAL_ROUNDING_REPAIR_MONITOR_STARTED marker=%s", _MARKER)


def install_import_hook() -> None:
    with _INSTALL_LOCK:
        _try_patch_loaded()
        _start_monitor()
        if getattr(builtins, "_NIJA_ECEL_MIN_NOTIONAL_ROUNDING_REPAIR_V20260709C", False):
            logger.warning("ECEL_MIN_NOTIONAL_ROUNDING_REPAIR_INSTALL_COMPLETE marker=%s already_installed=True patched_modules=%s", _MARKER, sorted(_PATCHED_MODULES))
            return
        original_import = builtins.__import__

        def guarded_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
            module = original_import(name, globals, locals, fromlist, level)
            if _interesting(name):
                _try_patch_loaded()
            return module

        builtins.__import__ = guarded_import
        setattr(builtins, "_NIJA_ECEL_MIN_NOTIONAL_ROUNDING_REPAIR_V20260709C", True)
        logger.warning("ECEL_MIN_NOTIONAL_ROUNDING_REPAIR_INSTALL_COMPLETE marker=%s patched_modules=%s", _MARKER, sorted(_PATCHED_MODULES))


def install() -> None:
    install_import_hook()
