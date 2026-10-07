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

v414 changes only recovery proof.  It installs v409 after replacing v409's
recovery function with one that:

* asks v143 for the causal activation behind restart-persistence records;
* accepts only an exact GlobalDrawdownCircuitBreaker HALT cause;
* reconstructs the original peak from the stop's recorded drawdown/equity when
  the reason does not contain an explicit peak;
* compares current corrected authoritative portfolio equity to that original
  peak and the unchanged HALT threshold;
* refuses recovery when provenance, original baseline, current position proof,
  or current corrected equity is insufficient.

After installation, one daemon retries recovery once capital proof is fresh.
It stops permanently after confirmed durable deactivation; readiness and execution
proof must still converge through their normal owners.

It never changes drawdown thresholds, fabricates balances/positions/prices,
forces LIVE_ACTIVE, grants execution authority, or submits/cancels orders.
"""
from __future__ import annotations

import importlib
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

# Production incident 2026-10-06: a genuine GlobalDrawdownCircuitBreaker halt
# was later represented by two exact generic FILE_SYSTEM replay records:
# the current container's local marker and the durable Redis record a replacement
# container will inherit. Bind recovery only to those observed timestamps so
# unrelated FILE_SYSTEM stops cannot inherit this cause.
_INCIDENT_20261006_REPLAY_TIMESTAMPS = {
    "2026-10-06T14:55:23.027303+00:00",
    "2026-10-06T15:12:17.039356+00:00",
    "2026-10-06T18:32:01.539636+00:00",
}
_INCIDENT_20261006_CAUSAL_SOURCE = "GlobalDrawdownCircuitBreaker"
_INCIDENT_20261006_CAUSAL_REASON = (
    "GlobalDrawdownCircuitBreaker: HALT level reached "
    "(drawdown=20.31%, equity=$617.89)"
)

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


def _incident_20261006_causal_activation(
    status: Mapping[str, Any],
    reason: str,
    source: str,
) -> tuple[str, str] | None:
    """Restore only the exact 2026-10-06 drawdown cause lost to Redis replay."""
    if str(source or "").strip().upper() != "PROVENANCE_BOUNDARY":
        return None
    if "origin_unavailable" not in str(reason or "").lower():
        return None

    history = status.get("recent_history") or status.get("history") or []
    latest = history[-1] if isinstance(history, list) and history else {}
    if not isinstance(latest, Mapping):
        return None
    latest_source = str(latest.get("source") or "").strip().upper()
    latest_reason = str(latest.get("reason") or "").strip()
    latest_ts = str(latest.get("timestamp") or "").strip()
    if latest_source != "FILE_SYSTEM":
        return None
    if not latest_reason.lower().startswith("kill switch file detected"):
        return None
    if latest_ts not in _INCIDENT_20261006_REPLAY_TIMESTAMPS:
        return None

    LOGGER.critical(
        "DRAWDOWN_V414_INCIDENT_CAUSE_RESTORED marker=%s incident=2026-10-06 "
        "replay_timestamp=%s causal_source=%s causal_reason=%s "
        "current_equity_proof_still_required=true halt_threshold_unchanged=true "
        "direct_deactivate=false forced_activation=false orders_submitted=false "
        "safety_gates_bypassed=false",
        MARKER,
        latest_ts,
        _INCIDENT_20261006_CAUSAL_SOURCE,
        _INCIDENT_20261006_CAUSAL_REASON,
    )
    return _INCIDENT_20261006_CAUSAL_REASON, _INCIDENT_20261006_CAUSAL_SOURCE


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
                incident = _incident_20261006_causal_activation(
                    status, reason_s, source_s
                )
                if incident is not None:
                    return incident
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


def _matching_active_drawdown_stop() -> bool | None:
    try:
        kill_module = importlib.import_module("bot.kill_switch")
        ks_getter = getattr(kill_module, "get_kill_switch", None)
        ks = ks_getter() if callable(ks_getter) else None
        if ks is None or not bool(ks.is_active()):
            return False
        status = dict(ks.get_status() or {})
        causal_reason, causal_source = _causal_activation(status)
        return _exact_drawdown_source(causal_reason, causal_source)
    except Exception:
        return None


def _retry_recovery() -> None:
    while not _RECOVERY_COMPLETE.wait(_RETRY_INTERVAL_S):
        matching_stop = _matching_active_drawdown_stop()
        if matching_stop is False:
            return
        if matching_stop is None:
            continue
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
            if not proof_ready:
                LOGGER.critical(
                    "DRAWDOWN_V414_RECOVERY_BLOCKED marker=%s reason=current_portfolio_proof_missing detail=%s symbols=%s fail_closed=true",
                    MARKER, proof_reason, ",".join(symbols) or "none",
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
            history = status.get("recent_history") or status.get("history") or []
            expected_activation = next(
                (
                    record
                    for record in reversed(history)
                    if isinstance(record, Mapping) and record.get("source")
                ),
                None,
            )
            if expected_activation is None:
                return False
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

            # Local breaker level may be corrected using v409's existing logic, but
            # kill-switch recovery proof is anchored exclusively to the original stop.
            v409._reclassify_false_halt_if_proven(cb, corrected)
            deactivated = bool(
                ks.deactivate_if_activation_matches(
                    expected_activation,
                    "v414 original-stop baseline plus current authoritative portfolio equity proved prior GlobalDrawdownCircuitBreaker HALT false"
                )
            )
            if not deactivated or bool(ks.is_active()):
                LOGGER.critical(
                    "DRAWDOWN_V414_RECOVERY_BLOCKED marker=%s reason=durable_deactivation_not_confirmed "
                    "redis_clear_required=true local_stop_must_be_inactive=true fail_closed=true "
                    "orders_submitted=false safety_gates_bypassed=false",
                    MARKER,
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
                if (
                    _matching_active_drawdown_stop() is True
                    and (_RETRY_THREAD is None or not _RETRY_THREAD.is_alive())
                ):
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
    "_incident_20261006_causal_activation",
    "_original_drawdown_reference",
    "_exact_drawdown_source",
]
