"""Assure fixed and trailing exit protections remain active across NIJA.

This startup patch is the shared safety bridge for platform and user trading.  It
keeps NIJA's existing stop-loss and v239 take-profit policies, adds symmetric
long/short trailing protection at the shared trigger boundary, and makes
protective closes fail closed unless a fill is actually proven.

It does not change position sizing, leverage, entry signals, writer authority,
nonce checks, broker readiness, minimum-order rules, or kill-switch behavior.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
from collections.abc import Mapping
from functools import wraps
from types import ModuleType
from typing import Any, Callable

logger = logging.getLogger("nija.exit_protection_assurance")
_MARKER = "20260905-exit-protection-assurance-v2"
_PATCHED = "__nija_exit_protection_assurance_v2__"
_KRAKEN_PATCHED = "__nija_exit_protection_assurance_v2_kraken__"
_FILL_PATCHED = "__nija_exit_protection_assurance_v2_fill__"
_HOOK = "_NIJA_EXIT_PROTECTION_ASSURANCE_IMPORT_HOOK_V2"

_FILL_LIKE = {
    "filled", "closed", "done", "complete", "completed", "success", "settled",
}
_REJECT_LIKE = {
    "error", "failed", "rejected", "cancelled", "canceled", "expired",
    "unfilled", "pending", "open", "accepted", "acknowledged", "new",
}
_PROTECTION_MODULES = {
    "bot.auto_exit_sl_tp_runtime_patch",
    "auto_exit_sl_tp_runtime_patch",
    "bot.trailing_stop_loss_runtime_patch",
    "trailing_stop_loss_runtime_patch",
    "bot.trailing_take_profit_runtime_patch",
    "trailing_take_profit_runtime_patch",
    "bot.combined_trailing_tp_sl_runtime_patch",
    "combined_trailing_tp_sl_runtime_patch",
    "bot.combo_breakeven_trailing_runtime_patch",
    "combo_breakeven_trailing_runtime_patch",
    "bot.breakeven_stop_loss_runtime_patch",
    "breakeven_stop_loss_runtime_patch",
}
_KRAKEN_MODULES = {
    "bot.kraken_all_account_exit_runtime_patch",
    "kraken_all_account_exit_runtime_patch",
}


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in {
        "1", "true", "yes", "on", "enabled", "y",
    }


def _f(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return default if parsed != parsed else parsed
    except Exception:
        return default


def _configure() -> None:
    defaults = {
        "NIJA_AUTO_EXIT_SL_TP_ENABLED": "true",
        "NIJA_AUTO_EXIT_POLL_SECONDS": "3",
        "NIJA_HARD_STOP_LOSS_PCT": "0.015",
        "NIJA_MAX_POSITION_LOSS_USD": "2.00",
        "NIJA_PROFIT_TAKE_ENABLED": "true",
        "NIJA_PROFIT_LOCK_ACTIVATION_PCT": "0.008",
        "NIJA_PROFIT_LOCK_CALLBACK_PCT": "0.0035",
        "NIJA_TRAILING_STOP_ENABLED": "true",
        "NIJA_TRAILING_STOP_ACTIVATION_PCT": "0.008",
        "NIJA_TRAILING_STOP_PCT": "0.0035",
        "NIJA_TRAILING_TP_ENABLED": "true",
        "NIJA_TRAILING_TP_ACTIVATION_PCT": "0.008",
        "NIJA_TRAILING_TP_CALLBACK_PCT": "0.0035",
        "NIJA_COMBINED_TRAILING_TP_SL_ENABLED": "true",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


def _filled_result(payload: Any) -> bool:
    """Return true only for terminal/positive fill evidence.

    An exchange acknowledgement, accepted status, or bare order id is not a
    confirmed protective close.
    """
    if not isinstance(payload, Mapping):
        return False
    status = str(payload.get("status") or payload.get("state") or "").strip().lower()
    if status in _FILL_LIKE:
        return True
    values = (
        payload.get("filled_size"),
        payload.get("filled_qty"),
        payload.get("filled_quantity"),
        payload.get("executed_qty"),
        payload.get("executed_quantity"),
        payload.get("filled_size_usd"),
    )
    filled = max((_f(value) for value in values), default=0.0)
    return filled > 0.0 and status not in _REJECT_LIKE


def _with_profit_targets(raw: Any) -> dict[str, Any]:
    """Reuse v239's fixed TP ladder without inventing a second policy."""
    pos = dict(raw) if isinstance(raw, Mapping) else {}
    try:
        v239 = importlib.import_module("bot.runtime_all_account_profit_targets_v239_patch")
        fn = getattr(v239, "_with_profit_targets", None)
        if callable(fn):
            enriched = fn(pos)
            if isinstance(enriched, Mapping):
                return dict(enriched)
    except Exception:
        logger.debug("EXIT_PROTECTION_V2_V239_TARGET_ENRICHMENT_DEFERRED", exc_info=True)
    return pos


