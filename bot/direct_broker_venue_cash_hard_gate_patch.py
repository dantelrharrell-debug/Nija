from __future__ import annotations

import builtins
import logging
import os
import sys
from types import ModuleType
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("nija.direct_broker_venue_cash_hard_gate")
_PATCHED_ATTR = "_nija_direct_broker_venue_cash_hard_gate_20260709x"
_MARKER = "20260709x"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_PSEUDO_ORDER_IDS = {"", "pipeline", "coinbase", "kraken", "okx", "simulated", "paper", "mock", "stub"}


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.getenv(name, default)).strip().lower() in _TRUE


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


def _broker_label(broker: Any, fallback: str = "") -> str:
    btype = getattr(broker, "broker_type", None)
    value = str(getattr(btype, "value", btype) or "").strip().lower()
    if value:
        return value
    name = str(getattr(broker, "NAME", "") or "").strip().lower()
    if name:
        return name.replace("broker", "").strip("_-")
    text = str(type(broker).__name__ or "").lower()
    if "okx" in text:
        return "okx"
    if "coinbase" in text:
        return "coinbase"
    if "kraken" in text:
        return "kraken"
    return fallback.strip().lower()


def _norm_symbol(symbol: Any) -> str:
    text = str(symbol or "").strip().upper().replace("/", "-").replace("_", "-").replace(":", "-")
    while "--" in text:
        text = text.replace("--", "-")
    return text


def _quote_from_symbol(symbol: Any) -> str:
    symbol_s = _norm_symbol(symbol)
    if "-" not in symbol_s:
        return ""
    return symbol_s.rsplit("-", 1)[-1]


def _extract_quote_from_mapping(payload: Any, quote: str) -> Optional[float]:
    quote = str(quote or "").upper()
    if not quote or not isinstance(payload, dict):
        return None

    for key in (quote, quote.lower()):
        if key in payload:
            entry = payload.get(key)
            if isinstance(entry, dict):
                for subkey in ("availBal", "available", "available_balance", "free", "cash", "balance", "amount"):
                    if subkey in entry:
                        return _f(entry.get(subkey), 0.0)
            return _f(entry, 0.0)

    total = 0.0
    found = False
    for container_key in ("data", "details", "balances", "accounts", "assets", "result"):
        nested = payload.get(container_key)
        if isinstance(nested, dict):
            amount = _extract_quote_from_mapping(nested, quote)
            if amount is not None:
                total += amount
                found = True
        elif isinstance(nested, (list, tuple)):
            for item in nested:
                if not isinstance(item, dict):
                    continue
                currency = str(item.get("ccy") or item.get("currency") or item.get("asset") or item.get("symbol") or "").upper()
                if currency == quote:
                    for subkey in ("availBal", "available", "available_balance", "free", "cash", "balance", "amount"):
                        if subkey in item:
                            total += _f(item.get(subkey), 0.0)
                            found = True
                            break
                amount = _extract_quote_from_mapping(item, quote)
                if amount is not None and currency != quote:
                    total += amount
                    found = True
    if found:
        return total
    return None


def _call_method(obj: Any, method_name: str, *args: Any) -> Any:
    fn = getattr(obj, method_name, None)
    if not callable(fn):
        return None
    try:
        return fn(*args)
    except TypeError:
        try:
            return fn()
        except Exception:
            return None
    except Exception as exc:
        logger.debug("OKX quote-cash probe %s failed: %s", method_name, exc)
        return None


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


