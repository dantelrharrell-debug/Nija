"""Persisted drawdown-stop provenance and original-baseline recovery guard (v414).

v409 correctly adds authoritative Coinbase holdings to cash-like CapitalAuthority
before evaluating global drawdown.  Its kill-switch recovery path, however, used
only ``recent_history[-1]`` and the breaker's in-process peak.  Two production
facts make that unsafe/incomplete across restarts:

* restart persistence appends ``FILE_SYSTEM / Kill switch file detected`` records,
  hiding the original ``GlobalDrawdownCircuitBreaker`` activation from v409;
* a new process can initialise the drawdown breaker from today's already-reduced
  equity, so its new in-process peak must never be used to prove an older stop
  false.

v414 replaces v409's recovery function with one that:

* migrates only the active schema-v1 Oct-6 FILE_SYSTEM replay, with an atomic
  Redis compare-and-set that preserves its audit record and adds immutable origin
  identity;
* requires an explicit operator gate before any normal KillSwitch.deactivate();
* accepts only an exact GlobalDrawdownCircuitBreaker HALT cause;
* reconstructs the original peak from the stop's recorded drawdown/equity when
  the reason does not contain an explicit peak;
* compares fresh current authoritative portfolio equity to that original peak and
  the unchanged HALT threshold;
* refuses recovery when provenance, original baseline, current position proof,
  or current corrected equity is insufficient.

After installation, one daemon retries recovery as capital proof becomes fresh.
Without the operator gate it may annotate the exact legacy incident but leaves
the stop active. It stops permanently only after confirmed durable deactivation;
readiness and execution proof must still converge through their normal owners.

It never changes drawdown thresholds, fabricates balances/positions/prices,
forces LIVE_ACTIVE, grants execution authority, or submits/cancels orders.
"""
from __future__ import annotations

import importlib
import hashlib
import json
import logging
import math
import os
import re
import threading
from collections.abc import Mapping
from typing import Any

LOGGER = logging.getLogger("nija.runtime_drawdown_stop_provenance_v414")
MARKER = "20260913-runtime-drawdown-stop-provenance-v414"
_READY_FLAG = "NIJA_RUNTIME_DRAWDOWN_STOP_PROVENANCE_V414_READY"
_PATCH_ATTR = "_nija_drawdown_stop_provenance_v414"
_LOCK = threading.RLock()
_RETRY_THREAD: threading.Thread | None = None
_RECOVERY_COMPLETE = threading.Event()
_RETRY_INTERVAL_S = 5.0
_RECOVERY_OPERATOR_GATE = "NIJA_ALLOW_PROVEN_LEGACY_STOP_RECOVERY"
_LEGACY_MIGRATION_MARKER = "20261007-legacy-oct6-stop-v1-migration"

# Production incident 2026-10-06: a genuine GlobalDrawdownCircuitBreaker halt
# was later represented by two exact generic FILE_SYSTEM replay records:
# the current container's local marker and the durable Redis record a replacement
# container will inherit. Bind recovery only to those observed timestamps so
# unrelated FILE_SYSTEM stops cannot inherit this cause.
_INCIDENT_20261006_REPLAY_TIMESTAMPS = {
    "2026-10-06T14:55:23.027303+00:00",
    "2026-10-06T15:12:17.039356+00:00",
    "2026-10-06T18:32:01.539636+00:00",
    "2026-10-07T00:39:22.506451+00:00",
}
_INCIDENT_20261006_CAUSAL_SOURCE = "GlobalDrawdownCircuitBreaker"
_INCIDENT_20261006_CAUSAL_REASON = (
    "GlobalDrawdownCircuitBreaker: HALT level reached "
    "(drawdown=20.31%, equity=$617.89)"
)
_INCIDENT_20261006_ID = hashlib.sha256(
    f"2026-10-06|{_INCIDENT_20261006_CAUSAL_SOURCE}|{_INCIDENT_20261006_CAUSAL_REASON}".encode("utf-8")
).hexdigest()[:24]

