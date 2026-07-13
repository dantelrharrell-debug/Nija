"""Profit-first live trading safety convergence for NIJA.

This module is loaded at Python startup.  It fail-closes the specific runtime
paths that can turn trade-frequency pressure, fabricated fallback payloads,
unconfirmed fills, or unknown cost bases into real Kraken/Coinbase losses.
"""
from __future__ import annotations

import builtins
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any, Callable, Mapping, MutableMapping, Optional

logger = logging.getLogger("nija.profit_first_loss_prevention")
_MARKER = "20260713_profit_first_v1"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_INSTALL_FLAG = "_NIJA_PROFIT_FIRST_LOSS_PREVENTION_INSTALLED_V1"
_IMPORT_FLAG = "_NIJA_PROFIT_FIRST_IMPORT_HOOK_V1"
_PATCH_LOCK = threading.RLock()
_IMPORT_GUARD = threading.local()


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUE


def _live_mode() -> bool:
    return not _truthy("DRY_RUN_MODE") and not _truthy("PAPER_MODE")


def _unsafe_override_allowed() -> bool:
    return _truthy("NIJA_PROFIT_FIRST_ALLOW_UNSAFE_OVERRIDES", "false")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return default if out != out else out
    except Exception:
        return default


def _force_live_defaults() -> None:
    if not _live_mode() or _unsafe_override_allowed():
        return
    # Entry quality must never be relaxed merely to manufacture trade volume.
    os.environ["FORCE_TRADE"] = "false"
    os.environ["NIJA_LIVE_FALLBACK_ENTRY_ALLOWED"] = "false"
    os.environ["NIJA_ALLOW_LIVE_FREQUENCY_RELAXATION"] = "false"

    # Stop geometry: allow normal crypto movement, then preserve dollar risk by
    # reducing position size when a previously compressed stop is widened.
    os.environ["MAX_SL_PCT"] = "0.025"
    os.environ["NIJA_GLOBAL_STOP_LOSS_PCT"] = "0.015"
    os.environ["NIJA_PROFIT_FIRST_MIN_STOP_PCT"] = "0.015"
    os.environ["NIJA_PROFIT_FIRST_MAX_STOP_PCT"] = "0.025"

    # Profit locks must sit above conservative round-trip fees + slippage.
    protected = {
        "NIJA_TRAILING_TP_ACTIVATION_PCT": "0.0125",
        "NIJA_TRAILING_TP_CALLBACK_PCT": "0.0025",
        "NIJA_BREAKEVEN_PROFIT_THRESHOLD_PCT": "0.0090",
        "NIJA_BREAKEVEN_STOP_OFFSET_PCT": "0.0065",
        "NIJA_COMBO_BREAKEVEN_THRESHOLD_PCT": "0.0090",
        "NIJA_COMBO_BREAKEVEN_OFFSET_PCT": "0.0065",
        "NIJA_COMBO_TRAILING_SWITCH_PCT": "0.0125",
        "NIJA_COMBO_TRAILING_STOP_PCT": "0.0035",
        "NIJA_TRAILING_STOP_ACTIVATION_PCT": "0.0100",
        "NIJA_TRAILING_STOP_PCT": "0.0035",
        "NIJA_COMBINED_TRAILING_SL_ACTIVATION_PCT": "0.0100",
        "NIJA_COMBINED_TRAILING_SL_DISTANCE_PCT": "0.0035",
        "NIJA_COMBINED_TRAILING_TP_ACTIVATION_PCT": "0.0125",
        "NIJA_COMBINED_TRAILING_TP_CALLBACK_PCT": "0.0025",
        "NIJA_GLOBAL_TRAILING_ACTIVATION_PCT": "0.0100",
        "NIJA_GLOBAL_TRAILING_STOP_PCT": "0.0035",
        "NIJA_GLOBAL_TRAILING_TP_ACTIVATION_PCT": "0.0125",
    }
    os.environ.update(protected)


def _hold_skip(symbol: str, reason: str) -> dict[str, Any]:
    return {
        "action": "hold",
        "symbol": symbol,
        "reason": reason,
        "filter_stage": "profit_first_loss_prevention",
        "blocked_before_execute_action": True,
        "skip_before_execute_action": True,
        "fallback_entry_skipped": True,
        "forced_fallback": False,
        "fallback_entry": False,
        "order_should_not_submit": True,
    }


