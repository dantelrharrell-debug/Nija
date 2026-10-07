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
import importlib.util
import hashlib
import json
import logging
import math
import os
import re
import sys
import threading
import time
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
_RECOVERY_DIAGNOSTIC_LOCK = threading.RLock()
_RECOVERY_PHASE = "not_started"
_RECOVERY_PHASE_STARTED_AT = 0.0
_RECOVERY_PHASE_DETAILS: dict[str, str] = {}
_RECOVERY_PHASE_SIGNATURES: dict[str, tuple[Any, ...]] = {}
_RECOVERY_MONITOR_THREAD: threading.Thread | None = None

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


def _module_alias_identity(names: tuple[str, ...]) -> str:
    modules = [
        sys.modules[name]
        for name in names
        if isinstance(sys.modules.get(name), type(sys))
    ]
    if not modules:
        return "not_loaded"
    if len(modules) == 1:
        return "single_module"
    return "same_module" if len({id(module) for module in modules}) == 1 else "distinct_modules"


def _capital_provider_chain_diagnostics(details: dict[str, str]) -> None:
    root_name = "preactivation_readiness_convergence_v16_patch"
    package_name = "bot.preactivation_readiness_convergence_v16_patch"
    details["v16_alias_identity"] = _module_alias_identity((root_name, package_name))
    v16_name = root_name if isinstance(sys.modules.get(root_name), type(sys)) else package_name
    v16 = sys.modules.get(v16_name)
    if not isinstance(v16, type(sys)):
        details["v16_reader_module"] = "not_loaded"
        details["v358_reader_module"] = "not_loaded"
        details["v358_collector"] = "not_loaded"
        return
    details["v16_reader_module"] = v16_name
    details["v358_reader_module"] = v16_name
    v358 = sys.modules.get("bot.runtime_capital_readiness_mode_decoupling_v358_patch")
    collector = getattr(v16, "_collect_proofs", None)
    details["v358_collector"] = (
        "installed" if bool(getattr(collector, "_nija_v358_capital_mode_decoupled", False))
        else "unavailable" if v358 is not None
        else "not_loaded"
    )


def _proof_rejection_category(proof: Mapping[str, Any]) -> str:
    try:
        hydrated = bool(proof.get("hydrated", False))
        stale = bool(proof.get("stale", True))
        real = float(proof.get("real", 0.0) or 0.0)
        registered = int(float(proof.get("registered", 0) or 0))
    except (TypeError, ValueError, OverflowError):
        return "proof_fields_invalid"
    if not hydrated:
        return "hydrated"
    if stale:
        return "stale"
    if real <= 0.0:
        return "real"
    if registered <= 0:
        return "registered"
    return "provider_acceptance"


def _reason_category(reason: Any) -> str:
    text = str(reason or "").strip()
    category = text.split(":", 1)[0].split(" ", 1)[0]
    return re.sub(r"[^A-Za-z0-9_.-]", "_", category)[:64] or "unknown"