_DRAW_EQUITY_RE = re.compile(
    r"drawdown\s*=\s*([0-9]+(?:\.[0-9]+)?)%.*?"
    r"equity\s*=\s*\$?([0-9][0-9,]*(?:\.[0-9]+)?)"
    r"(?:.*?peak\s*=\s*\$?([0-9][0-9,]*(?:\.[0-9]+)?))?",
    re.IGNORECASE,
)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return default if number != number else number
    except Exception:
        return default


def _recent_activation(status: Mapping[str, Any]) -> tuple[str, str]:
    history = status.get("recent_history") or status.get("history") or []
    last = history[-1] if isinstance(history, list) and history else {}
    if isinstance(last, Mapping):
        return str(last.get("reason") or ""), str(last.get("source") or "")
    return str(last or ""), ""


def _causal_activation(status: Mapping[str, Any]) -> tuple[str, str]:
    """Return the original activation behind restart persistence, or fail closed."""
    try:
        v143 = importlib.import_module("bot.kill_switch_persistence_provenance_v143_patch")
        reader = getattr(v143, "_causal_activation_from_status", None)
        if callable(reader):
            reason, source = reader(dict(status))
            reason_s = str(reason or "")
            source_s = str(source or "")
            if source_s and source_s.upper() != "FILE_SYSTEM":
                return reason_s, source_s
    except Exception:
        pass
    return _recent_activation(status)


def _original_drawdown_reference(reason: str) -> tuple[bool, float, float, float, str]:
    """Return (ok, drawdown_pct, stopped_equity, original_peak, detail)."""
    text = str(reason or "")
    match = _DRAW_EQUITY_RE.search(text)
    if not match:
        return False, 0.0, 0.0, 0.0, "drawdown_equity_not_parseable"
    drawdown_pct = _float(match.group(1))
    stopped_equity = _float(str(match.group(2) or "").replace(",", ""))
    explicit_peak = _float(str(match.group(3) or "").replace(",", ""))
    if not (0.0 < drawdown_pct < 100.0) or stopped_equity <= 0.0:
        return False, drawdown_pct, stopped_equity, 0.0, "drawdown_reference_invalid"
    original_peak = explicit_peak
    if original_peak <= 0.0:
        original_peak = stopped_equity / (1.0 - (drawdown_pct / 100.0))
    if original_peak <= stopped_equity:
        return False, drawdown_pct, stopped_equity, original_peak, "original_peak_invalid"
    return True, drawdown_pct, stopped_equity, original_peak, (
        "explicit_peak" if explicit_peak > 0.0 else "derived_peak_from_stop"
    )


def _exact_drawdown_source(reason: str, source: str) -> bool:
    reason_l = str(reason or "").lower()
    source_l = str(source or "").lower().replace("_", "").replace("-", "").replace(" ", "")
    return (
        "globaldrawdowncircuitbreaker" in reason_l
        and "halt" in reason_l
        and "drawdown=" in reason_l.replace(" ", "")
        and "globaldrawdowncircuitbreaker" in source_l
    )


def _capital_proof_current() -> bool:
    try:
        ca = importlib.import_module("bot.capital_authority").get_capital_authority()
        return ca.is_fresh() is True
    except Exception:
        return False


def _fresh_authoritative_position_proof(v409: Any) -> tuple[bool, str, float, int]:
    """Require the canonical broker snapshot's bounded v285 freshness proof."""
    try:
        manager_getter = getattr(v409, "_canonical_manager", None)
        broker_getter = getattr(v409, "_platform_coinbase", None)
        manager = manager_getter() if callable(manager_getter) else None
        broker = broker_getter(manager) if callable(broker_getter) else None
        v285 = importlib.import_module("bot.runtime_authoritative_position_coverage_v285_patch")
        snapshot_status = getattr(v285, "_snapshot_status", None)
        if broker is None or not callable(snapshot_status):
            return False, "authoritative_snapshot_checker_unavailable", float("inf"), 0
        ok, detail, _rows, age, generation = snapshot_status(broker)
        return bool(ok), str(detail or ""), _float(age, float("inf")), int(generation or 0)
    except Exception as exc:
        return False, f"authoritative_snapshot_check_failed:{type(exc).__name__}", float("inf"), 0


