"""System-wide fixed and trailing exit protection assurance for NIJA.

The patch keeps NIJA's existing hard-stop and v239 profit-target policies,
adds symmetric trailing stop-loss / trailing take-profit evaluation at shared
exit boundaries, and rejects order acknowledgements as proof of a close.
It does not bypass writer, nonce, risk, broker-health, kill-switch, minimum
order, or terminal execution gates.
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
from typing import Any

logger = logging.getLogger("nija.exit_protection_assurance")
_MARKER = "20260905-exit-protection-assurance-v2"
_AUTO_PATCH = "__nija_exit_protection_assurance_v2__"
_KRAKEN_PATCH = "__nija_exit_protection_assurance_v2_kraken__"
_FILL_PATCH = "__nija_exit_protection_assurance_v2_fill__"
_HOOK = "_NIJA_EXIT_PROTECTION_ASSURANCE_IMPORT_HOOK_V2"

_FILL_STATES = {"filled", "closed", "done", "complete", "completed", "success", "settled"}
_NONTERMINAL = {
    "error", "failed", "rejected", "cancelled", "canceled", "expired",
    "unfilled", "pending", "open", "accepted", "acknowledged", "new",
}
_PROTECTION_MODULES = {
    "bot.auto_exit_sl_tp_runtime_patch", "auto_exit_sl_tp_runtime_patch",
    "bot.trailing_stop_loss_runtime_patch", "trailing_stop_loss_runtime_patch",
    "bot.trailing_take_profit_runtime_patch", "trailing_take_profit_runtime_patch",
    "bot.combined_trailing_tp_sl_runtime_patch", "combined_trailing_tp_sl_runtime_patch",
    "bot.combo_breakeven_trailing_runtime_patch", "combo_breakeven_trailing_runtime_patch",
    "bot.breakeven_stop_loss_runtime_patch", "breakeven_stop_loss_runtime_patch",
}
_KRAKEN_MODULES = {
    "bot.kraken_all_account_exit_runtime_patch", "kraken_all_account_exit_runtime_patch",
}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        value = float(value)
        return default if value != value else value
    except Exception:
        return default


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in {
        "1", "true", "yes", "on", "enabled", "y",
    }


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
    """Require terminal fill evidence; accepted/order_id alone is not a fill."""
    if not isinstance(payload, Mapping):
        return False
    status = str(payload.get("status") or payload.get("state") or "").strip().lower()
    if status in _FILL_STATES:
        return True
    filled = max(
        (
            _f(payload.get(key))
            for key in (
                "filled_size", "filled_qty", "filled_quantity",
                "executed_qty", "executed_quantity", "filled_size_usd",
            )
        ),
        default=0.0,
    )
    return filled > 0.0 and status not in _NONTERMINAL


def _with_profit_targets(raw: Any) -> dict[str, Any]:
    pos = dict(raw) if isinstance(raw, Mapping) else {}
    try:
        v239 = importlib.import_module("bot.runtime_all_account_profit_targets_v239_patch")
        fn = getattr(v239, "_with_profit_targets", None)
        if callable(fn):
            enriched = fn(pos)
            if isinstance(enriched, Mapping):
                return dict(enriched)
    except Exception:
        logger.debug("V239_TARGET_ENRICHMENT_DEFERRED", exc_info=True)
    return pos


def _trail_settings(prefix: str) -> tuple[float, float]:
    if prefix == "sl":
        return (
            max(0.0, _f(os.environ.get("NIJA_TRAILING_STOP_ACTIVATION_PCT"), 0.008)),
            max(0.0005, _f(os.environ.get("NIJA_TRAILING_STOP_PCT"), 0.0035)),
        )
    return (
        max(
            0.0,
            _f(
                os.environ.get("NIJA_TRAILING_TP_ACTIVATION_PCT"),
                _f(os.environ.get("NIJA_PROFIT_LOCK_ACTIVATION_PCT"), 0.008),
            ),
        ),
        max(
            0.0005,
            _f(
                os.environ.get("NIJA_TRAILING_TP_CALLBACK_PCT"),
                _f(os.environ.get("NIJA_PROFIT_LOCK_CALLBACK_PCT"), 0.0035),
            ),
        ),
    )


def _choose_trailing(
    *,
    long_side: bool,
    entry: float,
    price: float,
    extreme: float,
    fee_floor: float = 0.0,
) -> tuple[bool, str, float]:
    candidates: list[tuple[float, int, str]] = []

    if _truthy("NIJA_TRAILING_STOP_ENABLED"):
        activation, distance = _trail_settings("sl")
        armed = (
            extreme >= entry * (1.0 + activation)
            if long_side else extreme <= entry * (1.0 - activation)
        )
        stop = extreme * (1.0 - distance) if long_side else extreme * (1.0 + distance)
        crossed = price <= stop if long_side else price >= stop
        if armed and crossed:
            candidates.append((stop, 1, "trailing_stop_loss"))

    if _truthy("NIJA_TRAILING_TP_ENABLED"):
        activation, callback = _trail_settings("tp")
        armed = (
            extreme >= entry * (1.0 + activation)
            if long_side else extreme <= entry * (1.0 - activation)
        )
        target = extreme * (1.0 - callback) if long_side else extreme * (1.0 + callback)
        crossed = price <= target if long_side else price >= target
        fee_safe = not fee_floor or (price >= fee_floor if long_side else price <= fee_floor)
        if armed and crossed and fee_safe:
            candidates.append((target, 0, "profit_lock_trailing_exit"))

    if not candidates:
        return False, "", 0.0
    if long_side:
        threshold, _priority, reason = max(candidates, key=lambda x: (x[0], -x[1]))
    else:
        threshold, _priority, reason = min(candidates, key=lambda x: (x[0], x[1]))
    return True, reason, threshold


def _trigger_components(module: ModuleType, raw: Mapping[str, Any], price: float):
    pos = _with_profit_targets(raw)
    if price <= 0:
        return False, "", 0.0
    entry_fn = getattr(module, "_entry_price", None)
    qty_fn = getattr(module, "_quantity", None)
    side_fn = getattr(module, "_side", None)
    key_fn = getattr(module, "_position_key", None)
    stop_fn = getattr(module, "_effective_stop", None)
    water = getattr(module, "_HIGH_WATER", None)
    if not all((callable(entry_fn), callable(qty_fn), callable(side_fn), callable(key_fn), callable(stop_fn))):
        return False, "", 0.0
    if not isinstance(water, dict):
        return False, "", 0.0

    entry, qty = _f(entry_fn(pos)), _f(qty_fn(pos))
    if entry <= 0 or qty <= 0:
        return False, "", 0.0
    long_side = str(side_fn(pos.get("side"), pos) or "").lower() in {"long", "buy"}

    if _truthy("NIJA_AUTO_EXIT_SL_TP_ENABLED"):
        stop, source = stop_fn(pos, price)
        stop = _f(stop)
        if stop > 0 and ((long_side and price <= stop) or (not long_side and price >= stop)):
            return True, f"stop_loss:{source}", stop

    if _truthy("NIJA_PROFIT_TAKE_ENABLED"):
        for name in ("take_profit_1", "take_profit_2", "take_profit_3", "take_profit"):
            target = _f(pos.get(name))
            if target > 0 and ((long_side and price >= target) or (not long_side and price <= target)):
                return True, name, target

    key = str(key_fn(pos))
    previous = _f(water.get(key), entry)
    extreme = max(previous, price, entry) if long_side else min(
        previous if previous > 0 else entry, price, entry
    )
    water[key] = extreme
    return _choose_trailing(
        long_side=long_side, entry=entry, price=price, extreme=extreme
    )


def _patch_fill_predicate(module: ModuleType) -> bool:
    changed = False
    for name in ("_ok", "_success"):
        current = getattr(module, name, None)
        if not callable(current) or getattr(current, _FILL_PATCH, False):
            continue

        @wraps(current)
        def strict(payload: Any, *args: Any, **kwargs: Any):
            return _filled_result(payload)

        setattr(strict, _FILL_PATCH, True)
        setattr(module, name, strict)
        changed = True
    return changed or any(
        callable(getattr(module, name, None))
        and getattr(getattr(module, name), _FILL_PATCH, False)
        for name in ("_ok", "_success")
    )


def _patch_auto(module: ModuleType) -> bool:
    if getattr(module, _AUTO_PATCH, False):
        _patch_fill_predicate(module)
        return True
    original = getattr(module, "_trigger", None)
    if not callable(original):
        return False

    @wraps(original)
    def trigger(pos: dict[str, Any], price: float):
        return _trigger_components(module, pos, price)

    trigger.__wrapped__ = original
    module._trigger = trigger
    _patch_fill_predicate(module)
    setattr(module, _AUTO_PATCH, True)
    os.environ["NIJA_EXIT_PROTECTION_ASSURANCE_READY"] = "1"
    logger.critical(
        "EXIT_PROTECTION_ASSURANCE_V2_READY marker=%s fixed_sl=true fixed_tp=true "
        "trailing_sl=true trailing_tp=true long_short_symmetric=true "
        "ack_is_not_fill=true v239_targets_reused=true",
        _MARKER,
    )
    return True


def _patch(module: ModuleType) -> bool:
    """Backward-compatible test/runtime entrypoint."""
    return _patch_auto(module)


def _kraken_trailing(module: ModuleType, position: Mapping[str, Any], price: float,
                     account: str, symbol: str, breakeven: float):
    entry_fn = getattr(module, "_entry_price", None)
    state = getattr(module, "_EXIT_STATE", None)
    if not callable(entry_fn) or not isinstance(state, dict):
        return None, 0.0
    pos = _with_profit_targets(position)
    entry = _f(entry_fn(pos))
    if entry <= 0 or price <= 0:
        return None, 0.0
    short = str(pos.get("side") or "long").lower() in {"short", "sell"}
    row = state.setdefault((account, symbol), {"high": price, "low": price, "armed": False})
    row["high"] = max(_f(row.get("high"), price), price)
    row["low"] = min(_f(row.get("low"), price), price)
    extreme = _f(row["low"] if short else row["high"], price)
    hit, reason, threshold = _choose_trailing(
        long_side=not short,
        entry=entry,
        price=price,
        extreme=extreme,
        fee_floor=_f(breakeven),
    )
    return (reason if hit else None), threshold


def _patch_kraken(module: ModuleType) -> bool:
    if getattr(module, _KRAKEN_PATCH, False):
        return True
    original_reason = getattr(module, "_exit_reason", None)
    original_submit = getattr(module, "_submit_exit", None)
    if not callable(original_reason) or not callable(original_submit):
        return False

    @wraps(original_reason)
    def exit_reason(position: Mapping[str, Any], price: float, account: str, symbol: str):
        position = _with_profit_targets(position)
        reason, breakeven, target = original_reason(position, price, account, symbol)
        if reason:
            return reason, breakeven, target
        trailing_reason, trailing_target = _kraken_trailing(
            module, position, price, account, symbol, _f(breakeven)
        )
        if trailing_reason:
            return trailing_reason, breakeven, trailing_target
        return None, breakeven, target

    @wraps(original_submit)
    def submit_exit(*args: Any, **kwargs: Any):
        result = original_submit(*args, **kwargs)
        if _filled_result(result):
            return result
        if isinstance(result, Mapping):
            return {
                "status": "error",
                "error": "protective_exit_not_fill_confirmed",
                "pending_order_id": result.get("order_id") or result.get("id") or result.get("txid"),
                "raw_status": result.get("status") or result.get("state"),
            }
        return {"status": "error", "error": "protective_exit_invalid_result"}

    exit_reason.__wrapped__ = original_reason
    submit_exit.__wrapped__ = original_submit
    module._exit_reason = exit_reason
    module._submit_exit = submit_exit
    setattr(module, _KRAKEN_PATCH, True)
    logger.critical(
        "KRAKEN_EXIT_PROTECTION_ASSURANCE_V2_READY marker=%s "
        "fixed_sl=true fixed_tp=true trailing_sl=true trailing_tp=true "
        "margin_rows_supported=true fill_confirmation_required=true",
        _MARKER,
    )
    return True


def _patch_loaded(name: str, module: ModuleType) -> None:
    try:
        if name in _PROTECTION_MODULES:
            _patch_auto(module) if name.endswith("auto_exit_sl_tp_runtime_patch") else _patch_fill_predicate(module)
        if name in _KRAKEN_MODULES:
            _patch_kraken(module)
    except Exception:
        logger.exception("EXIT_PROTECTION_ASSURANCE_V2_PATCH_FAILED marker=%s module=%s", _MARKER, name)


def install_import_hook() -> None:
    _configure()
    for name, module in tuple(sys.modules.items()):
        if isinstance(module, ModuleType) and (name in _PROTECTION_MODULES or name in _KRAKEN_MODULES):
            _patch_loaded(name, module)

    if getattr(builtins, _HOOK, False):
        return
    original_import = builtins.__import__

    def hook(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        candidates = {name, name[4:] if name.startswith("bot.") else f"bot.{name}"}
        for candidate in candidates:
            loaded = sys.modules.get(candidate)
            if isinstance(loaded, ModuleType):
                _patch_loaded(candidate, loaded)
        return module

    builtins.__import__ = hook
    setattr(builtins, _HOOK, True)
    logger.warning("EXIT_PROTECTION_ASSURANCE_V2_IMPORT_HOOK_INSTALLED marker=%s", _MARKER)


def install() -> None:
    install_import_hook()


__all__ = [
    "install", "install_import_hook", "_patch", "_patch_auto", "_patch_kraken",
    "_filled_result", "_configure",
]
