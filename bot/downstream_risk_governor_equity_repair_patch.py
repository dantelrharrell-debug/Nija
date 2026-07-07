from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from dataclasses import is_dataclass, replace
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.downstream_risk_governor_equity_repair")
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_PATCHED = False
_MONITOR_STARTED = False
_INSTALL_LOCK = threading.Lock()
_PIPELINE_PATCHED = False
_PRE_TRADE_RISK_PATCHED = False
_EXECUTION_ENGINE_TAXONOMY_PATCHED = False
_TRUTHY = {"1", "true", "yes", "on", "y", "enabled"}


# ---------------------------------------------------------------------------
# Existing downstream risk-governor equity repair
# ---------------------------------------------------------------------------

def _live_equity_usd() -> float:
    best = 0.0
    try:
        try:
            from bot.capital_authority import get_capital_authority
        except ImportError:
            from capital_authority import get_capital_authority  # type: ignore[import]
        ca = get_capital_authority()
        for attr in ("total_capital", "real_capital"):
            try:
                best = max(best, float(getattr(ca, attr, 0.0) or 0.0))
            except Exception:
                pass
        for meth in ("get_real_capital", "get_usable_capital"):
            getter = getattr(ca, meth, None)
            if callable(getter):
                try:
                    best = max(best, float(getter() or 0.0))
                except Exception:
                    pass
    except Exception:
        pass
    return best


def _install_on_downstream_blocker_guard(module: ModuleType) -> bool:
    global _PATCHED
    cls = getattr(module, "DownstreamBlockerGuard", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "check_risk_governor", None)
    if not callable(original):
        return False
    if getattr(original, "_nija_downstream_risk_governor_equity_repair_wrapped", False):
        _PATCHED = True
        return True

    def _patched_check_risk_governor(self: Any, symbol: str, proposed_risk_usd: float, portfolio_value: float = 0.0, volatility_ratio: float = 1.0):
        live_equity = _live_equity_usd()
        incoming = float(portfolio_value or 0.0)
        repaired_value = max(incoming, live_equity)
        if live_equity > 0.0 and repaired_value > incoming:
            logger.critical(
                "DOWNSTREAM_RISK_GOVERNOR_EQUITY_REPAIR_APPLIED symbol=%s proposed_risk_usd=%.2f incoming_portfolio_value=%.2f live_equity_usd=%.2f repaired_portfolio_value=%.2f",
                symbol,
                float(proposed_risk_usd or 0.0),
                incoming,
                live_equity,
                repaired_value,
            )
            print(
                f"[NIJA-PRINT] DOWNSTREAM_RISK_GOVERNOR_EQUITY_REPAIR_APPLIED | symbol={symbol} proposed=${float(proposed_risk_usd or 0.0):.2f} portfolio_value=${repaired_value:.2f}",
                flush=True,
            )
        return original(self, symbol, proposed_risk_usd, repaired_value, volatility_ratio)

    setattr(_patched_check_risk_governor, "_nija_downstream_risk_governor_equity_repair_wrapped", True)
    setattr(cls, "check_risk_governor", _patched_check_risk_governor)
    _PATCHED = True
    logger.warning("DOWNSTREAM_RISK_GOVERNOR_EQUITY_REPAIR_PATCHED module=%s", getattr(module, "__name__", "<unknown>"))
    return True


# ---------------------------------------------------------------------------
# July 6/7 live-execution fix: broker-aware exposure-headroom sizing before
# ECEL/broker dispatch.
# ---------------------------------------------------------------------------