def _history_has_operator_boundary(ks: Any) -> bool:
    """Fail closed when retained local audit history contains operator activity."""
    try:
        lock = getattr(ks, "_lock", None)
        if lock is not None:
            with lock:
                history = list(getattr(ks, "_activation_history", ()) or ())
        else:
            history = list(getattr(ks, "_activation_history", ()) or ())
    except Exception:
        return True

    operator_sources = {"MANUAL", "OPERATOR", "UI", "CLI"}
    for item in history:
        if not isinstance(item, Mapping):
            return True
        source = str(item.get("source") or "").strip().upper()
        if source in operator_sources:
            return True
        if not source and str(item.get("reason") or "").strip():
            return True
    return False


def _redis_record(ks: Any) -> tuple[Any, str, dict[str, Any]] | None:
    try:
        client_getter = getattr(ks, "_redis_client", None)
        client = client_getter() if callable(client_getter) else None
        key = str(getattr(ks, "DURABLE_REDIS_KEY", "") or "")
        raw = client.get(key) if client is not None and key else None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        if not isinstance(raw, str) or not raw:
            return None
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return None
        return client, raw, payload
    except Exception:
        return None


def _is_legacy_oct6_replay(payload: Mapping[str, Any]) -> bool:
    return (
        payload.get("is_active") is True
        and type(payload.get("schema")) is int
        and payload.get("schema") == 1
        and str(payload.get("source") or "").strip().upper() == "FILE_SYSTEM"
        and str(payload.get("reason") or "").strip().lower() == "kill switch file detected"
        and str(payload.get("timestamp") or "").strip() in _INCIDENT_20261006_REPLAY_TIMESTAMPS
        and not any(
            payload.get(key)
            for key in ("origin_source", "origin_reason", "origin_timestamp", "incident_id")
        )
    )


def _annotate_legacy_oct6_stop(
    ks: Any,
    record: tuple[Any, str, dict[str, Any]],
    status: Mapping[str, Any],
    *,
    original_peak: float,
    corrected_equity: float,
    original_reference_dd: float,
    halt_pct: float,
    snapshot_age: float,
    snapshot_generation: int,
) -> dict[str, Any] | None:
    """Atomically add immutable Oct-6 origin identity without clearing the stop."""
    client, raw, payload = record
    if not _is_legacy_oct6_replay(payload) or _history_has_operator_boundary(ks):
        return None

    history = status.get("recent_history") or status.get("history") or ()
    latest = history[-1] if isinstance(history, (list, tuple)) and history else None
    if not isinstance(latest, Mapping):
        return None
    latest_timestamp = str(latest.get("timestamp") or "").strip()
    if (
        str(latest.get("source") or "").strip().upper() != "FILE_SYSTEM"
        or str(latest.get("reason") or "").strip().lower() != "kill switch file detected"
        or latest_timestamp not in _INCIDENT_20261006_REPLAY_TIMESTAMPS
    ):
        return None

    key = str(getattr(ks, "DURABLE_REDIS_KEY", "") or "")
    annotated = dict(payload)
    annotated.update(
        {
            "origin_source": _INCIDENT_20261006_CAUSAL_SOURCE,
            "origin_reason": _INCIDENT_20261006_CAUSAL_REASON,
            "origin_timestamp": str(payload.get("timestamp") or ""),
            "incident_id": _INCIDENT_20261006_ID,
            "schema": 2,
        }
    )
    encoded = json.dumps(annotated, sort_keys=True)
    script = """
local current = redis.call('GET', KEYS[1])
if current ~= ARGV[1] then
  return 0
end
redis.call('SET', KEYS[1], ARGV[2])
return 1
"""
    try:
        result = client.eval(script, 1, key, raw, encoded)
        if int(result or 0) != 1:
            return None
        verified_raw = client.get(key)
        if isinstance(verified_raw, bytes):
            verified_raw = verified_raw.decode("utf-8")
        verified = json.loads(verified_raw) if verified_raw else {}
        if (
            not isinstance(verified, dict)
            or verified != annotated
            or verified.get("is_active") is not True
            or verified.get("incident_id") != _INCIDENT_20261006_ID
            or verified.get("origin_source") != _INCIDENT_20261006_CAUSAL_SOURCE
            or verified.get("origin_reason") != _INCIDENT_20261006_CAUSAL_REASON
        ):
            return None
    except Exception:
        return None

    LOGGER.critical(
        "LEGACY_KILL_SWITCH_V1_MIGRATION_APPLIED marker=%s incident_id=%s "
        "origin_source=%s original_peak=%.8f corrected_equity=%.8f "
        "original_reference_drawdown_pct=%.6f halt_pct=%.6f snapshot_age_s=%.3f "
        "snapshot_generation=%d redis_cas=true active_stop_preserved=true "
        "audit_history_preserved=true orders_submitted=false safety_gates_bypassed=false",
        _LEGACY_MIGRATION_MARKER,
        _INCIDENT_20261006_ID,
        _INCIDENT_20261006_CAUSAL_SOURCE,
        original_peak,
        corrected_equity,
        original_reference_dd,
        halt_pct,
        snapshot_age,
        snapshot_generation,
    )
    return verified


