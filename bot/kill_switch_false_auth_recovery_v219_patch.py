"""Recover the exact legacy false-auth hard-stop signature (v219).

Before v218, ``failure_mode_manager.handle_api_failure`` matched the substring
``auth``.  An error such as ``execution authority not granted`` could therefore
be mislabeled INVALID_CREDENTIALS and routed to the global EMERGENCY_STOP path.

v219 repairs only that proven historical classifier defect.  It may deactivate a
stop only when all of the following are true:

* the causal activation source is exactly FAILURE_MODE_MANAGER;
* the causal reason starts with INVALID_CREDENTIALS:;
* the embedded error is an authority/readiness message;
* v218 proves the embedded error contains no real authentication/credential
  evidence;
* the exact writer lease is currently acquired, not lost, and renewal-healthy;
* all non-stop readiness proofs (broker, balance, capital, risk, strategy,
  bootstrap, position sync) are current.

Manual/UI/CLI, drawdown, balance-delta, portfolio-risk, API-instability, genuine
401/unauthorized/invalid-key/signature, malformed, and unknown stops are never
cleared.  v219 does not mark authority/nonce/execution ready; after the false stop
is removed those proofs must be earned normally before trading can activate.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from typing import Any

LOGGER = logging.getLogger("nija.kill_switch_false_auth_recovery_v219")
MARKER = "20260824-kill-switch-false-auth-recovery-v219"
_FLAG = "NIJA_KILL_SWITCH_FALSE_AUTH_RECOVERY_V219_READY"
_LOCK = threading.RLock()
_STARTED = False
_RECOVERED = False

_REQUIRED_STRUCTURAL = (
    "broker_connected",
    "balance_hydrated",
    "capital_ready",
    "risk_ready",
    "strategy_ready",
    "bootstrap_ready",
    "position_sync_ready",
)


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def _dependencies_ready() -> bool:
    return bool(
        _truthy("NIJA_KILL_SWITCH_TRANSACTIONAL_RECOVERY_V193_READY")
        and _truthy("NIJA_FAILURE_MODE_AUTH_CLASSIFICATION_V218_READY")
    )


def _causal_record(status: dict[str, Any]) -> dict[str, Any]:
    history = list(status.get("recent_history") or [])
    # get_status() is bounded to the latest five records. That is sufficient for
    # the normal restart-persistence chain, and v143/v193 owns deeper guarded
    # reconstruction when a verified recovery boundary is involved.
    try:
        v143 = importlib.import_module("bot.kill_switch_persistence_provenance_v143_patch")
        derive = getattr(v143, "_derive_persisted_cause", None)
        if callable(derive):
            result = derive(history)
            if isinstance(result, dict) and result.get("source") and result.get("reason"):
                return dict(result)
    except Exception:
        pass

    for item in reversed(history):
        if not isinstance(item, dict):
            return {}
        source = str(item.get("source") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if not source:
            # A deactivation/reset boundary makes earlier history non-causal.
            return {}
        if source.upper() == "FILE_SYSTEM" and "kill switch file detected" in reason.lower():
            continue
        return {"source": source, "reason": reason}
    return {}


def _false_auth_signature(record: dict[str, Any]) -> tuple[bool, str]:
    source = str(record.get("source") or "").strip().upper()
    reason = str(record.get("reason") or "").strip()
    prefix = "INVALID_CREDENTIALS:"
    if source != "FAILURE_MODE_MANAGER":
        return False, f"source_not_failure_manager:{source or 'missing'}"
    if not reason.upper().startswith(prefix):
        return False, "reason_not_invalid_credentials"

    embedded = reason[len(prefix):].strip()
    embedded_l = embedded.lower()
    authority_evidence = any(
        token in embedded_l
        for token in (
            "authority",
            "writer authority",
            "execution authority",
            "authority heartbeat",
            "runtime authority",
        )
    )
    if not authority_evidence:
        return False, "embedded_error_not_authority"

    try:
        v218 = importlib.import_module("bot.failure_mode_auth_classification_v218_patch")
        checker = getattr(v218, "_is_authentication_failure", None)
        if not callable(checker):
            return False, "v218_checker_missing"
        if bool(checker(embedded)):
            return False, "real_authentication_evidence_present"
    except Exception as exc:
        return False, f"v218_check_error:{type(exc).__name__}"

    return True, embedded[:512]


def _writer_healthy() -> tuple[bool, str]:
    try:
        module = importlib.import_module("bot.entrypoint_writer_authority")
        getter = getattr(module, "get_entrypoint_writer_authority", None)
        if not callable(getter):
            return False, "writer_getter_missing"
        runtime = getter()
        if runtime is None:
            return False, "writer_runtime_missing"
        if not bool(getattr(runtime, "acquired", False)):
            return False, "writer_not_acquired"
        lost = getattr(runtime, "lost", None)
        if callable(getattr(lost, "is_set", None)):
            if bool(lost.is_set()):
                return False, "writer_lost_event_set"
        elif bool(lost):
            return False, "writer_lost"
        health = getattr(runtime, "_nija_lease_renewal_health", None)
        if not callable(health):
            return False, "writer_renewal_health_missing"
        healthy, reason, age_s, max_age_s = health()
        if not bool(healthy):
            return False, f"writer_renewal_unhealthy:{reason}:age={age_s}:max={max_age_s}"

        core = getattr(runtime, "_core_thread", None)
        if core is None or not callable(getattr(core, "is_alive", None)) or not core.is_alive():
            return False, "core_thread_not_alive"
        if not bool(getattr(runtime, "_core_thread_registered", False)):
            return False, "core_thread_not_registered"
        return True, "exact_writer_and_core_healthy"
    except Exception as exc:
        return False, f"writer_probe_error:{type(exc).__name__}:{exc}"


def _structural_readiness() -> tuple[bool, str]:
    try:
        table = importlib.import_module("bot.readiness_table")
        snapshot = dict(table.snapshot() or {})
    except Exception as exc:
        return False, f"readiness_probe_error:{type(exc).__name__}:{exc}"

    missing = [name for name in _REQUIRED_STRUCTURAL if not bool(snapshot.get(name, False))]
    if missing:
        return False, "structural_pending:" + ",".join(missing)
    return True, "structural_nonstop_proofs_current"


def attempt_once() -> bool:
    global _RECOVERED
    if _RECOVERED or not _dependencies_ready():
        return False

    try:
        kill_module = importlib.import_module("bot.kill_switch")
        getter = getattr(kill_module, "get_kill_switch", None)
        ks = getter() if callable(getter) else None
        if ks is None or not callable(getattr(ks, "get_status", None)):
            return False
        status = dict(ks.get_status() or {})
        if not bool(status.get("is_active")):
            return False

        record = _causal_record(status)
        signature_ok, signature_detail = _false_auth_signature(record)
        if not signature_ok:
            LOGGER.info(
                "KILL_SWITCH_FALSE_AUTH_V219_INELIGIBLE marker=%s detail=%s "
                "active_preserved=true trading_fail_closed=true",
                MARKER,
                signature_detail,
            )
            return False

        writer_ok, writer_detail = _writer_healthy()
        if not writer_ok:
            LOGGER.warning(
                "KILL_SWITCH_FALSE_AUTH_V219_WAIT marker=%s blocker=%s "
                "active_preserved=true trading_fail_closed=true",
                MARKER,
                writer_detail,
            )
            return False

        structural_ok, structural_detail = _structural_readiness()
        if not structural_ok:
            LOGGER.warning(
                "KILL_SWITCH_FALSE_AUTH_V219_WAIT marker=%s blocker=%s "
                "active_preserved=true trading_fail_closed=true",
                MARKER,
                structural_detail,
            )
            return False

        deactivate = getattr(ks, "deactivate", None)
        if not callable(deactivate):
            return False
        result = deactivate(
            "v219 verified recovery from legacy authority-as-authentication false stop"
        )
        if result is False:
            LOGGER.critical(
                "KILL_SWITCH_FALSE_AUTH_V219_DEACTIVATE_REFUSED marker=%s "
                "transactional_guard_preserved=true trading_fail_closed=true",
                MARKER,
            )
            return False

        # Re-read canonical truth. Never assume a successful method call means
        # the stop disappeared; v193's marker-first guard remains authoritative.
        after = dict(ks.get_status() or {})
        if bool(after.get("is_active")) or bool(after.get("kill_file_exists")):
            LOGGER.critical(
                "KILL_SWITCH_FALSE_AUTH_V219_VERIFY_FAILED marker=%s "
                "active=%s marker_exists=%s trading_fail_closed=true",
                MARKER,
                str(bool(after.get("is_active"))).lower(),
                str(bool(after.get("kill_file_exists"))).lower(),
            )
            return False

        _RECOVERED = True
        LOGGER.critical(
            "KILL_SWITCH_FALSE_AUTH_V219_RECOVERED marker=%s causal_source=FAILURE_MODE_MANAGER "
            "legacy_false_classifier=true embedded_error=%s writer_proof=exact "
            "structural_proofs=current authority_nonce_execution_not_fabricated=true "
            "activation_must_reprove=true forced_activation=false safety_gates_bypassed=false",
            MARKER,
            signature_detail,
        )
        return True
    except Exception as exc:
        LOGGER.warning(
            "KILL_SWITCH_FALSE_AUTH_V219_ERROR marker=%s err=%s:%s "
            "active_preserved=true trading_fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False


def _worker() -> None:
    while not _dependencies_ready():
        time.sleep(1.0)
    os.environ[_FLAG] = "1"
    LOGGER.critical(
        "KILL_SWITCH_FALSE_AUTH_RECOVERY_V219_READY marker=%s ready=true "
        "exact_legacy_signature_only=true real_auth_stops_preserved=true "
        "manual_risk_unknown_stops_preserved=true authority_nonce_execution_not_fabricated=true "
        "forced_activation=false safety_gates_bypassed=false",
        MARKER,
    )
    # A bounded startup recovery window is enough for capital/position proofs to
    # settle. If the exact signature is not present, v219 simply exits without
    # touching the stop.
    deadline = time.monotonic() + 180.0
    while time.monotonic() < deadline:
        if attempt_once():
            return
        time.sleep(2.0)


def install() -> bool:
    global _STARTED
    with _LOCK:
        if _STARTED:
            return True
        _STARTED = True
        threading.Thread(
            target=_worker,
            name="KillSwitchFalseAuthRecoveryV219",
            daemon=True,
        ).start()
    return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "attempt_once",
    "_causal_record",
    "_false_auth_signature",
    "_writer_healthy",
    "_structural_readiness",
]