def _extract_spendable_quote_balance(broker: Any, quote: str) -> Optional[float]:
    quote = str(quote or "").upper()
    if broker is None or not quote:
        return None

    attr_names = (
        f"_available_{quote.lower()}",
        f"_last_known_{quote.lower()}",
        f"_spot_available_{quote.lower()}",
        f"_{quote.lower()}_available",
        f"available_{quote.lower()}",
    )
    for attr in attr_names:
        if hasattr(broker, attr):
            amount = _f(getattr(broker, attr), -1.0)
            if amount >= 0:
                return amount

    for attr in (
        "_balance_cache",
        "_last_balance_snapshot",
        "_last_account_inventory",
        "_last_raw_balance",
        "_last_balance_response",
        "_cached_balance_response",
    ):
        amount = _extract_quote_from_mapping(getattr(broker, attr, None), quote)
        if amount is not None:
            return amount

    for method in (
        "get_spot_balances",
        "get_account_balances",
        "get_balances",
        "get_available_balances",
        "fetch_balance",
        "get_balance",
        "get_account_balance",
    ):
        payload = _call_method(broker, method)
        amount = _extract_quote_from_mapping(payload, quote)
        if amount is not None:
            return amount
    return None


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
    required = _required_cash(size_usd, label or broker_name)

    quote = _quote_from_symbol(symbol)
    if label == "okx" and quote in {"USDT", "USDC", "USD"} and _truthy("NIJA_OKX_DIRECT_QUOTE_CASH_HARD_GATE", "true"):
        # OKX rejected live ADA/ATOM/APE/BASED USDT orders with sCode=51008
        # while scalar OKX equity looked funded. For OKX buys, use spendable
        # quote cash only; never treat total equity as spendable USDT/USDC.
        preferred_quotes = [quote] if quote in {"USDT", "USDC"} else ["USDT", "USDC"]
        quote_balances: dict[str, Optional[float]] = {q: _extract_spendable_quote_balance(broker, q) for q in preferred_quotes}
        available = max((amount for amount in quote_balances.values() if amount is not None), default=None)
        if available is None:
            ok = False
            available_for_log = 0.0
            reason = "quote_balance_unknown"
        else:
            ok = available + 1e-9 >= required
            available_for_log = available
            reason = "ok" if ok else "quote_cash_below_required"
        if not ok:
            logger.critical(
                "OKX_DIRECT_QUOTE_CASH_HARD_BLOCK marker=%s surface=%s symbol=%s quote=%s available=%s required=$%.2f size=$%.2f reason=%s action=reroute_or_block_before_broker_submit",
                _MARKER,
                surface,
                symbol,
                quote or "unknown",
                "unknown" if available is None else f"${available_for_log:.2f}",
                required,
                float(size_usd or 0.0),
                reason,
            )
        return ok, available_for_log, required, label

    available = _extract_available_balance(broker)
    ok = available + 1e-9 >= required
    if not ok:
        logger.critical(
            "DIRECT_BROKER_VENUE_CASH_HARD_BLOCK marker=%s surface=%s broker=%s symbol=%s available=$%.2f required=$%.2f size=$%.2f action=block_false_fill",
            _MARKER,
            surface,
            label or broker_name,
            symbol,
            available,
            required,
            float(size_usd or 0.0),
        )
    return ok, available, required, label or broker_name