def _wrap_once(owner: Any, name: str, factory: Callable[[Callable[..., Any]], Callable[..., Any]], marker: str) -> bool:
    original = getattr(owner, name, None)
    if not callable(original) or getattr(original, marker, False):
        return False
    wrapped = factory(original)
    setattr(wrapped, marker, True)
    setattr(wrapped, "__wrapped__", original)
    setattr(owner, name, wrapped)
    return True


def _patch_frequency_controller(module: ModuleType) -> bool:
    cls = getattr(module, "TradeFrequencyController", None)
    if not isinstance(cls, type):
        return False
    changed = False

    def delta_factory(original: Callable[..., Any]):
        @wraps(original)
        def wrapped(self: Any, *args: Any, **kwargs: Any) -> float:
            value = original(self, *args, **kwargs)
            if _live_mode() and not _truthy("NIJA_ALLOW_LIVE_FREQUENCY_RELAXATION"):
                try:
                    self._confidence_delta = 0.0
                except Exception:
                    pass
                return 0.0
            return _f(value, 0.0)
        return wrapped

    def update_factory(original: Callable[..., Any]):
        @wraps(original)
        def wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
            out = original(self, *args, **kwargs)
            if _live_mode() and not _truthy("NIJA_ALLOW_LIVE_FREQUENCY_RELAXATION"):
                self._confidence_delta = 0.0
            return out
        return wrapped

    def drought_factory(original: Callable[..., Any]):
        @wraps(original)
        def wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
            result = original(self, *args, **kwargs)
            if not (_live_mode() and not _truthy("NIJA_ALLOW_LIVE_FREQUENCY_RELAXATION")):
                return result
            result_type = type(result)
            try:
                return result_type(
                    active=False,
                    secs_since_last_trade=_f(getattr(result, "secs_since_last_trade", 0.0)),
                    adx_reduction=0.0,
                    volume_multiplier=1.0,
                    score_reduction=0.0,
                    gate_pct_reduction=0.0,
                    confidence_delta=0.0,
                    reason="live frequency relaxation disabled by profit-first guard",
                )
            except Exception:
                for key, value in {
                    "active": False,
                    "adx_reduction": 0.0,
                    "volume_multiplier": 1.0,
                    "score_reduction": 0.0,
                    "gate_pct_reduction": 0.0,
                    "confidence_delta": 0.0,
                    "reason": "live frequency relaxation disabled by profit-first guard",
                }.items():
                    try:
                        setattr(result, key, value)
                    except Exception:
                        pass
                return result
        return wrapped

    changed |= _wrap_once(cls, "get_confidence_delta", delta_factory, "_nija_profit_first_delta_v1")
    changed |= _wrap_once(cls, "_update_delta", update_factory, "_nija_profit_first_update_v1")
    changed |= _wrap_once(cls, "get_drought_relaxation", drought_factory, "_nija_profit_first_drought_v1")
    if changed:
        logger.warning("PROFIT_FIRST_FREQUENCY_RELAXATION_DISABLED marker=%s", _MARKER)
    return changed


def _patch_core_loop(module: ModuleType) -> bool:
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False

    def factory(original: Callable[..., Any]):
        @wraps(original)
        def wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
            if _live_mode() and not _truthy("NIJA_LIVE_FALLBACK_ENTRY_ALLOWED"):
                sig = kwargs.get("sig") if "sig" in kwargs else (args[1] if len(args) > 1 else None)
                symbol = str(getattr(sig, "symbol", "UNKNOWN") or "UNKNOWN")
                logger.warning(
                    "LIVE_FALLBACK_ENTRY_BLOCKED marker=%s symbol=%s action=hold_skip_before_execute",
                    _MARKER,
                    symbol,
                )
                return _hold_skip(symbol, "live_fallback_entry_disabled")
            return original(self, *args, **kwargs)
        return wrapped

    changed = _wrap_once(
        cls,
        "_build_forced_fallback_entry_analysis",
        factory,
        "_nija_profit_first_fallback_block_v1",
    )
    if changed:
        logger.warning("PROFIT_FIRST_FALLBACK_ENTRY_GUARD_PATCHED marker=%s", _MARKER)
    return changed


