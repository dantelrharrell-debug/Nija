from __future__ import annotations

import builtins
import logging
import os
import sys
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.execution_minimum_position_micro_broker_repair")
_MARKER = "20260709aa"
_PATCHED_GATE_ATTR = "_nija_micro_broker_minimum_repair_20260709aa"
_PATCHED_HARDENING_ATTR = "_nija_micro_broker_hardening_repair_20260709aa"
_TRUTHY = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUTHY


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        amount = float(value)
        if amount != amount:
            return default
        return amount
    except Exception:
        return default


def _micro_broker_balance_threshold() -> float:
    return max(0.0, _f(os.environ.get("NIJA_MICRO_BROKER_BALANCE_THRESHOLD_USD"), 250.0))


def _micro_broker_floor() -> float:
    # Keep this aligned with true exchange/broker floors. This is not a risk bypass;
    # it only prevents the platform-level tier from raising a broker-level $10 order
    # to the INVESTOR $20 floor when the actual routed broker is still in SAVER-size
    # spendable capital.
    values = [
        os.environ.get("NIJA_MICRO_BROKER_MIN_POSITION_USD"),
        os.environ.get("OKX_MIN_ORDER_USD"),
        os.environ.get("COINBASE_MIN_ORDER_USD"),
        os.environ.get("COINBASE_MIN_ORDER"),
        os.environ.get("MIN_CASH_TO_BUY"),
        "10.0",
    ]
    floors = [_f(v, 0.0) for v in values]
    floors = [v for v in floors if v > 0]
    if not floors:
        return 10.0
    return max(10.0, min(floors))


def _broker_floor_for_symbol(symbol: str) -> float:
    symbol_s = str(symbol or "").upper()
    if symbol_s.endswith("-USDT") or symbol_s.endswith("/USDT"):
        return max(10.0, _f(os.environ.get("OKX_MIN_ORDER_USD"), 10.0))
    if symbol_s.endswith("-USD") or symbol_s.endswith("/USD") or symbol_s.endswith("-USDC") or symbol_s.endswith("/USDC"):
        return max(1.0, _f(os.environ.get("COINBASE_MIN_ORDER_USD"), _micro_broker_floor()))
    return _micro_broker_floor()


def _should_apply_micro_broker_repair(balance: float, tier_name: str, min_usd: float) -> bool:
    if not _truthy("NIJA_MICRO_BROKER_MIN_POSITION_REPAIR", "true"):
        return False
    balance_f = _f(balance, 0.0)
    if balance_f <= 0:
        return False
    if balance_f >= _micro_broker_balance_threshold():
        return False
    # This is the exact Railway failure: get_tier_from_balance was patched to
    # platform-level INVESTOR, but the broker balance argument remained $101.63.
    # The tier floor therefore became $20 while the micro routed order was $10.
    tier = str(tier_name or "").upper()
    return tier in {"INVESTOR", "INCOME", "LIVABLE", "BALLER"} and _f(min_usd, 0.0) > _micro_broker_floor()


