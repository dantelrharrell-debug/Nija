"""Fail-closed Kraken/Coinbase loss-prevention convergence for NIJA live mode."""
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
_MARKER = "20260713_profit_first_v2"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_LOCK = threading.RLock()
_IMPORT_GUARD = threading.local()
_TARGETS = (
    "trade_frequency_controller", "nija_core_loop", "live_entry_runtime_fixes",
    "auto_exit_sl_tp_runtime_patch", "trailing_take_profit_runtime_patch",
    "trailing_stop_loss_runtime_patch", "breakeven_stop_loss_runtime_patch",
    "combo_breakeven_trailing_runtime_patch", "combined_trailing_tp_sl_runtime_patch",
    "global_trailing_protection_patch", "execution_entry_tp_geometry_patch",
    "execution_engine", "execution_pipeline",
)


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUE


def _live_mode() -> bool:
    return not _truthy("DRY_RUN_MODE") and not _truthy("PAPER_MODE")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        value = float(value)
        return default if value != value else value
    except Exception:
        return default


def _force_live_defaults() -> None:
    if not _live_mode() or _truthy("NIJA_PROFIT_FIRST_ALLOW_UNSAFE_OVERRIDES"):
        return
    os.environ.update({
        "FORCE_TRADE": "false",
        "NIJA_LIVE_FALLBACK_ENTRY_ALLOWED": "false",
        "NIJA_ALLOW_LIVE_FREQUENCY_RELAXATION": "false",
        "MAX_SL_PCT": "0.025",
        "NIJA_GLOBAL_STOP_LOSS_PCT": "0.015",
        "NIJA_PROFIT_FIRST_MIN_STOP_PCT": "0.015",
        "NIJA_PROFIT_FIRST_MAX_STOP_PCT": "0.025",
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
    })


def _wrap_once(owner: Any, name: str, marker: str, factory: Callable[[Callable[..., Any]], Callable[..., Any]]) -> bool:
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

    def delta(original):
        @wraps(original)
        def wrapped(self, *args, **kwargs):
            value = original(self, *args, **kwargs)
            if _live_mode() and not _truthy("NIJA_ALLOW_LIVE_FREQUENCY_RELAXATION"):
                self._confidence_delta = 0.0
                return 0.0
            return value
        return wrapped

    def update(original):
        @wraps(original)
        def wrapped(self, *args, **kwargs):
            value = original(self, *args, **kwargs)
            if _live_mode() and not _truthy("NIJA_ALLOW_LIVE_FREQUENCY_RELAXATION"):
                self._confidence_delta = 0.0
            return value
        return wrapped

    def drought(original):
        @wraps(original)
        def wrapped(self, *args, **kwargs):
            result = original(self, *args, **kwargs)
            if not (_live_mode() and not _truthy("NIJA_ALLOW_LIVE_FREQUENCY_RELAXATION")):
                return result
            values = dict(
                active=False,
                secs_since_last_trade=_f(getattr(result, "secs_since_last_trade", 0.0)),
                adx_reduction=0.0,
                volume_multiplier=1.0,
                score_reduction=0.0,
                gate_pct_reduction=0.0,
                confidence_delta=0.0,
                reason="live frequency relaxation disabled by profit-first guard",
            )
            try:
                return type(result)(**values)
            except Exception:
                for key, value in values.items():
                    try:
                        setattr(result, key, value)
                    except Exception:
                        pass
                return result
        return wrapped

    changed = _wrap_once(cls, "get_confidence_delta", "_nija_profit_first_delta_v2", delta)
    changed |= _wrap_once(cls, "_update_delta", "_nija_profit_first_update_v2", update)
    changed |= _wrap_once(cls, "get_drought_relaxation", "_nija_profit_first_drought_v2", drought)
    if changed:
        logger.warning("PROFIT_FIRST_FREQUENCY_RELAXATION_DISABLED marker=%s", _MARKER)
    return changed


def _patch_core_loop(module: ModuleType) -> bool:
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False

    def factory(original):
        @wraps(original)
        def wrapped(self, *args, **kwargs):
            if not (_live_mode() and not _truthy("NIJA_LIVE_FALLBACK_ENTRY_ALLOWED")):
                return original(self, *args, **kwargs)
            sig = kwargs.get("sig") if "sig" in kwargs else (args[1] if len(args) > 1 else None)
            symbol = str(getattr(sig, "symbol", "UNKNOWN") or "UNKNOWN")
            logger.warning("LIVE_FALLBACK_ENTRY_BLOCKED marker=%s symbol=%s", _MARKER, symbol)
            return {
                "action": "hold", "symbol": symbol, "reason": "live_fallback_entry_disabled",
                "filter_stage": "profit_first_loss_prevention",
                "blocked_before_execute_action": True, "skip_before_execute_action": True,
                "fallback_entry_skipped": True, "forced_fallback": False,
                "fallback_entry": False, "order_should_not_submit": True,
            }
        return wrapped

    return _wrap_once(
        cls, "_build_forced_fallback_entry_analysis",
        "_nija_profit_first_fallback_v2", factory,
    )


