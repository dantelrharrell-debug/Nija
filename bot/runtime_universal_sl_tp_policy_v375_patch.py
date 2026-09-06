"""Universal stop-loss / take-profit policy convergence v375.

Make the existing NIJA software exit policy explicit at every shared exit boundary
for platform and registered-user positions on Kraken, Coinbase, and OKX.

This layer does not create native exchange orders and does not fabricate protection.
It reuses the existing hard-loss policy from auto_exit_sl_tp_runtime_patch and the
existing v239 TP1/TP2/TP3 policy, then requires the live protective-exit authority
before new exposure can be considered protected. Existing exit/reduce requests stay
allowed and all writer/nonce/risk/capital/kill-switch/broker-health/fill gates remain
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
MARKER = "20260906-universal-sl-tp-policy-v375"
_READY_FLAG = "NIJA_RUNTIME_UNIVERSAL_SL_TP_POLICY_V375_READY"
_PATCH_ATTR = "_nija_universal_sl_tp_policy_v375"
_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None
_LOGGED: set[tuple[str, str, str, str]] = set()
_EPS = 1e-12


def _f(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if number == number else default
    except Exception:
        return default


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled", "y"}


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
    return any(_f(row.get(key)) > _EPS for key in ("take_profit", "take_profit_1", "take_profit_2", "take_profit_3"))


def _policy_row(raw: Any) -> Any:
    """Return one position with explicit existing-policy SL and TP targets."""
    if not isinstance(raw, Mapping):
        return raw
    row = dict(raw)
    entry = _entry(row)
    qty = _qty(row)
    if entry <= _EPS or qty <= _EPS:
        row["universal_sl_tp_policy_complete"] = False
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

    stop_ok = _f(row.get("stop_loss")) > _EPS
    tp_ok = _has_tp(row)
    row["software_stop_loss_available"] = stop_ok
    row["software_take_profit_available"] = tp_ok
    row["universal_sl_tp_policy_complete"] = bool(stop_ok and tp_ok)
    row["universal_sl_tp_policy_marker"] = MARKER
    return row


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
        venue_fn = getattr(importlib.import_module("bot.auto_exit_sl_tp_runtime_patch"), "_broker_label", None)
        account = str(account_fn(broker) if callable(account_fn) else getattr(broker, "account_id", "platform") or "platform")
        venue = str(venue_fn(broker) if callable(venue_fn) else type(broker).__name__).lower()
        for row in hardened:
            if not isinstance(row, Mapping):
                continue
            sig = (account, venue, str(row.get("symbol") or ""), str(row.get("position_id") or ""))
            if bool(row.get("universal_sl_tp_policy_complete")) and sig not in _LOGGED:
                _LOGGED.add(sig)
                LOGGER.critical(
                    "UNIVERSAL_SL_TP_POLICY_V375_APPLIED marker=%s account=%s venue=%s symbol=%s "
                    "quantity=%.12f entry=%.8f stop_loss=%.8f take_profit_1=%.8f "
                    "take_profit_2=%.8f take_profit_3=%.8f native_order_created=false "
                    "existing_exit_pipeline_only=true safety_gates_bypassed=false",
                    MARKER, account, venue, str(row.get("symbol") or "unknown"), _qty(row), _entry(row),
                    _f(row.get("stop_loss")), _f(row.get("take_profit_1")),
                    _f(row.get("take_profit_2")), _f(row.get("take_profit_3")),
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
        hardened = _policy_row(pos)
        return current(hardened if isinstance(hardened, dict) else pos, price)

    setattr(trigger_v375, _PATCH_ATTR, True)
    setattr(trigger_v375, "__wrapped__", current)
    module._trigger = trigger_v375
    return True


def _patch_v281_coverage() -> bool:
    """Require both policy legs on each tracker position; never invent authority."""
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
        for row in output:
            symbol = str(row.get("symbol") or "").strip().upper().replace("/", "-").replace("_", "-")
            policy = _policy_row(by_symbol.get(symbol, {}))
            complete = bool(isinstance(policy, Mapping) and policy.get("universal_sl_tp_policy_complete") is True)
            if isinstance(policy, Mapping):
                for key in ("stop_loss", "take_profit_1", "take_profit_2", "take_profit_3"):
                    if _f(policy.get(key)) > _EPS:
                        row[key] = policy.get(key)
            row["protective_stop_verified"] = bool(complete and connected and authority and structural_exit_ready)
            row["protective_take_profit_verified"] = bool(complete and connected and authority and structural_exit_ready)
            row["universal_sl_tp_policy_complete"] = complete
            row["protective_exit_verified"] = bool(
                row.get("protective_exit_verified") is True
                and row["protective_stop_verified"]
                and row["protective_take_profit_verified"]
            )
            if complete:
                attached = list(row.get("exit_protections_attached") or ())
                attached.extend(("stop_loss", "take_profit"))
                row["exit_protections_attached"] = tuple(dict.fromkeys(attached))
            else:
                reasons.append(f"universal_sl_tp_policy_incomplete:{symbol or 'unknown'}")
        return list(dict.fromkeys(reasons)), output

    setattr(account_audit_v375, _PATCH_ATTR, True)
    setattr(account_audit_v375, "__wrapped__", current)
    v281._account_audit = account_audit_v375
    return True


def _patch_v265_stack_truth() -> bool:
    """Make v375 mandatory for new exposure while preserving exits."""
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
        return bool(ready and policy_ready), details

    setattr(stack_truth_v375, _PATCH_ATTR, True)
    setattr(stack_truth_v375, "__wrapped__", current)
    v265._stack_truth = stack_truth_v375
    return True


def _reassert() -> bool:
    try:
        # v239 owns the established TP policy; install/reassert it first.
        v239 = importlib.import_module("bot.runtime_all_account_profit_targets_v239_patch")
        installer = getattr(v239, "install", None)
        if callable(installer):
            installer()
        patched = all((
            _patch_universal_supervisor(),
            _patch_auto_exit_trigger(),
            _patch_v281_coverage(),
            _patch_v265_stack_truth(),
        ))
        os.environ[_READY_FLAG] = "1" if patched else "0"
        # Re-evaluate v265 only after our ready flag is truthful.
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
            "RUNTIME_UNIVERSAL_SL_TP_POLICY_V375_%s marker=%s ready=%s scope=platform_and_registered_users "
            "venues=kraken,coinbase,okx stop_policy=existing_auto_exit_hard_loss "
            "take_profit_policy=existing_v239_tp1_tp2_tp3 new_entries_require_policy=true "
            "existing_exits_preserved=true native_orders_created=false fill_proof_fabricated=false "
            "writer_nonce_risk_capital_killswitch_broker_health_order_fill_gates_unchanged=true "
            "safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY", MARKER, str(ready).lower(),
        )
        return ready
    except Exception as exc:
        os.environ[_READY_FLAG] = "0"
        LOGGER.exception(
            "RUNTIME_UNIVERSAL_SL_TP_POLICY_V375_INSTALL_FAILED marker=%s error=%s:%s "
            "new_entries_fail_closed=true existing_exits_preserved=true safety_gates_bypassed=false",
            MARKER, type(exc).__name__, exc,
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
            _THREAD = threading.Thread(target=_worker, name="UniversalSlTpPolicyV375", daemon=True)
            _THREAD.start()
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "install", "install_import_hook", "_policy_row"]
