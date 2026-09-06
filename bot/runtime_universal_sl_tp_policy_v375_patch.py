"""Universal four-way protective exit policy convergence v375.

Make the existing NIJA software exit policy explicit at every shared exit boundary
for platform and registered-user positions on Kraken, Coinbase, and OKX.

The required software contract is:
  * fixed stop-loss;
  * fixed take-profit (existing v239 TP ladder);
  * trailing stop-loss;
  * trailing take-profit / profit lock.

This layer does not create native exchange orders and does not fabricate protection.
It reuses NIJA's existing hard-loss and TP policies, keeps long/short behavior
symmetric, and requires the live protective-exit authority before new exposure can
be considered protected. Existing exit/reduce requests stay allowed and all writer,
nonce, risk, capital, kill-switch, broker-health, minimum-order and fill gates remain
unchanged.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from collections.abc import Mapping
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_universal_sl_tp_policy_v375")
MARKER = "20260906-universal-four-way-protection-v375"
_READY_FLAG = "NIJA_RUNTIME_UNIVERSAL_SL_TP_POLICY_V375_READY"
_PATCH_ATTR = "_nija_universal_sl_tp_policy_v375"
_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None
_LOGGED: set[tuple[str, str, str, str]] = set()
_EPS = 1e-12
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if number == number else default
    except Exception:
        return default


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in _TRUE


def _qty(row: Mapping[str, Any]) -> float:
    for key in ("quantity", "qty", "size", "amount", "units", "balance"):
        if row.get(key) is not None:
            return abs(_f(row.get(key)))
    return 0.0


def _entry(row: Mapping[str, Any]) -> float:
    for key in ("entry_price", "avg_entry_price", "average_price", "cost_basis_price", "avg_price"):
        value = _f(row.get(key))
        if value > _EPS:
            return value
    return 0.0


def _has_tp(row: Mapping[str, Any]) -> bool:
    return any(
        _f(row.get(key)) > _EPS
        for key in ("take_profit", "take_profit_1", "take_profit_2", "take_profit_3")
    )


def _trail_settings() -> dict[str, float | bool]:
    sl_enabled = _truthy(os.environ.get("NIJA_TRAILING_STOP_ENABLED", "true"))
    tp_enabled = _truthy(os.environ.get("NIJA_TRAILING_TP_ENABLED", "true"))
    sl_activation = max(
        0.0,
        min(0.25, _f(os.environ.get("NIJA_TRAILING_STOP_ACTIVATION_PCT"), 0.008)),
    )
    sl_distance = max(
        0.0005,
        min(0.25, _f(os.environ.get("NIJA_TRAILING_STOP_PCT"), 0.0035)),
    )
    tp_activation = max(
        0.0,
        min(
            0.25,
            _f(
                os.environ.get("NIJA_TRAILING_TP_ACTIVATION_PCT"),
                _f(os.environ.get("NIJA_PROFIT_LOCK_ACTIVATION_PCT"), 0.008),
            ),
        ),
    )
    tp_callback = max(
        0.0005,
        min(
            0.25,
            _f(
                os.environ.get("NIJA_TRAILING_TP_CALLBACK_PCT"),
                _f(os.environ.get("NIJA_PROFIT_LOCK_CALLBACK_PCT"), 0.0035),
            ),
        ),
    )
    return {
        "trailing_stop_loss_enabled": sl_enabled,
        "trailing_stop_activation_pct": sl_activation,
        "trailing_stop_distance_pct": sl_distance,
        "trailing_take_profit_enabled": tp_enabled,
        "trailing_take_profit_activation_pct": tp_activation,
        "trailing_take_profit_callback_pct": tp_callback,
    }


def _policy_row(raw: Any) -> Any:
    """Attach all four existing-policy protection legs to one position row."""
    if not isinstance(raw, Mapping):
        return raw
    row = dict(raw)
    entry = _entry(row)
    qty = _qty(row)
    if entry <= _EPS or qty <= _EPS:
        row["universal_sl_tp_policy_complete"] = False
        row["universal_four_way_policy_complete"] = False
        return row

    auto_exit = importlib.import_module("bot.auto_exit_sl_tp_runtime_patch")
    v239 = importlib.import_module("bot.runtime_all_account_profit_targets_v239_patch")

    if _f(row.get("stop_loss")) <= _EPS:
        effective = getattr(auto_exit, "_effective_stop", None)
        if callable(effective):
            stop, source = effective(row, entry)
            if _f(stop) > _EPS:
                row["stop_loss"] = float(stop)
                row["software_stop_loss_source"] = str(source or "existing_nija_hard_loss_policy")
                row["software_stop_loss_derived"] = True

    target_fn = getattr(v239, "_with_profit_targets", None)
    if callable(target_fn):
        targeted = target_fn(row)
        if isinstance(targeted, Mapping):
            row = dict(targeted)

    row.update(_trail_settings())
    stop_ok = _f(row.get("stop_loss")) > _EPS
    tp_ok = _has_tp(row)
    trailing_stop_ok = bool(
        row.get("trailing_stop_loss_enabled")
        and _f(row.get("trailing_stop_distance_pct")) > 0.0
        and _f(row.get("trailing_stop_activation_pct")) >= 0.0
    )
    trailing_tp_ok = bool(
        row.get("trailing_take_profit_enabled")
        and _f(row.get("trailing_take_profit_callback_pct")) > 0.0
        and _f(row.get("trailing_take_profit_activation_pct")) >= 0.0
    )
    row["software_stop_loss_available"] = stop_ok
    row["software_take_profit_available"] = tp_ok
    row["software_trailing_stop_available"] = trailing_stop_ok
    row["software_trailing_take_profit_available"] = trailing_tp_ok
    # Backward compatibility: existing consumers still read this fixed-leg flag.
    row["universal_sl_tp_policy_complete"] = bool(stop_ok and tp_ok)
    row["universal_four_way_policy_complete"] = bool(
        stop_ok and tp_ok and trailing_stop_ok and trailing_tp_ok
    )
    row["universal_sl_tp_policy_marker"] = MARKER
    row["universal_four_way_policy_marker"] = MARKER
    return row


def _select_trailing_candidate(
    row: Mapping[str, Any],
    *,
    entry: float,
    price: float,
    long_side: bool,
    extreme: float,
) -> tuple[bool, str, float]:
    candidates: list[tuple[float, int, str]] = []

    if bool(row.get("software_trailing_stop_available")):
        activation = _f(row.get("trailing_stop_activation_pct"), 0.008)
        distance = _f(row.get("trailing_stop_distance_pct"), 0.0035)
        armed = (
            extreme >= entry * (1.0 + activation)
            if long_side
            else extreme <= entry * (1.0 - activation)
        )
        threshold = (
            extreme * (1.0 - distance)
            if long_side
            else extreme * (1.0 + distance)
        )
        crossed = price <= threshold if long_side else price >= threshold
        if armed and crossed:
            candidates.append((threshold, 1, "trailing_stop_loss"))

    if bool(row.get("software_trailing_take_profit_available")):
        activation = _f(row.get("trailing_take_profit_activation_pct"), 0.008)
        callback = _f(row.get("trailing_take_profit_callback_pct"), 0.0035)
        armed = (
            extreme >= entry * (1.0 + activation)
            if long_side
            else extreme <= entry * (1.0 - activation)
        )
        threshold = (
            extreme * (1.0 - callback)
            if long_side
            else extreme * (1.0 + callback)
        )
        crossed = price <= threshold if long_side else price >= threshold
        if armed and crossed:
            candidates.append((threshold, 0, "profit_lock_trailing_exit"))

    if not candidates:
        return False, "", 0.0
    # Use the tighter protective boundary. Equal thresholds preserve the
    # established profit-lock reason for dashboard/log compatibility.
    if long_side:
        threshold, _priority, reason = max(candidates, key=lambda item: (item[0], -item[1]))
    else:
        threshold, _priority, reason = min(candidates, key=lambda item: (item[0], item[1]))
    return True, reason, threshold


def _four_way_trigger(pos: dict[str, Any], price: float) -> tuple[bool, str, float]:
    auto_exit = importlib.import_module("bot.auto_exit_sl_tp_runtime_patch")
    row = _policy_row(pos)
    if not isinstance(row, Mapping) or price <= 0.0:
        return False, "", 0.0

    entry = _entry(row)
    qty = _qty(row)
    if entry <= _EPS or qty <= _EPS:
        return False, "", 0.0
    side_fn = getattr(auto_exit, "_side", None)
    side = str(side_fn(row.get("side"), dict(row)) if callable(side_fn) else row.get("side") or "").lower()
    long_side = side in {"long", "buy"}

    stop = _f(row.get("stop_loss"))
    if stop > _EPS and ((long_side and price <= stop) or (not long_side and price >= stop)):
        return True, "stop_loss:universal_four_way_policy", stop

    for name in ("take_profit_1", "take_profit_2", "take_profit_3", "take_profit"):
        target = _f(row.get(name))
        if target > _EPS and ((long_side and price >= target) or (not long_side and price <= target)):
            return True, name, target

    key_fn = getattr(auto_exit, "_position_key", None)
    water = getattr(auto_exit, "_HIGH_WATER", None)
    if not callable(key_fn) or not isinstance(water, dict):
        return False, "", 0.0
    key = str(key_fn(dict(row)))
    previous = _f(water.get(key), entry)
    extreme = (
        max(previous, entry, price)
        if long_side
        else min(previous if previous > 0 else entry, entry, price)
    )
    water[key] = extreme
    return _select_trailing_candidate(
        row,
        entry=entry,
        price=price,
        long_side=long_side,
        extreme=extreme,
    )


def _patch_universal_supervisor() -> bool:
    module = importlib.import_module("bot.universal_broker_exit_supervisor_patch")
    current = getattr(module, "_tracker_positions", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def tracker_positions_v375(broker: Any):
        rows = current(broker)
        if not isinstance(rows, list):
            return rows
        hardened = [_policy_row(row) for row in rows]
        account_fn = getattr(module, "_account_label", None)
        auto_exit = importlib.import_module("bot.auto_exit_sl_tp_runtime_patch")
        venue_fn = getattr(auto_exit, "_broker_label", None)
        account = str(account_fn(broker) if callable(account_fn) else getattr(broker, "account_id", "platform") or "platform")
        venue = str(venue_fn(broker) if callable(venue_fn) else type(broker).__name__).lower()
        for row in hardened:
            if not isinstance(row, Mapping):
                continue
            sig = (account, venue, str(row.get("symbol") or ""), str(row.get("position_id") or ""))
            if bool(row.get("universal_four_way_policy_complete")) and sig not in _LOGGED:
                _LOGGED.add(sig)
                LOGGER.critical(
                    "UNIVERSAL_FOUR_WAY_POLICY_V375_APPLIED marker=%s account=%s venue=%s symbol=%s "
                    "quantity=%.12f entry=%.8f stop_loss=%.8f take_profit_1=%.8f "
                    "take_profit_2=%.8f take_profit_3=%.8f trailing_stop_activation=%.6f "
                    "trailing_stop_distance=%.6f trailing_tp_activation=%.6f trailing_tp_callback=%.6f "
                    "native_order_created=false existing_exit_pipeline_only=true safety_gates_bypassed=false",
                    MARKER,
                    account,
                    venue,
                    str(row.get("symbol") or "unknown"),
                    _qty(row),
                    _entry(row),
                    _f(row.get("stop_loss")),
                    _f(row.get("take_profit_1")),
                    _f(row.get("take_profit_2")),
                    _f(row.get("take_profit_3")),
                    _f(row.get("trailing_stop_activation_pct")),
                    _f(row.get("trailing_stop_distance_pct")),
                    _f(row.get("trailing_take_profit_activation_pct")),
                    _f(row.get("trailing_take_profit_callback_pct")),
                )
        return hardened

    setattr(tracker_positions_v375, _PATCH_ATTR, True)
    setattr(tracker_positions_v375, "__wrapped__", current)
    module._tracker_positions = tracker_positions_v375
    return True


def _patch_auto_exit_trigger() -> bool:
    module = importlib.import_module("bot.auto_exit_sl_tp_runtime_patch")
    current = getattr(module, "_trigger", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def trigger_v375(pos: dict[str, Any], price: float):
        return _four_way_trigger(pos, price)

    setattr(trigger_v375, _PATCH_ATTR, True)
    setattr(trigger_v375, "__wrapped__", current)
    module._trigger = trigger_v375
    return True


def _patch_v281_coverage() -> bool:
    """Require all four policy legs on each tracker position; never invent authority."""
    v281 = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
    universal = importlib.import_module("bot.universal_broker_exit_supervisor_patch")
    current = getattr(v281, "_account_audit", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def account_audit_v375(account: str, broker: Any, structural_exit_ready: bool):
        reasons, positions = current(account, broker, structural_exit_ready)
        reasons = [str(reason) for reason in list(reasons or []) if str(reason)]
        output = [dict(row) for row in list(positions or []) if isinstance(row, Mapping)]
        try:
            rows = universal._tracker_positions(broker) if broker is not None else []
        except Exception:
            rows = []
        by_symbol = {
            str(row.get("symbol") or "").strip().upper().replace("/", "-").replace("_", "-"): row
            for row in rows if isinstance(row, Mapping)
        }
        connected_fn = getattr(v281, "_connected", None)
        connected = bool(callable(connected_fn) and connected_fn(broker))
        authority = _truthy(os.environ.get("NIJA_PROTECTIVE_EXIT_AUTHORITY_V265_READY"))
        runtime_ready = bool(connected and authority and structural_exit_ready)

        for row in output:
            symbol = str(row.get("symbol") or "").strip().upper().replace("/", "-").replace("_", "-")
            policy = _policy_row(by_symbol.get(symbol, {}))
            fixed_complete = bool(
                isinstance(policy, Mapping)
                and policy.get("universal_sl_tp_policy_complete") is True
            )
            four_complete = bool(
                isinstance(policy, Mapping)
                and policy.get("universal_four_way_policy_complete") is True
            )
            if isinstance(policy, Mapping):
                for key in (
                    "stop_loss",
                    "take_profit_1",
                    "take_profit_2",
                    "take_profit_3",
                    "trailing_stop_activation_pct",
                    "trailing_stop_distance_pct",
                    "trailing_take_profit_activation_pct",
                    "trailing_take_profit_callback_pct",
                ):
                    if policy.get(key) is not None:
                        row[key] = policy.get(key)

            row["protective_stop_verified"] = bool(fixed_complete and runtime_ready)
            row["protective_take_profit_verified"] = bool(fixed_complete and runtime_ready)
            row["protective_trailing_stop_verified"] = bool(four_complete and runtime_ready)
            row["protective_trailing_take_profit_verified"] = bool(four_complete and runtime_ready)
            row["universal_sl_tp_policy_complete"] = fixed_complete
            row["universal_four_way_policy_complete"] = four_complete
            row["protective_exit_verified"] = bool(
                row.get("protective_exit_verified") is True
                and row["protective_stop_verified"]
                and row["protective_take_profit_verified"]
                and row["protective_trailing_stop_verified"]
                and row["protective_trailing_take_profit_verified"]
            )
            if four_complete:
                attached = list(row.get("exit_protections_attached") or ())
                attached.extend(
                    (
                        "stop_loss",
                        "take_profit",
                        "trailing_stop_loss",
                        "trailing_take_profit",
                    )
                )
                row["exit_protections_attached"] = tuple(dict.fromkeys(attached))
            else:
                reasons.append(f"universal_four_way_policy_incomplete:{symbol or 'unknown'}")
        return list(dict.fromkeys(reasons)), output

    setattr(account_audit_v375, _PATCH_ATTR, True)
    setattr(account_audit_v375, "__wrapped__", current)
    v281._account_audit = account_audit_v375
    return True


def _patch_v265_stack_truth() -> bool:
    """Make the four-way v375 policy mandatory for new exposure while preserving exits."""
    v265 = importlib.import_module("bot.runtime_protective_exit_authority_v265_patch")
    current = getattr(v265, "_stack_truth", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def stack_truth_v375():
        ready, details = current()
        details = dict(details or {})
        policy_ready = _truthy(os.environ.get(_READY_FLAG))
        details["universal_sl_tp_policy_v375"] = policy_ready
        details["universal_four_way_policy_v375"] = policy_ready
        return bool(ready and policy_ready), details

    setattr(stack_truth_v375, _PATCH_ATTR, True)
    setattr(stack_truth_v375, "__wrapped__", current)
    v265._stack_truth = stack_truth_v375
    return True


def _reassert() -> bool:
    try:
        v239 = importlib.import_module("bot.runtime_all_account_profit_targets_v239_patch")
        installer = getattr(v239, "install", None)
        if callable(installer):
            installer()
        patched = all(
            (
                _patch_universal_supervisor(),
                _patch_auto_exit_trigger(),
                _patch_v281_coverage(),
                _patch_v265_stack_truth(),
            )
        )
        os.environ[_READY_FLAG] = "1" if patched else "0"
        v265 = importlib.import_module("bot.runtime_protective_exit_authority_v265_patch")
        reassert = getattr(v265, "reassert", None)
        authority_ready = bool(callable(reassert) and reassert())
        ready = bool(patched and authority_ready)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        try:
            v281 = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
            audit = getattr(v281, "audit_once", None)
            if callable(audit):
                audit()
        except Exception:
            pass
        LOGGER.critical(
            "RUNTIME_UNIVERSAL_FOUR_WAY_POLICY_V375_%s marker=%s ready=%s scope=platform_and_registered_users "
            "venues=kraken,coinbase,okx fixed_stop=existing_auto_exit_hard_loss "
            "fixed_take_profit=existing_v239_tp1_tp2_tp3 trailing_stop=true trailing_take_profit=true "
            "long_short_symmetric=true new_entries_require_four_way_policy=true existing_exits_preserved=true "
            "native_orders_created=false fill_proof_fabricated=false writer_nonce_risk_capital_killswitch_"
            "broker_health_order_fill_gates_unchanged=true safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY",
            MARKER,
            str(ready).lower(),
        )
        return ready
    except Exception as exc:
        os.environ[_READY_FLAG] = "0"
        LOGGER.exception(
            "RUNTIME_UNIVERSAL_FOUR_WAY_POLICY_V375_INSTALL_FAILED marker=%s error=%s:%s "
            "new_entries_fail_closed=true existing_exits_preserved=true safety_gates_bypassed=false",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False


def _worker() -> None:
    while True:
        time.sleep(max(3.0, _f(os.environ.get("NIJA_UNIVERSAL_SL_TP_REASSERT_SECONDS"), 5.0)))
        _reassert()


def install_import_hook() -> bool:
    global _THREAD
    with _LOCK:
        ready = _reassert()
        if _THREAD is None or not _THREAD.is_alive():
            _THREAD = threading.Thread(target=_worker, name="UniversalFourWayPolicyV375", daemon=True)
            _THREAD.start()
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_policy_row",
    "_four_way_trigger",
    "_select_trailing_candidate",
]