def _mapping(raw: Any) -> Optional[dict[str, Any]]:
    if isinstance(raw, Mapping):
        return dict(raw)
    raw = getattr(raw, "__dict__", None)
    return dict(raw) if isinstance(raw, Mapping) else None


def _recover_cost_basis(raw: Any) -> float:
    data = _mapping(raw)
    if not data:
        return 0.0
    qty = next((abs(_f(data.get(k))) for k in
                ("qty", "quantity", "amount", "size", "units", "balance", "available", "free")
                if abs(_f(data.get(k))) > 0), 0.0)
    for key in ("entry_price", "avg_entry_price", "average_price", "cost_basis_price",
                "average_filled_price", "avg_fill_price", "avg_price", "purchase_price"):
        value = _f(data.get(key))
        if value > 0:
            return value
    basis = data.get("cost_basis")
    if isinstance(basis, Mapping):
        for key in ("price", "average_price", "avg_price", "cost_basis_price"):
            value = _f(basis.get(key))
            if value > 0:
                return value
        total = next((_f(basis.get(k)) for k in ("amount", "value", "total", "cost")
                      if _f(basis.get(k)) > 0), 0.0)
        return total / qty if total > 0 and qty > 0 else 0.0
    if qty > 0 and _f(basis) > 0:
        total = _f(basis)
        mark = next((_f(data.get(k)) for k in ("mark_price", "current_price", "last_price", "price")
                     if _f(data.get(k)) > 0), 0.0)
        if mark > 0 and mark * 0.10 <= total <= mark * 10.0:
            return total
        return total / qty
    if qty > 0:
        total = next((_f(data.get(k)) for k in
                      ("cost_basis_usd", "total_cost", "cost", "invested_amount", "net_invested")
                      if _f(data.get(k)) > 0), 0.0)
        if total > 0:
            return total / qty
    return 0.0


def _mark_cost_basis(position: Any, verified: bool) -> Any:
    if not isinstance(position, MutableMapping):
        return position
    position["cost_basis_verified"] = verified
    position["auto_exit_blocked"] = not verified
    if verified:
        return position
    position.update({
        "auto_exit_block_reason": "unverified_cost_basis",
        "exit_profile": "UNVERIFIED_COST_BASIS_RECONCILIATION_REQUIRED",
        "reconciliation_required": True,
    })
    position["notes"] = (str(position.get("notes") or "") +
                         "\nUNVERIFIED_COST_BASIS_RECONCILIATION_REQUIRED").strip()
    for key in ("stop_loss", "take_profit_1", "take_profit_2", "take_profit_3"):
        position.pop(key, None)
    return position


def _patch_live_adoption(module: ModuleType) -> bool:
    def factory(original):
        @wraps(original)
        def wrapped(raw, broker, broker_name, account_id):
            recovered = _recover_cost_basis(raw)
            payload = _mapping(raw) if recovered > 0 else raw
            if isinstance(payload, dict) and recovered > 0:
                payload["entry_price"] = recovered
            position = original(payload, broker, broker_name, account_id)
            if not isinstance(position, MutableMapping):
                return position
            source = str(position.get("entry_price_source") or "")
            verified = recovered > 0 or (source == "broker_cost_basis" and _f(position.get("entry_price")) > 0)
            _mark_cost_basis(position, verified)
            if not verified:
                logger.critical(
                    "ADOPTED_POSITION_COST_BASIS_UNVERIFIED marker=%s account=%s broker=%s symbol=%s",
                    _MARKER, account_id, broker_name, position.get("symbol"),
                )
            return position
        return wrapped
    return _wrap_once(module, "_normalize_position", "_nija_profit_first_adoption_v2", factory)


def _is_unverified_position(position: Any) -> bool:
    if not isinstance(position, Mapping):
        return False
    text = " ".join(str(position.get(k) or "").lower()
                    for k in ("entry_price_source", "exit_profile", "notes"))
    return (position.get("cost_basis_verified") is False or
            position.get("auto_exit_blocked") is True or
            "estimated_from_adoption_mark" in text or "unverified_cost_basis" in text)