def _is_migrated_oct6_stop(payload: Mapping[str, Any]) -> bool:
    return (
        payload.get("is_active") is True
        and int(payload.get("schema") or 0) >= 2
        and str(payload.get("source") or "").strip().upper() == "FILE_SYSTEM"
        and str(payload.get("reason") or "").strip().lower() == "kill switch file detected"
        and str(payload.get("timestamp") or "").strip() in _INCIDENT_20261006_REPLAY_TIMESTAMPS
        and payload.get("origin_source") == _INCIDENT_20261006_CAUSAL_SOURCE
        and payload.get("origin_reason") == _INCIDENT_20261006_CAUSAL_REASON
        and payload.get("origin_timestamp") == payload.get("timestamp")
        and payload.get("incident_id") == _INCIDENT_20261006_ID
    )


def _retry_recovery() -> None:
    while not _RECOVERY_COMPLETE.wait(_RETRY_INTERVAL_S):
        if not _capital_proof_current():
            continue
        try:
            v409 = importlib.import_module("bot.runtime_drawdown_portfolio_equity_v409_patch")
            with v409._LOCK:
                if _RECOVERY_COMPLETE.is_set():
                    return
                if v409._recover_exact_false_drawdown_stop():
                    _RECOVERY_COMPLETE.set()
                    return
        except Exception:
            LOGGER.exception(
                "DRAWDOWN_V414_RETRY_ERROR marker=%s fail_closed=true execution_authority_unchanged=true",
                MARKER,
            )


