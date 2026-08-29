"""Kraken user position-proof eligibility and coverage liveness v282.

Production on 2026-08-29 proved two related account-local safety/liveness gaps:

* the v86 Kraken-user reconnect watchdog called post-connect capital/portfolio
  reconciliation on every poll even when a user broker was already connected.
  That reconciliation performs private balance/position reads, so two healthy
  users plus platform monitoring repeatedly contended for the same process-wide
  Kraken private-read lock;
* a local-read contention during that audit could produce
  ``position_snapshot_fail_closed=true`` and then immediately publish the same
  user as ``trading_eligible=true`` because the legacy capital audit swallowed
  the position-read exception and treated position_count as zero.

v282 keeps platform/user isolation intact while closing both gaps.  Connected
Kraken users are post-connect audited once per connection and then only on a
bounded maintenance cadence.  A user account is entry-blocked whenever its
latest v98/v279 authoritative position proof is missing, or when proven local
Kraken read contention occurs during the eligibility audit.  The broker remains
connected and exits remain available; platform execution is not revoked.

v282 also corrects v281 denominator semantics: a bare boolean in mutable MABM
metadata is trading eligibility, not static configuration enablement, so
``False`` must not silently remove a blocked account from all-account coverage.
Only explicit configuration objects/mappings with an enabled field may exclude
a disabled account.

Finally, v282 reuses v265's existing periodic reassert worker to refresh v281
coverage truth.  It adds no thread and performs no broker I/O itself.

No connectivity, balance, position, cost-basis, nonce, execution, order, fill,
kill-switch, or readiness proof is fabricated.  Genuine exchange/API/auth
failures remain authoritative and all existing safety gates remain intact.
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

from bot import kraken_all_account_supervision_v86 as v86

LOGGER = logging.getLogger("nija.runtime_kraken_user_position_eligibility_v282")
MARKER = "20260829-kraken-user-position-eligibility-v282"
_READY_FLAG = "NIJA_KRAKEN_USER_POSITION_ELIGIBILITY_V282_READY"
_PATCH_RECONCILE = "_nija_kraken_user_position_eligibility_v282_reconcile"
_PATCH_SCHEDULE = "_nija_kraken_user_position_eligibility_v282_schedule"
_PATCH_V265 = "_nija_all_account_coverage_v282_reassert"
_POSITION_BLOCK_PREFIX = "position_sync_v282:"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_LOCK = threading.RLock()
_AUDIT_STATE: dict[str, dict[str, Any]] = {}
_LAST_BLOCK_REASON: dict[str, str] = {}


def _label(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip().lower()


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in _TRUE


def _connected(broker: Any) -> bool:
    if broker is None:
        return False
    try:
        value = getattr(broker, "connected", False)
        return bool(value() if callable(value) else value)
    except Exception:
        return False


def _busy_seq(broker: Any) -> int:
    try:
        return max(0, int(getattr(broker, "_nija_kraken_local_read_busy_seq_v242", 0) or 0))
    except Exception:
        return 0


def _maintenance_reaudit_s() -> float:
    try:
        value = float(os.environ.get("NIJA_KRAKEN_USER_ELIGIBILITY_REAUDIT_S", "60") or 60.0)
    except (TypeError, ValueError):
        value = 60.0
    return max(30.0, min(600.0, value))


def _contention_retry_s() -> float:
    try:
        value = float(os.environ.get("NIJA_KRAKEN_USER_POSITION_RETRY_S", "15") or 15.0)
    except (TypeError, ValueError):
        value = 15.0
    return max(5.0, min(120.0, value))


def _position_proof(broker: Any) -> tuple[bool, str]:
    if broker is None:
        return False, "broker_missing"
    if not _connected(broker):
        return False, "disconnected"
    if getattr(broker, "_startup_position_sync_fetch_ok", None) is not True:
        exact = str(getattr(broker, "_startup_position_sync_error", "") or "").strip()
        return False, exact or "authoritative_position_fetch_unproven"
    if getattr(broker, "_startup_position_sync_adopted", None) is not True:
        exact = str(getattr(broker, "_startup_position_sync_error", "") or "").strip()
        return False, exact or "position_snapshot_not_adopted"
    if not hasattr(broker, "_startup_position_sync_symbols"):
        return False, "authoritative_snapshot_symbols_missing"
    return True, "authoritative_position_snapshot_adopted"


def _account_id(user_id: Any) -> str:
    return f"user:{str(user_id)}:kraken"


def _set_position_block(
    manager: Any,
    user_id: str,
    broker_type: Any,
    broker: Any,
    reason: str,
) -> None:
    account = _account_id(user_id)
    key = (user_id, broker_type)
    tagged = _POSITION_BLOCK_PREFIX + str(reason or "position_proof_unavailable")
    blocked = getattr(manager, "_capital_blocked_users", None)
    if isinstance(blocked, dict):
        blocked[key] = tagged
    metadata = getattr(manager, "_user_metadata", None)
    if isinstance(metadata, dict):
        metadata.setdefault(user_id, {}).setdefault("brokers", {})[broker_type] = False
    try:
        setattr(broker, "_nija_user_position_entry_blocked_v282", True)
        setattr(broker, "_nija_user_position_entry_block_reason_v282", tagged)
    except Exception:
        pass

    with _LOCK:
        previous = _LAST_BLOCK_REASON.get(account)
        _LAST_BLOCK_REASON[account] = tagged
    if previous != tagged:
        LOGGER.warning(
            "KRAKEN_USER_POSITION_ELIGIBILITY_V282_BLOCKED marker=%s account=%s reason=%s "
            "connected_preserved=true exits_preserved=true platform_activation_unchanged=true "
            "user_entries_fail_closed=true synthetic_position=false synthetic_eligibility=false "
            "safety_gates_bypassed=false",
            MARKER, account, tagged,
        )


def _clear_owned_position_block(
    manager: Any,
    user_id: str,
    broker_type: Any,
    broker: Any,
) -> None:
    account = _account_id(user_id)
    key = (user_id, broker_type)
    blocked = getattr(manager, "_capital_blocked_users", None)
    if isinstance(blocked, dict):
        current = str(blocked.get(key, "") or "")
        if current.startswith(_POSITION_BLOCK_PREFIX):
            blocked.pop(key, None)
    try:
        setattr(broker, "_nija_user_position_entry_blocked_v282", False)
        setattr(broker, "_nija_user_position_entry_block_reason_v282", "")
    except Exception:
        pass
    with _LOCK:
        prior = _LAST_BLOCK_REASON.pop(account, None)
    if prior:
        LOGGER.critical(
            "KRAKEN_USER_POSITION_ELIGIBILITY_V282_POSITION_PROOF_RECOVERED marker=%s account=%s "
            "authoritative_position_proof=true eligibility_requires_existing_capital_audit=true "
            "platform_activation_unchanged=true",
            MARKER, account,
        )


def _record_audit(
    account: str,
    broker: Any,
    *,
    audited: bool,
    position_ready: bool,
    reason: str,
    next_audit_s: float,
) -> None:
    with _LOCK:
        _AUDIT_STATE[account] = {
            "broker_id": id(broker) if broker is not None else 0,
            "audited": bool(audited),
            "position_ready": bool(position_ready),
            "reason": str(reason or ""),
            "next_audit_at": time.monotonic() + max(0.0, float(next_audit_s)),
        }


def _patch_v86_reconcile() -> bool:
    current = getattr(v86, "_reconcile_post_connect", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_RECONCILE, False)):
        return True
    original = current

    @wraps(original)
    def reconcile_post_connect_v282(manager: Any, user_id: str, broker_type: Any, broker: Any) -> None:
        account = _account_id(user_id)
        if not _connected(broker):
            with _LOCK:
                _AUDIT_STATE.pop(account, None)
            return original(manager, user_id, broker_type, broker)

        proof_ok, proof_reason = _position_proof(broker)
        if not proof_ok:
            _set_position_block(manager, user_id, broker_type, broker, proof_reason)
            _record_audit(
                account, broker, audited=False, position_ready=False,
                reason=proof_reason, next_audit_s=0.0,
            )
            return None

        before_busy = _busy_seq(broker)
        original(manager, user_id, broker_type, broker)
        after_busy = _busy_seq(broker)
        if after_busy > before_busy:
            reason = f"local_read_contention_during_eligibility_audit:{before_busy}->{after_busy}"
            _set_position_block(manager, user_id, broker_type, broker, reason)
            _record_audit(
                account, broker, audited=False, position_ready=False,
                reason=reason, next_audit_s=_contention_retry_s(),
            )
            return None

        # The original capital audit remains authoritative for cash eligibility.
        # Clear only a v282-owned position block; never erase a genuine capital,
        # auth, broker-health, or isolation failure published by another layer.
        _clear_owned_position_block(manager, user_id, broker_type, broker)
        _record_audit(
            account, broker, audited=True, position_ready=True,
            reason="position_and_capital_audit_completed",
            next_audit_s=_maintenance_reaudit_s(),
        )
        return None

    setattr(reconcile_post_connect_v282, _PATCH_RECONCILE, True)
    setattr(reconcile_post_connect_v282, "__wrapped__", original)
    v86._reconcile_post_connect = reconcile_post_connect_v282
    return True


def _patch_v86_schedule() -> bool:
    current = getattr(v86, "_schedule", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_SCHEDULE, False)):
        return True
    original = current

    @wraps(original)
    def schedule_v282(manager: Any, record: tuple[str, str, Any, Any]) -> str:
        try:
            account, user_id, broker_type, broker = record
        except Exception:
            return original(manager, record)

        if broker is None or not _connected(broker):
            with _LOCK:
                _AUDIT_STATE.pop(str(account), None)
            return original(manager, record)

        proof_ok, proof_reason = _position_proof(broker)
        if not proof_ok:
            _set_position_block(manager, user_id, broker_type, broker, proof_reason)
            _record_audit(
                str(account), broker, audited=False, position_ready=False,
                reason=proof_reason, next_audit_s=0.0,
            )
            with v86._LOCK:
                v86._FAILURES.pop(str(account), None)
                v86._NEXT_RETRY.pop(str(account), None)
            # Transport is connected; keep connectivity truth separate from
            # account-local entry eligibility.
            return "connected"

        now = time.monotonic()
        with _LOCK:
            state = dict(_AUDIT_STATE.get(str(account), {}))
        same_broker = int(state.get("broker_id", 0) or 0) == id(broker)
        if same_broker and bool(state.get("audited")) and bool(state.get("position_ready")):
            if now < float(state.get("next_audit_at", 0.0) or 0.0):
                with v86._LOCK:
                    v86._FAILURES.pop(str(account), None)
                    v86._NEXT_RETRY.pop(str(account), None)
                return "connected"
        elif same_broker and now < float(state.get("next_audit_at", 0.0) or 0.0):
            return "connected"

        # One bounded post-connect/maintenance audit.  v86._mark_connected calls
        # the patched reconciliation function above.  Steady-state polls inside
        # the maintenance window perform no broker I/O.
        v86._mark_connected(manager, user_id, broker_type, broker)
        with v86._LOCK:
            v86._FAILURES.pop(str(account), None)
            v86._NEXT_RETRY.pop(str(account), None)
        return "connected"

    setattr(schedule_v282, _PATCH_SCHEDULE, True)
    setattr(schedule_v282, "__wrapped__", original)
    v86._schedule = schedule_v282
    return True


def _patch_v281_disabled_semantics() -> bool:
    try:
        v281 = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
    except Exception:
        return False
    current = getattr(v281, "_explicitly_disabled", None)
    if not callable(current):
        return False
    if bool(getattr(current, "_nija_v282_disabled_semantics", False)):
        return True

    def explicitly_disabled_v282(value: Any) -> bool:
        # Bare booleans in MABM metadata are mutable trading eligibility, not a
        # durable configuration-enabled flag.  Excluding False here can hide the
        # very account v281 is meant to report as pending.
        if isinstance(value, bool):
            return False
        if isinstance(value, Mapping):
            for key in ("enabled", "is_enabled", "trading_enabled"):
                if key in value:
                    return not _truthy(value.get(key))
            return False
        for key in ("enabled", "is_enabled", "trading_enabled"):
            if hasattr(value, key):
                try:
                    return not _truthy(getattr(value, key))
                except Exception:
                    return True
        return False

    setattr(explicitly_disabled_v282, "_nija_v282_disabled_semantics", True)
    setattr(explicitly_disabled_v282, "__wrapped__", current)
    v281._explicitly_disabled = explicitly_disabled_v282
    return True


def _audit_v281_from_v265() -> bool:
    try:
        v281 = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
        audit = getattr(v281, "audit_once", None)
        if not callable(audit):
            raise RuntimeError("v281_audit_once_missing")
        result = audit()
        return isinstance(result, dict)
    except Exception as exc:
        os.environ["NIJA_ALL_ACCOUNT_POSITION_EXIT_COVERAGE_READY"] = "0"
        LOGGER.error(
            "ALL_ACCOUNT_COVERAGE_V282_AUDIT_ERROR marker=%s error=%s:%s "
            "coverage_certification_fail_closed=true platform_activation_unchanged=true",
            MARKER, type(exc).__name__, exc,
        )
        return False


def _patch_v265_periodic_audit() -> bool:
    try:
        v265 = importlib.import_module("bot.runtime_protective_exit_authority_v265_patch")
    except Exception:
        return False
    current = getattr(v265, "reassert", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_V265, False)):
        return True
    original = current

    @wraps(original)
    def reassert_v282() -> bool:
        structural_ready = bool(original())
        audited = _audit_v281_from_v265()
        if not audited:
            os.environ["NIJA_ALL_ACCOUNT_POSITION_EXIT_COVERAGE_READY"] = "0"
        # v281 operational coverage never changes v265 structural entry/exit
        # authority. Account-local eligibility is enforced separately above.
        return structural_ready

    setattr(reassert_v282, _PATCH_V265, True)
    setattr(reassert_v282, "__wrapped__", original)
    v265.reassert = reassert_v282
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["kraken_user_position_eligibility_v282"] = _READY_FLAG
        required["all_account_position_exit_coverage_v281_capability"] = (
            "NIJA_ALL_ACCOUNT_POSITION_EXIT_COVERAGE_V281_INSTALLED"
        )
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        reconcile_ok = _patch_v86_reconcile()
        schedule_ok = _patch_v86_schedule()
        denominator_ok = _patch_v281_disabled_semantics()
        periodic_ok = _patch_v265_periodic_audit()
        manifest_ok = _register_manifest()
        ready = bool(reconcile_ok and schedule_ok and denominator_ok and periodic_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if ready:
            LOGGER.critical(
                "KRAKEN_USER_POSITION_ELIGIBILITY_V282_READY marker=%s ready=true "
                "steady_connected_poll_broker_io_suppressed=true maintenance_reaudit_s=%.1f "
                "contention_retry_s=%.1f authoritative_position_proof_required=true "
                "account_local_entry_block=true exits_preserved=true platform_activation_unchanged=true "
                "v281_false_metadata_kept_in_denominator=true v281_periodic_v265_audit=true "
                "connectivity_fabricated=false position_fabricated=false cost_basis_fabricated=false "
                "kill_switch_writer_nonce_capital_risk_order_fill_gates_unchanged=true "
                "safety_gates_bypassed=false",
                MARKER, _maintenance_reaudit_s(), _contention_retry_s(),
            )
        else:
            LOGGER.error(
                "KRAKEN_USER_POSITION_ELIGIBILITY_V282_NOT_READY marker=%s reconcile=%s schedule=%s "
                "denominator=%s periodic=%s manifest=%s user_entries_fail_closed=true",
                MARKER, reconcile_ok, schedule_ok, denominator_ok, periodic_ok, manifest_ok,
            )
        return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER", "install", "install_import_hook", "_position_proof", "_busy_seq",
    "_set_position_block", "_clear_owned_position_block", "_patch_v86_reconcile",
    "_patch_v86_schedule", "_patch_v281_disabled_semantics", "_patch_v265_periodic_audit",
    "_audit_v281_from_v265", "_maintenance_reaudit_s", "_contention_retry_s",
]
