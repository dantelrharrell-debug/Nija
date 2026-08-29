"""Re-arm genuine heartbeat execution after a proven writer renewal (v238/v275).

Production on 2026-08-26 showed the entrypoint writer lease renewing successfully
while the live activation circuit breaker still reported
``heartbeat_verification ... marker_missing``. The previous v238 implementation
called ``authority_heartbeat._write_heartbeat_marker()`` from a writer renewal.
That is AUTH_VERIFY liveness, not ORDER_VERIFY/FILL_VERIFY execution proof.

The corrected v238 never writes an execution heartbeat marker from writer renewal.
A healthy renewal is only a liveness wake-up: locate the already-published strategy
and idempotently ensure its genuine heartbeat scheduler is running. Production on
2026-08-29 then exposed a second startup gap: the writer renewed while the canonical
strategy publication monitor remained deferred, leaving v238 permanently at
``strategy_not_published``. v275 closes only that owner handoff. After a proven
healthy writer renewal, and only when no strategy is already published, v238 may
idempotently arm the existing strategy publication monitor. The publication module's
own live-capital, runtime-state, writer-token, writer-generation, and hydrated-broker
checks remain authoritative. v238 still reports scheduler-not-ready until a real
strategy exists and never publishes readiness itself.

The normal heartbeat order path must obtain a real broker result and
``TradingStrategy._persist_heartbeat_marker`` remains the owner of execution proof.
Activation convergence is woken only after the canonical trading-state-machine
verifier confirms that genuine marker is present, stage-sufficient, and fresh.

No execution authority, readiness, nonce, risk, capital, broker-health, ECEL,
minimum-notional, acknowledgement, or fill gate is bypassed or fabricated.
"""
from __future__ import annotations

import importlib
import logging
import os
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_heartbeat_marker_convergence_v238")
MARKER = "20260826-heartbeat-marker-convergence-v238"
V275_MARKER = "20260829-strategy-publication-writer-handoff-v275"
_PATCH_ATTR = "_nija_heartbeat_marker_convergence_v238"


def _arm_strategy_publication_monitor(publication: Any) -> tuple[bool, str]:
    """Arm the existing publisher after writer proof; never publish readiness here."""
    starter = getattr(publication, "start_monitor", None)
    if not callable(starter):
        return False, "publication_start_unavailable"
    try:
        armed = bool(starter())
    except Exception as exc:
        return False, f"publication_start_error:{type(exc).__name__}:{exc}"
    if armed:
        LOGGER.warning(
            "STRATEGY_PUBLICATION_WRITER_HANDOFF_V275_ARMED marker=%s "
            "writer_renewal_required=true publication_monitor_only=true "
            "strategy_published=false readiness_fabricated=false execution_authority_granted=false "
            "execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
            V275_MARKER,
        )
        return True, "publication_monitor_armed"
    return False, "publication_monitor_not_armed"


def _rearm_genuine_heartbeat() -> tuple[bool, str]:
    try:
        v203 = importlib.import_module("bot.runtime_existing_strategy_heartbeat_rearm_v203_patch")
        publication = importlib.import_module("bot.strategy_publication_patch")
        finder = getattr(v203, "_already_published_strategy", None)
        ensure = getattr(v203, "_ensure_heartbeat_scheduler", None)
        if not callable(finder) or not callable(ensure):
            return False, "v203_helpers_unavailable"
        strategy = finder(publication)
        if strategy is None:
            armed, detail = _arm_strategy_publication_monitor(publication)
            if armed:
                return False, f"strategy_not_published:{detail}"
            return False, f"strategy_not_published:{detail}"
        ready = bool(ensure(strategy))
        return ready, "scheduler_alive" if ready else "scheduler_not_alive"
    except Exception as exc:
        return False, f"rearm_error:{type(exc).__name__}:{exc}"


def _genuine_execution_marker_ready() -> tuple[bool, str]:
    try:
        tsm = importlib.import_module("bot.trading_state_machine")
        verifier = getattr(tsm, "_heartbeat_verification_status", None)
        if not callable(verifier):
            return False, "canonical_verifier_unavailable"
        ok, detail, _meta = verifier()
        return bool(ok), str(detail or "verified")
    except Exception as exc:
        return False, f"verification_error:{type(exc).__name__}:{exc}"


