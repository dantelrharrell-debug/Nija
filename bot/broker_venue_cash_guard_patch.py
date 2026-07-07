"""Broker venue cash guard for live order dispatch.

This patch prevents aggregate platform capital from authorizing an order that the
selected broker venue cannot actually fund.  The live incident pattern was:
CapitalAuthority saw ~$285-$292, but Coinbase Advanced Trade venue cash saw
~$1.63, while a $15 order still reached the router and was marked filled.

Safety rule:
- use the selected broker's real spendable USD/USDC cash as the final buy-side
  dispatch cap;
- clamp only when the clamped size is still above the selected broker's minimum;
- otherwise block before broker dispatch so no insufficient-funds order can be
  submitted or recorded as a fill.
"""

from __future__ import annotations

import builtins
import logging
import os
import time
from dataclasses import replace
from functools import wraps
from typing import Any, Optional

logger = logging.getLogger("nija.broker_venue_cash_guard")

_PATCHED_ENGINE_ATTR = "__nija_broker_venue_cash_engine_guard__"
_PATCHED_PIPELINE_ATTR = "__nija_broker_venue_cash_pipeline_guard__"
_FEE_BUFFER_ENV = "NIJA_BROKER_VENUE_CASH_FEE_BUFFER_PCT"
_DEFAULT_FEE_BUFFER = 0.02


def _float(value: Any, default: float = 0.0) -> float:
    try:
        amount = float(value)
        if amount != amount or amount < 0:
            return default
        return amount
    except Exception:
        return default


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _fee_buffer_pct() -> float:
    value = _float(os.environ.get(_FEE_BUFFER_ENV), _DEFAULT_FEE_BUFFER)
    # Never allow a negative buffer; cap at 20% so a bad env cannot zero out trading.
    return max(0.0, min(value, 0.20))


def _norm_broker(value: Any) -> str:
    text = str(value or "").strip().lower()
    if ":" in text:
        text = text.split(":", 1)[0]
    return text


def _broker_label(broker_client: Any = None, preferred: Any = None) -> str:
    preferred_text = _norm_broker(preferred)
    if preferred_text:
        return preferred_text
    if broker_client is None:
        return ""
    try:
        btype = getattr(broker_client, "broker_type", None)
        value = getattr(btype, "value", None)
        if value:
            return _norm_broker(value)
        if isinstance(btype, str) and btype.strip():
            return _norm_broker(btype)
    except Exception:
        pass
    for attr in ("NAME", "name", "exchange", "venue"):
        try:
            text = str(getattr(broker_client, attr, "") or "").strip().lower()
            if text:
                for broker in ("coinbase", "kraken", "okx", "binance", "alpaca"):
                    if broker in text:
                        return broker
                return text
        except Exception:
            pass
    return type(broker_client).__name__.replace("Broker", "").strip().lower() or "unknown"


def _extract_cash_from_mapping(payload: Any) -> Optional[float]:
    if not isinstance(payload, dict):
        return None

    # Prefer explicit spendable/trading cash keys over account equity keys.
    for key in (
        "available_usd",
        "usd_available",
        "available_cash_usd",
        "trading_balance_usd",
        "cash_usd",
        "buying_power_usd",
        "available",
        "free",
        "cash",
    ):
        if key in payload:
            amount = _float(payload.get(key), -1.0)
            if amount >= 0:
                return amount

    total = 0.0
    found_quote_cash = False
    for quote in ("USD", "USDC"):
        for key in (quote, quote.lower()):
            if key not in payload:
                continue
            entry = payload.get(key)
            if isinstance(entry, dict):
                for subkey in ("available", "free", "cash", "balance", "amount"):
                    if subkey in entry:
                        total += _float(entry.get(subkey), 0.0)
                        found_quote_cash = True
                        break
            else:
                total += _float(entry, 0.0)
                found_quote_cash = True
    if found_quote_cash:
        return total

    accounts = payload.get("accounts") or payload.get("balances") or payload.get("data")
    if isinstance(accounts, list):
        total = 0.0
        found = False
        for item in accounts:
            if not isinstance(item, dict):
                continue
            currency = str(item.get("currency") or item.get("asset") or item.get("symbol") or "").upper()
            if currency not in {"USD", "USDC"}:
                continue
            for subkey in ("available_balance", "available", "free", "cash", "balance", "amount"):
                raw = item.get(subkey)
                if isinstance(raw, dict):
                    raw = raw.get("value") or raw.get("amount")
                amount = _float(raw, -1.0)
                if amount >= 0:
                    total += amount
                    found = True
                    break
        if found:
            return total

    return None