def _trigger_components(
    module: ModuleType,
    raw: Mapping[str, Any],
    price: float,
) -> tuple[bool, str, float]:
    """Evaluate fixed SL/TP plus both trailing protections symmetrically."""
    pos = _with_profit_targets(raw)
    if not pos or price <= 0:
        return False, "", 0.0

    entry_fn = getattr(module, "_entry_price", None)
    quantity_fn = getattr(module, "_quantity", None)
    side_fn = getattr(module, "_side", None)
    position_key_fn = getattr(module, "_position_key", None)
    effective_stop_fn = getattr(module, "_effective_stop", None)
    high_water = getattr(module, "_HIGH_WATER", None)
    if not (
        callable(entry_fn)
        and callable(quantity_fn)
        and callable(side_fn)
        and callable(position_key_fn)
        and callable(effective_stop_fn)
        and isinstance(high_water, dict)
    ):
        return False, "", 0.0

    entry = _f(entry_fn(pos))
    quantity = _f(quantity_fn(pos))
    if entry <= 0 or quantity <= 0:
        return False, "", 0.0
    side = str(side_fn(pos.get("side"), pos) or "").strip().lower()
    long_side = side in {"long", "buy"}

    if _truthy("NIJA_AUTO_EXIT_SL_TP_ENABLED", "true"):
        stop, stop_source = effective_stop_fn(pos, price)
        stop = _f(stop)
        if stop > 0 and ((long_side and price <= stop) or (not long_side and price >= stop)):
            return True, f"stop_loss:{stop_source}", stop

    if _truthy("NIJA_PROFIT_TAKE_ENABLED", "true"):
        for name in ("take_profit_1", "take_profit_2", "take_profit_3", "take_profit"):
            target = _f(pos.get(name))
            if target > 0 and ((long_side and price >= target) or (not long_side and price <= target)):
                return True, name, target

    key = str(position_key_fn(pos))
    prior = _f(high_water.get(key), entry)
    if long_side:
        extreme = max(prior, price, entry)
    else:
        extreme = min(prior if prior > 0 else entry, price, entry)
    high_water[key] = extreme

    candidates: list[tuple[float, int, str]] = []

    if _truthy("NIJA_TRAILING_STOP_ENABLED", "true"):
        activation = max(
            0.0,
            _f(os.environ.get("NIJA_TRAILING_STOP_ACTIVATION_PCT"), 0.008),
        )
        distance = max(
            0.0005,
            _f(os.environ.get("NIJA_TRAILING_STOP_PCT"), 0.0035),
        )
        activated = (
            extreme >= entry * (1.0 + activation)
            if long_side
            else extreme <= entry * (1.0 - activation)
        )
        trailing_stop = (
            extreme * (1.0 - distance)
            if long_side
            else extreme * (1.0 + distance)
        )
        hit = price <= trailing_stop if long_side else price >= trailing_stop
        if activated and hit:
            candidates.append((trailing_stop, 1, "trailing_stop_loss"))

    if _truthy("NIJA_TRAILING_TP_ENABLED", "true"):
        activation = max(
            0.0,
            _f(
                os.environ.get("NIJA_TRAILING_TP_ACTIVATION_PCT"),
                _f(os.environ.get("NIJA_PROFIT_LOCK_ACTIVATION_PCT"), 0.008),
            ),
        )
        callback = max(
            0.0005,
            _f(
                os.environ.get("NIJA_TRAILING_TP_CALLBACK_PCT"),
                _f(os.environ.get("NIJA_PROFIT_LOCK_CALLBACK_PCT"), 0.0035),
            ),
        )
        activated = (
            extreme >= entry * (1.0 + activation)
            if long_side
            else extreme <= entry * (1.0 - activation)
        )
        trailing_tp = (
            extreme * (1.0 - callback)
            if long_side
            else extreme * (1.0 + callback)
        )
        hit = price <= trailing_tp if long_side else price >= trailing_tp
        if activated and hit:
            candidates.append((trailing_tp, 0, "profit_lock_trailing_exit"))

    if not candidates:
        return False, "", 0.0

    if long_side:
        threshold, _priority, reason = max(
            candidates, key=lambda item: (item[0], -item[1])
        )
    else:
        threshold, _priority, reason = min(
            candidates, key=lambda item: (item[0], item[1])
        )
    return True, reason, threshold


