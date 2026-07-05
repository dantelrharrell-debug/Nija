from __future__ import annotations

import dataclasses
import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.execution_route_integrity_patch")

_MARKER = "EXECUTION_ROUTE_INTEGRITY_PATCHED marker=20260705c"
_TRUTHY = {"1", "true", "yes", "enabled", "on", "y"}
_FALSEY = {"0", "false", "no", "disabled", "off", "n"}
_IMPORT_LOCK = threading.Lock()
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_MONITOR_STARTED = False
_STRATEGY_PATCHED = False
_PIPELINE_PATCHED = False
_ROUTER_PATCHED = False
_INDEPENDENT_PATCHED = False

_STRATEGY_WRAP_ATTR = "_nija_execution_route_integrity_strategy_v20260705c"
_PIPELINE_DISPATCH_WRAP_ATTR = "_nija_execution_route_integrity_dispatch_v20260705c"
_PIPELINE_REJECT_WRAP_ATTR = "_nija_execution_route_integrity_reject_v20260705c"
_ROUTER_ROUTE_WRAP_ATTR = "_nija_execution_route_integrity_route_v20260705c"
_INDEPENDENT_INIT_WRAP_ATTR = "_nija_execution_route_integrity_independent_init_v20260705c"
_INDEPENDENT_THREAD_WRAP_ATTR = "_nija_execution_route_integrity_independent_thread_v20260705c"


def _truthy_value(value: Any) -> bool:
    return str(value or "").strip().lower() in _TRUTHY


def _falsey_value(value: Any) -> bool:
    return str(value or "").strip().lower() in _FALSEY


def _truthy(name: str, default: str = "") -> bool:
    return _truthy_value(os.environ.get(name, default))


def _csv_env(name: str, default: str = "") -> list[str]:
    raw = os.environ.get(name, default) or ""
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


def _ensure_csv_contains_env(name: str, values: list[str]) -> None:
    current = _csv_env(name, "")
    merged = []
    for item in current + values:
        item = _normalise_broker_name(item)
        if item and item not in merged:
            merged.append(item)
    os.environ[name] = ",".join(merged)


def _apply_safe_defaults() -> None:
    """Install fail-closed route defaults.

    OKX live execution is disabled by default until the adapter dispatch path
    is fully repaired.  The router still uses a generic direct-broker call
    pattern whose third fallback omits ``size_type`` — passing the wrong
    denomination to OKX.  OKX must be opted-in explicitly via an env var
    (e.g. ``NIJA_OKX_EXECUTION_ENABLED=true``) once the dispatch path is
    verified.  The default broker priority therefore excludes OKX.
    """
    os.environ.setdefault("NIJA_COPY_TRADE_ENABLED", "false")
    os.environ.setdefault("NIJA_INDEPENDENT_USER_TRADING", "true")
    os.environ.setdefault("NIJA_MASTER_SIGNAL_ONLY", "true")
    os.environ.setdefault("NIJA_ENTRY_BROKER_PRIORITY", "kraken,coinbase,alpaca")
    os.environ.setdefault("NIJA_BROKER_PRIORITY", "kraken,coinbase,alpaca")
    os.environ.setdefault("NIJA_ALLOWED_EXECUTION_BROKERS", "kraken,coinbase,alpaca")
    os.environ.setdefault("NIJA_ROUTE_INTEGRITY_FAIL_CLOSED", "true")
    if _okx_execution_enabled() and "okx" not in _disabled_brokers(explicit_only=True):
        _ensure_csv_contains_env("NIJA_ALLOWED_EXECUTION_BROKERS", ["okx"])
        _ensure_csv_contains_env("NIJA_ENTRY_BROKER_PRIORITY", ["okx"])
        _ensure_csv_contains_env("NIJA_BROKER_PRIORITY", ["okx"])