def _call_zero_arg(obj: Any, name: str) -> Any:
    fn = getattr(obj, name, None)
    if not callable(fn):
        return None
    try:
        return fn()
    except TypeError:
        return None
    except Exception as exc:
        logger.debug("venue cash probe %s failed: %s", name, exc)
        return None


def _resolve_broker_spendable_cash(broker_client: Any) -> Optional[float]:
    if broker_client is None:
        return None

    # Cached balance details are often the exact source logged by the broker layer.
    for attr in (
        "_advanced_trade_available_cash_usd",
        "_venue_available_cash_usd",
        "_spot_available_cash_usd",
        "_available_cash_usd",
        "_last_known_cash_usd",
        "_last_known_available_cash_usd",
    ):
        if hasattr(broker_client, attr):
            amount = _float(getattr(broker_client, attr), -1.0)
            if amount >= 0:
                return amount

    for attr in ("_balance_cache", "_last_balance_snapshot", "_last_account_inventory"):
        try:
            amount = _extract_cash_from_mapping(getattr(broker_client, attr, None))
            if amount is not None:
                return amount
        except Exception:
            pass

    for method in (
        "get_spot_trading_cash",
        "get_available_cash_usd",
        "get_available_usd",
        "get_usd_available",
        "get_cash_balance",
        "get_available_balance",
        "get_account_balance",
        "get_balance",
        "fetch_balance",
    ):
        payload = _call_zero_arg(broker_client, method)
        if payload is None:
            continue
        if isinstance(payload, (int, float, str)):
            amount = _float(payload, -1.0)
            if amount >= 0:
                return amount
        amount = _extract_cash_from_mapping(payload)
        if amount is not None:
            return amount

    return None


def _min_order_usd(broker: str) -> float:
    broker = _norm_broker(broker)
    env_by_broker = {
        "coinbase": ("COINBASE_MIN_ORDER_USD", "NIJA_COINBASE_MIN_ORDER_USD", "MIN_TRADE_USD"),
        "kraken": ("KRAKEN_MIN_NOTIONAL_USD", "NIJA_KRAKEN_FINAL_MIN_NOTIONAL_USD", "MIN_TRADE_USD"),
        "okx": ("OKX_MIN_ORDER_USD", "NIJA_OKX_MIN_ORDER_USD", "MIN_TRADE_USD"),
    }
    for key in env_by_broker.get(broker, ("MIN_TRADE_USD",)):
        if key in os.environ:
            value = _float(os.environ.get(key), 0.0)
            if value > 0:
                return value
    return 1.0 if broker == "coinbase" else 10.0


def _build_result(result_cls: Any, request: Any, t_start: float, reason: str, broker: str = "") -> Any:
    latency_ms = (time.monotonic() - float(t_start or time.monotonic())) * 1000.0
    symbol = str(getattr(request, "symbol", "") or "")
    side = str(getattr(request, "side", "") or "")
    size = _float(getattr(request, "size_usd", 0.0), 0.0)
    if result_cls is not None:
        try:
            return result_cls(
                success=False,
                symbol=symbol,
                side=side,
                size_usd=size,
                broker=broker,
                error=reason,
                latency_ms=latency_ms,
            )
        except Exception:
            pass
    return {"success": False, "symbol": symbol, "side": side, "size_usd": size, "broker": broker, "error": reason}


