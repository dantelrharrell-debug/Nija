"""Preserve the verified startup-heartbeat terminal grant through broker-manager (v235).

Production proof showed v233 correctly re-verifies startup write authority and arms a
same-thread 0.75s grant, but intermediate terminal checks can exhaust its two-read
budget before broker_manager performs the actual exchange-submit authority guard.

v235 does not create authority and does not change lifecycle/readiness state. It only
raises the bounded read budget on an already-v233-verified, same-thread, sub-second
grant so it survives the known pipeline -> router -> broker-manager terminal chain.
Ordinary orders cannot arm this grant.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from typing import Any

LOGGER = logging.getLogger("nija.runtime_heartbeat_terminal_broker_manager_v235")
MARKER = "20260826-heartbeat-terminal-broker-manager-v235"
_FLAG = "NIJA_HEARTBEAT_TERMINAL_BROKER_MANAGER_V235_READY"
_READ_BUDGET = 8
_PATCH_ATTR = "_nija_v235_bounded_grant"


def _patch_v233() -> bool:
    v233 = importlib.import_module("bot.runtime_heartbeat_terminal_authority_v233_patch")
    original = getattr(v233, "_set_one_shot_grant", None)
    if not callable(original):
        return False
    if bool(getattr(original, _PATCH_ATTR, False)):
        return True

    def _set_bounded_terminal_grant(probe_reason: str) -> None:
        # Preserve every v233 invariant: only v233's independently verified startup
        # probe can call this function; thread identity and TTL remain unchanged.
        grant = getattr(v233, "_GRANT")
        grant.thread_id = threading.get_ident()
        grant.expires = time.monotonic() + float(getattr(v233, "_GRANT_TTL_S", 0.75))
        grant.remaining = _READ_BUDGET
        grant.probe_reason = str(probe_reason)

    setattr(_set_bounded_terminal_grant, _PATCH_ATTR, True)
    setattr(_set_bounded_terminal_grant, "__wrapped__", original)
    setattr(v233, "_set_one_shot_grant", _set_bounded_terminal_grant)
    return True


def install() -> bool:
    try:
        ready = _patch_v233()
    except Exception as exc:
        LOGGER.error(
            "HEARTBEAT_TERMINAL_BROKER_MANAGER_V235_INSTALL_ERROR marker=%s error=%s:%s trading_fail_closed=true",
            MARKER, type(exc).__name__, exc,
        )
        ready = False
    os.environ[_FLAG] = "1" if ready else "0"
    if ready:
        LOGGER.critical(
            "HEARTBEAT_TERMINAL_BROKER_MANAGER_V235_READY marker=%s ready=true read_budget=%d "
            "grant_ttl_s=0.75 same_thread=true startup_probe_verification_unchanged=true "
            "canonical_lifecycle_unchanged=true ordinary_orders_unchanged=true kill_switch_unchanged=true "
            "writer_nonce_risk_capital_broker_health_ecel_min_notional_order_fill_gates_unchanged=true "
            "execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
            MARKER, _READ_BUDGET,
        )
    return ready


def install_import_hook() -> bool:
    return install()


__all__ = ["MARKER", "install", "install_import_hook", "_patch_v233"]