def _patch_minimum_gate(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionMinimumPositionGate", None)
    if not isinstance(cls, type):
        return False
    original_get_min = getattr(cls, "get_minimum_position_size", None)
    original_validate = getattr(cls, "validate_position_size", None)
    if not callable(original_get_min) or not callable(original_validate):
        return False
    if getattr(cls, _PATCHED_GATE_ATTR, False):
        return True

    @wraps(original_get_min)
    def get_minimum_position_size_repaired(self: Any, balance: float):
        min_usd, min_pct, tier_name = original_get_min(self, balance)
        if _should_apply_micro_broker_repair(balance, tier_name, min_usd):
            repaired = min(_f(min_usd, 0.0), _micro_broker_floor())
            logger.warning(
                "EXECUTION_MICRO_BROKER_MINIMUM_REPAIRED marker=%s surface=get_minimum_position_size balance=$%.2f tier=%s old_min=$%.2f new_min=$%.2f reason=platform_tier_applied_to_micro_broker_balance",
                _MARKER,
                _f(balance, 0.0),
                tier_name,
                _f(min_usd, 0.0),
                repaired,
            )
            return repaired, min_pct, tier_name
        return min_usd, min_pct, tier_name

    @wraps(original_validate)
    def validate_position_size_repaired(self: Any, position_size_usd: float, balance: float, symbol: str = "UNKNOWN", user_id: Any = None):
        ok, reason, details = original_validate(self, position_size_usd, balance, symbol=symbol, user_id=user_id)
        if ok:
            return ok, reason, details
        min_usd = _f(details.get("min_size_usd") if isinstance(details, dict) else 0.0, 0.0)
        tier_name = str(details.get("tier") if isinstance(details, dict) else "")
        if _should_apply_micro_broker_repair(balance, tier_name, min_usd):
            repaired_floor = max(_micro_broker_floor(), _broker_floor_for_symbol(symbol))
            if _f(position_size_usd, 0.0) + 1e-9 >= repaired_floor:
                details = dict(details or {})
                details["original_min_size_usd"] = min_usd
                details["min_size_usd"] = repaired_floor
                details["micro_broker_minimum_repair"] = True
                details["repair_marker"] = _MARKER
                repaired_reason = (
                    f"Position size OK after micro-broker repair: ${_f(position_size_usd):.2f} "
                    f">= ${repaired_floor:.2f} broker floor ({tier_name} platform tier, broker balance ${_f(balance):.2f})"
                )
                logger.warning(
                    "EXECUTION_MICRO_BROKER_MINIMUM_ACCEPTED marker=%s symbol=%s balance=$%.2f tier=%s position=$%.2f old_min=$%.2f repaired_min=$%.2f",
                    _MARKER,
                    symbol,
                    _f(balance, 0.0),
                    tier_name,
                    _f(position_size_usd, 0.0),
                    min_usd,
                    repaired_floor,
                )
                return True, repaired_reason, details
        return ok, reason, details

    setattr(cls, "get_minimum_position_size", get_minimum_position_size_repaired)
    setattr(cls, "validate_position_size", validate_position_size_repaired)
    setattr(cls, _PATCHED_GATE_ATTR, True)
    logger.warning("EXECUTION_MICRO_BROKER_MINIMUM_GATE_PATCHED marker=%s module=%s", _MARKER, getattr(module, "__name__", "unknown"))
    print(f"[NIJA-PRINT] EXECUTION_MICRO_BROKER_MINIMUM_GATE_PATCHED marker={_MARKER}", flush=True)
    return True


def _patch_hardening(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionLayerHardening", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "validate_order_hardening", None)
    if not callable(original) or getattr(original, _PATCHED_HARDENING_ATTR, False):
        return bool(getattr(original, _PATCHED_HARDENING_ATTR, False))

    @wraps(original)
    def validate_order_hardening_repaired(self: Any, symbol: str, side: str, position_size_usd: float, balance: float, current_positions: list, user_id: Any = None, force_liquidate: bool = False):
        ok, reason, details = original(self, symbol, side, position_size_usd, balance, current_positions, user_id=user_id, force_liquidate=force_liquidate)
        if ok:
            return ok, reason, details
        # Preserve all terminal risk/position-cap/average/dust blocks. Only repair
        # the exact min-position mismatch caused by platform tier inflation over a
        # micro broker balance.
        checks = list((details or {}).get("checks_performed", [])) if isinstance(details, dict) else []
        failed_min = None
        for check in checks:
            if check.get("check") == "minimum_position_size" and not check.get("passed", True):
                failed_min = check
                break
        size_details = dict((failed_min or {}).get("details") or {})
        tier_name = str(size_details.get("tier") or "")
        min_usd = _f(size_details.get("min_size_usd"), 0.0)
        if failed_min and _should_apply_micro_broker_repair(balance, tier_name, min_usd):
            repaired_floor = max(_micro_broker_floor(), _broker_floor_for_symbol(symbol))
            if _f(position_size_usd, 0.0) + 1e-9 >= repaired_floor:
                repaired_details = dict(details or {})
                repaired_details["micro_broker_minimum_repair"] = True
                repaired_details["repair_marker"] = _MARKER
                repaired_details["original_error"] = reason
                success_msg = (
                    f"Minimum position accepted after micro-broker repair for {symbol}: "
                    f"${_f(position_size_usd):.2f} >= ${repaired_floor:.2f} broker floor"
                )
                logger.warning(
                    "EXECUTION_HARDENING_MICRO_BROKER_MINIMUM_ACCEPTED marker=%s symbol=%s broker=%s balance=$%.2f position=$%.2f old_min=$%.2f repaired_min=$%.2f",
                    _MARKER,
                    symbol,
                    getattr(self, "broker_type", "unknown"),
                    _f(balance, 0.0),
                    _f(position_size_usd, 0.0),
                    min_usd,
                    repaired_floor,
                )
                return True, success_msg, repaired_details
        return ok, reason, details

    setattr(validate_order_hardening_repaired, _PATCHED_HARDENING_ATTR, True)
    setattr(cls, "validate_order_hardening", validate_order_hardening_repaired)
    logger.warning("EXECUTION_MICRO_BROKER_HARDENING_PATCHED marker=%s module=%s", _MARKER, getattr(module, "__name__", "unknown"))
    print(f"[NIJA-PRINT] EXECUTION_MICRO_BROKER_HARDENING_PATCHED marker={_MARKER}", flush=True)
    return True


def _patch_loaded() -> None:
    for name in ("bot.execution_minimum_position_gate", "execution_minimum_position_gate"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                _patch_minimum_gate(module)
            except Exception as exc:
                logger.warning("EXECUTION_MICRO_BROKER_MINIMUM_GATE_PATCH_FAILED marker=%s module=%s err=%s", _MARKER, name, exc)
    for name in ("bot.execution_layer_hardening", "execution_layer_hardening"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                _patch_hardening(module)
            except Exception as exc:
                logger.warning("EXECUTION_MICRO_BROKER_HARDENING_PATCH_FAILED marker=%s module=%s err=%s", _MARKER, name, exc)


def install_import_hook() -> None:
    _patch_loaded()
    if getattr(builtins, "_NIJA_EXECUTION_MICRO_BROKER_MINIMUM_REPAIR_HOOK_20260709AA", False):
        return
    original_import = builtins.__import__

    def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        if str(name).endswith("execution_minimum_position_gate") or str(name).endswith("execution_layer_hardening"):
            _patch_loaded()
        return module

    builtins.__import__ = importing
    setattr(builtins, "_NIJA_EXECUTION_MICRO_BROKER_MINIMUM_REPAIR_HOOK_20260709AA", True)
    logger.warning("EXECUTION_MICRO_BROKER_MINIMUM_REPAIR_INSTALL_COMPLETE marker=%s", _MARKER)


def install() -> None:
    install_import_hook()