def _okx_execution_enabled() -> bool:
    """OKX live execution is enabled only when explicitly opted in.

    Returns False by default — OKX remains disabled until the adapter dispatch
    path is repaired and the operator sets one of the OKX enable env vars.
    """
    explicit_values = [
        os.environ.get("NIJA_OKX_EXECUTION_ENABLED"),
        os.environ.get("NIJA_OKX_LIVE_TRADING_ENABLED"),
        os.environ.get("OKX_LIVE_TRADING_ENABLED"),
        os.environ.get("NIJA_ENABLE_OKX_EXECUTION"),
    ]
    if any(_truthy_value(value) for value in explicit_values):
        return True
    if any(_falsey_value(value) for value in explicit_values if value is not None):
        return False
    return False


def _disabled_brokers(*, explicit_only: bool = False) -> set[str]:
    disabled = set(_csv_env("NIJA_DISABLED_BROKERS", ""))
    if explicit_only:
        return disabled
    if not _okx_execution_enabled():
        disabled.add("okx")
    return disabled


def _allowed_brokers() -> list[str]:
    allowed = _csv_env("NIJA_ALLOWED_EXECUTION_BROKERS", "")
    if not allowed:
        allowed = _csv_env("NIJA_ENTRY_BROKER_PRIORITY", "okx,kraken,coinbase,alpaca")
    if _okx_execution_enabled() and "okx" not in _disabled_brokers(explicit_only=True) and "okx" not in allowed:
        allowed = ["okx"] + allowed
    return [name for name in allowed if _broker_enabled(name)]


def _broker_enabled(name: Any) -> bool:
    key = _normalise_broker_name(name)
    if not key or key == "unknown":
        return False
    if key in _disabled_brokers():
        return False
    allowed = _csv_env("NIJA_ALLOWED_EXECUTION_BROKERS", "")
    if key == "okx" and _okx_execution_enabled() and key not in _disabled_brokers(explicit_only=True):
        return True
    if allowed and key not in allowed:
        return False
    return True


def _normalise_broker_name(value: Any) -> str:
    raw = getattr(value, "value", value)
    text = str(raw or "").strip().lower()
    if not text:
        return ""
    for key in ("kraken", "coinbase", "okx", "alpaca", "binance"):
        if key in text:
            return key
    return text


def _broker_key_from_obj(obj: Any) -> str:
    if obj is None:
        return "unknown"
    for attr in ("broker_type", "name", "broker_name", "exchange", "exchange_name"):
        try:
            value = getattr(obj, attr, None)
            key = _normalise_broker_name(value)
            if key:
                return key
        except Exception:
            pass
    try:
        cls_name = type(obj).__name__.lower()
        for key in ("kraken", "coinbase", "okx", "alpaca", "binance"):
            if key in cls_name:
                return key
    except Exception:
        pass
    return "unknown"


def _collect_candidate_brokers(strategy: Any) -> dict[str, Any]:
    candidates: dict[str, Any] = {}
    for broker in (getattr(strategy, "broker", None),):
        key = _broker_key_from_obj(broker)
        if broker is not None and key != "unknown":
            candidates[key] = broker

    for container_attr in ("multi_account_manager", "broker_manager"):
        manager = getattr(strategy, container_attr, None)
        for mapping_attr in ("platform_brokers", "brokers"):
            try:
                mapping = getattr(manager, mapping_attr, {}) or {}
                for raw_key, broker in mapping.items():
                    key = _broker_key_from_obj(broker)
                    if key == "unknown":
                        key = _normalise_broker_name(raw_key)
                    if broker is not None and key:
                        candidates[key] = broker
            except Exception:
                continue
    return candidates


def _set_strategy_broker(strategy: Any, name: str, broker: Any) -> None:
    try:
        strategy.broker = broker
    except Exception:
        pass
    try:
        setattr(strategy, "_nija_execution_route_broker", name)
        setattr(strategy, "_nija_selected_execution_broker", name)
    except Exception:
        pass
    try:
        os.environ["NIJA_SELECTED_EXECUTION_BROKER"] = name
    except Exception:
        pass
    try:
        broker_manager = getattr(strategy, "broker_manager", None)
        if broker_manager is not None:
            broker_manager.active_broker = broker
    except Exception:
        pass
    try:
        apex = getattr(strategy, "apex", None)
        if apex is not None:
            setattr(apex, "_nija_execution_route_broker", name)
            if hasattr(apex, "update_broker_client"):
                apex.update_broker_client(broker)
    except Exception:
        pass


