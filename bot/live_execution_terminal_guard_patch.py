from __future__ import annotations

import builtins
import logging
import os
import sys
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.live_execution_terminal_guard")

_MARKER = "LIVE_EXECUTION_TERMINAL_GUARD marker=20260707k"
_IMPORT_FLAG = "_NIJA_LIVE_EXECUTION_TERMINAL_GUARD_IMPORT_HOOK_V20260707K"
_TRUTHY = {"1", "true", "yes", "on", "y", "enabled"}

_TARGETS = {
    "bot.trade_permission_engine",
    "trade_permission_engine",
    "bot.execution_pipeline",
    "execution_pipeline",
    "bot.multi_broker_execution_router",
    "multi_broker_execution_router",
    "bot.ai_intelligence_hub",
    "ai_intelligence_hub",
}

_TERMINAL_MARKERS = (
    "terminal_risk_hard_block",
    "hard_sector_limit_block",
    "entry_blocked_terminal_risk_hard_block",
    "portfolio exposure limit reached",
    "position blocked by risk engine",
    "sector limit enforcement",
    "hard sector limit block",
    "global_exposure_cap",
    "pretraderiskengine reject",
)


def _truthy_env(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUTHY


def _norm_symbol(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _norm_broker(value: Any) -> str:
    text = str(value or "").strip().lower().replace(" ", "_")
    aliases = {
        "coinbaseadvanced": "coinbase",
        "coinbase_advanced": "coinbase",
        "coinbase_advanced_trade": "coinbase",
        "coinbaseadvancedtrade": "coinbase",
        "kraken_spot": "kraken",
        "krakenpro": "kraken",
        "okxus": "okx",
        "okx_us": "okx",
        "okx_spot": "okx",
    }
    return aliases.get(text, text)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _stringify(value: Any, *, _depth: int = 0) -> str:
    if _depth > 3:
        return ""
    if value is None:
        return ""
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            parts.append(str(key))
            parts.append(_stringify(item, _depth=_depth + 1))
        return " ".join(parts)
    if isinstance(value, (list, tuple, set)):
        return " ".join(_stringify(item, _depth=_depth + 1) for item in value)
    return str(value)


def _contains_terminal_hard_block(value: Any) -> bool:
    text = _stringify(value).lower()
    return any(marker in text for marker in _TERMINAL_MARKERS)


def _metadata_from_request(request: Any) -> dict[str, Any]:
    try:
        meta = getattr(request, "metadata", {}) or {}
        return dict(meta) if isinstance(meta, dict) else {}
    except Exception:
        return {}


def _metadata_from_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    meta = kwargs.get("metadata") or {}
    return dict(meta) if isinstance(meta, dict) else {}


def _broker_from_request(request: Any) -> str:
    meta = _metadata_from_request(request)
    for value in (
        getattr(request, "preferred_broker", None),
        getattr(request, "broker", None),
        meta.get("broker_name"),
        meta.get("broker"),
        meta.get("broker_hint"),
        meta.get("venue"),
        meta.get("exchange"),
    ):
        broker = _norm_broker(value)
        if broker:
            return broker
    return ""


def _broker_from_tpe_args(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    return _norm_broker(kwargs.get("broker") or (args[8] if len(args) > 8 else ""))


def _explicit_zero_allocation(value: Any) -> bool:
    """Return true only when a live route/request explicitly says $0 is allocated."""
    if value is None:
        return False
    try:
        return float(value) <= 0.0
    except Exception:
        return False


def _has_explicit_zero_route(*objects: Any) -> tuple[bool, str]:
    keys = (
        "capital_allocated",
        "allocated_capital",
        "broker_allocated_capital",
        "venue_allocated_capital",
        "selected_broker_capital",
        "route_capital",
        "spendable_capital",
        "usable_capital",
    )
    for obj in objects:
        if obj is None:
            continue
        # TradeDecision.capital_allocated defaults to 0.0 and is only diagnostic.
        # Do not treat that default as a live route allocation unless it was in
        # request metadata or an execution request object.
        if obj.__class__.__name__ == "TradeDecision":
            continue
        if isinstance(obj, dict):
            for key in keys:
                if key in obj and _explicit_zero_allocation(obj.get(key)):
                    return True, key
            continue
        for key in keys:
            if hasattr(obj, key):
                value = getattr(obj, key, None)
                if callable(value):
                    try:
                        value = value()
                    except Exception:
                        continue
                if _explicit_zero_allocation(value):
                    return True, key
    return False, ""


def _request_size_usd(request: Any) -> float:
    meta = _metadata_from_request(request)
    for source in (request, meta):
        if isinstance(source, dict):
            for key in ("size_usd", "position_size", "notional_usd", "usd_size", "amount_usd"):
                if key in source:
                    size = _float(source.get(key), 0.0)
                    if size > 0.0:
                        return size
        else:
            for key in ("size_usd", "position_size", "notional_usd", "usd_size", "amount_usd"):
                if hasattr(source, key):
                    size = _float(getattr(source, key, 0.0), 0.0)
                    if size > 0.0:
                        return size
    return 0.0


def _make_tpe_decision(module: ModuleType, *, symbol: str, side: str, score: float, threshold: float, balance: float, broker: str, reason: str):
    TradeDecision = getattr(module, "TradeDecision", None)
    if TradeDecision is None:
        return None
    try:
        return TradeDecision(
            symbol=symbol,
            side=side,
            signal="NO",
            signal_score=score,
            signal_threshold=threshold,
            signal_bypass=False,
            regime_label="TERMINAL_RISK",
            regime_pass=False,
            regime_bypass=False,
            capital="PASS" if balance > 0 else "FAIL",
            capital_balance=balance,
            capital_threshold=0.0,
            liquidity="FAIL",
            liquidity_detail=reason,
            execution_mode="TERMINAL_GUARD",
            final_decision="BLOCKED",
            block_reason=reason,
            broker=broker,
            broker_criticality="TERMINAL_GUARD",
            broker_health="BLOCKED",
            risk_allowed=False,
            capital_allocated=0.0,
            market_regime="TERMINAL_RISK",
            strategy_name="live_execution_terminal_guard",
        )
    except Exception as exc:
        logger.warning("TERMINAL_GUARD_TPE_DECISION_BUILD_FAILED symbol=%s err=%s", symbol, exc)
        return None


def _patch_trade_permission_engine(module: ModuleType) -> bool:
    cls = getattr(module, "TradePermissionEngine", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "evaluate", None)
    if not callable(original) or getattr(original, "_nija_terminal_guard_wrapped", False):
        return False

    @wraps(original)
    def evaluate(self: Any, *args: Any, **kwargs: Any):
        meta = _metadata_from_kwargs(kwargs)
        symbol = str(kwargs.get("symbol") or (args[0] if args else "UNKNOWN"))
        side = str(kwargs.get("side") or (args[1] if len(args) > 1 else ""))
        score = _float(kwargs.get("ai_score") or (args[2] if len(args) > 2 else 0.0), 0.0)
        threshold = _float(kwargs.get("ai_threshold") or (args[3] if len(args) > 3 else 0.0), 0.0)
        balance = _float(kwargs.get("balance") or (args[4] if len(args) > 4 else 0.0), 0.0)
        broker = _broker_from_tpe_args(args, kwargs)

        reason = ""
        if _contains_terminal_hard_block(meta):
            reason = "NON_OVERRIDEABLE_TERMINAL_RISK_HARD_BLOCK"
        zero_route, zero_key = _has_explicit_zero_route(meta)
        if zero_route:
            reason = f"NO_FUNDED_BROKER_ROUTE selected_broker={broker or 'unknown'} allocation_key={zero_key}"

        if reason:
            logger.critical(
                "TPE_TERMINAL_GUARD_BLOCK marker=20260707k symbol=%s side=%s broker=%s reason=%s",
                _norm_symbol(symbol),
                side,
                broker or "unknown",
                reason,
            )
            decision = _make_tpe_decision(
                module,
                symbol=_norm_symbol(symbol),
                side=side,
                score=score,
                threshold=threshold,
                balance=balance,
                broker=broker,
                reason=reason,
            )
            if decision is not None:
                return decision

        decision = original(self, *args, **kwargs)
        try:
            decision_text = _stringify(getattr(decision, "to_dict", lambda: vars(decision))())
        except Exception:
            decision_text = _stringify(decision)
        zero_route, zero_key = _has_explicit_zero_route(meta)
        if _contains_terminal_hard_block(meta) or _contains_terminal_hard_block(decision_text) or zero_route:
            block_reason = (
                "NON_OVERRIDEABLE_TERMINAL_RISK_HARD_BLOCK"
                if (_contains_terminal_hard_block(meta) or _contains_terminal_hard_block(decision_text))
                else f"NO_FUNDED_BROKER_ROUTE selected_broker={broker or getattr(decision, 'broker', '') or 'unknown'} allocation_key={zero_key}"
            )
            for attr, value in (
                ("final_decision", "BLOCKED"),
                ("block_reason", block_reason),
                ("risk_allowed", False),
                ("capital_allocated", 0.0),
                ("broker_health", "BLOCKED"),
                ("broker_criticality", "TERMINAL_GUARD"),
            ):
                try:
                    setattr(decision, attr, value)
                except Exception:
                    pass
            logger.critical(
                "TPE_EXECUTE_CONVERTED_TO_HOLD marker=20260707k symbol=%s side=%s reason=%s",
                _norm_symbol(getattr(decision, "symbol", symbol)),
                getattr(decision, "side", side),
                block_reason,
            )
        return decision

    setattr(evaluate, "_nija_terminal_guard_wrapped", True)
    setattr(cls, "evaluate", evaluate)
    logger.warning("%s patched=TradePermissionEngine.evaluate", _MARKER)
    return True


def _pipeline_failure(PipelineResult: Any, request: Any, *, reason: str):
    symbol = _norm_symbol(getattr(request, "symbol", "UNKNOWN"))
    side = str(getattr(request, "side", ""))
    size_usd = _request_size_usd(request)
    broker = _broker_from_request(request) or "terminal_guard"
    return PipelineResult(
        success=False,
        symbol=symbol,
        side=side,
        size_usd=size_usd,
        broker=broker,
        latency_ms=0.0,
        error=reason,
    )


def _patch_execution_pipeline(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionPipeline", None)
    PipelineResult = getattr(module, "PipelineResult", None)
    if not isinstance(cls, type) or PipelineResult is None:
        return False
    original = getattr(cls, "execute", None)
    if not callable(original) or getattr(original, "_nija_terminal_guard_wrapped", False):
        return False

    @wraps(original)
    def execute(self: Any, request: Any):
        meta = _metadata_from_request(request)
        symbol = _norm_symbol(getattr(request, "symbol", "UNKNOWN"))
        side = str(getattr(request, "side", ""))
        size = _request_size_usd(request)
        zero_route, zero_key = _has_explicit_zero_route(request, meta)
        reason = ""
        if _contains_terminal_hard_block(request) or _contains_terminal_hard_block(meta):
            reason = "NON_OVERRIDEABLE_TERMINAL_RISK_HARD_BLOCK"
        elif size <= 0.0:
            reason = "ZERO_SIZE_ORDER_BLOCKED_BEFORE_BROKER"
        elif zero_route:
            reason = f"NO_FUNDED_BROKER_ROUTE allocation_key={zero_key}"
        if reason:
            logger.critical(
                "PIPELINE_TERMINAL_GUARD_BLOCK marker=20260707k symbol=%s side=%s broker=%s size_usd=%.2f reason=%s",
                symbol,
                side,
                _broker_from_request(request) or "unknown",
                size,
                reason,
            )
            return _pipeline_failure(PipelineResult, request, reason=reason)

        result = original(self, request)
        error_text = str(getattr(result, "error", "") or "")
        if "ack_timeout_no_confirmed_fill" in error_text.lower():
            try:
                setattr(result, "error", f"ORDER_ACK_UNCONFIRMED_RECONCILIATION_REQUIRED: {error_text}")
            except Exception:
                pass
            logger.critical(
                "ORDER_ACK_TIMEOUT_NOT_TREATED_AS_FILL marker=20260707k symbol=%s broker=%s error=%s",
                _norm_symbol(getattr(result, "symbol", symbol)),
                getattr(result, "broker", ""),
                error_text[:500],
            )
        return result

    setattr(execute, "_nija_terminal_guard_wrapped", True)
    setattr(cls, "execute", execute)
    logger.warning("%s patched=ExecutionPipeline.execute", _MARKER)
    return True


def _route_failure(RouteResult: Any, module: ModuleType, request: Any, *, reason: str):
    symbol = _norm_symbol(getattr(request, "symbol", "UNKNOWN"))
    side = str(getattr(request, "side", ""))
    size = _request_size_usd(request)
    asset_class = str(getattr(request, "asset_class", "") or "crypto")
    broker = _broker_from_request(request) or "NONE"
    return RouteResult(
        success=False,
        symbol=symbol,
        side=side,
        size_usd=size,
        asset_class=asset_class,
        broker=broker,
        fill_price=0.0,
        filled_size_usd=0.0,
        order_type=getattr(request, "order_type", None) or "MARKET",
        latency_ms=0.0,
        error=reason,
    )


def _patch_multi_broker_router(module: ModuleType) -> bool:
    cls = getattr(module, "MultiBrokerExecutionRouter", None)
    RouteResult = getattr(module, "RouteResult", None)
    if not isinstance(cls, type) or RouteResult is None:
        return False
    original = getattr(cls, "route", None)
    if not callable(original) or getattr(original, "_nija_terminal_guard_wrapped", False):
        return False

    @wraps(original)
    def route(self: Any, request: Any):
        meta = _metadata_from_request(request)
        symbol = _norm_symbol(getattr(request, "symbol", "UNKNOWN"))
        side = str(getattr(request, "side", ""))
        size = _request_size_usd(request)
        zero_route, zero_key = _has_explicit_zero_route(request, meta)
        reason = ""
        if _contains_terminal_hard_block(request) or _contains_terminal_hard_block(meta):
            reason = "NON_OVERRIDEABLE_TERMINAL_RISK_HARD_BLOCK"
        elif size <= 0.0:
            reason = "ZERO_SIZE_ORDER_BLOCKED_BEFORE_ROUTER"
        elif zero_route:
            reason = f"NO_FUNDED_BROKER_ROUTE allocation_key={zero_key}"

        if reason:
            logger.critical(
                "ROUTER_TERMINAL_GUARD_BLOCK marker=20260707k symbol=%s side=%s broker=%s size_usd=%.2f reason=%s",
                symbol,
                side,
                _broker_from_request(request) or "unknown",
                size,
                reason,
            )
            return _route_failure(RouteResult, module, request, reason=reason)

        return original(self, request)

    setattr(route, "_nija_terminal_guard_wrapped", True)
    setattr(cls, "route", route)
    logger.warning("%s patched=MultiBrokerExecutionRouter.route", _MARKER)
    return True


def _patch_ai_hub(module: ModuleType) -> bool:
    cls = getattr(module, "AIIntelligenceHub", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "evaluate_trade", None)
    if not callable(original) or getattr(original, "_nija_terminal_guard_wrapped", False):
        return False

    @wraps(original)
    def evaluate_trade(self: Any, *args: Any, **kwargs: Any):
        result = original(self, *args, **kwargs)
        text = " ".join(
            str(getattr(result, attr, "") or "")
            for attr in ("exposure_rejection_reason", "ai_reason", "reason")
        )
        if getattr(result, "exposure_allowed", True) is False or _contains_terminal_hard_block(text):
            if _contains_terminal_hard_block(text) or "hard" in text.lower() or "sector" in text.lower():
                reason = f"terminal_risk_hard_block:{text or 'risk engine hard block'}"
                for attr, value in (
                    ("exposure_allowed", False),
                    ("ai_approved", False),
                    ("approved", False),
                    ("allowed", False),
                    ("trade_allowed", False),
                    ("ai_score", 0.0),
                    ("allocated_capital", 0.0),
                ):
                    try:
                        setattr(result, attr, value)
                    except Exception:
                        pass
                try:
                    setattr(result, "ai_reason", reason)
                    setattr(result, "exposure_rejection_reason", reason)
                except Exception:
                    pass
                logger.critical(
                    "AI_HUB_TERMINAL_GUARD_BLOCK marker=20260707k symbol=%s side=%s reason=%s",
                    args[0] if args else kwargs.get("symbol", ""),
                    args[1] if len(args) > 1 else kwargs.get("side", ""),
                    reason,
                )
        return result

    setattr(evaluate_trade, "_nija_terminal_guard_wrapped", True)
    setattr(cls, "evaluate_trade", evaluate_trade)
    logger.warning("%s patched=AIIntelligenceHub.evaluate_trade", _MARKER)
    return True


def _patch_module(module: ModuleType) -> bool:
    name = getattr(module, "__name__", "")
    patched = False
    try:
        if name in {"bot.trade_permission_engine", "trade_permission_engine"}:
            patched = _patch_trade_permission_engine(module) or patched
        elif name in {"bot.execution_pipeline", "execution_pipeline"}:
            patched = _patch_execution_pipeline(module) or patched
        elif name in {"bot.multi_broker_execution_router", "multi_broker_execution_router"}:
            patched = _patch_multi_broker_router(module) or patched
        elif name in {"bot.ai_intelligence_hub", "ai_intelligence_hub"}:
            patched = _patch_ai_hub(module) or patched
    except Exception as exc:
        logger.warning("LIVE_EXECUTION_TERMINAL_GUARD_PATCH_FAILED marker=20260707k module=%s err=%s", name, exc)
    return patched


def _try_patch_loaded() -> bool:
    patched = False
    for name in tuple(_TARGETS):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_module(module) or patched
    return patched


def install_import_hook() -> None:
    if not _truthy_env("NIJA_LIVE_EXECUTION_TERMINAL_GUARD", "true"):
        logger.warning("LIVE_EXECUTION_TERMINAL_GUARD_DISABLED marker=20260707k")
        return

    _try_patch_loaded()
    if getattr(builtins, _IMPORT_FLAG, False):
        return

    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if name in _TARGETS or any(str(name).endswith(target.split(".")[-1]) for target in _TARGETS):
                _try_patch_loaded()
        except Exception as exc:
            logger.warning("LIVE_EXECUTION_TERMINAL_GUARD_IMPORT_HOOK_FAILED marker=20260707k name=%s err=%s", name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, _IMPORT_FLAG, True)
    logger.warning("LIVE_EXECUTION_TERMINAL_GUARD_IMPORT_HOOK_INSTALLED marker=20260707k")


def install() -> None:
    install_import_hook()