def _deep_get(obj: Any, *keys: str) -> Any:
    """Safely traverse nested dicts; returns None if any level is missing or not a dict."""
    for key in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _normalize_coinbase_result(result: Dict[str, Any], size_usd: float = 0.0) -> None:
    """COINBASE_ORDER_ID_PAYLOAD_REPAIRED marker=20260709ap

    Copy nested Coinbase order_id / fill fields up to the top-level result dict
    so that _looks_confirmed_fill() can inspect them without knowing the SDK
    nesting structure.

    Checks (for each field) in priority order:
      order_id        : top-level → exchange_order_id → client_order_id →
                        order.order_id → order.success_response.order_id →
                        raw.order_id → raw.success_response.order_id →
                        success_response.order_id
      filled_price    : standard top-level keys → order.success_response.average_filled_price
                        → order.average_filled_price → raw.average_filled_price → …
      filled_size_usd : standard top-level keys → order.total_value_after_fees →
                        order.success_response.total_value_after_fees →
                        computed from filled_size * filled_price → size_usd fallback

    Existing top-level values are never overwritten.
    """
    if not isinstance(result, dict):
        return

    # ── order_id ─────────────────────────────────────────────────────────────
    if not result.get("order_id"):
        for candidate in (
            result.get("exchange_order_id"),
            result.get("client_order_id"),
            _deep_get(result, "order", "order_id"),
            _deep_get(result, "order", "success_response", "order_id"),
            _deep_get(result, "raw", "order_id"),
            _deep_get(result, "raw", "success_response", "order_id"),
            _deep_get(result, "success_response", "order_id"),
        ):
            if candidate and str(candidate).strip():
                result["order_id"] = str(candidate).strip()
                break

    # ── fill price ────────────────────────────────────────────────────────────
    _has_price = bool(
        result.get("filled_price") or result.get("average_filled_price")
        or result.get("average_fill_price") or result.get("avg_price")
        or result.get("price")
    )
    if not _has_price:
        for candidate in (
            _deep_get(result, "order", "success_response", "average_filled_price"),
            _deep_get(result, "order", "average_filled_price"),
            _deep_get(result, "order", "price"),
            _deep_get(result, "raw", "average_filled_price"),
            _deep_get(result, "raw", "price"),
            _deep_get(result, "success_response", "average_filled_price"),
        ):
            v = _f(candidate)
            if v > 0:
                result["filled_price"] = v
                break

    # ── filled notional (USD) ─────────────────────────────────────────────────
    _has_notional = bool(
        result.get("filled_size_usd") or result.get("filled_value")
        or result.get("notional_usd") or result.get("size_usd")
    )
    if not _has_notional:
        # Try explicit broker-level total-value fields first
        for candidate in (
            _deep_get(result, "order", "total_value_after_fees"),
            _deep_get(result, "order", "success_response", "total_value_after_fees"),
            _deep_get(result, "raw", "total_value_after_fees"),
            _deep_get(result, "raw", "success_response", "total_value_after_fees"),
        ):
            v = _f(candidate)
            if v > 0:
                result["filled_size_usd"] = v
                _has_notional = True
                break

        if not _has_notional:
            # Compute from filled_size (base crypto) × fill_price
            fp = _f(
                result.get("filled_price") or result.get("average_filled_price")
                or result.get("average_fill_price") or result.get("avg_price")
                or result.get("price")
            )
            fs = _f(
                result.get("filled_size")
                or _deep_get(result, "order", "success_response", "filled_size")
                or _deep_get(result, "order", "filled_size")
                or _deep_get(result, "raw", "filled_size")
                or _deep_get(result, "success_response", "filled_size")
            )
            if fp > 0 and fs > 0:
                result["filled_size_usd"] = fp * fs
                _has_notional = True

        if not _has_notional and size_usd > 0:
            # Last resort: the size_usd the caller was about to spend is a
            # reasonable lower-bound proxy for filled notional on a market buy.
            result["filled_size_usd"] = float(size_usd)


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
            "DIRECT_BROKER_PROFILE_CASH_REJECTED marker=%s broker=%s available=$%.2f required=$%.2f symbol=%s fallback=scored_selection",
            _MARKER,
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
            raise RuntimeError(f"venue_cash_insufficient:{label}:available=${available:.2f}<required=${required:.2f}:symbol={symbol}")

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

        # COINBASE_ORDER_ID_PAYLOAD_REPAIRED marker=20260709ap
        # Promote nested Coinbase order_id / fill fields to the top level so
        # _looks_confirmed_fill() can inspect them without needing to know the
        # exact SDK nesting structure.
        _normalize_coinbase_result(result, size_usd=float(size_usd or 0.0))

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
            "DIRECT_BROKER_CONFIRMED_FILL marker=%s broker=%s symbol=%s side=%s filled_usd=$%.2f price=%.8f",
            _MARKER,
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
    logger.warning("DIRECT_BROKER_VENUE_CASH_HARD_GATE_PATCHED marker=%s module=%s", _MARKER, getattr(module, "__name__", "unknown"))
    return True


def _patch_loaded() -> None:
    for name in ("bot.multi_broker_execution_router", "multi_broker_execution_router"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                _patch_module(module)
            except Exception as exc:
                logger.warning("DIRECT_BROKER_VENUE_CASH_HARD_GATE_PATCH_FAILED marker=%s module=%s err=%s", _MARKER, name, exc)


def install_import_hook() -> None:
    _patch_loaded()
    if getattr(builtins, "_NIJA_DIRECT_BROKER_VENUE_CASH_HARD_GATE_HOOK_20260709X", False):
        return
    original_import = builtins.__import__

    def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        if name in {"bot.multi_broker_execution_router", "multi_broker_execution_router"} or str(name).endswith("multi_broker_execution_router"):
            _patch_loaded()
        return module

    builtins.__import__ = importing
    setattr(builtins, "_NIJA_DIRECT_BROKER_VENUE_CASH_HARD_GATE_HOOK_20260709X", True)
    logger.warning("DIRECT_BROKER_VENUE_CASH_HARD_GATE_INSTALL_COMPLETE marker=%s", _MARKER)


def install() -> None:
    install_import_hook()