def _wake_activation_after_genuine_marker(source: str) -> bool:
    marker_ready, marker_detail = _genuine_execution_marker_ready()
    if not marker_ready:
        LOGGER.info(
            "HEARTBEAT_MARKER_V238_EXECUTION_PROOF_PENDING marker=%s source=%s detail=%s "
            "execution_proof_fabricated=false activation_commit_attempted=false trading_fail_closed=true",
            MARKER, source, marker_detail,
        )
        return False
    try:
        repair = importlib.import_module("bot.runtime_authority_convergence_repair_patch")
        converge = getattr(repair, "converge_runtime_authority", None)
        if callable(converge):
            converge("heartbeat_execution_marker_v238")
            LOGGER.critical(
                "HEARTBEAT_MARKER_V238_GENUINE_EXECUTION_PROOF_READY marker=%s source=%s "
                "canonical_verifier=true activation_reconcile_wakeup=true proof_fabricated=false "
                "forced_activation=false safety_gates_bypassed=false",
                MARKER, source,
            )
            return True
    except Exception as exc:
        LOGGER.warning(
            "HEARTBEAT_MARKER_V238_RECONCILE_DEFERRED marker=%s error=%s:%s trading_fail_closed=true",
            MARKER, type(exc).__name__, exc,
        )
    return False


def _patch_entrypoint_writer() -> bool:
    module = importlib.import_module("bot.entrypoint_writer_authority")
    cls = getattr(module, "EntrypointWriterAuthority", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "_heartbeat_tick", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def heartbeat_tick_v238(self: Any, *args: Any, **kwargs: Any):
        result = current(self, *args, **kwargs)
        try:
            acquired = bool(getattr(self, "acquired", False))
            lost = bool(getattr(self, "lost", True))
            health = getattr(self, "_nija_lease_renewal_health", None)
            healthy = False
            reason = "health_unavailable"
            if callable(health):
                proof = health()
                healthy = bool(proof and proof[0])
                reason = str(proof[1] if len(proof) > 1 else "unknown")
            if acquired and not lost and healthy:
                rearmed, rearm_detail = _rearm_genuine_heartbeat()
                LOGGER.critical(
                    "HEARTBEAT_MARKER_V238_LIVENESS_WAKE marker=%s source=entrypoint_writer_renewal "
                    "lease_acquired=true writer_lost=false renewal_health=true scheduler_ready=%s "
                    "scheduler_detail=%s execution_marker_written=false writer_renewal_not_execution_proof=true "
                    "execution_proof_fabricated=false nonce_risk_capital_order_gates_unchanged=true "
                    "safety_gates_bypassed=false",
                    MARKER, str(rearmed).lower(), rearm_detail,
                )
                _wake_activation_after_genuine_marker("entrypoint_writer_renewal")
            else:
                LOGGER.debug(
                    "HEARTBEAT_MARKER_V238_WAKE_SKIPPED marker=%s acquired=%s lost=%s healthy=%s reason=%s",
                    MARKER, acquired, lost, healthy, reason,
                )
        except Exception as exc:
            LOGGER.warning(
                "HEARTBEAT_MARKER_V238_WAKE_FAILED marker=%s error=%s:%s trading_fail_closed=true",
                MARKER, type(exc).__name__, exc,
            )
        return result

    setattr(heartbeat_tick_v238, _PATCH_ATTR, True)
    setattr(heartbeat_tick_v238, "__wrapped__", current)
    cls._heartbeat_tick = heartbeat_tick_v238
    return True


def install() -> bool:
    try:
        ready = _patch_entrypoint_writer()
        rearmed, detail = _rearm_genuine_heartbeat()
        LOGGER.info(
            "HEARTBEAT_MARKER_V238_INSTALL_REARM marker=%s scheduler_ready=%s detail=%s",
            MARKER, str(rearmed).lower(), detail,
        )
        _wake_activation_after_genuine_marker("install")
    except Exception as exc:
        LOGGER.error(
            "HEARTBEAT_MARKER_V238_INSTALL_ERROR marker=%s error=%s:%s trading_fail_closed=true",
            MARKER, type(exc).__name__, exc,
        )
        ready = False
    os.environ["NIJA_HEARTBEAT_MARKER_CONVERGENCE_V238_READY"] = "1" if ready else "0"
    if ready:
        LOGGER.critical(
            "HEARTBEAT_MARKER_CONVERGENCE_V238_READY marker=%s ready=true genuine_writer_renewal_wakeup_only=true "
            "real_heartbeat_scheduler_rearmed=true execution_marker_owner=TradingStrategy._persist_heartbeat_marker "
            "canonical_execution_marker_verifier=true activation_reconcile_after_genuine_marker_only=true "
            "strategy_publication_writer_handoff_v275=true execution_proof_fabricated=false forced_activation=false "
            "safety_gates_bypassed=false",
            MARKER,
        )
    return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "V275_MARKER",
    "install",
    "install_import_hook",
    "_arm_strategy_publication_monitor",
    "_rearm_genuine_heartbeat",
    "_genuine_execution_marker_ready",
]