def _capital_proof_snapshot() -> tuple[bool, float, dict[str, str]]:
    """Return acceptance, current canonical capital, and non-sensitive diagnostics."""
    provider_name = "bot.readiness_proof_convergence_v134_patch"
    details: dict[str, str] = {
        "proof_provider": provider_name,
        "proof_provider_identity": "unavailable",
        "v16_alias_identity": "not_loaded",
        "v16_reader_module": "not_loaded",
        "v358_reader_module": "not_loaded",
        "v358_collector": "not_loaded",
        "proof_rejection": "provider_unavailable",
        "proof_exception": "none",
    }

    try:
        v134 = importlib.import_module(provider_name)
    except ModuleNotFoundError as exc:
        if exc.name != provider_name:
            details.update(proof_rejection="provider_import", proof_exception=type(exc).__name__)
            return False, 0.0, details
        try:
            if importlib.util.find_spec(exc.name) is not None:
                details.update(proof_rejection="provider_import", proof_exception=type(exc).__name__)
                return False, 0.0, details
        except Exception as spec_exc:
            details.update(proof_rejection="provider_import", proof_exception=type(spec_exc).__name__)
            return False, 0.0, details
        v134 = None
    except Exception as exc:
        details.update(proof_rejection="provider_import", proof_exception=type(exc).__name__)
        return False, 0.0, details

    if v134 is not None:
        provider_module_name = str(getattr(v134, "__name__", type(v134).__name__))
        details["proof_provider_identity"] = f"{provider_module_name}:{id(v134):x}"
        reader = getattr(v134, "_current_capital_proof", None)
        accepted = getattr(v134, "_current_capital_accepted", None)
        if not callable(reader) or not callable(accepted):
            details.update(proof_rejection="reader_unavailable", proof_exception="none")
            return False, 0.0, details
        try:
            proof = reader()
        except Exception as exc:
            _capital_provider_chain_diagnostics(details)
            details.update(proof_rejection="reader_error", proof_exception=type(exc).__name__)
            return False, 0.0, details
        _capital_provider_chain_diagnostics(details)
        try:
            if not isinstance(proof, Mapping):
                details["proof_rejection"] = "proof_shape"
                return False, 0.0, details
            proof_dict = dict(proof)
            is_accepted = bool(accepted(proof_dict))
            proof_real = _float(proof_dict.get("real", 0.0))
            if not math.isfinite(proof_real) or proof_real <= 0.0:
                details["proof_rejection"] = "real"
                return False, 0.0, details
            details["proof_rejection"] = (
                "none" if is_accepted else _proof_rejection_category(proof_dict)
            )
            return is_accepted, proof_real if is_accepted else 0.0, details
        except Exception as exc:
            details.update(proof_rejection="reader_error", proof_exception=type(exc).__name__)
            return False, 0.0, details

    try:
        ca = importlib.import_module("bot.capital_authority").get_capital_authority()
        is_current = ca.is_fresh() is True
        current_real = _float(ca.get_real_capital()) if is_current else 0.0
        # Preserve the pre-existing optional-provider fallback contract: current
        # standalone freshness can satisfy _capital_proof_current(). Recovery
        # remains stricter because it separately requires canonical_capital > 0
        # before evaluating any durable stop.
        details.update(
            proof_provider="capital_authority_fallback",
            proof_provider_identity="canonical_provider_absent",
            proof_rejection="none" if is_current else "standalone_not_fresh",
        )
        return is_current, current_real if math.isfinite(current_real) else 0.0, details
    except Exception as exc:
        details.update(
            proof_provider="capital_authority_fallback",
            proof_provider_identity="canonical_provider_absent",
            proof_rejection="standalone_reader_error",
            proof_exception=type(exc).__name__,
        )
        return False, 0.0, details


def _capital_proof_diagnostic() -> tuple[bool, dict[str, str]]:
    """Return canonical capital acceptance and safe provider-identity diagnostics."""
    accepted, _current_real, details = _capital_proof_snapshot()
    return accepted, details


def _capital_proof_current() -> bool:
    """Use NIJA's canonical v134 current-capital proof when available."""
    return _capital_proof_snapshot()[0]

def _recovery_diagnostic(
    phase: str, *, log_transition: bool = True, **details: Any
) -> bool:
    """Log only recovery-state transitions, with no account payload or values."""
    global _RECOVERY_PHASE, _RECOVERY_PHASE_STARTED_AT
    global _RECOVERY_PHASE_DETAILS
    safe_details = {key: str(value) for key, value in sorted(details.items())}
    signature = (str(phase), tuple(safe_details.items()))
    with _RECOVERY_DIAGNOSTIC_LOCK:
        phase_signature = (str(phase), tuple(safe_details.items()))
        if (
            phase != _RECOVERY_PHASE
            or safe_details != _RECOVERY_PHASE_DETAILS
        ):
            _RECOVERY_PHASE = str(phase)
            _RECOVERY_PHASE_STARTED_AT = time.monotonic()
            _RECOVERY_PHASE_DETAILS = safe_details
        if not log_transition:
            return False
        if _RECOVERY_PHASE_SIGNATURES.get(str(phase)) == signature:
            return False
        _RECOVERY_PHASE_SIGNATURES[str(phase)] = phase_signature
    retry_thread = _RETRY_THREAD
    worker_alive = bool(
        retry_thread is not None and retry_thread.is_alive()
    ) or threading.current_thread().name == "DrawdownRecoveryV414"
    detail_text = " ".join(f"{key}={value}" for key, value in safe_details.items())
    LOGGER.critical(
        "DRAWDOWN_V414_RECOVERY_DIAGNOSTIC marker=%s worker_alive=%s phase=%s "
        "transition=true phase_age_s=0.0 %s",
        MARKER,
        str(worker_alive).lower(),
        phase,
        detail_text,
    )
    return True


