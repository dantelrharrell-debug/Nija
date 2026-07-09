from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import logging
import os
import sys
import threading
import time
from dataclasses import replace
from datetime import datetime, timezone
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.live_execution_boundary_repair")

_TRUTHY = {"1", "true", "yes", "on", "enabled", "y"}
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_INSTALL_LOCK = threading.RLock()
_PATCHED_MODULES: set[tuple[str, int]] = set()
_QUARANTINE_LOCK = threading.RLock()
_MARKET_QUARANTINE: dict[tuple[str, str], tuple[float, str]] = {}

_TARGETS = {
    "bot.exchange_kill_switch",
    "exchange_kill_switch",
    "bot.execution_pipeline",
    "execution_pipeline",
    "bot.multi_broker_execution_router",
    "multi_broker_execution_router",
    "bot.ai_intelligence_hub",
    "ai_intelligence_hub",
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _truthy_env(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUTHY


def _enabled() -> bool:
    return _truthy_env("NIJA_LIVE_EXECUTION_BOUNDARY_REPAIR_ENABLED", "true")


def _int_env(name: str, default: int) -> int:
    try:
        return int(float(os.environ.get(name, default)))
    except Exception:
        return int(default)


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except Exception:
        return float(default)


def _norm_symbol(symbol: Any) -> str:
    return str(symbol or "").strip().upper().replace("/", "-")


def _norm_broker(broker: Any) -> str:
    text = str(broker or "").strip().lower().replace(" ", "_")
    if not text or text in {"none", "null", "auto", "unset"}:
        return ""
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


def _request_metadata(request: Any) -> dict[str, Any]:
    try:
        return dict(getattr(request, "metadata", {}) or {})
    except Exception:
        return {}


def _broker_from_request(request: Any) -> str:
    meta = _request_metadata(request)
    for value in (
        getattr(request, "preferred_broker", None),
        meta.get("broker_name"),
        meta.get("broker"),
        meta.get("broker_hint"),
        meta.get("venue"),
        meta.get("exchange"),
    ):
        broker = _norm_broker(value)
        if broker:
            return broker
    broker_obj = meta.get("broker_client")
    if broker_obj is not None:
        for attr in ("broker_type", "NAME", "name"):
            value = getattr(broker_obj, attr, None)
            value = getattr(value, "value", value)
            broker = _norm_broker(value)
            if broker:
                return broker
    return ""


def _broker_from_error(error: Any, fallback: str = "") -> str:
    text = str(error or "").lower()
    if "okx" in text or "sCode=51001".lower() in text or "51001" in text:
        return "okx"
    if "coinbase" in text:
        return "coinbase"
    if "kraken" in text:
        return "kraken"
    if "binance" in text:
        return "binance"
    return _norm_broker(fallback)


def _is_unsupported_market_error(error: Any) -> bool:
    text = str(error or "").strip().lower()
    if not text:
        return False
    exact_markers = (
        "unsupported_symbol_for_broker",
        "unsupported market",
        "unsupported symbol",
        "market not found",
        "symbol not found",
        "unknown symbol",
        "unknown instrument",
        "invalid instrument",
        "instrument_id_not_found",
        "instrument id doesn't exist",
        "instrument id does not exist",
        "instrument id not exist",
        "instrument doesn't exist",
        "instrument does not exist",
        "pair not found",
        "unknown asset pair",
        "equery:unknown asset pair",
        "product not found",
        "product_id not found",
    )
    if any(marker in text for marker in exact_markers):
        return True
    if "51001" in text and ("instrument" in text or "instid" in text or "inst id" in text or "okx" in text):
        return True
    if "doesn't exist" in text and ("instrument" in text or "market" in text or "symbol" in text or "pair" in text):
        return True
    if "does not exist" in text and ("instrument" in text or "market" in text or "symbol" in text or "pair" in text):
        return True
    return False


def _quarantine_ttl_s() -> float:
    return max(60.0, _float_env("NIJA_UNSUPPORTED_MARKET_QUARANTINE_TTL_S", 3600.0))


def _quarantine_market(broker: Any, symbol: Any, reason: Any) -> None:
    if not _truthy_env("NIJA_UNSUPPORTED_MARKET_QUARANTINE_ENABLED", "true"):
        return
    b = _norm_broker(broker)
    s = _norm_symbol(symbol)
    if not b or not s:
        return
    expiry = time.time() + _quarantine_ttl_s()
    reason_text = str(reason or "unsupported market").strip()[:500]
    with _QUARANTINE_LOCK:
        _MARKET_QUARANTINE[(b, s)] = (expiry, reason_text)
    logger.critical(
        "UNSUPPORTED_SYMBOL_FOR_BROKER_QUARANTINED broker=%s symbol=%s ttl_s=%.0f reason=%s",
        b,
        s,
        _quarantine_ttl_s(),
        reason_text,
    )
    print(
        f"[NIJA-PRINT] UNSUPPORTED_SYMBOL_FOR_BROKER_QUARANTINED | broker={b} symbol={s} ttl_s={_quarantine_ttl_s():.0f}",
        flush=True,
    )


def _quarantine_reason(broker: Any, symbol: Any) -> str:
    b = _norm_broker(broker)
    s = _norm_symbol(symbol)
    if not b or not s:
        return ""
    now = time.time()
    with _QUARANTINE_LOCK:
        expired = [key for key, (expiry, _reason) in _MARKET_QUARANTINE.items() if expiry <= now]
        for key in expired:
            _MARKET_QUARANTINE.pop(key, None)
        item = _MARKET_QUARANTINE.get((b, s))
    if not item:
        return ""
    return item[1]


def _route_asset_class(module: ModuleType, request: Any) -> Any:
    detect = getattr(module, "detect_asset_class", None)
    AssetClass = getattr(module, "AssetClass", None)
    raw_asset_class = str(getattr(request, "asset_class", "") or "").strip().lower()
    if raw_asset_class and AssetClass is not None:
        try:
            return AssetClass(raw_asset_class)
        except Exception:
            pass
    if callable(detect):
        try:
            return detect(getattr(request, "symbol", ""))
        except Exception:
            pass
    if AssetClass is not None:
        try:
            return AssetClass.CRYPTO
        except Exception:
            pass
    return "crypto"


def _asset_value(asset_class: Any) -> str:
    return str(getattr(asset_class, "value", asset_class) or "crypto")


# ---------------------------------------------------------------------------
# Patch: Exchange kill switch warm-up sample for order rejection rate
# ---------------------------------------------------------------------------


def _patch_exchange_kill_switch(module: ModuleType) -> bool:
    cls = getattr(module, "ExchangeKillSwitchProtector", None)
    GateResult = getattr(module, "GateResult", None)
    GateStatus = getattr(module, "GateStatus", None)
    if not isinstance(cls, type) or GateResult is None or GateStatus is None:
        return False

    original = getattr(cls, "_gate_order_rejection", None)
    if not callable(original) or getattr(original, "_nija_boundary_min_sample_wrapped", False):
        return True

    def _patched_gate_order_rejection(self: Any):
        min_sample = max(1, _int_env("NIJA_ORDER_REJECT_KILL_MIN_SAMPLE", 5))
        try:
            with self._lock:
                results = list(self._order_results)
        except Exception:
            return original(self)

        total = len(results)
        if total <= 0:
            return GateResult("order_rejection", GateStatus.GREEN, "No orders recorded yet")

        rejected = sum(1 for accepted in results if not accepted)
        rate = rejected / total if total else 0.0
        detail = {
            "window_orders": total,
            "rejected": rejected,
            "rejection_rate_pct": round(rate * 100, 1),
            "min_red_sample": min_sample,
            "warmup_active": total < min_sample,
        }

        if total < min_sample:
            caution = float(getattr(self._cfg, "order_reject_rate_caution", 0.25) or 0.25)
            if rejected and rate >= caution:
                return GateResult(
                    "order_rejection",
                    GateStatus.YELLOW,
                    f"Order rejection warmup {rate*100:.1f}% ({rejected}/{total}); "
                    f"minimum RED sample is {min_sample} orders",
                    detail,
                )
            return GateResult(
                "order_rejection",
                GateStatus.GREEN,
                f"Order rejection sample warming up ({total}/{min_sample})",
                detail,
            )

        return original(self)

    setattr(_patched_gate_order_rejection, "_nija_boundary_min_sample_wrapped", True)
    setattr(cls, "_gate_order_rejection", _patched_gate_order_rejection)
    logger.warning(
        "LIVE_EXECUTION_BOUNDARY_REPAIR_PATCHED exchange_kill_switch min_order_reject_sample=%d module=%s",
        _int_env("NIJA_ORDER_REJECT_KILL_MIN_SAMPLE", 5),
        getattr(module, "__name__", "<unknown>"),
    )
    return True


# ---------------------------------------------------------------------------
# Patch: ExecutionPipeline unsupported-market soft quarantine
# ---------------------------------------------------------------------------


def _patch_execution_pipeline(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionPipeline", None)
    PipelineResult = getattr(module, "PipelineResult", None)
    if not isinstance(cls, type) or PipelineResult is None:
        return False

    original_emit = getattr(cls, "_emit_execution_rejection_telemetry", None)
    if callable(original_emit) and not getattr(original_emit, "_nija_boundary_emit_wrapped", False):
        def _patched_emit_execution_rejection_telemetry(self: Any, *, symbol: str, side: str, reason: str) -> None:
            if _is_unsupported_market_error(reason):
                broker = _broker_from_error(reason, "")
                _quarantine_market(broker, symbol, reason)
                logger.warning(
                    "UNSUPPORTED_MARKET_REJECTION_NOT_COUNTED broker=%s symbol=%s side=%s reason=%s",
                    broker or "unknown",
                    _norm_symbol(symbol),
                    side,
                    str(reason or "")[:300],
                )
                return
            return original_emit(self, symbol=symbol, side=side, reason=reason)

        setattr(_patched_emit_execution_rejection_telemetry, "_nija_boundary_emit_wrapped", True)
        setattr(cls, "_emit_execution_rejection_telemetry", _patched_emit_execution_rejection_telemetry)

    original_rejected = getattr(cls, "_on_order_rejected", None)
    if callable(original_rejected) and not getattr(original_rejected, "_nija_boundary_reject_wrapped", False):
        def _patched_on_order_rejected(self: Any, request: Any, error: str) -> None:
            if _is_unsupported_market_error(error):
                broker = _broker_from_error(error, _broker_from_request(request))
                _quarantine_market(broker, getattr(request, "symbol", ""), error)
                logger.critical(
                    "UNSUPPORTED_SYMBOL_FOR_BROKER_SOFT_BLOCKED broker=%s symbol=%s error=%s",
                    broker or "unknown",
                    _norm_symbol(getattr(request, "symbol", "")),
                    str(error or "")[:500],
                )
                return
            return original_rejected(self, request, error)

        setattr(_patched_on_order_rejected, "_nija_boundary_reject_wrapped", True)
        setattr(cls, "_on_order_rejected", _patched_on_order_rejected)

    original_execute = getattr(cls, "execute", None)
    if callable(original_execute) and not getattr(original_execute, "_nija_boundary_execute_wrapped", False):
        def _patched_execute(self: Any, request: Any):
            symbol = _norm_symbol(getattr(request, "symbol", ""))
            side = str(getattr(request, "side", "") or "")
            size_usd = float(getattr(request, "size_usd", 0.0) or 0.0)
            broker = _broker_from_request(request)
            reason = _quarantine_reason(broker, symbol)
            if reason:
                logger.warning(
                    "ORDER_BLOCKED_BY_SYMBOL_BROKER_QUARANTINE broker=%s symbol=%s reason=%s",
                    broker,
                    symbol,
                    reason,
                )
                return PipelineResult(
                    success=False,
                    symbol=symbol,
                    side=side,
                    size_usd=size_usd,
                    broker=broker,
                    error=f"UNSUPPORTED_SYMBOL_FOR_BROKER_QUARANTINED broker={broker} symbol={symbol}: {reason}",
                    latency_ms=0.0,
                )

            result = original_execute(self, request)
            error = getattr(result, "error", "")
            if not bool(getattr(result, "success", False)) and _is_unsupported_market_error(error):
                result_broker = _broker_from_error(error, getattr(result, "broker", "") or broker)
                _quarantine_market(result_broker, getattr(result, "symbol", symbol), error)
            return result

        setattr(_patched_execute, "_nija_boundary_execute_wrapped", True)
        setattr(cls, "execute", _patched_execute)

    logger.warning("LIVE_EXECUTION_BOUNDARY_REPAIR_PATCHED execution_pipeline module=%s", getattr(module, "__name__", "<unknown>"))
    return True


# ---------------------------------------------------------------------------
# Patch: MultiBrokerExecutionRouter direct broker lineage and quarantine
# ---------------------------------------------------------------------------


def _patch_multi_broker_router(module: ModuleType) -> bool:
    cls = getattr(module, "MultiBrokerExecutionRouter", None)
    BrokerProfile = getattr(module, "BrokerProfile", None)
    RouteResult = getattr(module, "RouteResult", None)
    if not isinstance(cls, type) or BrokerProfile is None or RouteResult is None:
        return False

    original_profile = getattr(cls, "_profile_for_direct_broker", None)
    if callable(original_profile) and not getattr(original_profile, "_nija_boundary_direct_profile_wrapped", False):
        def _patched_profile_for_direct_broker(self: Any, asset_class: Any, request: Any):
            meta = _request_metadata(request)
            direct_broker = meta.get("broker_client")
            if direct_broker is not None:
                preferred = _broker_from_request(request)
                if preferred:
                    try:
                        with self._lock:
                            existing = self._brokers.get(preferred)
                    except Exception:
                        existing = None
                    if existing is not None:
                        return existing if getattr(existing, "available", True) else None

                    # Do not fall back to the first crypto profile when the live direct
                    # broker is a concrete venue (for example OKX) that is not registered
                    # in the static router table.  Returning a synthesized profile keeps
                    # broker lineage immutable: selected profile == live adapter.
                    min_notional = _float_env(f"NIJA_{preferred.upper()}_MIN_NOTIONAL_USD", _float_env(f"{preferred.upper()}_MIN_ORDER_USD", 1.0))
                    profile = BrokerProfile(
                        name=preferred,
                        asset_classes=[asset_class],
                        priority=0,
                        available=True,
                        dispatch_fn=self._dispatch_via_inner_router,
                        min_notional_usd=max(0.0, min_notional),
                        fee_bps=16.0,
                    )
                    try:
                        with self._lock:
                            self._last_routing_decision = {
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "asset_class": _asset_value(asset_class),
                                "side": getattr(request, "side", ""),
                                "size_usd": float(getattr(request, "size_usd", 0.0) or 0.0),
                                "selected_broker": preferred,
                                "reason": "direct_broker_client_synthesized_profile",
                                "preferred_broker": getattr(request, "preferred_broker", None),
                                "candidates": [{"broker": preferred, "eligible": True, "reason": "direct_broker_client"}],
                            }
                    except Exception:
                        pass
                    logger.warning(
                        "DIRECT_BROKER_PROFILE_SYNTHESIZED broker=%s symbol=%s asset_class=%s",
                        preferred,
                        _norm_symbol(getattr(request, "symbol", "")),
                        _asset_value(asset_class),
                    )
                    return profile
            return original_profile(self, asset_class, request)

        setattr(_patched_profile_for_direct_broker, "_nija_boundary_direct_profile_wrapped", True)
        setattr(cls, "_profile_for_direct_broker", _patched_profile_for_direct_broker)

    original_route = getattr(cls, "route", None)
    if callable(original_route) and not getattr(original_route, "_nija_boundary_route_wrapped", False):
        def _patched_route(self: Any, request: Any):
            symbol = _norm_symbol(getattr(request, "symbol", ""))
            broker = _broker_from_request(request)
            reason = _quarantine_reason(broker, symbol)
            if reason:
                ac = _route_asset_class(module, request)
                return RouteResult(
                    success=False,
                    symbol=symbol,
                    side=getattr(request, "side", ""),
                    size_usd=float(getattr(request, "size_usd", 0.0) or 0.0),
                    asset_class=_asset_value(ac),
                    broker=broker or "NONE",
                    fill_price=0.0,
                    filled_size_usd=0.0,
                    order_type=getattr(request, "order_type", None) or "MARKET",
                    latency_ms=0.0,
                    error=f"UNSUPPORTED_SYMBOL_FOR_BROKER_QUARANTINED broker={broker} symbol={symbol}: {reason}",
                )

            result = original_route(self, request)
            error = getattr(result, "error", "")
            if not bool(getattr(result, "success", False)) and _is_unsupported_market_error(error):
                result_broker = _broker_from_error(error, getattr(result, "broker", "") or broker)
                _quarantine_market(result_broker, getattr(result, "symbol", symbol), error)
            return result

        setattr(_patched_route, "_nija_boundary_route_wrapped", True)
        setattr(cls, "route", _patched_route)

    original_dispatch = getattr(cls, "_dispatch", None)
    if callable(original_dispatch) and not getattr(original_dispatch, "_nija_boundary_dispatch_wrapped", False):
        def _patched_dispatch(self: Any, request: Any, broker: Any):
            broker_name = _norm_broker(getattr(broker, "name", "") or _broker_from_request(request))
            symbol = _norm_symbol(getattr(request, "symbol", ""))
            reason = _quarantine_reason(broker_name, symbol)
            if reason:
                return 0.0, 0.0, f"UNSUPPORTED_SYMBOL_FOR_BROKER_QUARANTINED broker={broker_name} symbol={symbol}: {reason}"
            return original_dispatch(self, request, broker)

        setattr(_patched_dispatch, "_nija_boundary_dispatch_wrapped", True)
        setattr(cls, "_dispatch", _patched_dispatch)

    logger.warning("LIVE_EXECUTION_BOUNDARY_REPAIR_PATCHED multi_broker_router module=%s", getattr(module, "__name__", "<unknown>"))
    return True


# ---------------------------------------------------------------------------
# Patch: AI hub hard risk blocks are terminal
# ---------------------------------------------------------------------------


def _patch_ai_hub(module: ModuleType) -> bool:
    cls = getattr(module, "AIIntelligenceHub", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "evaluate_trade", None)
    if not callable(original) or getattr(original, "_nija_boundary_ai_hub_wrapped", False):
        return True

    def _patched_evaluate_trade(self: Any, symbol: str, side: str, df: Any, indicators: dict, base_size_pct: float, portfolio_value: float = 0.0):
        result = original(self, symbol, side, df, indicators, base_size_pct, portfolio_value)
        try:
            rejection = str(getattr(result, "exposure_rejection_reason", "") or "").lower()
            if getattr(result, "exposure_allowed", True) is False and "hard" in rejection:
                setattr(result, "ai_approved", False)
                setattr(result, "ai_score", 0.0)
                setattr(result, "ai_reason", f"terminal_risk_hard_block:{rejection}")
                return result

            risk_engine = getattr(self, "risk_engine", None)
            if risk_engine is None:
                return result
            pv = float(portfolio_value or 0.0)
            if pv <= 0.0:
                return result
            sync_positions = getattr(self, "_sync_risk_engine_with_live_positions", None)
            if callable(sync_positions):
                try:
                    sync_positions(pv)
                except Exception:
                    pass
            proposed = float(getattr(result, "allocated_capital", 0.0) or 0.0)
            if proposed <= 0.0:
                proposed = max(0.0, float(base_size_pct or 0.0) * pv)
            if proposed <= 0.0:
                return result

            check = getattr(risk_engine, "check_sector_limits", None)
            if not callable(check):
                return result
            allowed, _adjusted_size, info = check(symbol, proposed, pv)
            info = dict(info or {})
            if not allowed or bool(info.get("hard_limit_triggered")):
                reason = (
                    f"hard_sector_limit_block sector={info.get('sector_name') or info.get('sector')} "
                    f"projected_pct={float(info.get('projected_sector_exposure_pct', 0.0) or 0.0)*100:.1f} "
                    f"hard_limit_pct={float(getattr(risk_engine, 'hard_sector_limit_pct', 0.0) or 0.0)*100:.1f}"
                )
                setattr(result, "exposure_allowed", False)
                setattr(result, "exposure_rejection_reason", reason)
                setattr(result, "ai_approved", False)
                setattr(result, "ai_score", 0.0)
                setattr(result, "ai_reason", f"terminal_risk_hard_block:{reason}")
                logger.critical("AI_HUB_TERMINAL_RISK_HARD_BLOCK symbol=%s side=%s reason=%s", symbol, side, reason)
        except Exception as exc:
            logger.warning("AI_HUB_TERMINAL_RISK_PATCH_SKIPPED symbol=%s err=%s", symbol, exc)
        return result

    setattr(_patched_evaluate_trade, "_nija_boundary_ai_hub_wrapped", True)
    setattr(cls, "evaluate_trade", _patched_evaluate_trade)
    logger.warning("LIVE_EXECUTION_BOUNDARY_REPAIR_PATCHED ai_hub module=%s", getattr(module, "__name__", "<unknown>"))
    return True


# ---------------------------------------------------------------------------
# Import hook installer
# ---------------------------------------------------------------------------


def _patch_module(module: ModuleType) -> bool:
    if not _enabled():
        return False
    key = (getattr(module, "__name__", ""), id(module))
    if key in _PATCHED_MODULES:
        return True
    name = getattr(module, "__name__", "")
    patched = False
    try:
        if name in {"bot.exchange_kill_switch", "exchange_kill_switch"}:
            patched = _patch_exchange_kill_switch(module)
        elif name in {"bot.execution_pipeline", "execution_pipeline"}:
            patched = _patch_execution_pipeline(module)
        elif name in {"bot.multi_broker_execution_router", "multi_broker_execution_router"}:
            patched = _patch_multi_broker_router(module)
        elif name in {"bot.ai_intelligence_hub", "ai_intelligence_hub"}:
            patched = _patch_ai_hub(module)
    except Exception as exc:
        logger.warning("LIVE_EXECUTION_BOUNDARY_REPAIR_PATCH_FAILED module=%s err=%s", name, exc)
        patched = False
    if patched:
        _PATCHED_MODULES.add(key)
    return patched


def _patch_loaded() -> bool:
    patched = False
    for name in tuple(_TARGETS):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_module(module) or patched
    return patched


class _BoundaryRepairLoader(importlib.abc.Loader):
    def __init__(self, wrapped: importlib.abc.Loader) -> None:
        self._wrapped = wrapped

    def create_module(self, spec: Any) -> Any:
        create = getattr(self._wrapped, "create_module", None)
        if callable(create):
            return create(spec)
        return None

    def exec_module(self, module: Any) -> None:
        self._wrapped.exec_module(module)  # type: ignore[attr-defined]
        if isinstance(module, ModuleType):
            _patch_module(module)


class _BoundaryRepairFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> Any:
        if fullname not in _TARGETS:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None:
            return spec
        if isinstance(spec.loader, _BoundaryRepairLoader):
            return spec
        spec.loader = _BoundaryRepairLoader(spec.loader)  # type: ignore[assignment]
        return spec


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _INSTALL_LOCK:
        if not _enabled():
            logger.warning("LIVE_EXECUTION_BOUNDARY_REPAIR_DISABLED")
            return

        os.environ.setdefault("NIJA_ORDER_REJECT_KILL_MIN_SAMPLE", "5")
        os.environ.setdefault("NIJA_UNSUPPORTED_MARKET_QUARANTINE_TTL_S", "3600")
        os.environ.setdefault("NIJA_UNSUPPORTED_MARKET_QUARANTINE_ENABLED", "true")
        os.environ.setdefault("NIJA_STRICT_DIRECT_BROKER_LINEAGE", "true")

        _patch_loaded()

        if not any(isinstance(finder, _BoundaryRepairFinder) for finder in sys.meta_path):
            sys.meta_path.insert(0, _BoundaryRepairFinder())
            logger.warning("LIVE_EXECUTION_BOUNDARY_REPAIR_IMPORT_HOOK_INSTALLED")

        if _ORIGINAL_IMPORT_MODULE is None:
            _ORIGINAL_IMPORT_MODULE = importlib.import_module

            def _wrapped_import_module(name: str, package: str | None = None):
                module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
                if name in _TARGETS and isinstance(module, ModuleType):
                    _patch_module(module)
                return module

            importlib.import_module = _wrapped_import_module  # type: ignore[assignment]

        logger.warning(
            "LIVE_EXECUTION_BOUNDARY_REPAIR_INSTALL_COMPLETE min_order_reject_sample=%s quarantine_ttl_s=%s",
            os.environ.get("NIJA_ORDER_REJECT_KILL_MIN_SAMPLE", "5"),
            os.environ.get("NIJA_UNSUPPORTED_MARKET_QUARANTINE_TTL_S", "3600"),
        )