def _install_v409_guarded_recovery() -> bool:
    v409 = importlib.import_module("bot.runtime_drawdown_portfolio_equity_v409_patch")
    current = getattr(v409, "_recover_exact_false_drawdown_stop", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    def recover_v414() -> bool:
        try:
            if _RECOVERY_COMPLETE.is_set() or not _capital_proof_current():
                return False
            drawdown = importlib.import_module("bot.global_drawdown_circuit_breaker")
            getter = getattr(drawdown, "get_global_drawdown_cb", None)
            cb = getter() if callable(getter) else None
            if cb is None:
                return False

            raw = _float(getattr(cb, "_current_equity", 0.0))
            matches, ca_total = v409._capital_authority_matches(raw)
            proof_ready, holding_value, symbols, proof_reason = v409._authoritative_coinbase_holding_value()
            snapshot_fresh, snapshot_detail, snapshot_age, snapshot_generation = (
                _fresh_authoritative_position_proof(v409)
            )
            if not proof_ready or not snapshot_fresh:
                LOGGER.critical(
                    "DRAWDOWN_V414_RECOVERY_BLOCKED marker=%s reason=current_portfolio_proof_missing "
                    "detail=%s snapshot_detail=%s symbols=%s fail_closed=true",
                    MARKER, proof_reason, snapshot_detail, ",".join(symbols) or "none",
                )
                return False
            holding_value = _float(holding_value)
            if not all(math.isfinite(value) for value in (raw, ca_total, holding_value)):
                return False
            if raw <= 0.0 or ca_total <= 0.0 or holding_value < 0.0:
                return False
            # v409.update_equity may already have included holdings in the breaker.
            # Value them exactly once, using the current CapitalAuthority series.
            corrected = ca_total + holding_value
            if not math.isfinite(corrected):
                return False
            if not matches and abs(raw - corrected) > max(1.0, ca_total * 0.02):
                return False

            kill_module = importlib.import_module("bot.kill_switch")
            ks_getter = getattr(kill_module, "get_kill_switch", None)
            ks = ks_getter() if callable(ks_getter) else None
            if ks is None or not bool(ks.is_active()):
                return False
            status = dict(ks.get_status() or {})
            durable = _redis_record(ks)
            if durable is None:
                return False
            _redis, _raw_record, durable_payload = durable
            if durable_payload.get("is_active") is not True:
                return False

            needs_legacy_migration = _is_legacy_oct6_replay(durable_payload)
            if needs_legacy_migration:
                causal_reason = _INCIDENT_20261006_CAUSAL_REASON
                causal_source = _INCIDENT_20261006_CAUSAL_SOURCE
            elif _is_migrated_oct6_stop(durable_payload):
                causal_reason = str(durable_payload.get("origin_reason") or "")
                causal_source = str(durable_payload.get("origin_source") or "")
            else:
                causal_reason, causal_source = _causal_activation(status)
            if not _exact_drawdown_source(causal_reason, causal_source):
                LOGGER.critical(
                    "DRAWDOWN_V414_RECOVERY_BLOCKED marker=%s reason=causal_source_not_exact source=%s causal_reason=%s fail_closed=true",
                    MARKER, causal_source or "missing", causal_reason or "missing",
                )
                return False

            ref_ok, stopped_dd, stopped_equity, original_peak, ref_detail = _original_drawdown_reference(causal_reason)
            if not ref_ok:
                LOGGER.critical(
                    "DRAWDOWN_V414_RECOVERY_BLOCKED marker=%s reason=original_baseline_unproven detail=%s causal_reason=%s fail_closed=true",
                    MARKER, ref_detail, causal_reason,
                )
                return False

            config = getattr(cb, "_config", None)
            halt_pct = _float(getattr(config, "halt_pct", 0.0))
            if not math.isfinite(halt_pct) or halt_pct <= 0.0 or stopped_dd < halt_pct:
                LOGGER.critical(
                    "DRAWDOWN_V414_RECOVERY_BLOCKED marker=%s reason=original_stop_not_halt stopped_drawdown_pct=%.6f halt_pct=%.6f fail_closed=true",
                    MARKER, stopped_dd, halt_pct,
                )
                return False

            original_reference_dd = max(0.0, (original_peak - corrected) / original_peak * 100.0)
            if original_reference_dd >= halt_pct:
                LOGGER.critical(
                    "DRAWDOWN_V414_RECOVERY_BLOCKED marker=%s reason=current_equity_still_below_original_halt_boundary "
                    "original_peak=%.8f stopped_equity=%.8f current_corrected_equity=%.8f original_reference_drawdown_pct=%.6f halt_pct=%.6f "
                    "current_process_peak_ignored=true fail_closed=true orders_submitted=false safety_gates_bypassed=false",
                    MARKER, original_peak, stopped_equity, corrected, original_reference_dd, halt_pct,
                )
                return False

            if needs_legacy_migration:
                durable_payload = _annotate_legacy_oct6_stop(
                    ks,
                    durable,
                    status,
                    original_peak=original_peak,
                    corrected_equity=corrected,
                    original_reference_dd=original_reference_dd,
                    halt_pct=halt_pct,
                    snapshot_age=snapshot_age,
                    snapshot_generation=snapshot_generation,
                ) or {}
                if not durable_payload:
                    LOGGER.critical(
                        "DRAWDOWN_V414_RECOVERY_BLOCKED marker=%s reason=legacy_incident_migration_failed "
                        "redis_cas_required=true fail_closed=true",
                        MARKER,
                    )
                    return False

            if os.environ.get(_RECOVERY_OPERATOR_GATE, "").strip() != "1":
                LOGGER.critical(
                    "DRAWDOWN_V414_RECOVERY_BLOCKED marker=%s reason=operator_gate_required "
                    "operator_gate=%s required_value=1 stop_remains_active=true readiness_unchanged=true "
                    "orders_submitted=false safety_gates_bypassed=false",
                    MARKER,
                    _RECOVERY_OPERATOR_GATE,
                )
                return False

            # Local breaker level may be corrected using v409's existing logic, but
            # kill-switch recovery proof is anchored exclusively to the original stop.
            v409._reclassify_false_halt_if_proven(cb, corrected)
            deactivated = ks.deactivate(
                "v414 operator-authorized original-stop baseline plus current authoritative portfolio equity proof"
            )
            durable_after = _redis_record(ks)
            durable_inactive = bool(
                durable_after is not None
                and durable_after[2].get("is_active") is False
                and durable_after[2].get("incident_id") == durable_payload.get("incident_id")
            )
            if deactivated is not True or bool(ks.is_active()) or not durable_inactive:
                LOGGER.critical(
                    "DRAWDOWN_V414_RECOVERY_BLOCKED marker=%s reason=durable_deactivation_not_confirmed "
                    "redis_clear_required=true local_stop_must_be_inactive=true redis_inactive_confirmed=%s fail_closed=true "
                    "orders_submitted=false safety_gates_bypassed=false",
                    MARKER,
                    str(durable_inactive).lower(),
                )
                return False
            _RECOVERY_COMPLETE.set()
            LOGGER.critical(
                "DRAWDOWN_V414_FALSE_KILL_SWITCH_CLEARED marker=%s source=%s original_peak=%.8f stopped_equity=%.8f "
                "current_corrected_equity=%.8f original_reference_drawdown_pct=%.6f halt_pct=%.6f baseline_detail=%s "
                "current_process_peak_ignored=true exact_drawdown_source_required=true force_activation=false readiness_bypass=false "
                "threshold_unchanged=true orders_submitted=false safety_gates_bypassed=false",
                MARKER, causal_source, original_peak, stopped_equity, corrected,
                original_reference_dd, halt_pct, ref_detail,
            )
            return True
        except Exception:
            LOGGER.exception(
                "DRAWDOWN_V414_RECOVERY_ERROR marker=%s fail_closed=true force_activation=false safety_gates_bypassed=false",
                MARKER,
            )
            return False

    setattr(recover_v414, _PATCH_ATTR, True)
    setattr(recover_v414, "__wrapped__", current)
    v409._recover_exact_false_drawdown_stop = recover_v414
    return True


def install() -> bool:
    global _RETRY_THREAD
    with _LOCK:
        try:
            v409 = importlib.import_module("bot.runtime_drawdown_portfolio_equity_v409_patch")
            if not _install_v409_guarded_recovery():
                os.environ[_READY_FLAG] = "0"
                return False
            installer = getattr(v409, "install", None)
            ready = bool(installer()) if callable(installer) else False
            if ready and not _RECOVERY_COMPLETE.is_set():
                if _RETRY_THREAD is None or not _RETRY_THREAD.is_alive():
                    _RETRY_THREAD = threading.Thread(
                        target=_retry_recovery, name="DrawdownRecoveryV414", daemon=True,
                    )
                    _RETRY_THREAD.start()
            os.environ[_READY_FLAG] = "1" if ready else "0"
            LOGGER.critical(
                "RUNTIME_DRAWDOWN_STOP_PROVENANCE_V414_%s marker=%s v409_installed=%s v143_causal_provenance_required=true "
                "original_stop_peak_required=true current_process_peak_ignored_for_recovery=true thresholds_unchanged=true "
                "force_activation=false orders_submitted=false safety_gates_bypassed=false",
                "READY" if ready else "PENDING", MARKER, str(ready).lower(),
            )
            return ready
        except Exception:
            os.environ[_READY_FLAG] = "0"
            LOGGER.exception("RUNTIME_DRAWDOWN_STOP_PROVENANCE_V414_INSTALL_ERROR marker=%s fail_closed=true", MARKER)
            return False


install_import_hook = install

__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_causal_activation",
    "_original_drawdown_reference",
    "_exact_drawdown_source",
    "_is_legacy_oct6_replay",
    "_is_migrated_oct6_stop",
]
