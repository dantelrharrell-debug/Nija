"""Post-2829 live completion guard.

Closes two production gaps observed after PR #2829 without weakening execution,
risk, writer, nonce, position, or kill-switch controls:

* Kraken BUY intents are checked against the pair's base-quantity minimum at the
  final multi-broker dispatch boundary.  Undersized intents fail closed before
  the broker adapter is called; this guard never upsizes an order.
* User Kraken margin scans do not call OpenPositions when the concrete broker
  explicitly reports missing credentials or a disconnected state.  Those
  accounts remain fail-closed and non-trading with a precise blocker.

No order is submitted by this patch itself.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
import threading
import time
from decimal import Decimal, InvalidOperation, ROUND_UP
from types import ModuleType
from typing import Any, Callable, Optional

LOGGER = logging.getLogger("nija.kraken_live_completion_v415")

MARKER = "20260920-post2829-live-completion-v415"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_CENT = Decimal("0.01")
_TARGET_MODULES = {
    "bot.multi_broker_execution_router",
    "multi_broker_execution_router",
    "bot.runtime_kraken_margin_canonical_coverage_v366_patch",
    "runtime_kraken_margin_canonical_coverage_v366_patch",
}
_ORIGINAL_IMPORT: Optional[Callable[..., Any]] = None
_LOCK = threading.Lock()
_MONITOR_STARTED = False


def _decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


def _round_usd_up(value: Any) -> Decimal:
    amount = _decimal(value)
    return (amount / _CENT).to_integral_value(rounding=ROUND_UP) * _CENT


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _is_kraken_label(value: Any) -> bool:
    text = str(getattr(value, "value", value) or "").strip().lower()
    return "kraken" in text


def _unwrap_broker(broker: Any) -> Any:
    current = broker
    seen: set[int] = set()
    for _ in range(12):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        next_obj = None
        for name in (
            "_broker",
            "broker",
            "client",
            "_client",
            "adapter",
            "_adapter",
            "inner",
            "_inner",
        ):
            candidate = getattr(current, name, None)
            if candidate is not None and candidate is not current:
                next_obj = candidate
                break
        if next_obj is None:
            break
        current = next_obj
    return current


def _kraken_pair(symbol: Any, broker: Any = None) -> str:
    converter = getattr(broker, "_convert_to_kraken_symbol", None)
    if callable(converter):
        try:
            converted = str(converter(str(symbol)) or "").strip().upper()
            if converted:
                return converted.replace("/", "").replace("-", "").replace("_", "")
        except Exception:
            pass

    text = str(symbol or "").strip().upper().replace("/", "").replace("-", "").replace("_", "")
    quote = ""
    for candidate in ("USDT", "USDC", "USD", "EUR", "GBP"):
        if text.endswith(candidate):
            quote = candidate
            text = text[: -len(candidate)]
            break
    base = text
    if base in {"BTC", "XBT", "XXBT"}:
        return f"XXBTZ{quote}" if quote in {"USD", "EUR", "GBP"} else f"XXBTZ{quote}"
    if base in {"ETH", "XETH"}:
        return f"XETHZ{quote}" if quote in {"USD", "EUR", "GBP", "USDT"} else f"XETH{quote}"
    return f"{base}{quote}" if quote else base


def _configured_kraken_floor() -> Decimal:
    values = [
        Decimal("23.00"),
        _decimal(os.environ.get("KRAKEN_MIN_NOTIONAL_USD"), Decimal("0")),
        _decimal(os.environ.get("NIJA_KRAKEN_MIN_NOTIONAL_USD"), Decimal("0")),
        _decimal(os.environ.get("NIJA_KRAKEN_EFFECTIVE_MIN_NOTIONAL_USD"), Decimal("0")),
        _decimal(os.environ.get("NIJA_KRAKEN_FINAL_MIN_NOTIONAL_USD"), Decimal("0")),
    ]
    return max(values)


def _pair_required_quote(symbol: Any, price: Any, broker: Any = None) -> tuple[Decimal, dict[str, Any]]:
    price_d = _decimal(price)
    pair = _kraken_pair(symbol, broker)
    min_base = Decimal("0")
    min_quote = Decimal("0")
    source = "configured_floor"

    try:
        validator = importlib.import_module("bot.kraken_order_validator")
        safe_fn = getattr(validator, "get_pair_safe_minimums", None)
        if callable(safe_fn):
            data = safe_fn(pair)
            if isinstance(data, dict):
                min_base = max(min_base, _decimal(data.get("min_base")))
                min_quote = max(
                    min_quote,
                    _decimal(data.get("min_quote")),
                    _decimal(data.get("raw_min_quote")),
                )
                source = "kraken_order_validator"
    except Exception as exc:
        LOGGER.debug("KRAKEN_PAIR_MINIMUM_METADATA_UNAVAILABLE pair=%s err=%s", pair, exc)

    # Known Kraken fallbacks are used only if metadata could not provide them.
    fallback_base = {
        "XXBTZUSD": Decimal("0.0001"),
        "XXBTZUSDT": Decimal("0.0001"),
        "XETHZUSD": Decimal("0.01"),
        "XETHZUSDT": Decimal("0.01"),
        "SOLUSD": Decimal("0.5"),
        "ADAUSD": Decimal("10"),
        "DOTUSD": Decimal("1"),
        "AVAXUSD": Decimal("0.5"),
        "LINKUSD": Decimal("1"),
    }.get(pair, Decimal("0"))
    if fallback_base > min_base:
        min_base = fallback_base
        source = f"{source}+static_fallback"

    configured = _configured_kraken_floor()
    base_quote = min_base * price_d if min_base > 0 and price_d > 0 else Decimal("0")
    if base_quote > 0:
        pair_buffer = Decimal(str(max(0.0, min(0.10, _float_env("NIJA_KRAKEN_PAIR_MIN_BASE_BUFFER_PCT", 0.03)))))
        base_quote *= Decimal("1") + pair_buffer

    required = _round_usd_up(max(configured, min_quote, base_quote))
    return required, {
        "pair": pair,
        "price": float(price_d),
        "min_base": float(min_base),
        "min_quote": float(min_quote),
        "configured_floor": float(configured),
        "required_quote": float(required),
        "source": source,
    }


def _patch_router(module: ModuleType) -> bool:
    cls = getattr(module, "MultiBrokerExecutionRouter", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_dispatch_via_inner_router", None)
    if not callable(original):
        return False
    if getattr(original, "_nija_post2829_pair_guard_v415", False):
        return True

    failure_cls = getattr(module, "_InternalDispatchFailure", RuntimeError)
    if not isinstance(failure_cls, type) or not issubclass(failure_cls, BaseException):
        failure_cls = RuntimeError

    def _dispatch_via_inner_router(self: Any, *args: Any, **kwargs: Any):
        symbol = kwargs.get("symbol", args[0] if len(args) > 0 else "")
        side = str(kwargs.get("side", args[1] if len(args) > 1 else "") or "").strip().lower()
        size_usd = _decimal(kwargs.get("size_usd", args[2] if len(args) > 2 else 0.0))
        limit_price = kwargs.get("limit_price", args[4] if len(args) > 4 else None)
        broker_name = kwargs.get("broker_name", args[5] if len(args) > 5 else "")
        metadata = kwargs.get("metadata", args[6] if len(args) > 6 else None)
        meta = dict(metadata or {})

        direct = meta.get("broker_client")
        if direct is None and _is_kraken_label(broker_name):
            resolver = getattr(self, "_resolve_live_broker", None)
            if callable(resolver):
                try:
                    direct = resolver("kraken")
                except Exception:
                    direct = None

        is_kraken = _is_kraken_label(broker_name)
        if not is_kraken and direct is not None:
            is_kraken = (
                _is_kraken_label(getattr(direct, "broker_type", None))
                or _is_kraken_label(getattr(direct, "NAME", None))
                or "kraken" in type(direct).__name__.lower()
            )

        # Entry BUYs only. SELL/reduce/exit paths retain their existing dust and
        # position-ownership semantics and are never enlarged by this guard.
        intent = str(meta.get("intent_type") or "").strip().lower()
        closing = bool(meta.get("closing_position")) or intent in {"exit", "reduce"}
        if is_kraken and side in {"buy", "long"} and not closing:
            price = (
                meta.get("price_hint_usd")
                or meta.get("entry_price")
                or meta.get("market_price")
                or meta.get("price")
                or limit_price
            )
            price_d = _decimal(price)
            if price_d > 0:
                required, details = _pair_required_quote(symbol, price_d, direct)
                if size_usd + Decimal("0.0000001") < required:
                    LOGGER.warning(
                        "KRAKEN_PAIR_MINIMUM_PRE_DISPATCH_BLOCKED_V415 marker=%s "
                        "symbol=%s pair=%s requested=$%.2f required=$%.2f price=$%.8f "
                        "min_base=%.8f source=%s broker_io=false order_upsized=false "
                        "risk_unchanged=true safety_gates_bypassed=false",
                        MARKER,
                        symbol,
                        details["pair"],
                        float(size_usd),
                        float(required),
                        details["price"],
                        details["min_base"],
                        details["source"],
                    )
                    raise failure_cls(
                        f"KRAKEN_PAIR_MINIMUM_PRE_DISPATCH_BLOCKED:"
                        f"requested={float(size_usd):.2f}:required={float(required):.2f}:"
                        f"pair={details['pair']}"
                    )

        return original(self, *args, **kwargs)

    _dispatch_via_inner_router._nija_post2829_pair_guard_v415 = True  # type: ignore[attr-defined]
    _dispatch_via_inner_router.__wrapped__ = original  # type: ignore[attr-defined]
    setattr(cls, "_dispatch_via_inner_router", _dispatch_via_inner_router)
    LOGGER.warning(
        "KRAKEN_PAIR_MINIMUM_DISPATCH_GUARD_V415_INSTALLED marker=%s order_upsized=false fail_closed=true",
        MARKER,
    )
    return True


def _patch_v366(module: ModuleType) -> bool:
    original = getattr(module, "fetch_margin_positions", None)
    if not callable(original):
        return False
    if getattr(original, "_nija_post2829_user_preflight_v415", False):
        return True

    def fetch_margin_positions(broker: Any, *, account: Any = "", force: bool = False):
        account_key = str(account or "")
        if account_key.lower().startswith("user:"):
            concrete = _unwrap_broker(broker)
            credential_values = (
                getattr(broker, "credentials_configured", None),
                getattr(concrete, "credentials_configured", None),
            )
            if False in credential_values:
                LOGGER.warning(
                    "KRAKEN_MARGIN_OPENPOSITIONS_PREFLIGHT_BLOCKED_V415 marker=%s "
                    "account=%s reason=credentials_not_configured broker_io=false "
                    "position_truth_fabricated=false readiness_unchanged=true safety_gates_bypassed=false",
                    MARKER,
                    account_key,
                )
                return False, {}, "credentials_not_configured"

            connected = getattr(concrete, "connected", getattr(broker, "connected", None))
            if connected is False:
                LOGGER.warning(
                    "KRAKEN_MARGIN_OPENPOSITIONS_PREFLIGHT_BLOCKED_V415 marker=%s "
                    "account=%s reason=disconnected broker_io=false "
                    "position_truth_fabricated=false readiness_unchanged=true safety_gates_bypassed=false",
                    MARKER,
                    account_key,
                )
                return False, {}, "disconnected"

        return original(broker, account=account, force=force)

    fetch_margin_positions._nija_post2829_user_preflight_v415 = True  # type: ignore[attr-defined]
    fetch_margin_positions.__wrapped__ = original  # type: ignore[attr-defined]
    setattr(module, "fetch_margin_positions", fetch_margin_positions)
    LOGGER.warning(
        "KRAKEN_USER_OPENPOSITIONS_PREFLIGHT_V415_INSTALLED marker=%s missing_credentials_fail_closed=true",
        MARKER,
    )
    return True


def _patch_module(module: Any) -> bool:
    if not isinstance(module, ModuleType):
        return False
    name = str(getattr(module, "__name__", ""))
    if name in {"bot.multi_broker_execution_router", "multi_broker_execution_router"}:
        return _patch_router(module)
    if name in {
        "bot.runtime_kraken_margin_canonical_coverage_v366_patch",
        "runtime_kraken_margin_canonical_coverage_v366_patch",
    }:
        return _patch_v366(module)
    return False


def _patch_loaded() -> bool:
    patched = False
    for name in _TARGET_MODULES:
        module = sys.modules.get(name)
        if module is not None:
            try:
                patched = _patch_module(module) or patched
            except Exception as exc:
                LOGGER.warning("KRAKEN_LIVE_COMPLETION_V415_PATCH_FAILED module=%s err=%s", name, exc)
    return patched


def _start_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def monitor() -> None:
        deadline = time.monotonic() + 300.0
        while time.monotonic() < deadline:
            _patch_loaded()
            if all(sys.modules.get(name) is not None for name in (
                "bot.multi_broker_execution_router",
                "bot.runtime_kraken_margin_canonical_coverage_v366_patch",
            )):
                return
            time.sleep(0.25)

    threading.Thread(
        target=monitor,
        name="kraken-live-completion-v415-monitor",
        daemon=True,
    ).start()


def install_import_hook() -> None:
    """Install the narrow fail-closed completion guard."""
    global _ORIGINAL_IMPORT
    with _LOCK:
        _patch_loaded()
        _start_monitor()
        if _ORIGINAL_IMPORT is not None:
            return

        _ORIGINAL_IMPORT = builtins.__import__

        def importing(
            name: str,
            globals: Any = None,
            locals: Any = None,
            fromlist: Any = (),
            level: int = 0,
        ):
            module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)  # type: ignore[misc]
            try:
                _patch_loaded()
            except Exception as exc:
                LOGGER.debug("KRAKEN_LIVE_COMPLETION_V415_IMPORT_CHECK_SKIPPED name=%s err=%s", name, exc)
            return module

        builtins.__import__ = importing
        LOGGER.warning(
            "KRAKEN_LIVE_COMPLETION_V415_INSTALLED marker=%s "
            "pair_minimum_pre_dispatch=true user_openpositions_preflight=true "
            "order_upsized=false live_trade_forced=false safety_gates_bypassed=false",
            MARKER,
        )


__all__ = [
    "MARKER",
    "_pair_required_quote",
    "_patch_router",
    "_patch_v366",
    "install_import_hook",
]
