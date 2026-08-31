"""Proof-gated Kraken short-margin profitability authority v325.

Purpose
-------
Allow NIJA to monetize bearish Kraken spot signals *only* when the exact
account and pair prove that margin shorting is currently permitted.

This is deliberately not a generic ``sell == short`` rewrite.  A short entry is
recognized only inside ``ExecutionEngine.execute_entry(side='short')`` and is
carried with a ContextVar so concurrent platform/user accounts cannot leak
short intent into one another.

Safety / profitability invariants
---------------------------------
* Kraken spot remains statically ``supports_short=False``.  Live account/pair
  margin proof is required instead of weakening the global capability matrix.
* Existing derivatives that already advertise short support are untouched.
* Generic sells and all exit/reduce flows are untouched.
* A Kraken short requires: runtime execution authority, margin feature enabled,
  explicit short-margin feature enabled, confirmed account margin permission,
  current healthy margin state, and non-empty ``leverage_sell`` for the pair.
* The strategy's already risk-sized notional is preserved.  Leverage is used as
  a borrowing mechanism; v325 does not multiply the requested position size.
* No failed short-margin admission may fall back to a spot sell.
* Pipeline/ECEL/writer/nonce/kill-switch/risk/fill gates remain authoritative.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import replace
from functools import wraps
import importlib
import logging
import math
import os
import threading
import time
from typing import Any, Mapping, Optional

LOGGER = logging.getLogger("nija.runtime_kraken_short_margin_profit_v325")
MARKER = "20260831-runtime-kraken-short-margin-profit-v325"
_PATCH_ATTR = "_nija_runtime_kraken_short_margin_profit_v325"
_LOCK = threading.RLock()

_CURRENT_APEX_STRATEGY: ContextVar[Any] = ContextVar(
    "nija_v325_current_apex_strategy", default=None
)
_SHORT_ENTRY_CONTEXT: ContextVar[Optional[dict[str, Any]]] = ContextVar(
    "nija_v325_short_entry_context", default=None
)

_PROOF_CACHE: dict[tuple[str, str], tuple[float, bool, str, int]] = {}
_PROOF_LOCK = threading.RLock()


def _truthy(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "y", "enabled"}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value if value is not None else default)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if math.isfinite(parsed) else default


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _is_derivative_symbol(symbol: str) -> bool:
    text = str(symbol or "").strip().upper()
    return any(token in text for token in ("PERP", "FUT", "SWAP"))


def _broker_name_from_strategy(strategy: Any) -> str:
    getter = getattr(strategy, "_get_broker_name", None)
    if callable(getter):
        try:
            value = _norm(getter())
            if value:
                return value
        except Exception:
            pass
    broker = getattr(strategy, "broker_client", None)
    for attr in ("broker_name", "exchange_name", "exchange", "name"):
        value = getattr(broker, attr, None)
        value = _norm(getattr(value, "value", value))
        if value:
            for known in ("kraken", "coinbase", "okx", "alpaca"):
                if known in value:
                    return known
    broker_type = getattr(broker, "broker_type", None)
    value = _norm(getattr(broker_type, "value", broker_type))
    if value:
        for known in ("kraken", "coinbase", "okx", "alpaca"):
            if known in value:
                return known
    class_name = _norm(type(broker).__name__) if broker is not None else ""
    for known in ("kraken", "coinbase", "okx", "alpaca"):
        if known in class_name:
            return known
    return "unknown"


def _account_id_from_strategy(strategy: Any) -> str:
    engine = getattr(strategy, "execution_engine", None)
    for owner in (engine, strategy, getattr(strategy, "broker_client", None)):
        if owner is None:
            continue
        for attr in ("user_id", "account_id", "account_identifier", "subaccount_id"):
            value = str(getattr(owner, attr, "") or "").strip()
            if value and value.lower() not in {"none", "unknown"}:
                return value
    return "platform"


def _execution_authority_ready() -> tuple[bool, str]:
    try:
        module = importlib.import_module("bot.execution_authority_context")
        can_execute = getattr(module, "can_execute", None)
        if not callable(can_execute):
            return False, "execution_authority_unavailable"
        decision = can_execute()
        if not bool(getattr(decision, "allowed", False)):
            return False, str(getattr(decision, "reason", "execution_authority_not_ready"))
        return True, "execution_authority_ready"
    except Exception as exc:
        return False, f"execution_authority_check_failed:{type(exc).__name__}"


def _kraken_short_margin_proof(
    strategy: Any,
    symbol: str,
    *,
    force_fresh_health: bool = False,
) -> tuple[bool, str, int]:
    """Return account+pair proof for a Kraken spot margin short."""
    if strategy is None:
        return False, "strategy_context_missing", 1
    if _broker_name_from_strategy(strategy) != "kraken":
        return False, "not_kraken", 1
    if _is_derivative_symbol(symbol):
        return False, "derivative_uses_existing_short_path", 1
    if not _truthy("NIJA_KRAKEN_MARGIN_ENABLED", True):
        return False, "kraken_margin_disabled", 1
    if not _truthy("NIJA_KRAKEN_SHORT_MARGIN_ENABLED", True):
        return False, "kraken_short_margin_disabled", 1

    authority_ok, authority_reason = _execution_authority_ready()
    if not authority_ok:
        return False, authority_reason, 1

    adapter = getattr(strategy, "broker_client", None)
    if adapter is None:
        return False, "kraken_adapter_missing", 1
    account_id = _account_id_from_strategy(strategy)
    key = (account_id, str(symbol or "").upper())
    ttl = max(1.0, min(60.0, _f(os.getenv("NIJA_KRAKEN_SHORT_PROOF_CACHE_S"), 15.0)))
    if not force_fresh_health:
        with _PROOF_LOCK:
            cached = _PROOF_CACHE.get(key)
            if cached and time.monotonic() - cached[0] <= ttl:
                return cached[1], cached[2], cached[3]

    try:
        margin_mod = importlib.import_module("bot.kraken_margin_engine")
        get_margin_engine = getattr(margin_mod, "get_margin_engine")
        permission_enum = getattr(margin_mod, "MarginPermissionState")
        engine = get_margin_engine(account_id, adapter=adapter)
        permission = engine.check_permissions(adapter)
        if permission != permission_enum.CONFIRMED:
            result = (False, f"margin_permission={getattr(permission, 'value', permission)}", 1)
        else:
            if force_fresh_health:
                invalidate = getattr(engine, "invalidate_health_cache", None)
                if callable(invalidate):
                    invalidate()
            allowed, health_reason = engine.is_margin_trade_allowed(
                is_reducing=False,
                adapter=adapter,
            )
            if not allowed:
                result = (False, f"margin_health={health_reason}", 1)
            else:
                leverages = tuple(engine.get_pair_leverages(symbol, "sell", adapter=adapter) or ())
                leverages = tuple(
                    sorted({int(v) for v in leverages if 2 <= int(v) <= 3})
                )
                if not leverages:
                    result = (False, "pair_leverage_sell_unavailable", 1)
                else:
                    desired = int(max(2, min(3, _f(os.getenv("NIJA_KRAKEN_MARGIN_DEFAULT_LEVERAGE"), 2.0))))
                    leverage = desired if desired in leverages else min(leverages)
                    result = (True, f"margin_short_proven:{health_reason}", leverage)
    except Exception as exc:
        result = (False, f"margin_proof_failed:{type(exc).__name__}:{exc}", 1)

    with _PROOF_LOCK:
        _PROOF_CACHE[key] = (time.monotonic(), result[0], result[1], result[2])
    return result


def _patch_apex_short_capability() -> bool:
    try:
        module = importlib.import_module("bot.nija_apex_strategy_v71")
    except Exception:
        LOGGER.exception("V325_APEX_IMPORT_FAILED marker=%s", MARKER)
        return False

    cls = getattr(module, "NIJAApexStrategyV71", None)
    original_can_short = getattr(module, "can_short", None)
    if cls is None or not callable(original_can_short):
        return False

    if not getattr(original_can_short, _PATCH_ATTR, False):
        @wraps(original_can_short)
        def can_short_with_live_margin(broker_name: str, symbol: str) -> bool:
            try:
                if bool(original_can_short(broker_name, symbol)):
                    return True
            except Exception:
                pass
            if _norm(broker_name) != "kraken" or _is_derivative_symbol(symbol):
                return False
            strategy = _CURRENT_APEX_STRATEGY.get()
            allowed, reason, leverage = _kraken_short_margin_proof(strategy, symbol)
            LOGGER.info(
                "KRAKEN_SHORT_MARGIN_V325_CAPABILITY marker=%s account=%s symbol=%s allowed=%s leverage=%s reason=%s",
                MARKER,
                _account_id_from_strategy(strategy) if strategy is not None else "none",
                symbol,
                allowed,
                leverage,
                reason,
            )
            return allowed

        setattr(can_short_with_live_margin, _PATCH_ATTR, True)
        setattr(can_short_with_live_margin, "__wrapped__", original_can_short)
        module.can_short = can_short_with_live_margin

    for method_name in ("analyze_market", "execute_action"):
        original = getattr(cls, method_name, None)
        if not callable(original) or getattr(original, _PATCH_ATTR, False):
            continue

        @wraps(original)
        def with_strategy_context(self, *args, __original=original, **kwargs):
            token = _CURRENT_APEX_STRATEGY.set(self)
            try:
                return __original(self, *args, **kwargs)
            finally:
                _CURRENT_APEX_STRATEGY.reset(token)

        setattr(with_strategy_context, _PATCH_ATTR, True)
        setattr(with_strategy_context, "__wrapped__", original)
        setattr(cls, method_name, with_strategy_context)

    LOGGER.critical(
        "KRAKEN_SHORT_MARGIN_V325_APEX_PATCHED marker=%s static_kraken_spot_short_unchanged=true live_margin_proof=true",
        MARKER,
    )
    return True


def _patch_execution_entry_context() -> bool:
    try:
        module = importlib.import_module("bot.execution_engine")
        cls = getattr(module, "ExecutionEngine", None)
    except Exception:
        return False
    if cls is None:
        return False
    original = getattr(cls, "execute_entry", None)
    if not callable(original):
        return False
    if getattr(original, _PATCH_ATTR, False):
        return True

    @wraps(original)
    def execute_entry_with_short_context(
        self,
        symbol: str,
        side: str,
        position_size: float,
        entry_price: float,
        stop_loss: float,
        take_profit_levels: Mapping[str, Any],
        *args,
        **kwargs,
    ):
        if _norm(side) != "short":
            return original(
                self, symbol, side, position_size, entry_price, stop_loss,
                take_profit_levels, *args, **kwargs,
            )
        ctx = {
            "execution_engine": self,
            "broker_client": getattr(self, "broker_client", None),
            "account_id": str(getattr(self, "user_id", "") or "platform"),
            "symbol": symbol,
            "position_size": float(position_size or 0.0),
            "entry_price": float(entry_price or 0.0),
        }
        token = _SHORT_ENTRY_CONTEXT.set(ctx)
        try:
            return original(
                self, symbol, side, position_size, entry_price, stop_loss,
                take_profit_levels, *args, **kwargs,
            )
        finally:
            _SHORT_ENTRY_CONTEXT.reset(token)

    setattr(execute_entry_with_short_context, _PATCH_ATTR, True)
    setattr(execute_entry_with_short_context, "__wrapped__", original)
    cls.execute_entry = execute_entry_with_short_context
    return True


def _deny_pipeline(pipeline: Any, request: Any, reason: str):
    deny = getattr(pipeline, "_deny", None)
    if callable(deny):
        return deny(request, time.monotonic(), f"KrakenShortMarginV325 deny: {reason}")
    module = importlib.import_module("bot.execution_pipeline")
    result_cls = getattr(module, "PipelineResult")
    return result_cls(
        success=False,
        symbol=getattr(request, "symbol", ""),
        side=getattr(request, "side", "sell"),
        size_usd=float(getattr(request, "size_usd", 0.0) or 0.0),
        error=f"KrakenShortMarginV325 deny: {reason}",
        latency_ms=0.0,
    )


def _patch_pipeline_short_intent() -> bool:
    try:
        module = importlib.import_module("bot.execution_pipeline")
        cls = getattr(module, "ExecutionPipeline", None)
    except Exception:
        return False
    if cls is None:
        return False
    original = getattr(cls, "execute", None)
    if not callable(original):
        return False
    if getattr(original, _PATCH_ATTR, False):
        return True

    @wraps(original)
    def execute_with_short_margin(self, request, *args, **kwargs):
        ctx = _SHORT_ENTRY_CONTEXT.get()
        if not ctx:
            return original(self, request, *args, **kwargs)

        side = _norm(getattr(request, "side", ""))
        symbol = str(getattr(request, "symbol", "") or ctx.get("symbol") or "")
        broker_hint = _norm(
            getattr(request, "preferred_broker", "")
            or getattr(getattr(ctx.get("broker_client"), "broker_type", None), "value", "")
            or type(ctx.get("broker_client")).__name__
        )
        if side != "sell" or "kraken" not in broker_hint or _is_derivative_symbol(symbol):
            return original(self, request, *args, **kwargs)

        intent = _norm(getattr(request, "intent_type", ""))
        effect = _norm(getattr(request, "position_effect", ""))
        reduce_only = getattr(request, "reduce_only", None)
        if intent in {"exit", "reduce"} or effect in {"close", "reduce"} or reduce_only is True:
            return original(self, request, *args, **kwargs)

        engine_self = ctx.get("execution_engine")
        strategy_proxy = type("_V325StrategyProxy", (), {})()
        setattr(strategy_proxy, "broker_client", ctx.get("broker_client"))
        setattr(strategy_proxy, "execution_engine", engine_self)
        setattr(strategy_proxy, "_get_broker_name", lambda: "kraken")
        allowed, reason, leverage = _kraken_short_margin_proof(
            strategy_proxy,
            symbol,
            force_fresh_health=True,
        )
        if not allowed:
            LOGGER.warning(
                "KRAKEN_SHORT_MARGIN_V325_ENTRY_BLOCKED marker=%s account=%s symbol=%s reason=%s spot_fallback=false",
                MARKER,
                ctx.get("account_id"),
                symbol,
                reason,
            )
            return _deny_pipeline(self, request, reason)

        size_usd = max(0.0, _f(getattr(request, "size_usd", None), ctx.get("position_size", 0.0)))
        if size_usd <= 0.0:
            return _deny_pipeline(self, request, "non_positive_short_notional")

        adapter = ctx.get("broker_client")
        account_id = str(getattr(request, "account_id", "") or ctx.get("account_id") or "platform")
        try:
            margin_mod = importlib.import_module("bot.kraken_margin_engine")
            get_margin_engine = getattr(margin_mod, "get_margin_engine")
            margin_scope = getattr(margin_mod, "margin_account_scope")
            margin_engine = get_margin_engine(account_id, adapter=adapter)
            snapshot = margin_engine.get_health_snapshot(adapter=adapter)
            collateral = max(
                0.0,
                _f(getattr(snapshot, "free_margin_usd", 0.0)),
                _f(getattr(snapshot, "trade_balance_free_usd", 0.0)),
                _f(getattr(request, "available_balance_usd", 0.0)),
            )
            buying_power = collateral * max(1, leverage)
            if buying_power + 1e-9 < size_usd:
                return _deny_pipeline(
                    self,
                    request,
                    f"insufficient_margin_buying_power:{buying_power:.2f}<{size_usd:.2f}",
                )

            metadata = dict(getattr(request, "metadata", {}) or {})
            metadata.update(
                {
                    "short_entry": True,
                    "position_side": "short",
                    "kraken_margin_short_v325": True,
                    "margin_proof_reason": reason,
                    "risk_notional_preserved": True,
                    "broker_client": adapter,
                }
            )
            transformed = replace(
                request,
                intent_type="entry",
                position_effect="open",
                leverage=int(leverage),
                margin_mode="cross",
                reduce_only=False,
                short_sell=True,
                buying_power_usd=buying_power,
                metadata=metadata,
            )
            LOGGER.critical(
                "KRAKEN_SHORT_MARGIN_V325_ENTRY_READY marker=%s account=%s symbol=%s notional=%.2f leverage=%sx "
                "risk_notional_preserved=true margin_permission=true leverage_sell=true health=true spot_fallback=false",
                MARKER,
                account_id,
                symbol,
                size_usd,
                leverage,
            )
            with margin_scope(account_id, adapter=adapter):
                return original(self, transformed, *args, **kwargs)
        except Exception as exc:
            LOGGER.exception(
                "KRAKEN_SHORT_MARGIN_V325_PIPELINE_ERROR marker=%s account=%s symbol=%s spot_fallback=false",
                MARKER,
                account_id,
                symbol,
            )
            return _deny_pipeline(self, request, f"short_margin_pipeline_error:{type(exc).__name__}:{exc}")

    setattr(execute_with_short_margin, _PATCH_ATTR, True)
    setattr(execute_with_short_margin, "__wrapped__", original)
    cls.execute = execute_with_short_margin
    return True


def install_import_hook() -> bool:
    with _LOCK:
        # Feature opt-in defaults to enabled because the user explicitly requested
        # profitable shorts where the venue/account permits them.  An explicit
        # operator false always wins.
        os.environ.setdefault("NIJA_KRAKEN_SHORT_MARGIN_ENABLED", "true")
        outcomes = {
            "apex_live_short_capability": _patch_apex_short_capability(),
            "execution_short_context": _patch_execution_entry_context(),
            "pipeline_short_margin_intent": _patch_pipeline_short_intent(),
        }
        ready = all(outcomes.values())
        os.environ["NIJA_RUNTIME_KRAKEN_SHORT_MARGIN_PROFIT_V325_READY"] = "1" if ready else "0"
        if ready:
            LOGGER.critical(
                "RUNTIME_KRAKEN_SHORT_MARGIN_PROFIT_V325_READY marker=%s outcomes=%s "
                "account_scoped=true pair_leverage_sell_proof=true margin_health_proof=true "
                "risk_notional_preserved=true generic_sell_unchanged=true exits_unchanged=true "
                "spot_fallback=false static_capabilities_unchanged=true safety_gates_bypassed=false",
                MARKER,
                outcomes,
            )
        else:
            LOGGER.critical(
                "RUNTIME_KRAKEN_SHORT_MARGIN_PROFIT_V325_INCOMPLETE marker=%s outcomes=%s fail_closed=true",
                MARKER,
                outcomes,
            )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_kraken_short_margin_proof",
]
