from __future__ import annotations

import builtins
import logging
import os
import sys
from types import ModuleType
from typing import Any, Dict, Tuple

logger = logging.getLogger("nija.direct_broker_venue_cash_hard_gate")
_PATCHED_ATTR = "_nija_direct_broker_venue_cash_hard_gate_20260708a"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_PSEUDO_ORDER_IDS = {"", "pipeline", "coinbase", "kraken", "okx", "simulated", "paper", "mock", "stub"}


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.getenv(name, default)).strip().lower() in _TRUE


def _broker_label(broker: Any, fallback: str = "") -> str:
    btype = getattr(broker, "broker_type", None)
    value = str(getattr(btype, "value", btype) or "").strip().lower()
    if value:
        return value
    name = str(getattr(broker, "NAME", "") or "").strip().lower()
    if name:
        return name.replace("broker", "").strip("_-")
    return fallback.strip().lower()


def _extract_available_balance(broker: Any) -> float:
    get_balance = getattr(broker, "get_account_balance", None)
    if not callable(get_balance):
        return 0.0
    raw = get_balance()
    if isinstance(raw, dict):
        for key in ("available_balance", "trading_balance", "available", "free", "total_balance"):
            try:
                value = raw.get(key)
                if value is not None:
                    return float(value or 0.0)
            except Exception:
                continue
        return 0.0
    try:
        return float(raw or 0.0)
    except Exception:
        return 0.0


def _required_cash(size_usd: float, broker_name: str) -> float:
    buffer_key = f"NIJA_{broker_name.upper()}_VENUE_CASH_FEE_BUFFER_PCT"
    buffer_pct = os.getenv(buffer_key, os.getenv("NIJA_BROKER_VENUE_CASH_FEE_BUFFER_PCT", "0.02"))
    try:
        pct = max(0.0, float(buffer_pct or 0.02))
    except Exception:
        pct = 0.02
    return float(size_usd or 0.0) * (1.0 + pct)


def _venue_cash_ok(broker: Any, broker_name: str, size_usd: float, side: str, surface: str, symbol: str = "") -> tuple[bool, float, float, str]:
    if not _truthy("NIJA_DIRECT_BROKER_VENUE_CASH_HARD_GATE", "true"):
        return True, 0.0, 0.0, "disabled"
    if str(side or "").strip().lower() not in {"buy", "long"}:
        return True, 0.0, 0.0, "sell_or_exit"
    label = _broker_label(broker, broker_name)
    available = _extract_available_balance(broker)
    required = _required_cash(size_usd, label or broker_name)
    ok = available + 1e-9 >= required
    if not ok:
        logger.critical(
            "DIRECT_BROKER_VENUE_CASH_HARD_BLOCK marker=20260708a surface=%s broker=%s symbol=%s available=$%.2f required=$%.2f size=$%.2f action=block_false_fill",
            surface,
            label or broker_name,
            symbol,
            available,
            required,
            float(size_usd or 0.0),
        )
    return ok, available, required, label or broker_name


def _looks_confirmed_fill(result: Dict[str, Any]) -> tuple[bool, str]:
    status = str(result.get("status") or result.get("state") or "").strip().lower()
    if status in {"error", "failed", "rejected", "canceled", "cancelled", "unfilled"}:
        return False, f"terminal_reject_status:{status or 'unknown'}"
    order_id = str(result.get("order_id") or result.get("id") or result.get("exchange_order_id") or "").strip().lower()
    if status not in {"filled", "closed", "complete", "completed", "done"}:
        return False, f"unconfirmed_status:{status or 'missing'}"
    if order_id in _PSEUDO_ORDER_IDS:
        return False, f"pseudo_order_id:{order_id or 'missing'}"
    return True, "confirmed_fill"