def _raw_mapping(raw: Any) -> Optional[dict[str, Any]]:
    if isinstance(raw, Mapping):
        return dict(raw)
    data = getattr(raw, "__dict__", None)
    return dict(data) if isinstance(data, Mapping) else None


def _recover_cost_basis(raw: Any) -> float:
    data = _raw_mapping(raw)
    if not data:
        return 0.0
    qty = 0.0
    for key in ("qty", "quantity", "amount", "size", "units", "balance", "total", "available", "free"):
        qty = abs(_f(data.get(key), 0.0))
        if qty > 0:
            break
    direct_keys = (
        "entry_price", "avg_entry_price", "average_price", "cost_basis_price",
        "average_filled_price", "avg_fill_price", "avg_price", "purchase_price",
    )
    for key in direct_keys:
        value = _f(data.get(key), 0.0)
        if value > 0:
            return value
    basis = data.get("cost_basis")
    if isinstance(basis, Mapping):
        for key in ("price", "average_price", "avg_price", "cost_basis_price"):
            value = _f(basis.get(key), 0.0)
            if value > 0:
                return value
        for key in ("amount", "value", "total", "cost"):
            total = _f(basis.get(key), 0.0)
            if total > 0 and qty > 0:
                return total / qty
    elif qty > 0:
        total = _f(basis, 0.0)
        if total > 0:
            return total / qty
    if qty > 0:
        for key in ("cost_basis_usd", "total_cost", "cost", "invested_amount", "net_invested"):
            total = _f(data.get(key), 0.0)
            if total > 0:
                return total / qty
    return 0.0


def _mark_cost_basis(position: Any, verified: bool) -> Any:
    if not isinstance(position, MutableMapping):
        return position
    if verified:
        position["cost_basis_verified"] = True
        position["auto_exit_blocked"] = False
        return position
    position["cost_basis_verified"] = False
    position["auto_exit_blocked"] = True
    position["auto_exit_block_reason"] = "unverified_cost_basis"
    position["exit_profile"] = "UNVERIFIED_COST_BASIS_RECONCILIATION_REQUIRED"
    position["reconciliation_required"] = True
    position["notes"] = (str(position.get("notes") or "") + "\nUNVERIFIED_COST_BASIS_RECONCILIATION_REQUIRED").strip()
    # Do not let an adoption-mark-derived stop or target masquerade as P&L truth.
    for key in ("stop_loss", "take_profit_1", "take_profit_2", "take_profit_3"):
        position.pop(key, None)
    return position


def _patch_live_adoption(module: ModuleType) -> bool:
    def factory(original: Callable[..., Any]):
        @wraps(original)
        def wrapped(raw: Any, broker: Any, broker_name: str, account_id: str) -> Any:
            recovered = _recover_cost_basis(raw)
            source_raw = _raw_mapping(raw)
            payload = raw
            if recovered > 0 and source_raw is not None:
                source_raw["entry_price"] = recovered
                payload = source_raw
            position = original(payload, broker, broker_name, account_id)
            if not isinstance(position, MutableMapping):
                return position
            source = str(position.get("entry_price_source") or "")
            verified = recovered > 0 or (source == "broker_cost_basis" and _f(position.get("entry_price")) > 0)
            _mark_cost_basis(position, verified)
            if not verified:
                logger.critical(
                    "ADOPTED_POSITION_COST_BASIS_UNVERIFIED marker=%s account=%s broker=%s symbol=%s auto_exit_blocked=true",
                    _MARKER,
                    account_id,
                    broker_name,
                    position.get("symbol"),
                )
            return position
        return wrapped

    changed = _wrap_once(module, "_normalize_position", factory, "_nija_profit_first_adoption_v1")
    if changed:
        logger.warning("PROFIT_FIRST_ADOPTED_COST_BASIS_GUARD_PATCHED marker=%s", _MARKER)
    return changed


def _is_unverified_position(position: Any) -> bool:
    if not isinstance(position, Mapping):
        return False
    if position.get("cost_basis_verified") is False or position.get("auto_exit_blocked") is True:
        return True
    source = str(position.get("entry_price_source") or "").lower()
    profile = str(position.get("exit_profile") or "").lower()
    notes = str(position.get("notes") or "").lower()
    return (
        "estimated_from_adoption_mark" in source
        or "unverified_cost_basis" in profile
        or "unverified_cost_basis" in notes
    )


