"""Converged downstream equity and pre-dispatch risk-sizing repair.

The legacy implementation repeatedly wrapped ``ExecutionPipeline.execute`` whenever
another runtime guard became the outermost wrapper.  The broker-local readiness
monitor then wrapped the risk wrapper again, producing an ever-growing alternating
chain and eventually ``maximum recursion depth exceeded``.  The legacy exception
handler also failed open and dispatched the original entry request.

This implementation is chain-aware and idempotent.  It exposes ``__wrapped__`` on
every wrapper, detects its marker anywhere in the chain, blocks recursive entry
re-entry, and fails closed when live entry sizing cannot be verified.  Exit/reduce
requests bypass the entry-sizing layer unchanged.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from dataclasses import is_dataclass, replace
from functools import wraps
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.downstream_risk_governor_equity_repair")
_MARKER = "20260714-downstream-risk-v2"
_TRUTHY = {"1", "true", "yes", "on", "y", "enabled"}
_INSTALL_LOCK = threading.RLock()
_TLS = threading.local()
_MONITOR_STARTED = False

_DOWNSTREAM_ATTR = "_nija_downstream_risk_governor_equity_v2"
_PIPELINE_ATTR = "_nija_pre_dispatch_risk_sizing_v2"
_PRETRADE_ATTR = "_nija_pre_trade_strict_headroom_v2"
_TAXONOMY_ATTR = "_nija_broker_specific_taxonomy_v2"

_PATCH_STATE = {
    "downstream": False,
    "pipeline": False,
    "pretrade": False,
    "taxonomy": False,
}


def _truthy(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in _TRUTHY


def _live_runtime() -> bool:
    return not _truthy("DRY_RUN_MODE") and not _truthy("PAPER_MODE")


def _chain_contains(func: Any, attr: str) -> tuple[bool, bool, int]:
    """Return (marker_found, cycle_detected, depth) for an explicit wrapper chain."""
    current = func
    seen: set[int] = set()
    depth = 0
    while callable(current):
        ident = id(current)
        if ident in seen:
            return False, True, depth
        seen.add(ident)
        if bool(getattr(current, attr, False)):
            return True, False, depth
        nxt = getattr(current, "__wrapped__", None)
        if not callable(nxt):
            return False, False, depth
        current = nxt
        depth += 1
        if depth >= 4096:
            return False, True, depth
    return False, False, depth


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        if isinstance(value, str):
            value = value.replace("$", "").replace(",", "").strip()
            if not value:
                return default
        return float(value)
    except Exception:
        return default


def _float_env(*names: str, default: float = 0.0) -> float:
    for name in names:
        raw = os.environ.get(name)
        if raw is None or not str(raw).strip():
            continue
        try:
            value = float(str(raw).strip())
            if value > 0:
                return value
        except Exception:
            continue
    return default


def _live_equity_usd() -> float:
    best = 0.0
    try:
        try:
            from bot.capital_authority import get_capital_authority
        except ImportError:
            from capital_authority import get_capital_authority  # type: ignore[import]
        authority = get_capital_authority()
        for attr in ("total_capital", "real_capital"):
            best = max(best, _coerce_float(getattr(authority, attr, 0.0), 0.0))
        for method_name in ("get_real_capital", "get_usable_capital"):
            method = getattr(authority, method_name, None)
            if callable(method):
                best = max(best, _coerce_float(method(), 0.0))
    except Exception:
        return best
    return best


def _request_symbol(request: Any = None, fallback: str = "") -> str:
    return str(getattr(request, "symbol", fallback) or fallback).strip().upper()


def _request_broker(request: Any = None) -> str:
    for attr in (
        "preferred_broker", "broker", "broker_name", "selected_broker",
        "execution_broker", "venue", "exchange",
    ):
        try:
            value = getattr(request, attr, None)
            raw = getattr(value, "value", value)
            text = str(raw or "").strip().lower()
            if text:
                return text
        except Exception:
            continue
    return ""


def _infer_broker_for_min_notional(request: Any = None, *, symbol: str = "") -> str:
    broker = _request_broker(request)
    for name in ("okx", "coinbase", "kraken"):
        if name in broker:
            return name
    sym = _request_symbol(request, symbol)
    if sym.endswith("-USDT") and str(os.environ.get("NIJA_LAST_ENTRY_BROKER", "")).lower() != "coinbase":
        return "okx"
    if sym.endswith(("-USD", "-USDC")) and _float_env("COINBASE_MIN_ORDER_USD", default=0.0) > 0:
        return "coinbase"
    return broker or "auto"


def _minimum_live_notional_usd(request: Any = None, *, symbol: str = "") -> float:
    broker = _infer_broker_for_min_notional(request, symbol=symbol)
    if broker == "okx":
        return max(0.01, _float_env("OKX_MIN_ORDER_USD", "NIJA_OKX_MIN_ORDER_USD", default=10.0))
    if broker == "coinbase":
        return max(0.01, _float_env("COINBASE_MIN_ORDER_USD", "NIJA_COINBASE_MIN_ORDER_USD", default=1.0))
    if broker == "kraken":
        return max(
            0.01,
            _float_env(
                "KRAKEN_MIN_NOTIONAL_USD", "NIJA_KRAKEN_MIN_NOTIONAL_USD",
                "MIN_TRADE_USD", default=23.0,
            ),
        )
    return max(
        0.01,
        _float_env(
            "NIJA_MIN_EXPOSURE_HEADROOM_TRADE_USD", "MIN_TRADE_USD",
            "MIN_NOTIONAL_USD", "MIN_NOTIONAL_OVERRIDE", default=1.0,
        ),
    )


def _entry_increases_exposure(request: Any) -> bool:
    side = str(getattr(request, "side", "") or "").strip().lower()
    intent = str(getattr(request, "intent_type", "entry") or "entry").strip().lower()
    effect = str(getattr(request, "position_effect", "") or "").strip().lower()
    reduce_only = bool(getattr(request, "reduce_only", False))
    if reduce_only or intent in {"reduce", "exit", "close", "liquidate", "liquidation"}:
        return False
    if effect in {"reduce", "exit", "close"}:
        return False
    return side in {"buy", "long"}


def _resolve_available_balance_usd(request: Any) -> float:
    for attr in ("available_balance_usd", "buying_power_usd", "spendable_quote_usd"):
        value = _coerce_float(getattr(request, attr, None), 0.0)
        if value > 0:
            return value
    return _live_equity_usd()


def _replace_request_size(request: Any, new_size_usd: float) -> Any:
    size = max(0.0, float(new_size_usd))
    if is_dataclass(request):
        fields: dict[str, Any] = {"size_usd": size}
        if hasattr(request, "notional_usd"):
            fields["notional_usd"] = size
        return replace(request, **fields)
    try:
        import copy
        cloned = copy.copy(request)
    except Exception:
        cloned = request
    setattr(cloned, "size_usd", size)
    if hasattr(cloned, "notional_usd"):
        setattr(cloned, "notional_usd", size)
    return cloned


def _pipeline_deny(
    module: ModuleType,
    request: Any,
    started: float,
    reason: str,
    *,
    size_usd: Optional[float] = None,
) -> Any:
    result_cls = getattr(module, "PipelineResult", None)
    if not callable(result_cls):
        raise RuntimeError(reason)
    return result_cls(
        success=False,
        symbol=str(getattr(request, "symbol", "") or ""),
        side=str(getattr(request, "side", "") or ""),
        size_usd=float(size_usd if size_usd is not None else getattr(request, "size_usd", 0.0) or 0.0),
        error=reason,
        latency_ms=(time.monotonic() - started) * 1000.0,
    )


def _headroom_safety_buffer(headroom_usd: float) -> float:
    return max(0.01, min(0.10, max(0.0, headroom_usd) * 0.001))


def _entry_fail_closed(module: ModuleType, request: Any, started: float, reason: str) -> Any:
    logger.critical(
        "PRE_DISPATCH_RISK_SIZING_PATCH_FAIL_CLOSED marker=%s symbol=%s side=%s reason=%s",
        _MARKER,
        _request_symbol(request),
        getattr(request, "side", ""),
        reason,
    )
    return _pipeline_deny(module, request, started, reason)


def _install_on_downstream_blocker_guard(module: ModuleType) -> bool:
    cls = getattr(module, "DownstreamBlockerGuard", None)
    current = getattr(cls, "check_risk_governor", None) if isinstance(cls, type) else None
    if not callable(current):
        return False
    found, cycle, _depth = _chain_contains(current, _DOWNSTREAM_ATTR)
    if cycle:
        logger.critical("DOWNSTREAM_RISK_WRAPPER_CHAIN_CYCLE marker=%s component=governor", _MARKER)
        return False
    if found:
        _PATCH_STATE["downstream"] = True
        return True

    @wraps(current)
    def check_risk_governor(
        self: Any,
        symbol: str,
        proposed_risk_usd: float,
        portfolio_value: float = 0.0,
        volatility_ratio: float = 1.0,
    ) -> Any:
        live_equity = _live_equity_usd()
        incoming = _coerce_float(portfolio_value, 0.0)
        repaired = max(incoming, live_equity)
        if live_equity > incoming:
            logger.critical(
                "DOWNSTREAM_RISK_GOVERNOR_EQUITY_REPAIR_APPLIED marker=%s symbol=%s proposed_risk_usd=%.2f incoming_portfolio_value=%.2f live_equity_usd=%.2f repaired_portfolio_value=%.2f",
                _MARKER, symbol, _coerce_float(proposed_risk_usd), incoming, live_equity, repaired,
            )
        return current(self, symbol, proposed_risk_usd, repaired, volatility_ratio)

    setattr(check_risk_governor, _DOWNSTREAM_ATTR, True)
    setattr(check_risk_governor, "__wrapped__", current)
    cls.check_risk_governor = check_risk_governor
    _PATCH_STATE["downstream"] = True
    logger.warning("DOWNSTREAM_RISK_GOVERNOR_EQUITY_REPAIR_PATCHED marker=%s module=%s", _MARKER, module.__name__)
    return True


def _install_on_execution_pipeline(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionPipeline", None)
    current = getattr(cls, "execute", None) if isinstance(cls, type) else None
    if not callable(current):
        return False
    found, cycle, depth = _chain_contains(current, _PIPELINE_ATTR)
    if cycle:
        logger.critical(
            "PRE_DISPATCH_RISK_WRAPPER_CHAIN_CYCLE marker=%s module=%s depth=%d action=fail_closed",
            _MARKER, module.__name__, depth,
        )
        os.environ["NIJA_PRE_DISPATCH_RISK_SIZING_READY"] = "0"
        return False
    if found:
        _PATCH_STATE["pipeline"] = True
        os.environ["NIJA_PRE_DISPATCH_RISK_SIZING_READY"] = "1"
        return True

    @wraps(current)
    def execute(self: Any, request: Any, *args: Any, **kwargs: Any) -> Any:
        started = time.monotonic()
        if not _entry_increases_exposure(request):
            return current(self, request, *args, **kwargs)

        token = (id(self), threading.get_ident())
        active = getattr(_TLS, "active_entries", set())
        if token in active:
            return _entry_fail_closed(
                module,
                request,
                started,
                "PRE_DISPATCH_RISK_REENTRANCY_BLOCKED",
            )

        active = set(active)
        active.add(token)
        _TLS.active_entries = active
        dispatch_request = request
        try:
            normalize = getattr(module, "normalize_pipeline_request", None)
            working = normalize(request) if callable(normalize) else request
            requested = _coerce_float(getattr(working, "size_usd", 0.0), 0.0)
            if requested <= 0.0:
                return _entry_fail_closed(module, working, started, "PRE_DISPATCH_INVALID_ENTRY_SIZE")

            risk_engine = getattr(self, "_pre_trade_risk_engine", None)
            get_headroom = getattr(risk_engine, "get_remaining_headroom_usd", None)
            if not callable(get_headroom):
                if _live_runtime():
                    return _entry_fail_closed(module, working, started, "PRE_DISPATCH_RISK_ENGINE_UNAVAILABLE")
                return current(self, request, *args, **kwargs)

            account_id = str(getattr(working, "account_id", "default") or "default")
            available = _resolve_available_balance_usd(working)
            if available <= 0.0 and _live_runtime():
                return _entry_fail_closed(module, working, started, "PRE_DISPATCH_CAPITAL_SIGNAL_UNAVAILABLE")

            headroom = max(0.0, _coerce_float(get_headroom(account_id, available), 0.0))
            symbol = _request_symbol(working)
            minimum = _minimum_live_notional_usd(working, symbol=symbol)
            broker = _infer_broker_for_min_notional(working, symbol=symbol)

            logger.info(
                "PRE_DISPATCH_EXPOSURE_HEADROOM_CHECK marker=%s account=%s symbol=%s requested_size_usd=%.2f headroom_usd=%.2f min_notional_usd=%.2f broker=%s available_balance_usd=%.2f",
                _MARKER, account_id, symbol, requested, headroom, minimum, broker, available,
            )

            if headroom + 0.01 < requested:
                safe_size = max(0.0, headroom - _headroom_safety_buffer(headroom))
                if safe_size < minimum:
                    return _entry_fail_closed(
                        module,
                        working,
                        started,
                        "PreTradeRiskEngine reject: GLOBAL_EXPOSURE_CAP_HEADROOM_EXHAUSTED "
                        f"requested_size_usd={requested:.2f} headroom_usd={headroom:.2f} "
                        f"min_notional_usd={minimum:.2f} broker={broker}",
                    )
                dispatch_request = _replace_request_size(working, safe_size)
                logger.warning(
                    "PRE_DISPATCH_EXPOSURE_HEADROOM_CLIPPED marker=%s account=%s symbol=%s requested_size_usd=%.2f clipped_size_usd=%.2f headroom_usd=%.2f min_notional_usd=%.2f broker=%s",
                    _MARKER, account_id, symbol, requested, safe_size, headroom, minimum, broker,
                )
            else:
                dispatch_request = working
        except Exception as exc:
            if _live_runtime():
                return _entry_fail_closed(
                    module,
                    request,
                    started,
                    f"PRE_DISPATCH_RISK_SIZING_ERROR:{type(exc).__name__}:{exc}",
                )
            dispatch_request = request

        try:
            return current(self, dispatch_request, *args, **kwargs)
        except RecursionError as exc:
            return _entry_fail_closed(
                module,
                dispatch_request,
                started,
                f"PRE_DISPATCH_EXECUTION_CHAIN_RECURSION:{exc}",
            )
        finally:
            remaining = set(getattr(_TLS, "active_entries", set()))
            remaining.discard(token)
            _TLS.active_entries = remaining

    setattr(execute, _PIPELINE_ATTR, True)
    setattr(execute, "__wrapped__", current)
    cls.execute = execute
    _PATCH_STATE["pipeline"] = True
    os.environ["NIJA_PRE_DISPATCH_RISK_SIZING_READY"] = "1"
    logger.critical(
        "PRE_DISPATCH_RISK_SIZING_PIPELINE_PATCHED marker=%s module=%s chain_aware=true fail_closed=true exits_bypass=true",
        _MARKER, module.__name__,
    )
    return True


def _install_on_pre_trade_risk_engine(module: ModuleType) -> bool:
    cls = getattr(module, "PreTradeRiskEngine", None)
    decision_cls = getattr(module, "PreTradeRiskDecision", None)
    current = getattr(cls, "assess", None) if isinstance(cls, type) else None
    if not callable(current) or not callable(decision_cls):
        return False
    found, cycle, _depth = _chain_contains(current, _PRETRADE_ATTR)
    if cycle:
        logger.critical("PRE_TRADE_RISK_WRAPPER_CHAIN_CYCLE marker=%s", _MARKER)
        return False
    if found:
        _PATCH_STATE["pretrade"] = True
        return True

    @wraps(current)
    def assess(self: Any, *args: Any, **kwargs: Any) -> Any:
        decision = current(self, *args, **kwargs)
        if not bool(getattr(decision, "approved", False)):
            return decision
        try:
            intent = str(kwargs.get("intent_type") or "entry").lower()
            if kwargs.get("reduce_only") or intent in {"reduce", "exit", "close"}:
                return decision
            requested = _coerce_float(kwargs.get("size_usd"), 0.0)
            details = dict(getattr(decision, "details", {}) or {})
            headroom_raw = details.get("remaining_headroom_usd")
            if requested <= 0.0 or headroom_raw is None:
                return decision
            headroom = max(0.0, _coerce_float(headroom_raw, 0.0))
            if requested <= headroom + 0.01:
                return decision
            symbol = str(kwargs.get("symbol") or "")
            minimum = _minimum_live_notional_usd(symbol=symbol)
            details.update(
                requested_size_usd=requested,
                max_approved_size_usd=headroom,
                broker_aware_min_notional_usd=minimum,
            )
            if headroom >= minimum:
                details["action_required"] = "clip_before_execution_pipeline_dispatch"
                return decision_cls(approved=True, reason="approved_headroom_clip_required", details=details)
            details["action_required"] = "downsize_before_execution_pipeline_dispatch"
            return decision_cls(
                approved=False,
                reason="GLOBAL_EXPOSURE_CAP_HEADROOM_REQUIRES_DOWNSIZE",
                details=details,
            )
        except Exception as exc:
            if _live_runtime():
                return decision_cls(
                    approved=False,
                    reason=f"PRE_TRADE_HEADROOM_VALIDATION_ERROR:{type(exc).__name__}",
                    details={"error": str(exc), "fail_closed": True},
                )
            return decision

    setattr(assess, _PRETRADE_ATTR, True)
    setattr(assess, "__wrapped__", current)
    cls.assess = assess
    _PATCH_STATE["pretrade"] = True
    logger.warning("PRE_TRADE_STRICT_HEADROOM_PATCHED marker=%s module=%s", _MARKER, module.__name__)
    return True


def _manual_failure_details(broker_response: Any = None, exc: Optional[Exception] = None) -> dict[str, str]:
    response = broker_response if isinstance(broker_response, dict) else {}
    status = str(response.get("status") or ("exception" if exc else "unknown")).lower()
    error = response.get("error", "")
    if isinstance(error, (list, tuple)):
        error = ", ".join(str(item) for item in error if item)
    message = str(response.get("message") or "")
    detail = " | ".join(part for part in (str(error or ""), message, str(exc or "")) if part) or "Unknown execution failure"
    normalized = detail.lower()
    hint = "Inspect broker rejection payload"
    if any(term in normalized for term in ("too small", "minimum", "min notional")):
        hint = "Check minimum order size / exchange notional floor"
    elif any(term in normalized for term in ("insufficient", "fund", "balance")):
        hint = "Check per-broker available balance and fee-adjusted sizing"
    elif any(term in normalized for term in ("exposure", "risk", "cap")):
        hint = "Check pre-trade exposure/risk caps before broker dispatch"
    code = (str(error or message or status or "UNKNOWN_REJECTION"))[:120].upper().replace(" ", "_")
    return {"status": status, "error_code": code, "detail": detail, "hint": hint}


def _install_on_execution_engine(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionEngine", None)
    current = getattr(cls, "_extract_order_failure_details", None) if isinstance(cls, type) else None
    if not callable(current):
        return False
    found, cycle, _depth = _chain_contains(current, _TAXONOMY_ATTR)
    if cycle:
        return False
    if found:
        _PATCH_STATE["taxonomy"] = True
        return True

    @wraps(current)
    def extract(self: Any, broker_response: Any = None, exc: Optional[Exception] = None) -> dict[str, str]:
        label = "unknown"
        try:
            label = str(self._get_broker_label()).strip().lower()
        except Exception:
            pass
        if label == "kraken":
            return current(self, broker_response=broker_response, exc=exc)
        details = _manual_failure_details(broker_response=broker_response, exc=exc)
        details["broker"] = label
        return details

    setattr(extract, _TAXONOMY_ATTR, True)
    setattr(extract, "__wrapped__", current)
    cls._extract_order_failure_details = extract
    _PATCH_STATE["taxonomy"] = True
    return True


def _try_patch_loaded() -> bool:
    patched = False
    targets = (
        (("bot.downstream_blocker_guard", "downstream_blocker_guard"), _install_on_downstream_blocker_guard),
        (("bot.execution_pipeline", "execution_pipeline"), _install_on_execution_pipeline),
        (("bot.pre_trade_risk_engine", "pre_trade_risk_engine"), _install_on_pre_trade_risk_engine),
        (("bot.execution_engine", "execution_engine"), _install_on_execution_engine),
    )
    for names, installer in targets:
        for name in names:
            module = sys.modules.get(name)
            if isinstance(module, ModuleType):
                patched = installer(module) or patched
    return patched


def _monitor() -> None:
    deadline = time.monotonic() + max(60.0, float(os.environ.get("NIJA_PATCH_MONITOR_SECONDS", "600") or 600))
    while time.monotonic() < deadline:
        try:
            _try_patch_loaded()
            if all(_PATCH_STATE.values()):
                os.environ["NIJA_DOWNSTREAM_RISK_GOVERNOR_V2_READY"] = "1"
                return
        except Exception:
            logger.exception("DOWNSTREAM_RISK_V2_MONITOR_ERROR marker=%s", _MARKER)
        time.sleep(0.10)
    os.environ["NIJA_DOWNSTREAM_RISK_GOVERNOR_V2_READY"] = "0"
    logger.critical("DOWNSTREAM_RISK_V2_MONITOR_EXPIRED marker=%s state=%s", _MARKER, _PATCH_STATE)


def install_import_hook() -> None:
    global _MONITOR_STARTED
    with _INSTALL_LOCK:
        _try_patch_loaded()
        if not _MONITOR_STARTED:
            _MONITOR_STARTED = True
            threading.Thread(target=_monitor, name="downstream-risk-v2-monitor", daemon=True).start()
        os.environ["NIJA_DOWNSTREAM_RISK_GOVERNOR_V2_INSTALLED"] = "1"
        os.environ["NIJA_PRE_DISPATCH_RISK_SIZING_FAIL_CLOSED"] = "1"
        logger.critical(
            "DOWNSTREAM_RISK_GOVERNOR_V2_INSTALLED marker=%s chain_aware=true fail_closed=true exits_bypass=true state=%s",
            _MARKER, _PATCH_STATE,
        )


def install() -> None:
    install_import_hook()


__all__ = [
    "install",
    "install_import_hook",
    "_chain_contains",
    "_entry_increases_exposure",
    "_install_on_execution_pipeline",
    "_install_on_pre_trade_risk_engine",
    "_install_on_downstream_blocker_guard",
    "_minimum_live_notional_usd",
]
