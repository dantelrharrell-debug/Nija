"""Aggregate-capital guard and one-shot recovery for the 2026-08-09 false drawdown stop.

The process-global drawdown breaker must never compare broker-local balances. In
production, its equity input is replaced with a fresh, complete CapitalAuthority
aggregate. Missing/stale aggregate proof blocks new entries without activating
KillSwitch.

This release also contains an incident-scoped recovery for the already-active
2026-08-09 stop. Recovery is allowed only when the latest non-file activation in
the persisted KillSwitch history matches the proven false GlobalDrawdown incident
and a synchronous canonical capital refresh proves every registered platform
broker is ready and aggregate capital is fresh, complete, and positive. It uses
the canonical KillSwitch.deactivate() API and never sets execution authority or
LIVE_ACTIVE directly.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Optional

LOGGER = logging.getLogger("nija.global_drawdown_capital_authority_v91")
MARKER = "20260814-global-drawdown-capital-authority-v91"
INCIDENT_ID = "2026-08-09-gdcb-cross-broker-balance"
_FALSE_SOURCE = "GlobalDrawdownCircuitBreaker"
_FALSE_DATE = "2026-08-09"
_FALSE_REASON_TOKENS = ("HALT level reached", "drawdown=34.39%", "equity=$95.12")
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_LOCK = threading.RLock()
_PATCHED = False
_RECOVERY_THREAD_STARTED = False
_RECOVERY_DONE = False
_RECOVERY_LAST_ATTEMPT = 0.0
_LAST_BLOCK_LOG = 0.0


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUE


def _production_runtime() -> bool:
    """Return True for deployed, non-paper runtimes.

    Deployment SHA presence is intentionally enough: recovery happens while the
    canonical runtime state is EMERGENCY_STOP/OFF, before LIVE_ACTIVE can exist.
    """
    if _truthy("DRY_RUN_MODE") or _truthy("PAPER_MODE"):
        return False
    if _truthy("NIJA_V91_FORCE_PRODUCTION"):
        return True
    for name in (
        "RAILWAY_GIT_COMMIT_SHA",
        "GIT_COMMIT_SHA",
        "SOURCE_VERSION",
        "RENDER_GIT_COMMIT",
        "HEROKU_SLUG_COMMIT",
    ):
        if str(os.environ.get(name, "") or "").strip():
            return True
    return _truthy("LIVE_CAPITAL_VERIFIED")


def _capital_ttl_s() -> float:
    try:
        return max(10.0, float(os.environ.get("NIJA_GLOBAL_DRAWDOWN_CAPITAL_TTL_S", "60") or 60))
    except Exception:
        return 60.0


def _authoritative_aggregate_equity() -> tuple[Optional[float], str]:
    """Return fresh complete aggregate real capital or a fail-closed reason."""
    try:
        from bot.capital_authority import get_capital_authority

        authority = get_capital_authority()
        hydrated = bool(getattr(authority, "is_hydrated", False))
        complete_probe = getattr(authority, "is_brokers_complete", None)
        fresh_probe = getattr(authority, "is_fresh", None)
        equity_probe = getattr(authority, "get_real_capital", None)
        complete = bool(complete_probe()) if callable(complete_probe) else False
        ttl_s = _capital_ttl_s()
        fresh = bool(fresh_probe(ttl_s=ttl_s)) if callable(fresh_probe) else False
        equity = float(equity_probe()) if callable(equity_probe) else 0.0
        detail = (
            f"hydrated={hydrated};complete={complete};fresh={fresh};"
            f"ttl_s={ttl_s:.1f};aggregate=${equity:.8f}"
        )
        if hydrated and complete and fresh and equity > 0.0:
            return equity, detail
        return None, detail
    except Exception as exc:
        return None, f"capital_authority_error={type(exc).__name__}:{exc}"


def _log_fail_closed(local_balance: float, detail: str) -> None:
    global _LAST_BLOCK_LOG
    now = time.monotonic()
    with _LOCK:
        if now - _LAST_BLOCK_LOG < 30.0:
            return
        _LAST_BLOCK_LOG = now
    LOGGER.critical(
        "GLOBAL_DRAWDOWN_AGGREGATE_GUARD_BLOCK marker=%s local_balance=$%.8f "
        "detail=%s action=block_new_entries kill_switch_unchanged=true",
        MARKER,
        float(local_balance or 0.0),
        detail,
    )


def _patch_drawdown_controller() -> bool:
    global _PATCHED
    try:
        from bot import drawdown_risk_controller as module
    except Exception as exc:
        LOGGER.warning(
            "GLOBAL_DRAWDOWN_AGGREGATE_GUARD_IMPORT_WAIT marker=%s error=%s:%s",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False

    cls = getattr(module, "DrawdownRiskController", None)
    if cls is None:
        return False
    current = getattr(cls, "_layer_drawdown", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_v91_aggregate_guard", False):
        _PATCHED = True
        return True

    original = current

    def _aggregate_guarded_layer(self: Any, account_balance: float):
        if not _production_runtime():
            return original(self, account_balance)

        aggregate, detail = _authoritative_aggregate_equity()
        if aggregate is None:
            _log_fail_closed(account_balance, detail)
            return (
                "HALT",
                0.0,
                True,
                "Global drawdown aggregate capital proof unavailable; " + detail,
            )

        # Keep the controller's fallback peak in the same aggregate-capital
        # domain. pre_entry_check may have seen a broker-local caller balance,
        # so promote the peak before delegating to the original layer.
        lock = getattr(self, "_lock", None)
        try:
            if lock is not None:
                with lock:
                    prior_peak = float(getattr(self, "_peak_balance", 0.0) or 0.0)
                    if aggregate > prior_peak:
                        setattr(self, "_peak_balance", aggregate)
        except Exception:
            pass

        LOGGER.debug(
            "GLOBAL_DRAWDOWN_AGGREGATE_GUARD_EQUITY marker=%s local=$%.8f aggregate=$%.8f detail=%s",
            MARKER,
            float(account_balance or 0.0),
            aggregate,
            detail,
        )
        return original(self, aggregate)

    setattr(_aggregate_guarded_layer, "_nija_v91_aggregate_guard", True)
    setattr(_aggregate_guarded_layer, "_nija_v91_original", original)
    setattr(cls, "_layer_drawdown", _aggregate_guarded_layer)
    _PATCHED = True
    os.environ["NIJA_GLOBAL_DRAWDOWN_AGGREGATE_GUARD_INSTALLED"] = "1"
    os.environ["NIJA_GLOBAL_DRAWDOWN_AGGREGATE_GUARD_READY"] = "1"
    LOGGER.critical(
        "GLOBAL_DRAWDOWN_AGGREGATE_GUARD_V91_INSTALLED marker=%s "
        "source=CapitalAuthority fail_closed=true broker_local_equity_forbidden=true",
        MARKER,
    )
    return True


def _last_non_file_activation(kill_switch: Any) -> Optional[dict[str, Any]]:
    history = list(getattr(kill_switch, "_activation_history", []) or [])
    for record in reversed(history):
        if not isinstance(record, dict):
            continue
        source = str(record.get("source", "") or "").strip()
        if not source:
            continue
        if source.upper() == "FILE_SYSTEM":
            continue
        return record
    return None


def _matches_known_false_incident(record: Optional[dict[str, Any]]) -> bool:
    if not record:
        return False
    source = str(record.get("source", "") or "").strip()
    reason = str(record.get("reason", "") or "")
    timestamp = str(record.get("timestamp", "") or "")
    return bool(
        source == _FALSE_SOURCE
        and timestamp.startswith(_FALSE_DATE)
        and all(token in reason for token in _FALSE_REASON_TOKENS)
    )


def _attempt_known_false_incident_recovery() -> bool:
    """Attempt exactly the incident-scoped, operator-authorized recovery."""
    global _RECOVERY_DONE, _RECOVERY_LAST_ATTEMPT

    if not _production_runtime() or not _PATCHED:
        return False

    with _LOCK:
        if _RECOVERY_DONE:
            return True
        now = time.monotonic()
        if now - _RECOVERY_LAST_ATTEMPT < 10.0:
            return False
        _RECOVERY_LAST_ATTEMPT = now

    try:
        from bot.kill_switch import get_kill_switch

        kill_switch = get_kill_switch()
        if not bool(kill_switch.is_active()):
            with _LOCK:
                _RECOVERY_DONE = True
            os.environ["NIJA_FALSE_DRAWDOWN_INCIDENT_RECOVERY_STATE"] = "not_needed"
            return True

        trigger = _last_non_file_activation(kill_switch)
        if not _matches_known_false_incident(trigger):
            LOGGER.critical(
                "FALSE_DRAWDOWN_INCIDENT_RECOVERY_PRESERVED_STOP marker=%s incident=%s "
                "reason=activation_signature_not_exact latest_non_file=%s",
                MARKER,
                INCIDENT_ID,
                trigger,
            )
            return False

        from bot.multi_account_broker_manager import get_broker_manager

        manager = get_broker_manager()
        all_ready_probe = getattr(manager, "all_brokers_fully_ready", None)
        if not callable(all_ready_probe) or not bool(all_ready_probe()):
            LOGGER.warning(
                "FALSE_DRAWDOWN_INCIDENT_RECOVERY_WAIT marker=%s incident=%s reason=platform_brokers_not_fully_ready",
                MARKER,
                INCIDENT_ID,
            )
            return False

        fetch_ready_probe = getattr(manager, "is_ready_for_balance_fetch", None)
        if callable(fetch_ready_probe):
            fetch_ready, fetch_reason = fetch_ready_probe()
            if not bool(fetch_ready):
                LOGGER.warning(
                    "FALSE_DRAWDOWN_INCIDENT_RECOVERY_WAIT marker=%s incident=%s reason=balance_fetch_not_ready detail=%s",
                    MARKER,
                    INCIDENT_ID,
                    fetch_reason,
                )
                return False

        refresh = getattr(manager, "refresh_capital_authority", None)
        if not callable(refresh):
            LOGGER.critical(
                "FALSE_DRAWDOWN_INCIDENT_RECOVERY_WAIT marker=%s incident=%s reason=refresh_api_missing",
                MARKER,
                INCIDENT_ID,
            )
            return False
        refresh_result = refresh(trigger=f"{MARKER}:{INCIDENT_ID}")

        aggregate, detail = _authoritative_aggregate_equity()
        if aggregate is None:
            LOGGER.critical(
                "FALSE_DRAWDOWN_INCIDENT_RECOVERY_WAIT marker=%s incident=%s "
                "reason=fresh_complete_aggregate_not_proven refresh=%s detail=%s",
                MARKER,
                INCIDENT_ID,
                refresh_result,
                detail,
            )
            return False

        # The in-process breaker may still carry the contaminated broker-local
        # baseline. Reset it only after fresh complete aggregate proof, and only
        # for this exact historical false incident.
        from bot.global_drawdown_circuit_breaker import get_global_drawdown_cb

        breaker = get_global_drawdown_cb()
        breaker.initialise(starting_equity=aggregate)

        reason = (
            f"Operator-authorized recovery {INCIDENT_ID}: corrected cross-broker "
            f"GlobalDrawdown equity source with {MARKER}; fresh complete aggregate "
            f"capital=${aggregate:.8f}"
        )
        kill_switch.deactivate(reason=reason)
        if bool(kill_switch.is_active()):
            LOGGER.critical(
                "FALSE_DRAWDOWN_INCIDENT_RECOVERY_FAILED marker=%s incident=%s reason=kill_switch_still_active",
                MARKER,
                INCIDENT_ID,
            )
            return False

        with _LOCK:
            _RECOVERY_DONE = True
        os.environ["NIJA_FALSE_DRAWDOWN_INCIDENT_RECOVERED"] = "1"
        os.environ["NIJA_FALSE_DRAWDOWN_INCIDENT_RECOVERY_STATE"] = "recovered"
        LOGGER.critical(
            "FALSE_DRAWDOWN_INCIDENT_RECOVERED marker=%s incident=%s aggregate=$%.8f "
            "canonical_deactivate=true state_transition_direct=false authority_synthesized=false",
            MARKER,
            INCIDENT_ID,
            aggregate,
        )
        return True
    except Exception as exc:
        LOGGER.exception(
            "FALSE_DRAWDOWN_INCIDENT_RECOVERY_ERROR marker=%s incident=%s error=%s:%s",
            MARKER,
            INCIDENT_ID,
            type(exc).__name__,
            exc,
        )
        return False


def _recovery_monitor() -> None:
    deadline = time.monotonic() + 900.0
    while time.monotonic() < deadline:
        if _attempt_known_false_incident_recovery():
            return
        time.sleep(15.0)
    LOGGER.critical(
        "FALSE_DRAWDOWN_INCIDENT_RECOVERY_MONITOR_EXPIRED marker=%s incident=%s "
        "action=leave_kill_switch_unchanged",
        MARKER,
        INCIDENT_ID,
    )


def install_import_hook() -> bool:
    global _RECOVERY_THREAD_STARTED
    patched = _patch_drawdown_controller()
    if not patched:
        return False

    # The user/operator explicitly authorized recovery of this proven incident.
    # The monitor still requires an exact persisted activation signature and a
    # fresh complete canonical capital refresh before canonical deactivation.
    with _LOCK:
        if not _RECOVERY_THREAD_STARTED:
            _RECOVERY_THREAD_STARTED = True
            threading.Thread(
                target=_recovery_monitor,
                name="false-drawdown-incident-recovery-v91",
                daemon=True,
            ).start()

    os.environ["NIJA_GLOBAL_DRAWDOWN_AGGREGATE_GUARD_INSTALLED"] = "1"
    os.environ["NIJA_GLOBAL_DRAWDOWN_AGGREGATE_GUARD_READY"] = "1"
    return True


__all__ = [
    "MARKER",
    "INCIDENT_ID",
    "install_import_hook",
    "_authoritative_aggregate_equity",
    "_patch_drawdown_controller",
    "_last_non_file_activation",
    "_matches_known_false_incident",
    "_attempt_known_false_incident_recovery",
]