def _strict_fill_wrapper(fn: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(fn)
    def wrapped(*args: Any, **kwargs: Any):
        result = fn(*args, **kwargs)
        return _filled_result(result)
    setattr(wrapped, _FILL_PATCHED, True)
    return wrapped


def _patch_fill_predicate(module: ModuleType) -> bool:
    changed = False
    for name in ("_ok", "_success"):
        current = getattr(module, name, None)
        if not callable(current) or bool(getattr(current, _FILL_PATCHED, False)):
            continue
        setattr(module, name, _strict_fill_wrapper(current))
        changed = True
    return changed or any(
        callable(getattr(module, name, None))
        and bool(getattr(getattr(module, name), _FILL_PATCHED, False))
        for name in ("_ok", "_success")
    )


def _patch_auto(module: ModuleType) -> bool:
    if getattr(module, _PATCHED, False):
        _patch_fill_predicate(module)
        return True
    current = getattr(module, "_trigger", None)
    if not callable(current):
        return False

    @wraps(current)
    def assured_trigger(pos: dict[str, Any], price: float) -> tuple[bool, str, float]:
        return _trigger_components(module, pos, price)

    setattr(assured_trigger, "__wrapped__", current)
    module._trigger = assured_trigger
    _patch_fill_predicate(module)
    setattr(module, _PATCHED, True)
    os.environ["NIJA_EXIT_PROTECTION_ASSURANCE_READY"] = "1"
    logger.critical(
        "EXIT_PROTECTION_ASSURANCE_V2_READY marker=%s fixed_take_profit=%s "
        "hard_stop_loss=%s trailing_take_profit=%s trailing_stop_loss=%s "
        "long_short_symmetric=true ack_is_not_fill=true v239_targets_reused=true",
        _MARKER,
        _truthy("NIJA_PROFIT_TAKE_ENABLED"),
        _truthy("NIJA_AUTO_EXIT_SL_TP_ENABLED"),
        _truthy("NIJA_TRAILING_TP_ENABLED"),
        _truthy("NIJA_TRAILING_STOP_ENABLED"),
    )
    return True


def _patch(module: ModuleType) -> bool:
    return _patch_auto(module)


def _kraken_trailing_reason(
    module: ModuleType,
    position: Mapping[str, Any],
    price: float,
    account: str,
    symbol: str,
    breakeven: float,
):
    entry_fn = getattr(module, "_entry_price", None)
    state = getattr(module, "_EXIT_STATE", None)
    if not callable(entry_fn) or not isinstance(state, dict):
        return None, 0.0
    pos = _with_profit_targets(position)
    entry = _f(entry_fn(pos))
    if entry <= 0 or price <= 0:
        return None, 0.0
    side = str(pos.get("side") or "long").strip().lower()
    short = side in {"short", "sell"}
    row = state.setdefault((account, symbol), {"high": price, "low": price, "armed": False})
    row["high"] = max(_f(row.get("high"), price), price)
    row["low"] = min(_f(row.get("low"), price), price)
    extreme = _f(row["low"] if short else row["high"], price)

    candidates: list[tuple[float, int, str]] = []
    if _truthy("NIJA_TRAILING_STOP_ENABLED", "true"):
        activation = max(0.0, _f(os.environ.get("NIJA_TRAILING_STOP_ACTIVATION_PCT"), 0.008))
        distance = max(0.0005, _f(os.environ.get("NIJA_TRAILING_STOP_PCT"), 0.0035))
        activated = (
            extreme <= entry * (1.0 - activation)
            if short else extreme >= entry * (1.0 + activation)
        )
        threshold = extreme * (1.0 + distance) if short else extreme * (1.0 - distance)
        hit = price >= threshold if short else price <= threshold
        if activated and hit:
            candidates.append((threshold, 1, "trailing_stop_loss"))

    if _truthy("NIJA_TRAILING_TP_ENABLED", "true"):
        activation = max(
            0.0,
            _f(
                os.environ.get("NIJA_TRAILING_TP_ACTIVATION_PCT"),
                _f(os.environ.get("NIJA_PROFIT_LOCK_ACTIVATION_PCT"), 0.008),
            ),
        )
        callback = max(
            0.0005,
            _f(
                os.environ.get("NIJA_TRAILING_TP_CALLBACK_PCT"),
                _f(os.environ.get("NIJA_PROFIT_LOCK_CALLBACK_PCT"), 0.0035),
            ),
        )
        activated = (
            extreme <= entry * (1.0 - activation)
            if short else extreme >= entry * (1.0 + activation)
        )
        threshold = extreme * (1.0 + callback) if short else extreme * (1.0 - callback)
        hit = price >= threshold if short else price <= threshold
        fee_safe = price <= breakeven if short else price >= breakeven
        if activated and hit and fee_safe:
            candidates.append((threshold, 0, "profit_lock_trailing_exit"))

    if not candidates:
        return None, 0.0
    if short:
        threshold, _priority, reason = min(candidates, key=lambda item: (item[0], item[1]))
    else:
        threshold, _priority, reason = max(candidates, key=lambda item: (item[0], -item[1]))
    return reason, threshold


def _patch_kraken(module: ModuleType) -> bool:
    if getattr(module, _KRAKEN_PATCHED, False):
        return True
    exit_reason = getattr(module, "_exit_reason", None)
    submit_exit = getattr(module, "_submit_exit", None)
    if not callable(exit_reason) or not callable(submit_exit):
        return False

    @wraps(exit_reason)
    def exit_reason_v2(position: Mapping[str, Any], price: float, account: str, symbol: str):
        enriched = _with_profit_targets(position)
        reason, breakeven, target = exit_reason(enriched, price, account, symbol)
        if reason:
            return reason, breakeven, target
        trail_reason, trail_target = _kraken_trailing_reason(
            module, enriched, price, account, symbol, _f(breakeven)
        )
        if trail_reason:
            return trail_reason, breakeven, trail_target
        return None, breakeven, target

    @wraps(submit_exit)
    def submit_exit_v2(*args: Any, **kwargs: Any):
        result = submit_exit(*args, **kwargs)
        if _filled_result(result):
            return result
        if isinstance(result, Mapping):
            pending_id = result.get("order_id") or result.get("id") or result.get("txid")
            return {
                "status": "error",
                "error": "protective_exit_not_fill_confirmed",
                "pending_order_id": pending_id,
                "raw_status": result.get("status") or result.get("state"),
            }
        return {"status": "error", "error": "protective_exit_invalid_result"}

    setattr(exit_reason_v2, "__wrapped__", exit_reason)
    setattr(submit_exit_v2, "__wrapped__", submit_exit)
    module._exit_reason = exit_reason_v2
    module._submit_exit = submit_exit_v2
    setattr(module, _KRAKEN_PATCHED, True)
    logger.critical(
        "KRAKEN_EXIT_PROTECTION_ASSURANCE_V2_READY marker=%s "
        "fixed_sl=true fixed_tp=true trailing_sl=true trailing_tp=true "
        "account_local=true margin_rows_supported=true fill_confirmation_required=true",
        _MARKER,
    )
    return True


def _patch_loaded_module(name: str, module: ModuleType) -> None:
    try:
        if name in _PROTECTION_MODULES:
            if name.endswith("auto_exit_sl_tp_runtime_patch"):
                _patch_auto(module)
            else:
                _patch_fill_predicate(module)
        if name in _KRAKEN_MODULES:
            _patch_kraken(module)
    except Exception:
        logger.exception(
            "EXIT_PROTECTION_ASSURANCE_V2_PATCH_FAILED marker=%s module=%s",
            _MARKER,
            name,
        )


def install_import_hook() -> None:
    _configure()

    for name, module in tuple(sys.modules.items()):
        if isinstance(module, ModuleType) and (name in _PROTECTION_MODULES or name in _KRAKEN_MODULES):
            _patch_loaded_module(name, module)

    if getattr(builtins, _HOOK, False):
        return
    original_import = builtins.__import__

    def hook(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            candidates = {name}
            if name.startswith("bot."):
                candidates.add(name[4:])
            else:
                candidates.add(f"bot.{name}")
            for candidate in candidates:
                loaded = sys.modules.get(candidate)
                if isinstance(loaded, ModuleType):
                    _patch_loaded_module(candidate, loaded)
        except Exception:
            logger.exception(
                "EXIT_PROTECTION_ASSURANCE_V2_IMPORT_PATCH_FAILED marker=%s module=%s",
                _MARKER,
                name,
            )
        return module

    builtins.__import__ = hook
    setattr(builtins, _HOOK, True)
    logger.warning(
        "EXIT_PROTECTION_ASSURANCE_V2_IMPORT_HOOK_INSTALLED marker=%s",
        _MARKER,
    )


def install() -> None:
    install_import_hook()


__all__ = [
    "install",
    "install_import_hook",
    "_patch",
    "_patch_auto",
    "_patch_kraken",
    "_filled_result",
    "_configure",
]
