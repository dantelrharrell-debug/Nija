"""Chain-aware, fail-closed downstream equity and risk-sizing convergence.

The former patch and the broker-local readiness patch repeatedly became each
other's outer wrapper. Because the former exposed no ``__wrapped__`` link and only
checked the outer function, the chain grew until ``maximum recursion depth
exceeded``. It then failed open and dispatched the original entry request.

This replacement detects its marker anywhere in an explicit wrapper chain, exposes
``__wrapped__`` on every wrapper, blocks same-thread entry reentry, and fails closed
when live entry sizing cannot be verified. Exit/reduce requests bypass this entry
sizing layer unchanged.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from dataclasses import is_dataclass, replace
from functools import wraps
from types import ModuleType
from typing import Any, Optional

logger = logging.getLogger("nija.downstream_risk_governor_equity_repair")
_MARKER = "20260714-downstream-risk-v2"
_TRUE = {"1", "true", "yes", "on", "y", "enabled"}
_LOCK = threading.RLock()
_TLS = threading.local()
_MONITOR_STARTED = False

_DOWNSTREAM_ATTR = "_nija_downstream_risk_governor_equity_v2"
_PIPELINE_ATTR = "_nija_pre_dispatch_risk_sizing_v2"
_PRETRADE_ATTR = "_nija_pre_trade_strict_headroom_v2"
_TAXONOMY_ATTR = "_nija_broker_specific_taxonomy_v2"
_STATE = {"downstream": False, "pipeline": False, "pretrade": False, "taxonomy": False}


def _truthy(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    return default if raw is None else str(raw).strip().lower() in _TRUE


def _live_runtime() -> bool:
    return not _truthy("DRY_RUN_MODE") and not _truthy("PAPER_MODE")


def _chain_contains(func: Any, attr: str) -> tuple[bool, bool, int]:
    current, seen, depth = func, set(), 0
    while callable(current):
        ident = id(current)
        if ident in seen:
            return False, True, depth
        seen.add(ident)
        if bool(getattr(current, attr, False)):
            return True, False, depth
        current = getattr(current, "__wrapped__", None)
        if not callable(current):
            return False, False, depth
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
            best = max(best, _coerce_float(getattr(authority, attr, 0.0)))
        for name in ("get_real_capital", "get_usable_capital"):
            method = getattr(authority, name, None)
            if callable(method):
                best = max(best, _coerce_float(method()))
    except Exception:
        pass
    return best


def _request_symbol(request: Any = None, fallback: str = "") -> str:
    return str(getattr(request, "symbol", fallback) or fallback).strip().upper()


def _request_broker(request: Any = None) -> str:
    for attr in (
        "preferred_broker", "broker", "broker_name", "selected_broker",
        "execution_broker", "venue", "exchange",
    ):
        value = getattr(request, attr, None)
        text = str(getattr(value, "value", value) or "").strip().lower()
        if text:
            return text
    return ""


def _infer_broker(request: Any = None, *, symbol: str = "") -> str:
    broker = _request_broker(request)
    for name in ("okx", "coinbase", "kraken"):
        if name in broker:
            return name
    sym = _request_symbol(request, symbol)
    if sym.endswith("-USDT") and str(os.environ.get("NIJA_LAST_ENTRY_BROKER", "")).lower() != "coinbase":
        return "okx"
    if sym.endswith(("-USD", "-USDC")) and _float_env("COINBASE_MIN_ORDER_USD") > 0:
        return "coinbase"
    return broker or "auto"


def _minimum_live_notional_usd(request: Any = None, *, symbol: str = "") -> float:
    broker = _infer_broker(request, symbol=symbol)
    if broker == "okx":
        return max(0.01, _float_env("OKX_MIN_ORDER_USD", "NIJA_OKX_MIN_ORDER_USD", default=10.0))
    if broker == "coinbase":
        return max(0.01, _float_env("COINBASE_MIN_ORDER_USD", "NIJA_COINBASE_MIN_ORDER_USD", default=1.0))
    if broker == "kraken":
        return max(0.01, _float_env("KRAKEN_MIN_NOTIONAL_USD", "NIJA_KRAKEN_MIN_NOTIONAL_USD", "MIN_TRADE_USD", default=23.0))
    return max(0.01, _float_env("NIJA_MIN_EXPOSURE_HEADROOM_TRADE_USD", "MIN_TRADE_USD", "MIN_NOTIONAL_USD", "MIN_NOTIONAL_OVERRIDE", default=1.0))


def _entry_increases_exposure(request: Any) -> bool:
    side = str(getattr(request, "side", "") or "").lower()
    intent = str(getattr(request, "intent_type", "entry") or "entry").lower()
    effect = str(getattr(request, "position_effect", "") or "").lower()
    if bool(getattr(request, "reduce_only", False)):
        return False
    if intent in {"reduce", "exit", "close", "liquidate", "liquidation"}:
        return False
    if effect in {"reduce", "exit", "close"}:
        return False
    return side in {"buy", "long"}


def _available_balance(request: Any) -> float:
    for attr in ("available_balance_usd", "buying_power_usd", "spendable_quote_usd"):
        value = _coerce_float(getattr(request, attr, None))
        if value > 0:
            return value
    return _live_equity_usd()


def _replace_size(request: Any, size: float) -> Any:
    size = max(0.0, float(size))
    if is_dataclass(request):
        fields = {"size_usd": size}
        if hasattr(request, "notional_usd"):
            fields["notional_usd"] = size
        return replace(request, **fields)
    try:
        import copy
        result = copy.copy(request)
    except Exception:
        result = request
    setattr(result, "size_usd", size)
    if hasattr(result, "notional_usd"):
        setattr(result, "notional_usd", size)
    return result


def _deny(module: ModuleType, request: Any, started: float, reason: str) -> Any:
    logger.critical(
        "PRE_DISPATCH_RISK_SIZING_PATCH_FAIL_CLOSED marker=%s symbol=%s side=%s reason=%s",
        _MARKER, _request_symbol(request), getattr(request, "side", ""), reason,
    )
    result_cls = getattr(module, "PipelineResult", None)
    if not callable(result_cls):
        raise RuntimeError(reason)
    return result_cls(
        success=False,
        symbol=str(getattr(request, "symbol", "") or ""),
        side=str(getattr(request, "side", "") or ""),
        size_usd=_coerce_float(getattr(request, "size_usd", 0.0)),
        error=reason,
        latency_ms=(time.monotonic() - started) * 1000.0,
    )


def _install_on_downstream_blocker_guard(module: ModuleType) -> bool:
    cls = getattr(module, "DownstreamBlockerGuard", None)
    current = getattr(cls, "check_risk_governor", None) if isinstance(cls, type) else None
    if not callable(current):
        return False
    found, cycle, _ = _chain_contains(current, _DOWNSTREAM_ATTR)
    if cycle:
        return False
    if found:
        _STATE["downstream"] = True
        return True

    @wraps(current)
    def check(self: Any, symbol: str, proposed_risk_usd: float, portfolio_value: float = 0.0, volatility_ratio: float = 1.0) -> Any:
        incoming = _coerce_float(portfolio_value)
        live = _live_equity_usd()
        repaired = max(incoming, live)
        if live > incoming:
            logger.critical(
                "DOWNSTREAM_RISK_GOVERNOR_EQUITY_REPAIR_APPLIED marker=%s symbol=%s incoming=%.2f live=%.2f repaired=%.2f",
                _MARKER, symbol, incoming, live, repaired,
            )
        return current(self, symbol, proposed_risk_usd, repaired, volatility_ratio)

    setattr(check, _DOWNSTREAM_ATTR, True)
    check.__wrapped__ = current
    cls.check_risk_governor = check
    _STATE["downstream"] = True
    return True


def _install_on_execution_pipeline(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionPipeline", None)
    current = getattr(cls, "execute", None) if isinstance(cls, type) else None
    if not callable(current):
        return False
    found, cycle, depth = _chain_contains(current, _PIPELINE_ATTR)
    if cycle:
        logger.critical("PRE_DISPATCH_RISK_WRAPPER_CHAIN_CYCLE marker=%s module=%s depth=%d", _MARKER, module.__name__, depth)
        os.environ["NIJA_PRE_DISPATCH_RISK_SIZING_READY"] = "0"
        return False
    if found:
        _STATE["pipeline"] = True
        os.environ["NIJA_PRE_DISPATCH_RISK_SIZING_READY"] = "1"
        return True

    @wraps(current)
    def execute(self: Any, request: Any, *args: Any, **kwargs: Any) -> Any:
        started = time.monotonic()
        if not _entry_increases_exposure(request):
            return current(self, request, *args, **kwargs)

        token = (id(self), threading.get_ident())
        active = set(getattr(_TLS, "active_entries", set()))
        if token in active:
            return _deny(module, request, started, "PRE_DISPATCH_RISK_REENTRANCY_BLOCKED")
        active.add(token)
        _TLS.active_entries = active

        try:
            dispatch_request = request
            try:
                normalize = getattr(module, "normalize_pipeline_request", None)
                working = normalize(request) if callable(normalize) else request
                requested = _coerce_float(getattr(working, "size_usd", 0.0))
                if requested <= 0:
                    return _deny(module, working, started, "PRE_DISPATCH_INVALID_ENTRY_SIZE")

                engine = getattr(self, "_pre_trade_risk_engine", None)
                headroom_fn = getattr(engine, "get_remaining_headroom_usd", None)
                if not callable(headroom_fn):
                    if _live_runtime():
                        return _deny(module, working, started, "PRE_DISPATCH_RISK_ENGINE_UNAVAILABLE")
                    return current(self, request, *args, **kwargs)

                account = str(getattr(working, "account_id", "default") or "default")
                available = _available_balance(working)
                if available <= 0 and _live_runtime():
                    return _deny(module, working, started, "PRE_DISPATCH_CAPITAL_SIGNAL_UNAVAILABLE")
                headroom = max(0.0, _coerce_float(headroom_fn(account, available)))
                symbol = _request_symbol(working)
                minimum = _minimum_live_notional_usd(working, symbol=symbol)
                broker = _infer_broker(working, symbol=symbol)

                logger.info(
                    "PRE_DISPATCH_EXPOSURE_HEADROOM_CHECK marker=%s account=%s symbol=%s requested=%.2f headroom=%.2f minimum=%.2f broker=%s available=%.2f",
                    _MARKER, account, symbol, requested, headroom, minimum, broker, available,
                )
                if headroom + 0.01 < requested:
                    safe = max(0.0, headroom - max(0.01, min(0.10, headroom * 0.001)))
                    if safe < minimum:
                        return _deny(
                            module, working, started,
                            "GLOBAL_EXPOSURE_CAP_HEADROOM_EXHAUSTED "
                            f"requested={requested:.2f} headroom={headroom:.2f} minimum={minimum:.2f} broker={broker}",
                        )
                    dispatch_request = _replace_size(working, safe)
                    logger.warning(
                        "PRE_DISPATCH_EXPOSURE_HEADROOM_CLIPPED marker=%s account=%s symbol=%s requested=%.2f clipped=%.2f headroom=%.2f minimum=%.2f broker=%s",
                        _MARKER, account, symbol, requested, safe, headroom, minimum, broker,
                    )
                else:
                    dispatch_request = working
            except Exception as exc:
                if _live_runtime():
                    return _deny(module, request, started, f"PRE_DISPATCH_RISK_SIZING_ERROR:{type(exc).__name__}:{exc}")
                dispatch_request = request

            try:
                return current(self, dispatch_request, *args, **kwargs)
            except RecursionError as exc:
                return _deny(module, dispatch_request, started, f"PRE_DISPATCH_EXECUTION_CHAIN_RECURSION:{exc}")
        finally:
            remaining = set(getattr(_TLS, "active_entries", set()))
            remaining.discard(token)
            _TLS.active_entries = remaining

    setattr(execute, _PIPELINE_ATTR, True)
    execute.__wrapped__ = current
    cls.execute = execute
    _STATE["pipeline"] = True
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
    found, cycle, _ = _chain_contains(current, _PRETRADE_ATTR)
    if cycle:
        return False
    if found:
        _STATE["pretrade"] = True
        return True

    @wraps(current)
    def assess(self: Any, *args: Any, **kwargs: Any) -> Any:
        decision = current(self, *args, **kwargs)
        if not bool(getattr(decision, "approved", False)):
            return decision
        try:
            if kwargs.get("reduce_only") or str(kwargs.get("intent_type") or "entry").lower() in {"reduce", "exit", "close"}:
                return decision
            requested = _coerce_float(kwargs.get("size_usd"))
            details = dict(getattr(decision, "details", {}) or {})
            raw = details.get("remaining_headroom_usd")
            if requested <= 0 or raw is None:
                return decision
            headroom = max(0.0, _coerce_float(raw))
            if requested <= headroom + 0.01:
                return decision
            minimum = _minimum_live_notional_usd(symbol=str(kwargs.get("symbol") or ""))
            details.update(requested_size_usd=requested, max_approved_size_usd=headroom, broker_aware_min_notional_usd=minimum)
            if headroom >= minimum:
                details["action_required"] = "clip_before_execution_pipeline_dispatch"
                return decision_cls(approved=True, reason="approved_headroom_clip_required", details=details)
            details["action_required"] = "downsize_before_execution_pipeline_dispatch"
            return decision_cls(approved=False, reason="GLOBAL_EXPOSURE_CAP_HEADROOM_REQUIRES_DOWNSIZE", details=details)
        except Exception as exc:
            if _live_runtime():
                return decision_cls(approved=False, reason=f"PRE_TRADE_HEADROOM_VALIDATION_ERROR:{type(exc).__name__}", details={"error": str(exc), "fail_closed": True})
            return decision

    setattr(assess, _PRETRADE_ATTR, True)
    assess.__wrapped__ = current
    cls.assess = assess
    _STATE["pretrade"] = True
    return True


def _install_on_execution_engine(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionEngine", None)
    current = getattr(cls, "_extract_order_failure_details", None) if isinstance(cls, type) else None
    if not callable(current):
        return False
    found, cycle, _ = _chain_contains(current, _TAXONOMY_ATTR)
    if cycle:
        return False
    if found:
        _STATE["taxonomy"] = True
        return True

    @wraps(current)
    def extract(self: Any, broker_response: Any = None, exc: Optional[Exception] = None) -> dict[str, str]:
        try:
            label = str(self._get_broker_label()).strip().lower()
        except Exception:
            label = "unknown"
        if label == "kraken":
            return current(self, broker_response=broker_response, exc=exc)
        response = broker_response if isinstance(broker_response, dict) else {}
        status = str(response.get("status") or ("exception" if exc else "unknown")).lower()
        error = response.get("error", "")
        if isinstance(error, (list, tuple)):
            error = ", ".join(str(item) for item in error if item)
        message = str(response.get("message") or "")
        detail = " | ".join(part for part in (str(error or ""), message, str(exc or "")) if part) or "Unknown execution failure"
        return {
            "status": status,
            "error_code": str(error or message or status or "UNKNOWN_REJECTION")[:120].upper().replace(" ", "_"),
            "detail": detail,
            "hint": "Inspect broker rejection payload",
            "broker": label,
        }

    setattr(extract, _TAXONOMY_ATTR, True)
    extract.__wrapped__ = current
    cls._extract_order_failure_details = extract
    _STATE["taxonomy"] = True
    return True


def _try_patch_loaded() -> bool:
    changed = False
    targets = (
        (("bot.downstream_blocker_guard", "downstream_blocker_guard"), _install_on_downstream_blocker_guard),
        (("bot.execution_pipeline", "execution_pipeline"), _install_on_execution_pipeline),
        (("bot.pre_trade_risk_engine", "pre_trade_risk_engine"), _install_on_pre_trade_risk_engine),
        (("bot.execution_engine", "execution_engine"), _install_on_execution_engine),
    )
    for names, installer in targets:
        loaded_module: ModuleType | None = None
        for name in names:
            module = sys.modules.get(name)
            if isinstance(module, ModuleType):
                loaded_module = module
                break
        if loaded_module is None and installer is _install_on_pre_trade_risk_engine:
            for name in names:
                try:
                    module = importlib.import_module(name)
                except Exception:
                    continue
                if isinstance(module, ModuleType):
                    loaded_module = module
                    break
        if isinstance(loaded_module, ModuleType):
            changed = installer(loaded_module) or changed
    return changed


def _monitor() -> None:
    deadline = time.monotonic() + max(60.0, float(os.environ.get("NIJA_PATCH_MONITOR_SECONDS", "600") or 600))
    while time.monotonic() < deadline:
        try:
            _try_patch_loaded()
            if all(_STATE.values()):
                os.environ["NIJA_DOWNSTREAM_RISK_GOVERNOR_V2_READY"] = "1"
                return
        except Exception:
            logger.exception("DOWNSTREAM_RISK_V2_MONITOR_ERROR marker=%s", _MARKER)
        time.sleep(0.10)
    os.environ["NIJA_DOWNSTREAM_RISK_GOVERNOR_V2_READY"] = "0"
    logger.critical("DOWNSTREAM_RISK_V2_MONITOR_EXPIRED marker=%s state=%s", _MARKER, _STATE)


def install_import_hook() -> None:
    global _MONITOR_STARTED
    with _LOCK:
        _try_patch_loaded()
        if not _MONITOR_STARTED:
            _MONITOR_STARTED = True
            threading.Thread(target=_monitor, name="downstream-risk-v2-monitor", daemon=True).start()
        os.environ["NIJA_DOWNSTREAM_RISK_GOVERNOR_V2_INSTALLED"] = "1"
        os.environ["NIJA_PRE_DISPATCH_RISK_SIZING_FAIL_CLOSED"] = "1"
        logger.critical(
            "DOWNSTREAM_RISK_GOVERNOR_V2_INSTALLED marker=%s chain_aware=true fail_closed=true exits_bypass=true state=%s",
            _MARKER, _STATE,
        )


def install() -> None:
    install_import_hook()


__all__ = [
    "install", "install_import_hook", "_chain_contains", "_entry_increases_exposure",
    "_install_on_execution_pipeline", "_install_on_pre_trade_risk_engine",
    "_install_on_downstream_blocker_guard", "_minimum_live_notional_usd",
]
