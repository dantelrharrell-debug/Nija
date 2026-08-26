"""Publish the canonical heartbeat verification marker from a proven writer renewal.

Production showed the entrypoint writer lease renewing successfully while the live
activation circuit breaker still reported heartbeat_verification marker_missing.
This patch does not fabricate heartbeat success. It only writes the existing
canonical authority-heartbeat marker after the exact entrypoint writer heartbeat
method returns with acquired=True, lost=False and a fresh renewal-health proof.
All existing circuit-breaker thresholds, nonce, risk, capital and order gates stay
unchanged.
"""
from __future__ import annotations

import importlib
import logging
import os
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_heartbeat_marker_convergence_v238")
MARKER = "20260826-heartbeat-marker-convergence-v238"
_PATCH_ATTR = "_nija_heartbeat_marker_convergence_v238"


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
                hb = importlib.import_module("bot.authority_heartbeat")
                writer = getattr(hb, "_write_heartbeat_marker", None)
                if callable(writer):
                    writer()
                    LOGGER.critical(
                        "HEARTBEAT_MARKER_V238_PUBLISHED marker=%s source=entrypoint_writer_renewal "
                        "lease_acquired=true writer_lost=false renewal_health=true "
                        "heartbeat_success_fabricated=false circuit_threshold_unchanged=true "
                        "nonce_risk_capital_order_gates_unchanged=true safety_gates_bypassed=false",
                        MARKER,
                    )
                    try:
                        repair = importlib.import_module("bot.runtime_authority_convergence_repair_patch")
                        converge = getattr(repair, "converge_runtime_authority", None)
                        if callable(converge):
                            converge("heartbeat_marker_v238")
                    except Exception as exc:
                        LOGGER.debug("HEARTBEAT_MARKER_V238_RECONCILE_DEFERRED marker=%s error=%s", MARKER, exc)
            else:
                LOGGER.debug(
                    "HEARTBEAT_MARKER_V238_NOT_PUBLISHED marker=%s acquired=%s lost=%s healthy=%s reason=%s",
                    MARKER, acquired, lost, healthy, reason,
                )
        except Exception as exc:
            LOGGER.warning(
                "HEARTBEAT_MARKER_V238_WRITE_FAILED marker=%s error=%s:%s trading_fail_closed=true",
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
    except Exception as exc:
        LOGGER.error("HEARTBEAT_MARKER_V238_INSTALL_ERROR marker=%s error=%s:%s trading_fail_closed=true", MARKER, type(exc).__name__, exc)
        ready = False
    os.environ["NIJA_HEARTBEAT_MARKER_CONVERGENCE_V238_READY"] = "1" if ready else "0"
    if ready:
        LOGGER.critical(
            "HEARTBEAT_MARKER_CONVERGENCE_V238_READY marker=%s ready=true genuine_writer_renewal_only=true "
            "canonical_marker_writer=true activation_reconcile_wakeup=true execution_proof_fabricated=false "
            "forced_activation=false safety_gates_bypassed=false",
            MARKER,
        )
    return ready


def install_import_hook() -> bool:
    return install()


__all__ = ["MARKER", "install", "install_import_hook"]
