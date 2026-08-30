"""Generation-bound account-scoped reconciliation truth v292.

Certifies that each configured account's v289 tracker has been reconciled
against the exact current v285 authoritative snapshot generation before v281 may
claim protective-exit coverage. This is a certification layer only: protective
SELL execution remains allowed and all entry/risk/capital/order gates remain
unchanged.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from collections.abc import Mapping
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_account_scoped_reconciliation_truth_v292")
MARKER = "20260830-account-scoped-reconciliation-truth-v292"
RELEASE_ID = "20260830-runtime-convergence-v292"
_READY_FLAG = "NIJA_RUNTIME_ACCOUNT_SCOPED_RECONCILIATION_V292_READY"
_CURRENT_FLAG = "NIJA_ACCOUNT_SCOPED_RECONCILIATION_V292_CURRENT_READY"
_PATCH_ATTR = "_nija_account_scoped_reconciliation_truth_v292"
_LOCK = threading.RLock()
_CERTS: dict[str, tuple[int, int, str, int]] = {}
_STOP = threading.Event()
_THREAD: threading.Thread | None = None
_LAST = ""


def _mods():
    return (
        importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch"),
        importlib.import_module("bot.runtime_authoritative_position_coverage_v285_patch"),
        importlib.import_module("bot.runtime_account_scoped_position_state_v289_patch"),
    )


def _expected() -> dict[str, Any]:
    v281, _v285, _v289 = _mods()
    manager = v281._canonical_manager()
    return dict(v281._expected_accounts(manager)) if manager is not None else {}


def _snapshot(broker: Any) -> tuple[bool, int, str]:
    if broker is None:
        return False, 0, "broker_missing"
    _v281, v285, _v289 = _mods()
    status = getattr(v285, "_snapshot_status", None)
    if not callable(status):
        return False, 0, "v285_snapshot_status_unavailable"
    ready, reason, _rows, _age, generation = status(broker)
    try:
        generation = int(generation or 0)
    except Exception:
        generation = 0
    if not ready or generation <= 0:
        return False, generation, str(reason or "authoritative_snapshot_unready")
    if getattr(broker, "_startup_position_sync_fetch_ok", None) is not True:
        return False, generation, str(getattr(broker, "_startup_position_sync_error", "") or "authoritative_position_fetch_unproven")
    if getattr(broker, "_startup_position_sync_adopted", None) is not True:
        return False, generation, str(getattr(broker, "_startup_position_sync_error", "") or "position_snapshot_not_adopted")
    return True, generation, "current_authoritative_snapshot_adopted"


def _binding(broker: Any) -> tuple[bool, str, str]:
    if broker is None:
        return False, "", "broker_missing"
    tracker = getattr(broker, "position_tracker", None)
    if tracker is None:
        return False, "", "tracker_missing"
    _v281, _v285, v289 = _mods()
    scope = str(v289._broker_scope(broker))
    expected_file = os.path.abspath(str(v289._position_file(scope)))
    actual_scope = str(getattr(tracker, "_nija_account_scope_v289", "") or "")
    actual_file = os.path.abspath(str(getattr(tracker, "storage_file", "") or ""))
    if actual_scope != scope:
        return False, scope, f"tracker_scope_mismatch:{actual_scope or 'missing'}"
    if actual_file != expected_file:
        return False, scope, "tracker_storage_mismatch"
    if getattr(tracker, "_nija_account_entry_store_v289", None) is None:
        return False, scope, "scoped_entry_price_store_missing"
    return True, scope, "account_scoped_tracker_binding_current"


def _current(account: str, broker: Any) -> tuple[bool, str]:
    with _LOCK:
        cert = _CERTS.get(account)
    if cert is None or broker is None:
        return False, "certificate_missing"
    tracker = getattr(broker, "position_tracker", None)
    if tracker is None:
        return False, "tracker_missing"
    broker_id, tracker_id, scope, generation = cert
    if broker_id != id(broker) or tracker_id != id(tracker):
        return False, "broker_or_tracker_identity_changed"
    binding_ok, current_scope, reason = _binding(broker)
    if not binding_ok or current_scope != scope:
        return False, reason
    snapshot_ok, current_generation, reason = _snapshot(broker)
    if not snapshot_ok:
        return False, reason
    if current_generation != generation:
        return False, f"snapshot_generation_changed:{generation}->{current_generation}"
    return True, "generation_bound_reconciliation_current"


def _certify(account: str, broker: Any, shared: set[int]) -> tuple[bool, str]:
    if broker is None:
        return False, "broker_missing"
    tracker = getattr(broker, "position_tracker", None)
    if tracker is None:
        return False, "tracker_missing"
    if id(tracker) in shared:
        return False, "shared_tracker_object_requires_fresh_reconstruction"
    binding_ok, scope, reason = _binding(broker)
    if not binding_ok:
        return False, reason
    snapshot_ok, generation, reason = _snapshot(broker)
    if not snapshot_ok:
        return False, reason
    _v281, _v285, v289 = _mods()
    removed, cleanup_reason = v289._clean_authoritative_orphans(broker, scope)
    if cleanup_reason != "authoritative_cleanup_complete":
        return False, str(cleanup_reason or "authoritative_cleanup_incomplete")
    after_ok, after_generation, reason = _snapshot(broker)
    if not after_ok or after_generation != generation:
        return False, reason if not after_ok else f"snapshot_generation_changed_during_cleanup:{generation}->{after_generation}"
    with _LOCK:
        _CERTS[account] = (id(broker), id(tracker), scope, generation)
    return True, f"generation_bound_reconciliation_current:generation={generation}:removed={int(removed or 0)}"


def _patch_v281() -> bool:
    v281, _v285, _v289 = _mods()
    current = getattr(v281, "_account_audit", None)
    if not callable(current):
        return False
    seen: set[int] = set()
    probe = current
    for _ in range(64):
        if not callable(probe) or id(probe) in seen:
            break
        seen.add(id(probe))
        if getattr(probe, _PATCH_ATTR, False):
            return True
        probe = getattr(probe, "__wrapped__", None)
    original = current

    @wraps(original)
    def account_audit_v292(account: str, broker: Any, structural_exit_ready: bool):
        reasons, positions = original(account, broker, structural_exit_ready)
        reasons = list(reasons or [])
        positions = [dict(row) for row in tuple(positions or ()) if isinstance(row, Mapping)]
        ok, reason = _current(account, broker)
        if not ok:
            reasons.append(f"account_scoped_reconciliation_uncertified:{reason}")
            for row in positions:
                row["protective_exit_verified"] = False
                row["account_scoped_reconciliation_verified"] = False
                if "exit_protections_attached" in row:
                    row["exit_protections_attached"] = ()
        else:
            for row in positions:
                row["account_scoped_reconciliation_verified"] = True
        return list(dict.fromkeys(str(reason) for reason in reasons if str(reason))), positions

    setattr(account_audit_v292, _PATCH_ATTR, True)
    setattr(account_audit_v292, "__wrapped__", original)
    v281._account_audit = account_audit_v292
    return True


def reconcile_once() -> dict[str, Any]:
    global _LAST
    _patch_v281()
    accounts = _expected()
    owners: dict[int, int] = {}
    for broker in accounts.values():
        tracker = getattr(broker, "position_tracker", None) if broker is not None else None
        if tracker is not None:
            owners[id(tracker)] = owners.get(id(tracker), 0) + 1
    shared = {key for key, count in owners.items() if count > 1}
    pending: dict[str, str] = {}
    with _LOCK:
        for stale in set(_CERTS) - set(accounts):
            _CERTS.pop(stale, None)
    for account, broker in accounts.items():
        try:
            ok, reason = _certify(account, broker, shared)
        except Exception as exc:
            ok, reason = False, f"certification_error:{type(exc).__name__}:{exc}"
        if not ok:
            pending[account] = reason
            with _LOCK:
                _CERTS.pop(account, None)
    ready = bool(accounts) and not shared and not pending
    os.environ[_CURRENT_FLAG] = "1" if ready else "0"
    signature = repr((ready, tuple(sorted(pending.items())), len(shared)))
    if signature != _LAST:
        _LAST = signature
        (LOGGER.critical if ready else LOGGER.warning)(
            "ACCOUNT_SCOPED_RECONCILIATION_V292_%s marker=%s accounts=%s pending=%s shared_tracker_objects=%d generation_bound=true authoritative_cleanup_required=true broker_io=false protective_sell_execution_unchanged=true synthetic_exit_coverage=false safety_gates_bypassed=false",
            "READY" if ready else "PENDING", MARKER, tuple(accounts), pending, len(shared),
        )
    return {"ready": ready, "accounts": tuple(accounts), "pending": pending, "shared_tracker_objects": len(shared)}


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_account_scoped_reconciliation_truth_v292"] = _READY_FLAG
        return True
    except Exception:
        return False


def _monitor() -> None:
    while not _STOP.wait(5.0):
        try:
            reconcile_once()
        except BaseException as exc:
            os.environ[_CURRENT_FLAG] = "0"
            LOGGER.error("ACCOUNT_SCOPED_RECONCILIATION_V292_MONITOR_ERROR marker=%s error=%s:%s fail_closed=true", MARKER, type(exc).__name__, exc)


def _ensure_monitor() -> bool:
    global _THREAD
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return True
        _THREAD = threading.Thread(target=_monitor, name="AccountScopedReconciliationTruthV292", daemon=True)
        _THREAD.start()
    return True


def install() -> bool:
    try:
        _v281, _v285, v289 = _mods()
        upstream = bool(v289.install())
    except Exception:
        upstream = False
    ready = bool(upstream and _patch_v281() and _register_manifest() and _ensure_monitor())
    os.environ[_READY_FLAG] = "1" if ready else "0"
    if ready:
        reconcile_once()
    LOGGER.critical(
        "RUNTIME_ACCOUNT_SCOPED_RECONCILIATION_V292_%s marker=%s installed=%s generation_bound=true v281_exit_coverage_fail_closed=true protective_sell_execution_unchanged=true forced_trade=false forced_activation=false writer_nonce_capital_risk_killswitch_order_fill_gates_unchanged=true safety_gates_bypassed=false",
        "READY" if ready else "NOT_READY", MARKER, str(ready).lower(),
    )
    return ready


def install_import_hook() -> bool:
    return install()


__all__ = ["MARKER", "RELEASE_ID", "install", "install_import_hook", "reconcile_once", "_snapshot", "_binding", "_current", "_certify", "_patch_v281"]