def _guard_predicate(module: ModuleType, name: str, blocked: Any) -> bool:
    def factory(original):
        @wraps(original)
        def wrapped(position, *args, **kwargs):
            if _is_unverified_position(position):
                logger.warning("AUTO_EXIT_SKIPPED_UNVERIFIED_COST_BASIS marker=%s module=%s symbol=%s",
                               _MARKER, module.__name__, position.get("symbol", "unknown"))
                return blocked() if callable(blocked) else blocked
            return original(position, *args, **kwargs)
        return wrapped
    return _wrap_once(module, name, f"_nija_profit_first_{name}_v2", factory)


def _patch_exit_module(module: ModuleType) -> bool:
    name = module.__name__
    predicates = {
        "auto_exit_sl_tp_runtime_patch": ("_trigger", lambda: (False, "unverified_cost_basis", 0.0)),
        "trailing_take_profit_runtime_patch": ("_armed", False),
        "trailing_stop_loss_runtime_patch": ("_update_trailing_state", lambda: (False, {})),
        "breakeven_stop_loss_runtime_patch": ("_is_threshold_reached", False),
        "combo_breakeven_trailing_runtime_patch": ("_profit_threshold_hit", False),
        "combined_trailing_tp_sl_runtime_patch": ("_fav_hit", False),
    }
    for suffix, (function, blocked) in predicates.items():
        if name.endswith(suffix):
            return _guard_predicate(module, function, blocked)
    if not name.endswith("global_trailing_protection_patch"):
        return False

    def factory(original):
        @wraps(original)
        def wrapped(position, *args, **kwargs):
            if _is_unverified_position(position):
                if isinstance(position, MutableMapping):
                    position["global_trailing_protection"] = False
                    position["profit_lock_enabled"] = False
                return position
            return original(position, *args, **kwargs)
        return wrapped
    return _wrap_once(module, "attach_global_trailing_protection",
                      "_nija_profit_first_global_guard_v2", factory)


def _atr_pct(levels: Any, kwargs: Mapping[str, Any]) -> float:
    values = []
    if isinstance(levels, Mapping):
        values += [levels.get(k) for k in ("atr_pct", "atr_percent", "volatility_pct")]
    values += [kwargs.get(k) for k in ("atr_pct", "atr_percent", "volatility_pct")]
    for value in values:
        value = _f(value)
        if value > 1:
            value /= 100
        if value > 0:
            return value
    return 0.0


def _safe_stop_geometry(side: str, position_size: float, entry_price: float,
                        stop_loss: float, levels: Any = None,
                        kwargs: Optional[Mapping[str, Any]] = None) -> tuple[float, float, float, float]:
    entry, stop, size = _f(entry_price), _f(stop_loss), _f(position_size)
    if entry <= 0 or stop <= 0 or size <= 0:
        return size, stop, 0.0, 0.0
    old_pct = abs(entry - stop) / entry
    if old_pct <= 0:
        return 0.0, stop, old_pct, old_pct
    minimum = max(0.005, _f(os.environ.get("NIJA_PROFIT_FIRST_MIN_STOP_PCT"), 0.015))
    maximum = max(minimum, _f(os.environ.get("NIJA_PROFIT_FIRST_MAX_STOP_PCT"), 0.025))
    atr = _atr_pct(levels, kwargs or {})
    desired = min(maximum, max(minimum, atr * 1.2 if atr > 0 else minimum))
    new_pct = min(maximum, max(old_pct, desired))
    short = str(side or "").lower() in {"short", "sell"}
    new_stop = entry * (1 + new_pct if short else 1 - new_pct)
    new_size = size * old_pct / new_pct if new_pct > old_pct else size
    return max(0.0, new_size), new_stop, old_pct, new_pct


def _patch_geometry_module(module: ModuleType) -> bool:
    current = getattr(module, "_max_sl_pct", None)
    if not callable(current) or getattr(current, "_nija_profit_first_max_sl_v2", False):
        return False

    def safe_max_sl_pct() -> float:
        return max(0.015, min(_f(os.environ.get("NIJA_PROFIT_FIRST_MAX_STOP_PCT"), 0.025), 0.05))
    safe_max_sl_pct._nija_profit_first_max_sl_v2 = True  # type: ignore[attr-defined]
    module._max_sl_pct = safe_max_sl_pct  # type: ignore[attr-defined]
    logger.warning("PROFIT_FIRST_LEGACY_STOP_CAP_REPLACED marker=%s max_stop_pct=%.4f",
                   _MARKER, safe_max_sl_pct())
    return True