def _replace_request(request: Any, **changes: Any) -> Any:
    try:
        return replace(request, **changes)
    except Exception:
        for key, value in changes.items():
            try:
                setattr(request, key, value)
            except Exception:
                pass
        return request


def _guard_size_for_cash(*, request: Any, broker_client: Any, broker: str, result_cls: Any = None, t_start: float = 0.0) -> tuple[bool, Any, Optional[Any]]:
    if not _truthy("NIJA_BROKER_VENUE_CASH_GUARD", "true"):
        return True, request, None

    side = str(getattr(request, "side", "") or "").strip().lower()
    if side in {"sell", "short"} or bool(getattr(request, "reduce_only", False)):
        return True, request, None

    cash = _resolve_broker_spendable_cash(broker_client)
    if cash is None:
        # Unknown cash should not create a false block. Native broker preflight still applies.
        logger.warning(
            "BROKER_VENUE_CASH_GUARD_SKIPPED reason=cash_unresolved broker=%s symbol=%s size_usd=%.2f",
            broker or "unknown",
            getattr(request, "symbol", "?"),
            _float(getattr(request, "size_usd", 0.0), 0.0),
        )
        return True, request, None

    requested = _float(getattr(request, "size_usd", 0.0), 0.0)
    buffer_pct = _fee_buffer_pct()
    max_affordable = cash / (1.0 + buffer_pct) if buffer_pct >= 0 else cash
    min_order = _min_order_usd(broker)

    if requested <= max_affordable:
        return True, request, None

    reason = (
        f"BrokerVenueCashGuard reject: broker={broker or 'unknown'} "
        f"available_cash=${cash:.2f} requested=${requested:.2f} "
        f"max_affordable=${max_affordable:.2f} min_order=${min_order:.2f} "
        f"fee_buffer={buffer_pct:.2%}"
    )

    if max_affordable >= min_order and _truthy("NIJA_BROKER_VENUE_CASH_GUARD_CLAMP", "true"):
        clamped = round(max_affordable, 2)
        logger.critical(
            "BROKER_VENUE_CASH_GUARD_CLAMPED broker=%s symbol=%s requested=%.2f clamped=%.2f available_cash=%.2f min_order=%.2f fee_buffer_pct=%.4f",
            broker or "unknown",
            getattr(request, "symbol", "?"),
            requested,
            clamped,
            cash,
            min_order,
            buffer_pct,
        )
        print(
            f"[NIJA-PRINT] BROKER_VENUE_CASH_GUARD_CLAMPED broker={broker or 'unknown'} "
            f"symbol={getattr(request, 'symbol', '?')} requested=${requested:.2f} clamped=${clamped:.2f} cash=${cash:.2f}",
            flush=True,
        )
        return True, _replace_request(request, size_usd=clamped, notional_usd=clamped, available_balance_usd=cash), None

    logger.critical("BROKER_VENUE_CASH_GUARD_BLOCKED %s", reason)
    print(
        f"[NIJA-PRINT] BROKER_VENUE_CASH_GUARD_BLOCKED broker={broker or 'unknown'} "
        f"symbol={getattr(request, 'symbol', '?')} requested=${requested:.2f} cash=${cash:.2f} max=${max_affordable:.2f}",
        flush=True,
    )
    return False, request, _build_result(result_cls, request, t_start, reason, broker=broker)


