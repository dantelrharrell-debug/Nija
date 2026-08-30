"""Generation-bound account-scoped reconciliation truth v291.

v289 isolates persistent position and entry-price state by account, but its
installation/binding readiness is intentionally separate from the stronger
runtime truth needed by protective-exit coverage. A tracker can be correctly
bound to an account-scoped file while authoritative cleanup is still waiting on
fresh broker position proof. Reporting that intermediate state as fully
reconciled would make legacy shared-state contamination harder to distinguish
from a current broker-adopted tracker.

v291 adds a process-local reconciliation certificate for every configured
account. A certificate is issued only when:

* the broker and tracker identities are known and not shared with another
  configured account;
* tracker scope, storage path and scoped entry-price store match v289 exactly;
* v285 exposes a current authoritative position snapshot with generation > 0;
* startup fetch and adoption proofs are both true;
* v289 authoritative orphan cleanup completes against that snapshot; and
* the same authoritative snapshot generation is still current after cleanup.

The certificate is generation-bound. Any newer/stale snapshot, tracker object
replacement, scope/path drift, missing broker, or lost startup proof invalidates
it immediately. v281 all-account protective-exit certification is wrapped so a
missing/currently-invalid certificate keeps that account fail closed and clears
``protective_exit_verified`` on reported rows. This does not block protective
SELL execution; it only prevents NIJA from claiming complete all-account exit
coverage before account-local persistence is demonstrably reconciled.

No broker I/O is added by this layer. Cleanup consumes the already-current v285
snapshot and the existing v289 tracker reconciliation primitive. No positions,
cost basis, connectivity, execution proof, capital, fills, readiness, or exit
protection are fabricated.
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

LOGGER = logging.getLogger("nija.runtime_account_scoped_reconciliation_truth_v291")
MARKER = "20260830-account-scoped-reconciliation-truth-v291"
RELEASE_ID = "20260830-runtime-convergence-v291"
_READY_FLAG = "NIJA_RUNTIME_ACCOUNT_SCOPED_RECONCILIATION_V291_READY"
_CURRENT_FLAG = "NIJA_ACCOUNT_SCOPED_RECONCILIATION_V291_CURRENT_READY"
_PATCH_ATTR = "_nija_account_scoped_reconciliation_truth_v291"
_LOCK = threading.RLock()
_MONITOR_STOP = threading.Event()
_MONITOR_THREAD: threading.Thread | None = None
_CERTIFICATES: dict[str, dict[str, Any]] = {}
_LAST_SIGNATURE = ""


def _v281() -> Any:
    return importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")


def _v285() -> Any:
    return importlib.import_module("bot.runtime_authoritative_position_coverage_v285_patch")


def _v289() -> Any:
    return importlib.import_module("bot.runtime_account_scoped_position_state_v289_patch")


def _expected_accounts() -> dict[str, Any]:
    try:
        v281 = _v281()
        manager = v281._canonical_manager()
        if manager is None:
            return {}
        return dict(v281._expected_accounts(manager))
    except Exception:
        return {}


def _snapshot_generation_status(broker: Any) -> tuple[bool, int, str]:
    if broker is None:
        return False, 0, "broker_missing"
    try:
        status = getattr(_v285(), "_snapshot_status", None)
        if not callable(status):
            return False, 0, "v285_snapshot_status_unavailable"
        ready, reason, _rows, _age, generation = status(broker)
        try:
            generation_i = int(generation or 0)
        except Exception:
            generation_i = 0
        if not bool(ready):
            return False, generation_i, str(reason or "authoritative_snapshot_unready")
        if generation_i <= 0:
            return False, generation_i, "authoritative_snapshot_generation_missing"
        if getattr(broker, "_startup_position_sync_fetch_ok", None) is not True:
            exact = str(getattr(broker, "_startup_position_sync_error", "") or "").strip()
            return False, generation_i, exact or "authoritative_position_fetch_unproven"
        if getattr(broker, "_startup_position_sync_adopted", None) is not True:
            exact = str(getattr(broker, "_startup_position_sync_error", "") or "").strip()
            return False, generation_i, exact or "position_snapshot_not_adopted"
        return True, generation_i, "current_authoritative_snapshot_adopted"
    except Exception as exc:
        return False, 0, f"snapshot_status_error:{type(exc).__name__}:{exc}"


def _tracker_binding_status(broker: Any) -> tuple[bool, str, str]:
    if broker is None:
        return False, "", "broker_missing"
    tracker = getattr(broker, "position_tracker", None)
    if tracker is None:
        return False, "", "tracker_missing"
    try:
        v289 = _v289()
        scope = str(v289._broker_scope(broker))
        expected_file = os.path.abspath(str(v289._position_file(scope)))
    except Exception as exc:
        return False, "", f"v289_scope_error:{type(exc).__name__}:{exc}"
    actual_scope = str(getattr(tracker, "_nija_account_scope_v289", "") or "")
    actual_file = os.path.abspath(str(getattr(tracker, "storage_file", "") or ""))
    store = getattr(tracker, "_nija_account_entry_store_v289", None)
    if actual_scope != scope:
        return False, scope, f"tracker_scope_mismatch:expected={scope}:actual={actual_scope or 'missing'}"
    if actual_file != expected_file:
        return False, scope, f"tracker_storage_mismatch:expected={expected_file}:actual={actual_file or 'missing'}"
    if store is None:
        return False, scope, "scoped_entry_price_store_missing"
    return True, scope, "account_scoped_tracker_binding_current"


def _certificate_current(account: str, broker: Any) -> tuple[bool, str]:
    with _LOCK:
        cert = dict(_CERTIFICATES.get(str(account), {}))
    if not cert:
        return False, "certificate_missing"
    tracker = getattr(broker, "position_tracker", None) if broker is not None else None
    if broker is None or tracker is None:
        return False, "broker_or_tracker_missing"
    if int(cert.get("broker_id", 0) or 0) != id(broker):
        return False, "broker_identity_changed"
    if int(cert.get("tracker_id", 0) or 0) != id(tracker):
        return False, "tracker_identity_changed"
    binding_ok, scope, binding_reason = _tracker_binding_status(broker)
    if not binding_ok:
        return False, binding_reason
    if str(cert.get("scope", "")) != scope:
        return False, "certificate_scope_changed"
    snapshot_ok, generation, snapshot_reason = _snapshot_generation_status(broker)
    if not snapshot_ok:
        return False, snapshot_reason
    if int(cert.get("snapshot_generation", 0) or 0) != generation:
        return False, f"snapshot_generation_changed:cert={cert.get('snapshot_generation', 0)}:current={generation}"
    return True, "generation_bound_reconciliation_current"


def _certify_account(account: str, broker: Any, shared_tracker_ids: set[int]) -> tuple[bool, str]:
    if broker is None:
        return False, "broker_missing"
    tracker = getattr(broker, "position_tracker", None)
    if tracker is None:
        return False, "tracker_missing"
    if id(tracker) in shared_tracker_ids:
        return False, "shared_tracker_object_requires_fresh_reconstruction"
    binding_ok, scope, binding_reason = _tracker_binding_status(broker)
    if not binding_ok:
        return False, binding_reason
    snapshot_ok, generation_before, snapshot_reason = _snapshot_generation_status(broker)
    if not snapshot_ok:
        return False, snapshot_reason
    try:
        removed, cleanup_reason = _v289()._clean_authoritative_orphans(broker, scope)
    except Exception as exc:
        return False, f"authoritative_cleanup_error:{type(exc).__name__}:{exc}"
    if str(cleanup_reason) != "authoritative_cleanup_complete":
        return False, str(cleanup_reason or "authoritative_cleanup_incomplete")
    snapshot_ok_after, generation_after, reason_after = _snapshot_generation_status(broker)
    if not snapshot_ok_after:
        return False, reason_after
    if generation_after != generation_before:
        return False, f"snapshot_generation_changed_during_cleanup:{generation_before}->{generation_after}"
    certificate = {
        "account": str(account),
        "broker_id": id(broker),
        "tracker_id": id(tracker),
        "scope": scope,
        "snapshot_generation": generation_after,
        "certified_at_monotonic": time.monotonic(),
        "removed_orphans": int(removed or 0),
    }
    with _LOCK:
        _CERTIFICATES[str(account)] = certificate
    return True, f"generation_bound_reconciliation_current:generation={generation_after}:removed={int(removed or 0)}"


def _shared_tracker_ids(accounts: Mapping[str, Any]) -> set[int]:
    owners: dict[int, int] = {}
    for broker in accounts.values():
        tracker = getattr(broker, "position_tracker", None) if broker is not None else None
        if tracker is not None:
            owners[id(tracker)] = owners.get(id(tracker), 0) + 1
    return {tracker_id for tracker_id, count in owners.items() if count > 1}


def reconcile_once() -> dict[str, Any]:
    try:
        v289 = _v289()
        install = getattr(v289, "install", None)
        if callable(install):
            install()
    except Exception:
        pass
    _patch_v281_account_audit()
    accounts = _expected_accounts()
    shared_ids = _shared_tracker_ids(accounts)
    pending: dict[str, str] = {}
    certified: dict[str, bool] = {}
    current_accounts = set(accounts)
    with _LOCK:
        for stale in set(_CERTIFICATES) - current_accounts:
            _CERTIFICATES.pop(stale, None)
    for account, broker in accounts.items():
        ok, reason = _certify_account(account, broker, shared_ids)
        certified[account] = bool(ok)
        if not ok:
            pending[account] = reason
            with _LOCK:
                _CERTIFICATES.pop(account, None)
    ready = bool(accounts) and not shared_ids and all(certified.values())
    os.environ[_CURRENT_FLAG] = "1" if ready else "0"
    signature = repr((ready, tuple(sorted(pending.items())), tuple(sorted(certified.items())), len(shared_ids)))
    global _LAST_SIGNATURE
    with _LOCK:
        changed = signature != _LAST_SIGNATURE
        if changed:
            _LAST_SIGNATURE = signature
    if changed:
        log = LOGGER.critical if ready else LOGGER.warning
        log(
            "ACCOUNT_SCOPED_RECONCILIATION_V291_%s marker=%s accounts=%s pending=%s shared_tracker_objects=%d generation_bound=true authoritative_cleanup_required=true broker_io=false protective_sell_execution_unchanged=true synthetic_position=false synthetic_cost_basis=false synthetic_exit_coverage=false safety_gates_bypassed=false",
            "READY" if ready else "PENDING",
            MARKER,
            tuple(accounts),
            pending,
            len(shared_ids),
        )
    return {
        "ready": ready,
        "accounts": tuple(accounts),
        "certified": certified,
        "pending": pending,
        "shared_tracker_objects": len(shared_ids),
    }


def _chain_has_exact(callable_obj: Any) -> bool:
    seen: set[int] = set()
    current = callable_obj
    for _ in range(64):
        if not callable(current) or id(current) in seen:
            return False
        seen.add(id(current))
        owner = getattr(current, "__globals__", {}) or {}
        if bool(getattr(current, _PATCH_ATTR, False)) and owner.get("MARKER") == MARKER:
            return True
        current = getattr(current, "__wrapped__", None)
    return False


def _patch_v281_account_audit() -> bool:
    try:
        v281 = _v281()
    except Exception:
        return False
    current = getattr(v281, "_account_audit", None)
    if not callable(current):
        return False
    if _chain_has_exact(current):
        return True
    original = current

    @wraps(original)
    def account_audit_v291(account: str, broker: Any, structural_exit_ready: bool):
        reasons, positions = original(account, broker, structural_exit_ready)
        reasons = list(reasons or [])
        positions = [dict(row) for row in tuple(positions or ()) if isinstance(row, Mapping)]
        certified, cert_reason = _certificate_current(account, broker)
        if not certified:
            reasons.append(f"account_scoped_reconciliation_uncertified:{cert_reason}")
            for row in positions:
                row["protective_exit_verified"] = False
                if "exit_protections_attached" in row:
                    row["exit_protections_attached"] = ()
                row["account_scoped_reconciliation_verified"] = False
        else:
            for row in positions:
                row["account_scoped_reconciliation_verified"] = True
        return list(dict.fromkeys(str(reason) for reason in reasons if str(reason))), positions

    account_audit_v291.__name__ = "account_audit_v291"
    setattr(account_audit_v291, _PATCH_ATTR, True)
    setattr(account_audit_v291, "__wrapped__", original)
    v281._account_audit = account_audit_v291
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_account_scoped_reconciliation_truth_v291"] = _READY_FLAG
        return True
    except Exception:
        return False


def _monitor() -> None:
    while not _MONITOR_STOP.wait(5.0):
        try:
            reconcile_once()
        except BaseException as exc:
            os.environ[_CURRENT_FLAG] = "0"
            LOGGER.error(
                "ACCOUNT_SCOPED_RECONCILIATION_V291_MONITOR_ERROR marker=%s error=%s:%s certification_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )


def _ensure_monitor() -> bool:
    global _MONITOR_THREAD
    with _LOCK:
        if _MONITOR_THREAD is not None and _MONITOR_THREAD.is_alive():
            return True
        if _MONITOR_STOP.is_set():
            _MONITOR_STOP.clear()
        _MONITOR_THREAD = threading.Thread(
            target=_monitor,
            name="AccountScopedReconciliationTruthV291",
            daemon=True,
        )
        _MONITOR_THREAD.start()
    return True


def install() -> bool:
    try:
        v289 = _v289()
        upstream = bool((getattr(v289, "install", None) or getattr(v289, "install_import_hook", None))())
    except Exception:
        upstream = False
    audit = _patch_v281_account_audit()
    manifest = _register_manifest()
    monitor = _ensure_monitor()
    installed = bool(upstream and audit and manifest and monitor)
    os.environ[_READY_FLAG] = "1" if installed else "0"
    if installed:
        try:
            reconcile_once()
        except Exception:
            os.environ[_CURRENT_FLAG] = "0"
    LOGGER.critical(
        "RUNTIME_ACCOUNT_SCOPED_RECONCILIATION_V291_%s marker=%s installed=%s generation_bound_certificate=true exact_tracker_identity=true exact_scope_path=true current_v285_snapshot_required=true startup_fetch_adoption_required=true authoritative_cleanup_required=true v281_exit_coverage_fail_closed=true protective_sell_execution_unchanged=true forced_trade=false forced_activation=false writer_nonce_capital_risk_killswitch_order_fill_gates_unchanged=true safety_gates_bypassed=false",
        "READY" if installed else "NOT_READY",
        MARKER,
        str(installed).lower(),
    )
    return installed


def install_import_hook() -> bool:
    return install()


def stop() -> None:
    _MONITOR_STOP.set()


__all__ = [
    "MARKER", "RELEASE_ID", "install", "install_import_hook", "stop", "reconcile_once",
    "_snapshot_generation_status", "_tracker_binding_status", "_certificate_current",
    "_certify_account", "_patch_v281_account_audit",
]