def _patch_execution_engine(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionEngine", None)
    if not isinstance(cls, type):
        return False

    def factory(original):
        @wraps(original)
        def wrapped(self, symbol, side, position_size, entry_price, stop_loss,
                    take_profit_levels, *args, **kwargs):
            if _live_mode():
                new_size, new_stop, old_pct, new_pct = _safe_stop_geometry(
                    side, position_size, entry_price, stop_loss, take_profit_levels, kwargs)
                minimum_notional = max(0.0, _f(os.environ.get("MIN_TRADE_USD"),
                                                    _f(os.environ.get("MIN_NOTIONAL_USD"))))
                if new_size <= 0 or (minimum_notional > 0 and new_size + 1e-9 < minimum_notional):
                    logger.critical(
                        "ENTRY_BLOCKED_RISK_NOTIONAL_CONFLICT marker=%s symbol=%s safe_size=%.4f minimum=%.4f",
                        _MARKER, symbol, new_size, minimum_notional,
                    )
                    return None
                if abs(new_pct - old_pct) > 1e-12:
                    logger.critical(
                        "ENTRY_RISK_GEOMETRY_REPAIRED marker=%s symbol=%s old_stop_pct=%.4f new_stop_pct=%.4f old_size=%.4f new_size=%.4f risk_preserved=true",
                        _MARKER, symbol, old_pct, new_pct, position_size, new_size,
                    )
                position_size, stop_loss = new_size, new_stop
            return original(self, symbol, side, position_size, entry_price, stop_loss,
                            take_profit_levels, *args, **kwargs)
        return wrapped
    return _wrap_once(cls, "execute_entry", "_nija_profit_first_execute_entry_v2", factory)


def _validate_live_fill_result(result: Any, request: Any = None) -> Any:
    if not _live_mode() or not getattr(result, "success", False):
        return result
    if str(getattr(request, "intent_type", "entry") or "entry").lower() != "entry":
        return result
    price, size = _f(getattr(result, "fill_price", 0)), _f(getattr(result, "filled_size_usd", 0))
    if price > 0 and size > 0:
        try:
            result.fill_confirmed = True
        except Exception:
            pass
        return result
    try:
        result.success = False
        result.error = "LIVE_FILL_CONFIRMATION_REQUIRED: nonpositive fill_price or filled_size_usd"
        result.fill_confirmed = False
    except Exception:
        pass
    logger.critical("LIVE_ENTRY_FILL_REJECTED marker=%s symbol=%s fill_price=%.8f filled_size=%.8f",
                    _MARKER, getattr(request, "symbol", "UNKNOWN"), price, size)
    return result


def _patch_execution_pipeline(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionPipeline", None)
    if not isinstance(cls, type):
        return False

    def factory(original):
        @wraps(original)
        def wrapped(self, request, *args, **kwargs):
            return _validate_live_fill_result(original(self, request, *args, **kwargs), request)
        return wrapped
    return _wrap_once(cls, "execute", "_nija_profit_first_fill_v2", factory)


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
            return _patch_geometry_module(module)
        if name.endswith("execution_engine"):
            return _patch_execution_engine(module)
        if name.endswith("execution_pipeline"):
            return _patch_execution_pipeline(module)
        return _patch_exit_module(module)
    except Exception as exc:
        logger.exception("PROFIT_FIRST_PATCH_FAILED marker=%s module=%s error=%s", _MARKER, name, exc)
        return False


def _try_patch_loaded() -> bool:
    changed = False
    with _LOCK:
        for module in tuple(sys.modules.values()):
            if isinstance(module, ModuleType) and any(module.__name__.endswith(x) for x in _TARGETS):
                changed = _patch_module(module) or changed
    return changed


def _start_monitor() -> None:
    if getattr(builtins, "_NIJA_PROFIT_FIRST_MONITOR_V2", False):
        return
    setattr(builtins, "_NIJA_PROFIT_FIRST_MONITOR_V2", True)

    def monitor():
        deadline = time.time() + max(30.0, _f(os.environ.get("NIJA_PATCH_MONITOR_SECONDS"), 300.0))
        while time.time() < deadline:
            _force_live_defaults()
            _try_patch_loaded()
            time.sleep(0.5)
    threading.Thread(target=monitor, name="nija-profit-first-guard", daemon=True).start()


def install_import_hook() -> None:
    _force_live_defaults()
    _try_patch_loaded()
    _start_monitor()
    if getattr(builtins, "_NIJA_PROFIT_FIRST_IMPORT_HOOK_V2", False):
        return
    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
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
    setattr(builtins, "_NIJA_PROFIT_FIRST_IMPORT_HOOK_V2", True)
    logger.warning("PROFIT_FIRST_LOSS_PREVENTION_INSTALLED marker=%s live=%s", _MARKER, _live_mode())


def install() -> None:
    install_import_hook()