def _patch_execution_engine(module: Any) -> bool:
    cls = getattr(module, "ExecutionEngine", None)
    if not isinstance(cls, type) or getattr(cls, _PATCHED_ENGINE_ATTR, False):
        return False
    original = getattr(cls, "_submit_market_order_via_pipeline", None)
    if not callable(original):
        return False

    @wraps(original)
    def guarded_submit(self: Any, broker_client: Any, symbol: str, side: str, size_usd: float, *args: Any, **kwargs: Any):
        broker = _broker_label(broker_client, kwargs.get("preferred_broker"))
        pseudo_request = type("VenueCashRequest", (), {})()
        pseudo_request.symbol = symbol
        pseudo_request.side = side
        pseudo_request.size_usd = _float(size_usd, 0.0)
        pseudo_request.notional_usd = pseudo_request.size_usd
        pseudo_request.available_balance_usd = kwargs.get("available_balance_usd")
        allowed, guarded_request, result = _guard_size_for_cash(
            request=pseudo_request,
            broker_client=broker_client,
            broker=broker,
            result_cls=None,
            t_start=time.monotonic(),
        )
        if not allowed:
            return {
                "status": "error",
                "error": result.get("error") if isinstance(result, dict) else str(getattr(result, "error", result)),
                "symbol": symbol,
                "side": side,
                "broker": broker,
            }
        size_usd = _float(getattr(guarded_request, "size_usd", size_usd), size_usd)
        kwargs["available_balance_usd"] = _resolve_broker_spendable_cash(broker_client) or kwargs.get("available_balance_usd")
        return original(self, broker_client, symbol, side, size_usd, *args, **kwargs)

    setattr(cls, "_submit_market_order_via_pipeline", guarded_submit)
    setattr(cls, _PATCHED_ENGINE_ATTR, True)
    logger.warning("BROKER_VENUE_CASH_ENGINE_GUARD_PATCHED class=%s", cls.__name__)
    return True


def _patch_execution_pipeline(module: Any) -> bool:
    cls = getattr(module, "ExecutionPipeline", None)
    result_cls = getattr(module, "PipelineResult", None)
    if not isinstance(cls, type) or getattr(cls, _PATCHED_PIPELINE_ATTR, False):
        return False
    original = getattr(cls, "_dispatch", None)
    if not callable(original):
        return False

    @wraps(original)
    def guarded_dispatch(self: Any, request: Any, t_start: float, *args: Any, **kwargs: Any):
        metadata = dict(getattr(request, "metadata", {}) or {})
        broker_client = metadata.get("broker_client")
        broker = _broker_label(broker_client, getattr(request, "preferred_broker", None) or metadata.get("broker_name"))
        allowed, guarded_request, result = _guard_size_for_cash(
            request=request,
            broker_client=broker_client,
            broker=broker,
            result_cls=result_cls,
            t_start=t_start,
        )
        if not allowed:
            return result
        return original(self, guarded_request, t_start, *args, **kwargs)

    setattr(cls, "_dispatch", guarded_dispatch)
    setattr(cls, _PATCHED_PIPELINE_ATTR, True)
    logger.warning("BROKER_VENUE_CASH_PIPELINE_GUARD_PATCHED class=%s", cls.__name__)
    return True


def install_import_hook() -> None:
    import sys

    for name in ("bot.execution_engine", "execution_engine"):
        module = sys.modules.get(name)
        if module is not None:
            try:
                _patch_execution_engine(module)
            except Exception as exc:
                logger.warning("broker venue cash engine guard install failed: %s", exc)

    for name in ("bot.execution_pipeline", "execution_pipeline"):
        module = sys.modules.get(name)
        if module is not None:
            try:
                _patch_execution_pipeline(module)
            except Exception as exc:
                logger.warning("broker venue cash pipeline guard install failed: %s", exc)

    if getattr(builtins, "_NIJA_BROKER_VENUE_CASH_GUARD_IMPORT_HOOK", False):
        return

    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        target = name.rsplit(".", 1)[-1]
        try:
            if target == "execution_engine" or name.endswith("execution_engine"):
                _patch_execution_engine(module)
            if target == "execution_pipeline" or name.endswith("execution_pipeline"):
                _patch_execution_pipeline(module)
        except Exception as exc:
            logger.warning("broker venue cash guard import patch failed module=%s err=%s", name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_BROKER_VENUE_CASH_GUARD_IMPORT_HOOK", True)
    logger.warning("BROKER_VENUE_CASH_GUARD_IMPORT_HOOK_INSTALLED")