def _patch_module(module: ModuleType) -> bool:
    cls = getattr(module, "MultiBrokerExecutionRouter", None)
    if not isinstance(cls, type):
        return False
    if getattr(cls, _PATCHED_ATTR, False):
        return True

    original_profile = getattr(cls, "_profile_for_direct_broker", None)
    original_dispatch = getattr(cls, "_dispatch_direct_broker_market_order", None)
    if not callable(original_profile) or not callable(original_dispatch):
        return False

    def _profile_for_direct_broker_guarded(self: Any, asset_class: Any, request: Any):
        profile = original_profile(self, asset_class, request)
        if profile is None:
            return None
        if not _truthy("NIJA_DIRECT_BROKER_PROFILE_CASH_GATE", "true"):
            return profile
        meta = dict(getattr(request, "metadata", {}) or {})
        broker_obj = meta.get("broker_client")
        if broker_obj is None:
            return profile
        ok, available, required, label = _venue_cash_ok(
            broker_obj,
            getattr(profile, "name", ""),
            float(getattr(request, "size_usd", 0.0) or 0.0),
            str(getattr(request, "side", "")),
            "profile_for_direct_broker",
            str(getattr(request, "symbol", "")),
        )
        if ok:
            return profile
        logger.critical(
            "DIRECT_BROKER_PROFILE_CASH_REJECTED marker=20260708a broker=%s available=$%.2f required=$%.2f symbol=%s fallback=scored_selection",
            label,
            available,
            required,
            getattr(request, "symbol", ""),
        )
        return None

    def _dispatch_direct_broker_market_order_guarded(broker: Any, *, symbol: str, side: str, size_usd: float, metadata: Dict[str, Any]) -> Tuple[float, float]:
        label = _broker_label(broker, str(metadata.get("broker_name") or metadata.get("preferred_broker") or ""))
        ok, available, required, label = _venue_cash_ok(broker, label, float(size_usd or 0.0), side, "direct_dispatch", symbol)
        if not ok:
            raise RuntimeError(f"venue_cash_insufficient:{label}:available=${available:.2f}<required=${required:.2f}")

        result = None
        submit = getattr(broker, "place_market_order", None)
        if not callable(submit):
            submit = getattr(broker, "execute_order", None)
        if not callable(submit):
            submit = getattr(broker, "place_order", None)
        if not callable(submit):
            raise RuntimeError(f"Broker {broker!r} has no market-order submit method")
        try:
            result = submit(symbol, side, float(size_usd), size_type="quote")
        except TypeError:
            try:
                result = submit(symbol=symbol, side=side, quantity=float(size_usd), size_type="quote")
            except TypeError:
                result = submit(symbol, side, float(size_usd))

        if isinstance(result, tuple) and len(result) >= 2:
            price = float(result[0] or 0.0)
            filled = float(result[1] or 0.0)
            if price <= 0 or filled <= 0:
                raise RuntimeError(f"unconfirmed_tuple_fill:{result!r}")
            return price, filled
        if not isinstance(result, dict):
            raise RuntimeError(f"Unsupported broker order response: {result!r}")

        confirmed, reason = _looks_confirmed_fill(result)
        if not confirmed:
            raise RuntimeError(reason)

        fill_price = float(
            result.get("filled_price")
            or result.get("average_filled_price")
            or result.get("average_fill_price")
            or result.get("avg_price")
            or result.get("price")
            or 0.0
        )
        filled_usd = float(
            result.get("filled_size_usd")
            or result.get("filled_value")
            or result.get("notional_usd")
            or result.get("size_usd")
            or 0.0
        )
        if fill_price <= 0 or filled_usd <= 0:
            raise RuntimeError(f"confirmed_status_without_fill_amounts:{result!r}")
        logger.critical(
            "DIRECT_BROKER_CONFIRMED_FILL marker=20260708a broker=%s symbol=%s side=%s filled_usd=$%.2f price=%.8f",
            label,
            symbol,
            side,
            filled_usd,
            fill_price,
        )
        return fill_price, filled_usd

    setattr(cls, "_profile_for_direct_broker", _profile_for_direct_broker_guarded)
    setattr(cls, "_dispatch_direct_broker_market_order", staticmethod(_dispatch_direct_broker_market_order_guarded))
    setattr(cls, _PATCHED_ATTR, True)
    logger.warning("DIRECT_BROKER_VENUE_CASH_HARD_GATE_PATCHED marker=20260708a module=%s", getattr(module, "__name__", "unknown"))
    return True


def _patch_loaded() -> None:
    for name in ("bot.multi_broker_execution_router", "multi_broker_execution_router"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                _patch_module(module)
            except Exception as exc:
                logger.warning("DIRECT_BROKER_VENUE_CASH_HARD_GATE_PATCH_FAILED marker=20260708a module=%s err=%s", name, exc)


def install_import_hook() -> None:
    _patch_loaded()
    if getattr(builtins, "_NIJA_DIRECT_BROKER_VENUE_CASH_HARD_GATE_HOOK_20260708A", False):
        return
    original_import = builtins.__import__

    def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        if name in {"bot.multi_broker_execution_router", "multi_broker_execution_router"} or str(name).endswith("multi_broker_execution_router"):
            _patch_loaded()
        return module

    builtins.__import__ = importing
    setattr(builtins, "_NIJA_DIRECT_BROKER_VENUE_CASH_HARD_GATE_HOOK_20260708A", True)
    logger.warning("DIRECT_BROKER_VENUE_CASH_HARD_GATE_INSTALL_COMPLETE marker=20260708a")


def install() -> None:
    install_import_hook()