def _choose_enabled_candidate(strategy: Any) -> tuple[str, Any, str]:
    candidates = _collect_candidate_brokers(strategy)
    priority = _csv_env("NIJA_ENTRY_BROKER_PRIORITY", "okx,kraken,coinbase,alpaca")
    names = [name for name in priority if name in candidates] + sorted(set(candidates) - set(priority))
    for name in names:
        if not _broker_enabled(name):
            continue
        broker = candidates.get(name)
        try:
            eligible_fn = getattr(strategy, "_is_broker_eligible_for_entry", None)
            if callable(eligible_fn):
                ok, reason = eligible_fn(broker)
                if not ok:
                    continue
                return name, broker, str(reason or "eligible")
        except Exception as exc:
            logger.debug("RouteGuard: eligibility check skipped for %s: %s", name, exc)
            continue
        return name, broker, "enabled_candidate"
    return "", None, "no_enabled_candidate"


def _patch_trading_strategy_module(module: ModuleType) -> bool:
    global _STRATEGY_PATCHED
    cls = getattr(module, "TradingStrategy", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_get_active_broker", None)
    if not callable(original):
        return False
    if getattr(original, _STRATEGY_WRAP_ATTR, False):
        _STRATEGY_PATCHED = True
        return True

    try:
        priority = getattr(module, "ENTRY_BROKER_PRIORITY", None)
        if isinstance(priority, list):
            desired = _csv_env("NIJA_ENTRY_BROKER_PRIORITY", "okx,kraken,coinbase,alpaca")
            priority[:] = desired + [p for p in priority if _normalise_broker_name(p) not in set(desired)]
        mins = getattr(module, "BROKER_MIN_BALANCE", None)
        if isinstance(mins, dict) and not _okx_execution_enabled():
            mins["okx"] = max(float(mins.get("okx", 50.0) or 50.0), 999999.0)
    except Exception as exc:
        logger.debug("RouteGuard: strategy priority/min update skipped: %s", exc)

    def _route_guard_get_active_broker(self: Any) -> Optional[Any]:
        selected = original(self)
        selected_name = _broker_key_from_obj(selected)
        if _broker_enabled(selected_name):
            _set_strategy_broker(self, selected_name, selected)
            return selected

        fallback_name, fallback_broker, reason = _choose_enabled_candidate(self)
        if fallback_broker is not None and fallback_name:
            _set_strategy_broker(self, fallback_name, fallback_broker)
            logger.critical(
                "ENTRY_BROKER_DISABLED_REROUTED marker=20260705c from=%s to=%s reason=%s disabled=%s allowed=%s",
                selected_name,
                fallback_name,
                reason,
                sorted(_disabled_brokers()),
                _allowed_brokers(),
            )
            print(
                f"[NIJA-PRINT] ENTRY_BROKER_DISABLED_REROUTED marker=20260705c from={selected_name} to={fallback_name}",
                flush=True,
            )
            return fallback_broker

        logger.critical(
            "ENTRY_BROKER_DISABLED_NO_FALLBACK marker=20260705c selected=%s disabled=%s allowed=%s",
            selected_name,
            sorted(_disabled_brokers()),
            _allowed_brokers(),
        )
        return selected

    setattr(_route_guard_get_active_broker, _STRATEGY_WRAP_ATTR, True)
    setattr(cls, "_get_active_broker", _route_guard_get_active_broker)
    _STRATEGY_PATCHED = True
    logger.warning("%s strategy_module=%s", _MARKER, getattr(module, "__name__", "<unknown>"))
    return True


def _structured_error_for(result: Any, selected_broker: str) -> str:
    error = str(getattr(result, "error", "") or "").strip()
    if error:
        return error
    return f"broker_dispatch_failed:{selected_broker or 'unknown'}:empty_order_result"


def _safe_replace(obj: Any, **updates: Any) -> Any:
    if dataclasses.is_dataclass(obj):
        try:
            return dataclasses.replace(obj, **updates)
        except Exception:
            pass
    for key, value in updates.items():
        try:
            setattr(obj, key, value)
        except Exception:
            pass
    return obj


def _route_guard_error_tokens(error: Any) -> bool:
    text = str(error or "").strip().lower()
    if not text:
        return True
    tokens = (
        "broker_dispatch_failed",
        "empty_order_result",
        "empty order result",
        "execution_route_mismatch",
        "brokerrouteguard deny",
        "broker disabled",
        "okx order failed",
        "all operations failed",
        "adapter_exception",
        "broker_dispatch_exception",
        "no_execution_venue_available",
    )
    return any(token in text for token in tokens)


def _resolve_selected_broker(request: Any) -> str:
    meta = dict(getattr(request, "metadata", {}) or {})
    for candidate in (
        getattr(request, "preferred_broker", None),
        meta.get("execution_broker"),
        meta.get("dispatch_broker"),
        meta.get("broker_name"),
        os.environ.get("NIJA_SELECTED_EXECUTION_BROKER"),
        os.environ.get("NIJA_PRIMARY_EXECUTION_BROKER"),
    ):
        key = _normalise_broker_name(candidate)
        if key:
            return key
    allowed = _allowed_brokers()
    return allowed[0] if allowed else "kraken"


def _stamp_request_route(request: Any, broker: str) -> Any:
    broker = _normalise_broker_name(broker) or "kraken"
    updates = {}
    if hasattr(request, "preferred_broker"):
        updates["preferred_broker"] = broker
    meta = dict(getattr(request, "metadata", {}) or {})
    meta.update({
        "execution_broker": broker,
        "symbol_broker": broker,
        "balance_broker": broker,
        "dispatch_broker": broker,
        "route_guard_marker": "20260705c",
    })
    if hasattr(request, "metadata"):
        updates["metadata"] = meta
    return _safe_replace(request, **updates)


def _make_pipeline_result(module: ModuleType, request: Any, t_start: float, broker: str, error: str) -> Any:
    result_cls = getattr(module, "PipelineResult", None)
    if callable(result_cls):
        return result_cls(
            success=False,
            symbol=getattr(request, "symbol", ""),
            side=getattr(request, "side", ""),
            size_usd=float(getattr(request, "size_usd", 0.0) or 0.0),
            broker=broker,
            error=error,
            latency_ms=(time.monotonic() - t_start) * 1000,
        )
    return None


def _patch_execution_pipeline_module(module: ModuleType) -> bool:
    global _PIPELINE_PATCHED
    cls = getattr(module, "ExecutionPipeline", None)
    if not isinstance(cls, type):
        return False

    original_dispatch = getattr(cls, "_dispatch", None)
    if callable(original_dispatch) and not getattr(original_dispatch, _PIPELINE_DISPATCH_WRAP_ATTR, False):
        def _route_guard_dispatch(self: Any, request: Any, t_start: float) -> Any:
            selected = _resolve_selected_broker(request)
            if not _broker_enabled(selected):
                error = (
                    f"BrokerRouteGuard deny: broker disabled for live execution selected={selected} "
                    f"disabled={sorted(_disabled_brokers())} allowed={_allowed_brokers()}"
                )
                logger.critical("EXECUTION_ROUTE_GUARD_DENY marker=20260705c %s symbol=%s", error, getattr(request, "symbol", ""))
                return _make_pipeline_result(module, request, t_start, selected, error)

            guarded_request = _stamp_request_route(request, selected)
            logger.critical(
                "EXECUTION_ROUTE_GUARD_ALLOW marker=20260705c selected=%s symbol=%s allowed=%s disabled=%s",
                selected,
                getattr(guarded_request, "symbol", ""),
                _allowed_brokers(),
                sorted(_disabled_brokers()),
            )
            result = original_dispatch(self, guarded_request, t_start)
            if result is None:
                error = f"broker_dispatch_failed:{selected}:none_result"
                return _make_pipeline_result(module, guarded_request, t_start, selected, error)

            result_broker = _normalise_broker_name(getattr(result, "broker", ""))
            if not bool(getattr(result, "success", False)):
                error = _structured_error_for(result, selected)
                if not result_broker or result_broker in {"none", "unknown"}:
                    result = _safe_replace(result, broker=selected, error=error)
                elif result_broker != selected:
                    mismatch = f"execution_route_mismatch:selected={selected}:actual={result_broker}:symbol={getattr(guarded_request, 'symbol', '')}"
                    logger.critical("EXECUTION_ROUTE_MISMATCH marker=20260705c %s", mismatch)
                    result = _safe_replace(result, broker=selected, error=mismatch)
                elif not str(getattr(result, "error", "") or "").strip():
                    result = _safe_replace(result, error=error)
            else:
                if result_broker and result_broker != selected:
                    mismatch = f"execution_route_mismatch:selected={selected}:actual={result_broker}:ack_success=True"
                    logger.critical("EXECUTION_ROUTE_MISMATCH_SUCCESS marker=20260705c %s", mismatch)
                    result = _safe_replace(result, success=False, broker=selected, error=mismatch)
            return result

        setattr(_route_guard_dispatch, _PIPELINE_DISPATCH_WRAP_ATTR, True)
        setattr(cls, "_dispatch", _route_guard_dispatch)

    original_reject = getattr(cls, "_on_order_rejected", None)
    if callable(original_reject) and not getattr(original_reject, _PIPELINE_REJECT_WRAP_ATTR, False):
        def _route_guard_on_rejected(self: Any, request: Any, error: str) -> None:
            if _route_guard_error_tokens(error):
                try:
                    self._emit_execution_rejection_telemetry(
                        symbol=getattr(request, "symbol", "unknown"),
                        side=getattr(request, "side", "unknown"),
                        reason=error or "broker_dispatch_failed:unknown:empty_order_result",
                    )
                except Exception:
                    pass
                logger.warning(
                    "🟡 EXCHANGE SOFT-REJECT [broker_dispatch] marker=20260705c symbol=%s broker=%s error=%s",
                    getattr(request, "symbol", "unknown"),
                    _resolve_selected_broker(request),
                    error or "broker_dispatch_failed:unknown:empty_order_result",
                )
                return
            return original_reject(self, request, error)

        setattr(_route_guard_on_rejected, _PIPELINE_REJECT_WRAP_ATTR, True)
        setattr(cls, "_on_order_rejected", _route_guard_on_rejected)

    _PIPELINE_PATCHED = True
    logger.warning("%s execution_pipeline_module=%s", _MARKER, getattr(module, "__name__", "<unknown>"))
    return True


def _make_route_result(module: ModuleType, request: Any, broker: str, error: str) -> Any:
    result_cls = getattr(module, "RouteResult", None)
    detect = getattr(module, "detect_asset_class", None)
    ac = "crypto"
    try:
        detected = detect(getattr(request, "symbol", "")) if callable(detect) else None
        ac = str(getattr(detected, "value", detected) or "crypto")
    except Exception:
        ac = "crypto"
    if callable(result_cls):
        return result_cls(
            success=False,
            symbol=getattr(request, "symbol", ""),
            side=getattr(request, "side", ""),
            size_usd=float(getattr(request, "size_usd", 0.0) or 0.0),
            asset_class=ac,
            broker=broker or "NONE",
            error=error,
        )
    return None


def _patch_multi_router_module(module: ModuleType) -> bool:
    global _ROUTER_PATCHED
    cls = getattr(module, "MultiBrokerExecutionRouter", None)
    if not isinstance(cls, type):
        return False
    original_route = getattr(cls, "route", None)
    if not callable(original_route):
        return False
    if getattr(original_route, _ROUTER_ROUTE_WRAP_ATTR, False):
        _ROUTER_PATCHED = True
        return True

    def _route_guard_route(self: Any, request: Any) -> Any:
        selected = _resolve_selected_broker(request)
        if not _broker_enabled(selected):
            error = (
                f"BrokerRouteGuard deny: broker disabled for live execution selected={selected} "
                f"disabled={sorted(_disabled_brokers())} allowed={_allowed_brokers()}"
            )
            logger.critical("ROUTER_ROUTE_GUARD_DENY marker=20260705c %s symbol=%s", error, getattr(request, "symbol", ""))
            return _make_route_result(module, request, selected, error)

        guarded_request = _stamp_request_route(request, selected)
        logger.critical(
            "ROUTER_ROUTE_GUARD_ALLOW marker=20260705c selected=%s symbol=%s allowed=%s disabled=%s",
            selected,
            getattr(guarded_request, "symbol", ""),
            _allowed_brokers(),
            sorted(_disabled_brokers()),
        )
        result = original_route(self, guarded_request)
        if result is None:
            return _make_route_result(module, guarded_request, selected, f"broker_dispatch_failed:{selected}:none_route_result")

        result_broker = _normalise_broker_name(getattr(result, "broker", ""))
        if not bool(getattr(result, "success", False)):
            error = _structured_error_for(result, selected)
            if not result_broker or result_broker in {"none", "unknown"}:
                result = _safe_replace(result, broker=selected, error=error)
            elif result_broker != selected:
                mismatch = f"execution_route_mismatch:selected={selected}:actual={result_broker}:symbol={getattr(guarded_request, 'symbol', '')}"
                logger.critical("ROUTER_ROUTE_MISMATCH marker=20260705c %s", mismatch)
                result = _safe_replace(result, broker=selected, error=mismatch)
            elif not str(getattr(result, "error", "") or "").strip():
                result = _safe_replace(result, error=error)
        elif result_broker and result_broker != selected:
            mismatch = f"execution_route_mismatch:selected={selected}:actual={result_broker}:ack_success=True"
            logger.critical("ROUTER_ROUTE_MISMATCH_SUCCESS marker=20260705c %s", mismatch)
            result = _safe_replace(result, success=False, broker=selected, error=mismatch)
        return result

    setattr(_route_guard_route, _ROUTER_ROUTE_WRAP_ATTR, True)
    setattr(cls, "route", _route_guard_route)
    _ROUTER_PATCHED = True
    logger.warning("%s multi_router_module=%s", _MARKER, getattr(module, "__name__", "<unknown>"))
    return True


def _copy_trading_enabled() -> bool:
    return _truthy("NIJA_COPY_TRADE_ENABLED", "false") and not _truthy("NIJA_MASTER_SIGNAL_ONLY", "true")


def _patch_independent_trader_module(module: ModuleType) -> bool:
    global _INDEPENDENT_PATCHED
    cls = getattr(module, "IndependentBrokerTrader", None)
    if not isinstance(cls, type):
        return False

    original_init = getattr(cls, "__init__", None)
    if callable(original_init) and not getattr(original_init, _INDEPENDENT_INIT_WRAP_ATTR, False):
        def _route_guard_init(self: Any, *args: Any, **kwargs: Any) -> None:
            original_init(self, *args, **kwargs)
            if not _copy_trading_enabled():
                engine = getattr(self, "copy_engine", None)
                if engine is not None:
                    for attr, value in (("active", False), ("enabled", False)):
                        try:
                            setattr(engine, attr, value)
                        except Exception:
                            pass
                try:
                    self.copy_engine = None
                except Exception:
                    pass
                logger.warning(
                    "COPY_TRADE_ENGINE_DISABLED marker=20260705c mode=independent_user_trading master_signal_only=%s",
                    os.environ.get("NIJA_MASTER_SIGNAL_ONLY", "true"),
                )

        setattr(_route_guard_init, _INDEPENDENT_INIT_WRAP_ATTR, True)
        setattr(cls, "__init__", _route_guard_init)

    original_should = getattr(cls, "should_start_user_independent_thread", None)
    if callable(original_should) and not getattr(original_should, _INDEPENDENT_THREAD_WRAP_ATTR, False):
        def _route_guard_should_start(self: Any, user_id: str) -> bool:
            if _truthy("NIJA_INDEPENDENT_USER_TRADING", "true") and not _copy_trading_enabled():
                return True
            return bool(original_should(self, user_id))

        setattr(_route_guard_should_start, _INDEPENDENT_THREAD_WRAP_ATTR, True)
        setattr(cls, "should_start_user_independent_thread", _route_guard_should_start)

    _INDEPENDENT_PATCHED = True
    logger.warning("%s independent_trader_module=%s", _MARKER, getattr(module, "__name__", "<unknown>"))
    return True


def _install_on_module(name: str, module: ModuleType) -> bool:
    patched = False
    if name in {"bot.trading_strategy", "trading_strategy"}:
        patched = _patch_trading_strategy_module(module) or patched
    if name in {"bot.execution_pipeline", "execution_pipeline"}:
        patched = _patch_execution_pipeline_module(module) or patched
    if name in {"bot.multi_broker_execution_router", "multi_broker_execution_router"}:
        patched = _patch_multi_router_module(module) or patched
    if name in {"bot.independent_broker_trader", "independent_broker_trader"}:
        patched = _patch_independent_trader_module(module) or patched
    return patched


def _try_patch_loaded() -> bool:
    patched = False
    for name in (
        "bot.trading_strategy",
        "trading_strategy",
        "bot.execution_pipeline",
        "execution_pipeline",
        "bot.multi_broker_execution_router",
        "multi_broker_execution_router",
        "bot.independent_broker_trader",
        "independent_broker_trader",
    ):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _install_on_module(name, module) or patched
    return patched


def _start_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + float(os.environ.get("NIJA_ROUTE_GUARD_MONITOR_SECONDS", "240") or "240")
        while time.time() < deadline:
            _try_patch_loaded()
            if _STRATEGY_PATCHED and _PIPELINE_PATCHED and _ROUTER_PATCHED and _INDEPENDENT_PATCHED:
                return
            time.sleep(1.0)
        logger.warning(
            "EXECUTION_ROUTE_INTEGRITY_MONITOR_EXPIRED marker=20260705c strategy=%s pipeline=%s router=%s independent=%s",
            _STRATEGY_PATCHED,
            _PIPELINE_PATCHED,
            _ROUTER_PATCHED,
            _INDEPENDENT_PATCHED,
        )

    threading.Thread(target=_monitor, name="execution-route-integrity-monitor", daemon=True).start()
    logger.warning("EXECUTION_ROUTE_INTEGRITY_MONITOR_STARTED marker=20260705c")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _IMPORT_LOCK:
        _apply_safe_defaults()
        logger.warning(
            "%s install_start=True allowed=%s disabled=%s copy_trade_enabled=%s okx_enabled=%s",
            _MARKER,
            _allowed_brokers(),
            sorted(_disabled_brokers()),
            _copy_trading_enabled(),
            _okx_execution_enabled(),
        )
        print("[NIJA-PRINT] EXECUTION_ROUTE_INTEGRITY_PATCHED marker=20260705c install_start", flush=True)
        _try_patch_loaded()
        _start_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            return
        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name in {
                "bot.trading_strategy",
                "trading_strategy",
                "bot.execution_pipeline",
                "execution_pipeline",
                "bot.multi_broker_execution_router",
                "multi_broker_execution_router",
                "bot.independent_broker_trader",
                "independent_broker_trader",
            }:
                _install_on_module(name, module)
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]


def install() -> None:
    install_import_hook()