def _guard_position_predicate(module: ModuleType, name: str, blocked_value: Any) -> bool:
    def factory(original: Callable[..., Any]):
        @wraps(original)
        def wrapped(position: Any, *args: Any, **kwargs: Any) -> Any:
            if _is_unverified_position(position):
                logger.warning(
                    "AUTO_EXIT_SKIPPED_UNVERIFIED_COST_BASIS marker=%s module=%s symbol=%s",
                    _MARKER,
                    getattr(module, "__name__", "unknown"),
                    position.get("symbol") if isinstance(position, Mapping) else "unknown",
                )
                return blocked_value() if callable(blocked_value) else blocked_value
            return original(position, *args, **kwargs)
        return wrapped
    return _wrap_once(module, name, factory, f"_nija_profit_first_{name}_v1")


def _patch_exit_module(module: ModuleType) -> bool:
    name = getattr(module, "__name__", "")
    changed = False
    if name.endswith("auto_exit_sl_tp_runtime_patch"):
        changed |= _guard_position_predicate(module, "_trigger", lambda: (False, "unverified_cost_basis", 0.0))
    elif name.endswith("trailing_take_profit_runtime_patch"):
        changed |= _guard_position_predicate(module, "_armed", False)
    elif name.endswith("trailing_stop_loss_runtime_patch"):
        changed |= _guard_position_predicate(module, "_update_trailing_state", lambda: (False, {}))
    elif name.endswith("breakeven_stop_loss_runtime_patch"):
        changed |= _guard_position_predicate(module, "_is_threshold_reached", False)
    elif name.endswith("combo_breakeven_trailing_runtime_patch"):
        changed |= _guard_position_predicate(module, "_profit_threshold_hit", False)
    elif name.endswith("combined_trailing_tp_sl_runtime_patch"):
        changed |= _guard_position_predicate(module, "_fav_hit", False)
    elif name.endswith("global_trailing_protection_patch"):
        def factory(original: Callable[..., Any]):
            @wraps(original)
            def wrapped(position: Any, *args: Any, **kwargs: Any) -> Any:
                if _is_unverified_position(position):
                    if isinstance(position, MutableMapping):
                        position["global_trailing_protection"] = False
                        position["profit_lock_enabled"] = False
                    return position
                return original(position, *args, **kwargs)
            return wrapped
        changed |= _wrap_once(module, "attach_global_trailing_protection", factory, "_nija_profit_first_global_guard_v1")
    if changed:
        logger.warning("PROFIT_FIRST_EXIT_COST_BASIS_GUARD_PATCHED marker=%s module=%s", _MARKER, name)
    return changed


def _normalize_atr_pct(levels: Any, kwargs: Mapping[str, Any]) -> float:
    candidates: list[Any] = []
    if isinstance(levels, Mapping):
        candidates.extend(levels.get(key) for key in ("atr_pct", "atr_percent", "volatility_pct"))
    candidates.extend(kwargs.get(key) for key in ("atr_pct", "atr_percent", "volatility_pct"))
    for value in candidates:
        pct = _f(value, 0.0)
        if pct > 1.0:
            pct /= 100.0
        if pct > 0:
            return pct
    return 0.0


def _safe_stop_geometry(
    side: str,
    position_size: float,
    entry_price: float,
    stop_loss: float,
    levels: Any = None,
    kwargs: Optional[Mapping[str, Any]] = None,
) -> tuple[float, float, float, float]:
    entry = _f(entry_price, 0.0)
    stop = _f(stop_loss, 0.0)
    size = _f(position_size, 0.0)
    if entry <= 0 or stop <= 0 or size <= 0:
        return size, stop, 0.0, 0.0
    old_pct = abs(entry - stop) / entry
    min_pct = max(0.005, _f(os.environ.get("NIJA_PROFIT_FIRST_MIN_STOP_PCT"), 0.015))
    max_pct = max(min_pct, _f(os.environ.get("NIJA_PROFIT_FIRST_MAX_STOP_PCT"), 0.025))
    atr_pct = _normalize_atr_pct(levels, kwargs or {})
    desired = min(max_pct, max(min_pct, 1.2 * atr_pct if atr_pct > 0 else min_pct))
    new_pct = min(max_pct, max(old_pct, desired))
    direction = str(side or "long").strip().lower()
    new_stop = entry * (1.0 + new_pct) if direction in {"short", "sell"} else entry * (1.0 - new_pct)
    # Preserve the pre-existing maximum dollar risk when widening the stop.
    new_size = size
    if old_pct > 0 and new_pct > old_pct:
        new_size = size * old_pct / new_pct
    return max(0.0, new_size), new_stop, old_pct, new_pct


