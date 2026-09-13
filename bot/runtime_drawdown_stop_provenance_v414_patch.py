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

It never changes drawdown thresholds, fabricates balances/positions/prices,
forces LIVE_ACTIVE, grants execution authority, or submits/cancels orders.
"""
from __future__ import annotations

import importlib
import logging
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


def _install_v409_guarded_recovery() -> bool:
    v409 = importlib.import_module("bot.runtime_drawdown_portfolio_equity_v409_patch")
    current = getattr(v409, "_recover_exact_false_drawdown_stop", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    def recover_v414() -> bool:
        try:
            drawdown = importlib.import_module("bot.global_drawdown_circuit_breaker")
            getter = getattr(drawdown, "get_global_drawdown_cb", None)
            cb = getter() if callable(getter) else None
            if cb is None:
                return False

            raw = _float(getattr(cb, "_current_equity", 0.0))
            matches, _ca_total = v409._capital_authority_matches(raw)
            if not matches:
                return False
            proof_ready, holding_value, symbols, proof_reason = v409._authoritative_coinbase_holding_value()
            if not proof_ready:
                LOGGER.critical(
                    "DRAWDOWN_V414_RECOVERY_BLOCKED marker=%s reason=current_portfolio_proof_missing detail=%s symbols=%s fail_closed=true",
                    MARKER, proof_reason, ",".join(symbols) or "none",
                )
                return False
            corrected = raw + max(0.0, _float(holding_value))
            if corrected <= 0.0:
                return False

            kill_module = importlib.import_module("bot.kill_switch")
            ks_getter = getattr(kill_module, "get_kill_switch", None)
            ks = ks_getter() if callable(ks_getter) else None
            if ks is None or not bool(ks.is_active()):
                return False
            status = dict(ks.get_status() or {})
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
            if halt_pct <= 0.0 or stopped_dd < halt_pct:
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
            ks.deactivate(
                "v414 original-stop baseline plus current authoritative portfolio equity proved prior GlobalDrawdownCircuitBreaker HALT false"
            )
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
    with _LOCK:
        try:
            v409 = importlib.import_module("bot.runtime_drawdown_portfolio_equity_v409_patch")
            if not _install_v409_guarded_recovery():
                os.environ[_READY_FLAG] = "0"
                return False
            installer = getattr(v409, "install", None)
            ready = bool(installer()) if callable(installer) else False
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
]