def _recovery_diagnostic_monitor() -> None:
    """Report a stuck retry phase without polling the recovery predicates."""
    last_signature: tuple[Any, ...] | None = None
    stalled_after_s = max(10.0, _RETRY_INTERVAL_S * 2.0)
    while not _RECOVERY_COMPLETE.wait(1.0):
        retry_thread = _RETRY_THREAD
        worker_alive = bool(retry_thread is not None and retry_thread.is_alive())
        with _RECOVERY_DIAGNOSTIC_LOCK:
            phase = _RECOVERY_PHASE
            phase_started_at = _RECOVERY_PHASE_STARTED_AT
        phase_age = max(0.0, time.monotonic() - phase_started_at) if phase_started_at else 0.0
        waiting_phase = phase in {"worker_wait", "awaiting_capital_proof"}
        status = "stalled" if worker_alive and not waiting_phase and phase_age >= stalled_after_s else (
            "running" if worker_alive else "stopped"
        )
        signature = (worker_alive, status)
        if signature == last_signature:
            continue
        last_signature = signature
        LOGGER.critical(
            "DRAWDOWN_V414_RECOVERY_DIAGNOSTIC marker=%s worker_alive=%s "
            "phase=%s status=%s phase_age_s=%.1f",
            MARKER,
            str(worker_alive).lower(),
            phase,
            status,
            phase_age,
        )


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
    capital_wait_logged = False
    _recovery_diagnostic("worker_wait", status="retry_interval")
    while not _RECOVERY_COMPLETE.wait(_RETRY_INTERVAL_S):
        _recovery_diagnostic(
            "capital_proof_check", log_transition=False, status="checking"
        )
        capital_current, proof_details = _capital_proof_diagnostic()
        if not capital_current:
            if not capital_wait_logged:
                LOGGER.critical(
                    "DRAWDOWN_V414_RETRY_WAITING marker=%s "
                    "reason=canonical_capital_proof_not_current fail_closed=true "
                    "readiness_unchanged=true orders_submitted=false",
                    MARKER,
                )
                capital_wait_logged = True
            _recovery_diagnostic(
                "awaiting_capital_proof",
                status="rejected",
                **proof_details,
            )
            continue
        capital_wait_logged = False
        _recovery_diagnostic(
            "capital_proof_accepted",
            status="accepted",
            **proof_details,
        )
        try:
            _recovery_diagnostic(
                "v409_import", log_transition=False, status="loading"
            )
            v409 = importlib.import_module("bot.runtime_drawdown_portfolio_equity_v409_patch")
            lock = getattr(v409, "_LOCK", None)
            acquire = getattr(lock, "acquire", None)
            release = getattr(lock, "release", None)
            if not callable(acquire) or not callable(release):
                _recovery_diagnostic(
                    "installation_lock_unavailable",
                    status="rejected",
                    error_type="lock_api_unavailable",
                )
                continue
            if not acquire(blocking=False):
                _recovery_diagnostic(
                    "installation_lock_wait",
                    status="busy",
                    worker_liveness="alive",
                )
                continue
            try:
                if _RECOVERY_COMPLETE.is_set():
                    return
                _recovery_diagnostic(
                    "predicate_evaluation",
                    log_transition=False,
                    status="running",
                    proof_provider=proof_details.get("proof_provider", "unknown"),
                )
                recovered = v409._recover_exact_false_drawdown_stop()
                if recovered:
                    _RECOVERY_COMPLETE.set()
                    _recovery_diagnostic("durable_clear", status="confirmed")
                    _recovery_diagnostic("recovery_complete", status="confirmed")
                    return
                _recovery_diagnostic("predicate_result", status="rejected")
            finally:
                release()
        except Exception as exc:
            transition_logged = _recovery_diagnostic(
                "recovery_error",
                status="failed_closed",
                error_type=type(exc).__name__,
            )
            if transition_logged:
                LOGGER.critical(
                    "DRAWDOWN_V414_RETRY_ERROR marker=%s error_type=%s "
                    "fail_closed=true execution_authority_unchanged=true",
                    MARKER,
                    type(exc).__name__,
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
            _recovery_diagnostic(
                "predicate_evaluation", log_transition=False, status="running"
            )
            if _RECOVERY_COMPLETE.is_set():
                _recovery_diagnostic(
                    "predicate_rejection", rejection="recovery_already_complete"
                )
                return False
            capital_current, canonical_capital, capital_details = _capital_proof_snapshot()
            _recovery_diagnostic(
                "canonical_capital_proof",
                status="accepted" if capital_current else "rejected",
                **capital_details,
            )
            if not capital_current:
                return False
            drawdown = importlib.import_module("bot.global_drawdown_circuit_breaker")
            getter = getattr(drawdown, "get_global_drawdown_cb", None)
            cb = getter() if callable(getter) else None
            if cb is None:
                _recovery_diagnostic(
                    "predicate_rejection",
                    rejection="drawdown_breaker_unavailable",
                )
                return False

            raw_value = getattr(cb, "_current_equity", None)
            try:
                raw = float(raw_value)
            except (TypeError, ValueError, OverflowError):
                _recovery_diagnostic(
                    "predicate_rejection",
                    rejection="breaker_current_equity_invalid",
                )
                return False
            if not math.isfinite(raw) or raw < 0.0:
                _recovery_diagnostic(
                    "predicate_rejection",
                    rejection="breaker_current_equity_invalid",
                )
                return False

            matches, ca_total = v409._capital_authority_matches(raw)
            proof_ready, holding_value, symbols, proof_reason = v409._authoritative_coinbase_holding_value()
            snapshot_fresh, snapshot_detail, snapshot_age, snapshot_generation = (
                _fresh_authoritative_position_proof(v409)
            )
            position_transition_logged = _recovery_diagnostic(
                "authoritative_position_proof",
                status="accepted" if proof_ready and snapshot_fresh else "rejected",
                position_status=_reason_category(proof_reason),
                freshness_status=_reason_category(snapshot_detail),
            )
            if not proof_ready or not snapshot_fresh:
                if position_transition_logged:
                    LOGGER.critical(
                        "DRAWDOWN_V414_RECOVERY_BLOCKED marker=%s reason=current_portfolio_proof_missing "
                        "detail=%s snapshot_detail=%s symbols=%s fail_closed=true",
                        MARKER, proof_reason, snapshot_detail, ",".join(symbols) or "none",
                    )
                return False
            holding_value = _float(holding_value)
            if not all(
                math.isfinite(value)
                for value in (canonical_capital, ca_total, holding_value)
            ):
                _recovery_diagnostic(
                    "predicate_rejection",
                    rejection="current_portfolio_value_invalid",
                )
                return False
            if canonical_capital <= 0.0 or ca_total <= 0.0 or holding_value < 0.0:
                _recovery_diagnostic(
                    "predicate_rejection",
                    rejection="current_portfolio_value_invalid",
                )
                return False

            # v134's accepted current proof and CapitalAuthority must describe the
            # same bounded snapshot before a newly initialized breaker may rely on
            # canonical capital.  This closes the startup deadlock without
            # accepting a stale or contradictory process-local equity value.
            canonical_tolerance = max(1.0, ca_total * 0.02)
            if abs(ca_total - canonical_capital) > canonical_tolerance:
                _recovery_diagnostic(
                    "predicate_rejection",
                    rejection="capital_authority_snapshot_mismatch",
                )
                return False

            # v409.update_equity may already have included holdings in the breaker.
            # Value them exactly once, using the current CapitalAuthority series.
            corrected = ca_total + holding_value
            if not math.isfinite(corrected) or corrected <= 0.0:
                _recovery_diagnostic(
                    "predicate_rejection", rejection="corrected_equity_invalid"
                )
                return False

            breaker_initialised = getattr(cb, "_initialised", None)
            startup_zero = raw == 0.0 and breaker_initialised is False
            if startup_zero:
                _recovery_diagnostic(
                    "breaker_equity_reference",
                    status="canonical_current_proof",
                    breaker_initialized="false",
                    canonical_snapshot_match="true",
                )
            elif not matches and abs(raw - corrected) > max(1.0, ca_total * 0.02):
                _recovery_diagnostic(
                    "predicate_rejection",
                    rejection=(
                        "initialized_zero_equity_mismatch"
                        if raw == 0.0 and breaker_initialised is True
                        else "capital_series_mismatch"
                    ),
                )
                return False
            else:
                _recovery_diagnostic(
                    "breaker_equity_reference",
                    status="breaker_series_consistent",
                    breaker_initialized=(
                        "true" if breaker_initialised is True else "unknown"
                    ),
                    canonical_snapshot_match="true",
                )

            kill_module = importlib.import_module("bot.kill_switch")
            ks_getter = getattr(kill_module, "get_kill_switch", None)
            ks = ks_getter() if callable(ks_getter) else None
            if ks is None or not bool(ks.is_active()):
                _recovery_diagnostic(
                    "predicate_rejection", rejection="kill_switch_inactive_or_missing"
                )
                return False
            status = dict(ks.get_status() or {})
            durable = _redis_record(ks)
            if durable is None:
                provenance_transition_logged = _recovery_diagnostic(
                    "durable_incident",
                    status="unavailable",
                    incident_identity="not_proven",
                )
                return False
            _redis, _raw_record, durable_payload = durable
            if durable_payload.get("is_active") is not True:
                _recovery_diagnostic(
                    "durable_incident",
                    status="inactive",
                    incident_identity="not_proven",
                )
                return False

            needs_legacy_migration = _is_legacy_oct6_replay(durable_payload)
            migrated_incident_match = _is_migrated_oct6_stop(durable_payload)
            if needs_legacy_migration:
                causal_reason = _INCIDENT_20261006_CAUSAL_REASON
                causal_source = _INCIDENT_20261006_CAUSAL_SOURCE
            elif migrated_incident_match:
                causal_reason = str(durable_payload.get("origin_reason") or "")
                causal_source = str(durable_payload.get("origin_source") or "")
            else:
                causal_reason, causal_source = _causal_activation(status)
            provenance_match = _exact_drawdown_source(causal_reason, causal_source)
            provenance_transition_logged = _recovery_diagnostic(
                "durable_incident",
                status="provenance_matched" if provenance_match else "provenance_rejected",
                incident_identity=(
                    "exact_legacy_candidate"
                    if needs_legacy_migration
                    else "exact_migrated"
                    if migrated_incident_match
                    else "unmatched"
                ),
                incident_id_match=(
                    "exact" if migrated_incident_match else "not_established"
                ),
                provenance_match=str(provenance_match).lower(),
            )
            if not provenance_match:
                if provenance_transition_logged:
                    LOGGER.critical(
                        "DRAWDOWN_V414_RECOVERY_BLOCKED marker=%s "
                        "reason=causal_source_not_exact source_category=%s "
                        "causal_reason_category=%s fail_closed=true",
                        MARKER,
                        _reason_category(causal_source),
                        _reason_category(causal_reason),
                    )
                return False

            ref_ok, stopped_dd, stopped_equity, original_peak, ref_detail = _original_drawdown_reference(causal_reason)
            if not ref_ok:
                transition_logged = _recovery_diagnostic(
                    "original_stop_reference",
                    status="rejected",
                    rejection=_reason_category(ref_detail),
                )
                if transition_logged:
                    LOGGER.critical(
                        "DRAWDOWN_V414_RECOVERY_BLOCKED marker=%s "
                        "reason=original_baseline_unproven detail_category=%s "
                        "causal_reason_category=%s fail_closed=true",
                        MARKER, _reason_category(ref_detail), _reason_category(causal_reason),
                    )
                return False

            config = getattr(cb, "_config", None)
            halt_pct = _float(getattr(config, "halt_pct", 0.0))
            if not math.isfinite(halt_pct) or halt_pct <= 0.0 or stopped_dd < halt_pct:
                transition_logged = _recovery_diagnostic(
                    "original_stop_reference",
                    status="rejected",
                    rejection="original_stop_not_halt",
                )
                if transition_logged:
                    LOGGER.critical(
                        "DRAWDOWN_V414_RECOVERY_BLOCKED marker=%s "
                        "reason=original_stop_not_halt fail_closed=true",
                        MARKER,
                    )
                return False

            original_reference_dd = max(0.0, (original_peak - corrected) / original_peak * 100.0)
            if original_reference_dd >= halt_pct:
                transition_logged = _recovery_diagnostic(
                    "original_stop_reference",
                    status="rejected",
                    rejection="current_equity_below_original_boundary",
                )
                if transition_logged:
                    LOGGER.critical(
                        "DRAWDOWN_V414_RECOVERY_BLOCKED marker=%s "
                        "reason=current_equity_still_below_original_halt_boundary "
                        "current_process_peak_ignored=true fail_closed=true "
                        "orders_submitted=false safety_gates_bypassed=false",
                        MARKER,
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
                    transition_logged = _recovery_diagnostic(
                        "legacy_migration",
                        status="compare_and_set_rejected",
                        incident_identity="exact_legacy_candidate",
                    )
                    if transition_logged:
                        LOGGER.critical(
                            "DRAWDOWN_V414_RECOVERY_BLOCKED marker=%s reason=legacy_incident_migration_failed "
                            "redis_cas_required=true fail_closed=true",
                            MARKER,
                        )
                    return False

            operator_authorized = (
                os.environ.get(_RECOVERY_OPERATOR_GATE, "").strip() == "1"
            )
            operator_transition_logged = _recovery_diagnostic(
                "operator_gate",
                status="authorized" if operator_authorized else "required",
            )
            if not operator_authorized:
                if operator_transition_logged:
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
            durable_transition_logged = _recovery_diagnostic(
                "durable_clear",
                status="confirmed" if durable_inactive and deactivated is True else "not_confirmed",
                incident_id_match=(
                    "same"
                    if durable_after is not None
                    and durable_after[2].get("incident_id") == durable_payload.get("incident_id")
                    else "different_or_missing"
                ),
                local_deactivation=str(deactivated is True).lower(),
            )
            if deactivated is not True or bool(ks.is_active()) or not durable_inactive:
                if durable_transition_logged:
                    LOGGER.critical(
                        "DRAWDOWN_V414_RECOVERY_BLOCKED marker=%s reason=durable_deactivation_not_confirmed "
                        "redis_clear_required=true local_stop_must_be_inactive=true "
                        "redis_inactive_confirmed=%s fail_closed=true "
                        "orders_submitted=false safety_gates_bypassed=false",
                        MARKER,
                        str(durable_inactive).lower(),
                    )
                return False
            _RECOVERY_COMPLETE.set()
            _recovery_diagnostic("recovery_complete", status="durable_clear_confirmed")
            LOGGER.critical(
                "DRAWDOWN_V414_FALSE_KILL_SWITCH_CLEARED marker=%s source=%s original_peak=%.8f stopped_equity=%.8f "
                "current_corrected_equity=%.8f original_reference_drawdown_pct=%.6f halt_pct=%.6f baseline_detail=%s "
                "current_process_peak_ignored=true exact_drawdown_source_required=true force_activation=false readiness_bypass=false "
                "threshold_unchanged=true orders_submitted=false safety_gates_bypassed=false",
                MARKER, causal_source, original_peak, stopped_equity, corrected,
                original_reference_dd, halt_pct, ref_detail,
            )
            return True
        except Exception as exc:
            transition_logged = _recovery_diagnostic(
                "predicate_error",
                status="failed_closed",
                error_type=type(exc).__name__,
            )
            if transition_logged:
                LOGGER.critical(
                    "DRAWDOWN_V414_RECOVERY_ERROR marker=%s error_type=%s "
                    "fail_closed=true force_activation=false safety_gates_bypassed=false",
                    MARKER,
                    type(exc).__name__,
                )
            return False

    setattr(recover_v414, _PATCH_ATTR, True)
    setattr(recover_v414, "__wrapped__", current)
    v409._recover_exact_false_drawdown_stop = recover_v414
    return True


def install() -> bool:
    global _RETRY_THREAD, _RECOVERY_MONITOR_THREAD
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
                if (
                    _RECOVERY_MONITOR_THREAD is None
                    or not _RECOVERY_MONITOR_THREAD.is_alive()
                ):
                    _RECOVERY_MONITOR_THREAD = threading.Thread(
                        target=_recovery_diagnostic_monitor,
                        name="DrawdownRecoveryV414Diagnostics",
                        daemon=True,
                    )
                    _RECOVERY_MONITOR_THREAD.start()
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