def _truthy(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in _TRUTHY


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        if isinstance(value, str):
            value = value.replace("$", "").replace(",", "").strip()
            if value == "":
                return default
        return float(value)
    except Exception:
        return default


def _float_env(*names: str, default: float = 0.0) -> float:
    for name in names:
        raw = os.environ.get(name)
        if raw is None or str(raw).strip() == "":
            continue
        try:
            value = float(str(raw).strip())
            if value > 0:
                return value
        except Exception:
            continue
    return default


def _request_symbol(request: Any = None, fallback: str = "") -> str:
    try:
        return str(getattr(request, "symbol", fallback) or fallback).strip().upper()
    except Exception:
        return str(fallback or "").strip().upper()


def _request_broker(request: Any = None) -> str:
    for attr in ("broker", "broker_name", "selected_broker", "venue", "exchange"):
        try:
            value = getattr(request, attr, None)
            raw = getattr(value, "value", value)
            text = str(raw or "").strip().lower()
            if text:
                return text
        except Exception:
            pass
    return ""


def _infer_broker_for_min_notional(request: Any = None, *, symbol: str = "") -> str:
    broker = _request_broker(request)
    if any(key in broker for key in ("okx", "coinbase", "kraken")):
        return "okx" if "okx" in broker else "coinbase" if "coinbase" in broker else "kraken"
    sym = _request_symbol(request, symbol)
    # When the active route selected OKX, USDT pairs are usually OKX-native. This
    # avoids applying the global Kraken $23.10 floor to OKX entries that can fill
    # at the OKX $10 floor.
    if sym.endswith("-USDT") and str(os.environ.get("NIJA_LAST_ENTRY_BROKER", "")).lower() != "coinbase":
        return "okx"
    if sym.endswith("-USD") or sym.endswith("-USDC"):
        if _float_env("COINBASE_MIN_ORDER_USD", default=0.0) > 0:
            return "coinbase"
    return broker or "auto"


def _minimum_live_notional_usd(request: Any = None, *, symbol: str = "") -> float:
    broker = _infer_broker_for_min_notional(request, symbol=symbol)
    if broker == "okx":
        return max(0.01, _float_env("OKX_MIN_ORDER_USD", "NIJA_OKX_MIN_ORDER_USD", default=10.0))
    if broker == "coinbase":
        return max(0.01, _float_env("COINBASE_MIN_ORDER_USD", "NIJA_COINBASE_MIN_ORDER_USD", default=1.0))
    if broker == "kraken":
        return max(0.01, _float_env("KRAKEN_MIN_NOTIONAL_USD", "NIJA_KRAKEN_MIN_NOTIONAL_USD", "MIN_TRADE_USD", default=23.0))
    return max(
        0.01,
        _float_env(
            "NIJA_MIN_EXPOSURE_HEADROOM_TRADE_USD",
            "MIN_TRADE_USD",
            "MIN_NOTIONAL_USD",
            "MIN_NOTIONAL_OVERRIDE",
            default=1.0,
        ),
    )


def _entry_increases_exposure(request: Any) -> bool:
    side = str(getattr(request, "side", "") or "").strip().lower()
    intent = str(getattr(request, "intent_type", "") or "entry").strip().lower()
    reduce_only = bool(getattr(request, "reduce_only", False))
    if reduce_only or intent in {"reduce", "exit", "close"}:
        return False
    return side in {"buy", "long"}


def _resolve_available_balance_usd(request: Any) -> float:
    available = _coerce_float(getattr(request, "available_balance_usd", None), 0.0)
    if available > 0:
        return available
    return _live_equity_usd()


def _replace_request_size(request: Any, new_size_usd: float) -> Any:
    new_size_usd = max(0.0, float(new_size_usd))
    if is_dataclass(request):
        fields: dict[str, Any] = {"size_usd": new_size_usd}
        if hasattr(request, "notional_usd"):
            fields["notional_usd"] = new_size_usd
        return replace(request, **fields)
    try:
        import copy
        cloned = copy.copy(request)
        setattr(cloned, "size_usd", new_size_usd)
        if hasattr(cloned, "notional_usd"):
            setattr(cloned, "notional_usd", new_size_usd)
        return cloned
    except Exception:
        setattr(request, "size_usd", new_size_usd)
        if hasattr(request, "notional_usd"):
            setattr(request, "notional_usd", new_size_usd)
        return request


def _pipeline_deny(module: ModuleType, request: Any, t_start: float, reason: str, *, size_usd: Optional[float] = None) -> Any:
    result_cls = getattr(module, "PipelineResult", None)
    if not callable(result_cls):
        return None
    return result_cls(
        success=False,
        symbol=str(getattr(request, "symbol", "") or ""),
        side=str(getattr(request, "side", "") or ""),
        size_usd=float(size_usd if size_usd is not None else getattr(request, "size_usd", 0.0) or 0.0),
        error=reason,
        latency_ms=(time.monotonic() - t_start) * 1000.0,
    )


def _headroom_safety_buffer(headroom_usd: float) -> float:
    return max(0.01, min(0.10, max(0.0, headroom_usd) * 0.001))


def _install_on_execution_pipeline(module: ModuleType) -> bool:
    global _PIPELINE_PATCHED
    cls = getattr(module, "ExecutionPipeline", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "execute", None)
    if not callable(original):
        return False
    if getattr(original, "_nija_pre_dispatch_exposure_headroom_wrapped_20260707a", False):
        _PIPELINE_PATCHED = True
        return True

    def _patched_execute(self: Any, request: Any, *args: Any, **kwargs: Any) -> Any:
        t_start = time.monotonic()
        if not _truthy("NIJA_PRE_DISPATCH_RISK_SIZING_PATCH_ENABLED", True):
            return original(self, request, *args, **kwargs)

        try:
            normalize = getattr(module, "normalize_pipeline_request", None)
            working_request = normalize(request) if callable(normalize) else request
            if not _entry_increases_exposure(working_request):
                return original(self, request, *args, **kwargs)

            risk_engine = getattr(self, "_pre_trade_risk_engine", None)
            get_headroom = getattr(risk_engine, "get_remaining_headroom_usd", None)
            requested_size = _coerce_float(getattr(working_request, "size_usd", 0.0), 0.0)
            if not callable(get_headroom) or requested_size <= 0.0:
                return original(self, request, *args, **kwargs)

            account_id = str(getattr(working_request, "account_id", "default") or "default")
            available_balance = _resolve_available_balance_usd(working_request)
            headroom = max(0.0, _coerce_float(get_headroom(account_id, available_balance), 0.0))
            symbol = _request_symbol(working_request)
            min_notional = _minimum_live_notional_usd(working_request, symbol=symbol)
            inferred_broker = _infer_broker_for_min_notional(working_request, symbol=symbol)

            # If there is no reliable capital signal yet, preserve the legacy path;
            # the regular pre-trade risk engine and capital gates still run next.
            if available_balance <= 0.0 and headroom <= 0.0:
                logger.warning(
                    "PRE_DISPATCH_EXPOSURE_HEADROOM_CHECK_SKIPPED account=%s symbol=%s reason=no_available_balance_or_headroom_signal requested_size_usd=%.2f",
                    account_id,
                    symbol,
                    requested_size,
                )
                return original(self, request, *args, **kwargs)

            logger.info(
                "PRE_DISPATCH_EXPOSURE_HEADROOM_CHECK account=%s symbol=%s side=%s requested_size_usd=%.2f headroom_usd=%.2f min_notional_usd=%.2f inferred_broker=%s available_balance_usd=%.2f",
                account_id,
                symbol,
                getattr(working_request, "side", ""),
                requested_size,
                headroom,
                min_notional,
                inferred_broker,
                available_balance,
            )

            if headroom + 0.01 >= requested_size:
                return original(self, request, *args, **kwargs)

            safe_size = max(0.0, headroom - _headroom_safety_buffer(headroom))
            if safe_size < min_notional:
                reason = (
                    "PreTradeRiskEngine reject: GLOBAL_EXPOSURE_CAP_HEADROOM_EXHAUSTED "
                    f"requested_size_usd={requested_size:.2f} headroom_usd={headroom:.2f} "
                    f"min_notional_usd={min_notional:.2f} broker={inferred_broker}"
                )
                logger.warning(
                    "PRE_DISPATCH_EXPOSURE_HEADROOM_REJECT account=%s symbol=%s requested_size_usd=%.2f headroom_usd=%.2f min_notional_usd=%.2f inferred_broker=%s action=skip_before_ecel",
                    account_id,
                    symbol,
                    requested_size,
                    headroom,
                    min_notional,
                    inferred_broker,
                )
                denied = _pipeline_deny(module, working_request, t_start, reason, size_usd=requested_size)
                if denied is not None:
                    return denied
                return original(self, request, *args, **kwargs)

            resized_request = _replace_request_size(working_request, safe_size)
            logger.warning(
                "PRE_DISPATCH_EXPOSURE_HEADROOM_CLIP_BROKER_AWARE marker=20260707a account=%s symbol=%s requested_size_usd=%.2f clipped_size_usd=%.2f headroom_usd=%.2f min_notional_usd=%.2f inferred_broker=%s action=resize_before_ecel",
                account_id,
                symbol,
                requested_size,
                safe_size,
                headroom,
                min_notional,
                inferred_broker,
            )
            return original(self, resized_request, *args, **kwargs)
        except Exception as exc:
            logger.warning("PRE_DISPATCH_RISK_SIZING_PATCH_FAIL_OPEN error=%s", exc)
            return original(self, request, *args, **kwargs)

    setattr(_patched_execute, "_nija_pre_dispatch_exposure_headroom_wrapped_20260707a", True)
    setattr(cls, "execute", _patched_execute)
    _PIPELINE_PATCHED = True
    logger.warning("PRE_DISPATCH_RISK_SIZING_PIPELINE_PATCHED marker=20260707a module=%s", getattr(module, "__name__", "<unknown>"))
    return True


def _install_on_pre_trade_risk_engine(module: ModuleType) -> bool:
    global _PRE_TRADE_RISK_PATCHED
    cls = getattr(module, "PreTradeRiskEngine", None)
    decision_cls = getattr(module, "PreTradeRiskDecision", None)
    if not isinstance(cls, type) or not callable(decision_cls):
        return False
    original = getattr(cls, "assess", None)
    if not callable(original):
        return False
    if getattr(original, "_nija_strict_headroom_assess_wrapped_20260707a", False):
        _PRE_TRADE_RISK_PATCHED = True
        return True

    def _patched_assess(self: Any, *args: Any, **kwargs: Any) -> Any:
        decision = original(self, *args, **kwargs)
        try:
            if not getattr(decision, "approved", False):
                return decision
            requested = _coerce_float(kwargs.get("size_usd"), 0.0)
            details = dict(getattr(decision, "details", {}) or {})
            headroom = details.get("remaining_headroom_usd")
            if headroom is None:
                return decision
            headroom_f = max(0.0, _coerce_float(headroom, 0.0))
            cap_base = _coerce_float(details.get("cap_base_usd"), 0.0)
            current_total = _coerce_float(details.get("total_exposure_usd", details.get("current_total_exposure_usd")), 0.0)
            if cap_base <= 0.0 and current_total <= 0.0:
                return decision
            if requested > 0.0 and requested > headroom_f + 0.01:
                account_id = str(kwargs.get("account_id") or details.get("account_id") or "default")
                symbol = str(kwargs.get("symbol") or "")
                min_notional = _minimum_live_notional_usd(symbol=symbol)
                # If headroom can still support the active broker's executable
                # minimum, allow the pipeline wrapper to clip before broker dispatch
                # instead of hard rejecting a near-headroom order.
                if headroom_f >= min_notional:
                    details["requested_size_usd"] = requested
                    details["max_approved_size_usd"] = headroom_f
                    details["action_required"] = "clip_before_execution_pipeline_dispatch"
                    details["broker_aware_min_notional_usd"] = min_notional
                    logger.warning(
                        "PRE_TRADE_RISK_STRICT_HEADROOM_ALLOW_FOR_CLIP marker=20260707a account=%s symbol=%s requested_size_usd=%.2f headroom_usd=%.2f min_notional_usd=%.2f",
                        account_id,
                        symbol,
                        requested,
                        headroom_f,
                        min_notional,
                    )
                    return decision_cls(approved=True, reason="approved_headroom_clip_required", details=details)
                details["requested_size_usd"] = requested
                details["max_approved_size_usd"] = headroom_f
                details["action_required"] = "downsize_before_execution_pipeline_dispatch"
                logger.warning(
                    "PRE_TRADE_RISK_STRICT_HEADROOM_REJECT account=%s symbol=%s requested_size_usd=%.2f headroom_usd=%.2f min_notional_usd=%.2f action=reject_direct_caller",
                    account_id,
                    symbol,
                    requested,
                    headroom_f,
                    min_notional,
                )
                return decision_cls(
                    approved=False,
                    reason=f"account={account_id} reason=GLOBAL_EXPOSURE_CAP_HEADROOM_REQUIRES_DOWNSIZE",
                    details=details,
                )
        except Exception as exc:
            logger.debug("PreTradeRisk strict-headroom wrapper skipped: %s", exc)
        return decision

    setattr(_patched_assess, "_nija_strict_headroom_assess_wrapped_20260707a", True)
    setattr(cls, "assess", _patched_assess)
    _PRE_TRADE_RISK_PATCHED = True
    logger.warning("PRE_DISPATCH_RISK_SIZING_PRE_TRADE_ENGINE_PATCHED marker=20260707a module=%s", getattr(module, "__name__", "<unknown>"))
    return True


# ---------------------------------------------------------------------------
# Broker-specific error taxonomy: Kraken classifier only for Kraken failures.
# ---------------------------------------------------------------------------

def _manual_failure_details(broker_response: Any = None, exc: Optional[Exception] = None) -> dict[str, str]:
    response = broker_response if isinstance(broker_response, dict) else {}
    status = str(response.get("status") or ("exception" if exc else "unknown")).lower()
    raw_error = response.get("error", "")
    raw_message = response.get("message", "")
    if isinstance(raw_error, (list, tuple)):
        error = ", ".join(str(item) for item in raw_error if item)
    else:
        error = str(raw_error or "")
    message = str(raw_message or "")
    if exc is not None and not error:
        error = str(exc)
    combined = " | ".join(part for part in (error, message) if part).strip() or "Unknown execution failure"
    normalized = combined.lower()

    hint = "Inspect broker rejection payload"
    if "too small" in normalized or "minimum" in normalized or "min notional" in normalized:
        hint = "Check minimum order size / exchange notional floor"
    elif "insufficient" in normalized or "fund" in normalized or "balance" in normalized:
        hint = "Check per-broker available balance and fee-adjusted sizing"
    elif "unsupported" in normalized or "invalid product" in normalized or "symbol" in normalized:
        hint = "Check symbol support / exchange restrictions"
    elif "nonce" in normalized or "signature" in normalized:
        hint = "Check broker nonce or API signature path"
    elif "geographic" in normalized or "region" in normalized or "jurisdiction" in normalized:
        hint = "Check exchange geographic restrictions for this symbol"
    elif "exposure" in normalized or "risk" in normalized or "cap" in normalized:
        hint = "Check pre-trade exposure/risk caps before broker dispatch"

    error_code = (error or message or status or "UNKNOWN_REJECTION")[:120].upper().replace(" ", "_")
    return {"status": status, "error_code": error_code, "detail": combined, "hint": hint}


def _install_on_execution_engine(module: ModuleType) -> bool:
    global _EXECUTION_ENGINE_TAXONOMY_PATCHED
    cls = getattr(module, "ExecutionEngine", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_extract_order_failure_details", None)
    if not callable(original):
        return False
    if getattr(original, "_nija_broker_specific_taxonomy_wrapped", False):
        _EXECUTION_ENGINE_TAXONOMY_PATCHED = True
        return True

    def _patched_extract_order_failure_details(self: Any, broker_response: Any = None, exc: Optional[Exception] = None) -> dict[str, str]:
        broker_label = "unknown"
        try:
            broker_label = str(self._get_broker_label()).strip().lower()
        except Exception:
            pass
        if broker_label == "kraken":
            return original(self, broker_response=broker_response, exc=exc)
        details = _manual_failure_details(broker_response=broker_response, exc=exc)
        details["broker"] = broker_label
        return details

    setattr(_patched_extract_order_failure_details, "_nija_broker_specific_taxonomy_wrapped", True)
    setattr(cls, "_extract_order_failure_details", _patched_extract_order_failure_details)
    _EXECUTION_ENGINE_TAXONOMY_PATCHED = True
    logger.warning("EXECUTION_FAILURE_TAXONOMY_PATCHED module=%s non_kraken_uses=generic_classifier", getattr(module, "__name__", "<unknown>"))
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.downstream_blocker_guard", "downstream_blocker_guard"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _install_on_downstream_blocker_guard(module) or patched
    for name in ("bot.execution_pipeline", "execution_pipeline"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _install_on_execution_pipeline(module) or patched
    for name in ("bot.pre_trade_risk_engine", "pre_trade_risk_engine"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _install_on_pre_trade_risk_engine(module) or patched
    for name in ("bot.execution_engine", "execution_engine"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _install_on_execution_engine(module) or patched
    return patched


def _patch_named_module(name: str, module: Any) -> None:
    if not isinstance(module, ModuleType):
        return
    if name in {"bot.downstream_blocker_guard", "downstream_blocker_guard"}:
        _install_on_downstream_blocker_guard(module)
    elif name in {"bot.execution_pipeline", "execution_pipeline"}:
        _install_on_execution_pipeline(module)
    elif name in {"bot.pre_trade_risk_engine", "pre_trade_risk_engine"}:
        _install_on_pre_trade_risk_engine(module)
    elif name in {"bot.execution_engine", "execution_engine"}:
        _install_on_execution_engine(module)


def _start_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + float(os.environ.get("NIJA_PATCH_MONITOR_SECONDS", "240") or "240")
        while time.time() < deadline:
            _try_patch_loaded()
            if _PATCHED and _PIPELINE_PATCHED and _PRE_TRADE_RISK_PATCHED and _EXECUTION_ENGINE_TAXONOMY_PATCHED:
                return
            time.sleep(0.25)
        logger.warning(
            "DOWNSTREAM_RISK_GOVERNOR_EQUITY_REPAIR_MONITOR_EXPIRED downstream=%s pipeline=%s pre_trade_risk=%s execution_taxonomy=%s",
            _PATCHED,
            _PIPELINE_PATCHED,
            _PRE_TRADE_RISK_PATCHED,
            _EXECUTION_ENGINE_TAXONOMY_PATCHED,
        )

    threading.Thread(target=_monitor, name="downstream-risk-governor-equity-repair-monitor", daemon=True).start()
    logger.warning("DOWNSTREAM_RISK_GOVERNOR_EQUITY_REPAIR_MONITOR_STARTED")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _INSTALL_LOCK:
        _try_patch_loaded()
        _start_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            logger.warning(
                "DOWNSTREAM_RISK_GOVERNOR_EQUITY_REPAIR_INSTALL_COMPLETE already_installed=True downstream=%s pipeline=%s pre_trade_risk=%s execution_taxonomy=%s",
                _PATCHED,
                _PIPELINE_PATCHED,
                _PRE_TRADE_RISK_PATCHED,
                _EXECUTION_ENGINE_TAXONOMY_PATCHED,
            )
            return
        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            _patch_named_module(name, module)
            _try_patch_loaded()
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
        logger.warning(
            "DOWNSTREAM_RISK_GOVERNOR_EQUITY_REPAIR_INSTALL_COMPLETE downstream=%s pipeline=%s pre_trade_risk=%s execution_taxonomy=%s",
            _PATCHED,
            _PIPELINE_PATCHED,
            _PRE_TRADE_RISK_PATCHED,
            _EXECUTION_ENGINE_TAXONOMY_PATCHED,
        )