def _patch_execution_geometry_module(module: ModuleType) -> bool:
    if not hasattr(module, "_max_sl_pct"):
        return False
    def safe_max_sl_pct() -> float:
        return max(0.015, min(_f(os.environ.get("NIJA_PROFIT_FIRST_MAX_STOP_PCT"), 0.025), 0.05))
    safe_max_sl_pct._nija_profit_first_max_sl_v1 = True  # type: ignore[attr-defined]
    module._max_sl_pct = safe_max_sl_pct  # type: ignore[attr-defined]
    logger.warning("PROFIT_FIRST_LEGACY_STOP_CAP_REPLACED marker=%s max_stop_pct=%.4f", _MARKER, safe_max_sl_pct())
    return True


def _patch_execution_engine(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionEngine", None)
    if not isinstance(cls, type):
        return False

    def entry_factory(original: Callable[..., Any]):
        @wraps(original)
        def wrapped(
            self: Any,
            symbol: str,
            side: str,
            position_size: float,
            entry_price: float,
            stop_loss: float,
            take_profit_levels: Any,
            *args: Any,
            **kwargs: Any,
        ) -> Any:
            if _live_mode():
                new_size, new_stop, old_pct, new_pct = _safe_stop_geometry(
                    side, position_size, entry_price, stop_loss, take_profit_levels, kwargs
                )
                if new_size <= 0:
                    logger.critical("ENTRY_BLOCKED_INVALID_RISK_GEOMETRY marker=%s symbol=%s", _MARKER, symbol)
                    return None
                if abs(new_pct - old_pct) > 1e-12:
                    logger.critical(
                        "ENTRY_RISK_GEOMETRY_REPAIRED marker=%s symbol=%s side=%s old_stop_pct=%.4f new_stop_pct=%.4f old_size=%.4f new_size=%.4f risk_preserved=true",
                        _MARKER, symbol, side, old_pct, new_pct, position_size, new_size,
                    )
                position_size, stop_loss = new_size, new_stop
            return original(self, symbol, side, position_size, entry_price, stop_loss, take_profit_levels, *args, **kwargs)
        return wrapped

    changed = _wrap_once(cls, "execute_entry", entry_factory, "_nija_profit_first_execute_entry_v1")
    if changed:
        logger.warning("PROFIT_FIRST_EXECUTION_GEOMETRY_PATCHED marker=%s", _MARKER)
    return changed


def _validate_live_fill_result(result: Any, request: Any = None) -> Any:
    if not _live_mode() or not getattr(result, "success", False):
        return result
    intent = str(getattr(request, "intent_type", "entry") or "entry").strip().lower()
    if intent != "entry":
        return result
    fill_price = _f(getattr(result, "fill_price", 0.0), 0.0)
    filled_size = _f(getattr(result, "filled_size_usd", 0.0), 0.0)
    if fill_price > 0 and filled_size > 0:
        try:
            setattr(result, "fill_confirmed", True)
        except Exception:
            pass
        return result
    try:
        setattr(result, "success", False)
        setattr(result, "error", "LIVE_FILL_CONFIRMATION_REQUIRED: nonpositive fill_price or filled_size_usd")
        setattr(result, "fill_confirmed", False)
    except Exception:
        pass
    logger.critical(
        "LIVE_ENTRY_FILL_REJECTED marker=%s symbol=%s fill_price=%.8f filled_size_usd=%.8f",
        _MARKER,
        getattr(request, "symbol", getattr(result, "symbol", "UNKNOWN")),
        fill_price,
        filled_size,
    )
    return result


def _patch_execution_pipeline(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionPipeline", None)
    if not isinstance(cls, type):
        return False
    def factory(original: Callable[..., Any]):
        @wraps(original)
        def wrapped(self: Any, request: Any, *args: Any, **kwargs: Any) -> Any:
            result = original(self, request, *args, **kwargs)
            return _validate_live_fill_result(result, request)
        return wrapped
    changed = _wrap_once(cls, "execute", factory, "_nija_profit_first_fill_validation_v1")
    if changed:
        logger.warning("PROFIT_FIRST_LIVE_FILL_VALIDATION_PATCHED marker=%s", _MARKER)
    return changed


_TARGET_SUFFIXES = (
    "trade_frequency_controller",
    "nija_core_loop",
    "live_entry_runtime_fixes",
    "auto_exit_sl_tp_runtime_patch",
    "trailing_take_profit_runtime_patch",
    "trailing_stop_loss_runtime_patch",
    "breakeven_stop_loss_runtime_patch",
    "combo_breakeven_trailing_runtime_patch",
    "combined_trailing_tp_sl_runtime_patch",
    "global_trailing_protection_patch",
    "execution_entry_tp_geometry_patch",
    "execution_engine",
    "execution_pipeline",
)


def _patch_module(module: ModuleType) -> bool:
    name = str(getattr(module, "__name__", ""))
    try:
        if name.endswith("trade_frequency_controller"):
            return _patch_frequency_controller(module)
        if name.endswith("nija_core_loop"):
            return _patch_core_loop(module)
        if name.endswith("live_entry_runtime_fixes"):
            return _patch_live_adoption(module)
        if name.endswith("execution_entry_tp_geometry_patch"):
            return _patch_execution_geometry_module(module)
        if name.endswith("execution_engine"):
            return _patch_execution_engine(module)
        if name.endswith("execution_pipeline"):
            return _patch_execution_pipeline(module)
        return _patch_exit_module(module)
    except Exception as exc:
        logger.exception("PROFIT_FIRST_PATCH_FAILED marker=%s module=%s error=%s", _MARKER, name, exc)
        return False


def _try_patch_loaded() -> bool:
    patched = False
    with _PATCH_LOCK:
        for module in tuple(sys.modules.values()):
            if not isinstance(module, ModuleType):
                continue
            name = str(getattr(module, "__name__", ""))
            if any(name.endswith(suffix) for suffix in _TARGET_SUFFIXES):
                patched = _patch_module(module) or patched
    return patched


def _start_monitor() -> None:
    if getattr(builtins, "_NIJA_PROFIT_FIRST_MONITOR_V1", False):
        return
    setattr(builtins, "_NIJA_PROFIT_FIRST_MONITOR_V1", True)

    def run() -> None:
        deadline = time.time() + max(30.0, _f(os.environ.get("NIJA_PATCH_MONITOR_SECONDS"), 300.0))
        while time.time() < deadline:
            _force_live_defaults()
            _try_patch_loaded()
            time.sleep(0.5)
        logger.warning("PROFIT_FIRST_PATCH_MONITOR_COMPLETE marker=%s", _MARKER)

    threading.Thread(target=run, name="nija-profit-first-guard", daemon=True).start()


def install_import_hook() -> None:
    _force_live_defaults()
    _try_patch_loaded()
    _start_monitor()
    if getattr(builtins, _IMPORT_FLAG, False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        if getattr(_IMPORT_GUARD, "active", False):
            return original_import(name, globals, locals, fromlist, level)
        _IMPORT_GUARD.active = True
        try:
            module = original_import(name, globals, locals, fromlist, level)
            _force_live_defaults()
            _try_patch_loaded()
            return module
        finally:
            _IMPORT_GUARD.active = False

    builtins.__import__ = guarded_import
    setattr(builtins, _IMPORT_FLAG, True)
    setattr(builtins, _INSTALL_FLAG, True)
    logger.warning(
        "PROFIT_FIRST_LOSS_PREVENTION_INSTALLED marker=%s live=%s fallback_allowed=%s frequency_relaxation=%s",
        _MARKER,
        _live_mode(),
        _truthy("NIJA_LIVE_FALLBACK_ENTRY_ALLOWED"),
        _truthy("NIJA_ALLOW_LIVE_FREQUENCY_RELAXATION"),
    )


def install() -> None:
    install_import_hook()
