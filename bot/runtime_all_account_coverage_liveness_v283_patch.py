"""Keep all-account position/exit coverage current after runtime registry repair (v283).

Production on 2026-08-29 proved that v281 could correctly fail closed with
``registry_empty`` early in startup, then remain stale after v267 rebuilt the
canonical user registry and the broker fabric converged.  v282 attempted to
piggy-back the audit on v265's reassert function, but runtime evidence showed
that this indirect wrapper was not sufficient to guarantee a post-rehydration
v281 audit.

v283 gives the existing RuntimePostImportConvergence watchdog an explicit,
observational audit step.  Every convergence iteration calls v281 *after* the
registry/liveness repairs have run.  v283 performs no broker I/O, reconnect,
position fetch, balance fetch, tracker mutation, order, or activation action.
A v281 result of ``ready=False`` is a valid audit outcome and does not make the
v283 capability unready; only inability to run the audit itself does.

Safety contract
---------------
* Dynamic v281 coverage remains fail closed and independent from platform v99
  execution isolation.
* No connectivity, position, cost basis, protective-exit, capital, nonce,
  execution, order, acknowledgement, fill, or kill-switch truth is fabricated.
* Existing writer, nonce, risk, capital, broker-health, ECEL, minimum-notional,
  order and fill gates remain authoritative.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from collections.abc import Mapping
from typing import Any

LOGGER = logging.getLogger("nija.runtime_all_account_coverage_liveness_v283")
MARKER = "20260829-all-account-coverage-liveness-v283"
_READY_FLAG = "NIJA_ALL_ACCOUNT_COVERAGE_LIVENESS_V283_READY"
_LOCK = threading.RLock()
_LAST_LOG_SIGNATURE = ""


def audit_once() -> dict[str, Any]:
    """Run the authoritative observational v281 audit exactly once."""
    v281 = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
    audit = getattr(v281, "audit_once", None)
    if not callable(audit):
        raise RuntimeError("v281_audit_once_missing")
    result = audit()
    if not isinstance(result, dict):
        raise RuntimeError(f"v281_invalid_result:{type(result).__name__}")
    return result


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["all_account_coverage_liveness_v283"] = _READY_FLAG
        return True
    except Exception:
        return False


def _result_counts(result: Mapping[str, Any]) -> tuple[int, int]:
    expected = result.get("expected_accounts", ())
    pending = result.get("pending", {})
    try:
        expected_count = len(expected)
    except Exception:
        expected_count = 0
    try:
        pending_count = len(pending)
    except Exception:
        pending_count = 0
    return expected_count, pending_count


def install() -> bool:
    """Refresh v281 truth and report whether the audit capability is operational."""
    global _LAST_LOG_SIGNATURE
    with _LOCK:
        manifest_ok = _register_manifest()
        result: dict[str, Any] = {}
        audit_ok = False
        error = ""
        try:
            result = audit_once()
            audit_ok = True
        except Exception as exc:
            error = f"{type(exc).__name__}:{exc}"
            # Failure to observe current account coverage is itself fail closed.
            os.environ["NIJA_ALL_ACCOUNT_POSITION_EXIT_COVERAGE_READY"] = "0"

        ready = bool(manifest_ok and audit_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"

        expected_count, pending_count = _result_counts(result)
        coverage_ready = bool(result.get("ready")) if audit_ok else False
        signature = repr((ready, coverage_ready, expected_count, pending_count, error))
        if signature != _LAST_LOG_SIGNATURE:
            _LAST_LOG_SIGNATURE = signature
            log = LOGGER.critical if ready else LOGGER.error
            log(
                "ALL_ACCOUNT_COVERAGE_LIVENESS_V283_%s marker=%s ready=%s "
                "audit_operational=%s coverage_ready=%s expected=%d pending=%d "
                "manifest=%s error=%s broker_io=false reconnect=false position_fetch=false "
                "tracker_mutation=false platform_activation_unchanged=true "
                "user_execution_isolation_preserved=true readiness_fabricated=false "
                "position_success_fabricated=false cost_basis_fabricated=false "
                "writer_nonce_capital_risk_killswitch_order_fill_gates_unchanged=true "
                "safety_gates_bypassed=false",
                "READY" if ready else "NOT_READY",
                MARKER,
                str(ready).lower(),
                str(audit_ok).lower(),
                str(coverage_ready).lower(),
                expected_count,
                pending_count,
                str(manifest_ok).lower(),
                error or "none",
            )
        return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "audit_once",
    "install",
    "install_import_hook",
    "_register_manifest",
    "_result_counts",
]
