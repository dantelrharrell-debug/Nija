"""v359 — make the scan-start watchdog readiness-aware.

Production evidence showed the canonical TradingLoop can remain intentionally
fail-closed in INIT STEP 2/6 while waiting for ``TRADING_ENGINE_READY``.  During
that interval ``run_scan_phase`` cannot execute, yet the writer scan watchdog
was measuring its 300-second deadline from STEP 3 handoff and repeatedly
emitting ``SCAN_STARTED_DEADLINE_EXCEEDED``.

This patch changes diagnostics only: the watchdog remains armed, but its scan
start deadline begins only after the canonical TRADING_ENGINE_READY Event is
actually set.  The core-loop readiness wait, execution proof, writer/nonce,
risk, capital, position-sync, ECEL, broker-health, minimum-order, order ACK,
fill-verification, kill-switch and protective-exit gates are untouched.
"""
from __future__ import annotations

import importlib
import logging
import os
import time

LOGGER = logging.getLogger("nija.runtime_scan_start_readiness_v359")
MARKER = "20260904-runtime-scan-start-readiness-v359"
READY_ENV = "NIJA_RUNTIME_SCAN_START_READINESS_V359_READY"


def _engine_start_signal_ready() -> bool:
    """Return truth from the canonical TRADING_ENGINE_READY Event only."""
    try:
        module = importlib.import_module("bot.nija_core_loop")
        event = getattr(module, "TRADING_ENGINE_READY", None)
        reader = getattr(event, "is_set", None)
        return bool(reader()) if callable(reader) else False
    except Exception:
        # Missing/unreadable readiness is not permission to start the scan
        # deadline.  The core loop remains independently fail-closed.
        return False


def _readiness_aware_scan_started_watchdog_loop(self, deadline_s: float) -> None:
    poll_interval = min(10.0, max(1.0, deadline_s / 10.0))
    deadline_last_logged = 0.0
    deadline_rewarning_s = min(60.0, max(poll_interval, deadline_s / 5.0))
    deferred_last_logged = 0.0
    eligible_since = 0.0

    while True:
        if (
            not self.acquired
            or self._scan_started_at
            or self._scan_complete_at
            or self._scan_watchdog_cancel.is_set()
        ):
            self._scan_deadline_exceeded = False
            return

        armed_at = self._scan_deadline_armed_at
        if armed_at <= 0.0:
            if self._stop.is_set():
                return
            if self._scan_watchdog_cancel.wait(timeout=poll_interval):
                self._scan_deadline_exceeded = False
                return
            continue

        # The canonical core cannot enter run_scan_phase until this Event is
        # set.  Do not classify that deliberate fail-closed wait as a missed
        # scan.  The core loop retains its own TRADING_ENGINE_READY timeout
        # diagnostics, so genuine readiness stalls remain observable.
        if not _engine_start_signal_ready():
            self._scan_deadline_exceeded = False
            eligible_since = 0.0
            now = time.time()
            if now - deferred_last_logged >= 60.0:
                deferred_last_logged = now
                LOGGER.info(
                    "SCAN_START_DEADLINE_V359_DEFERRED marker=%s reason=trading_engine_not_ready "
                    "arm_source=%s writer_acquired=%s instance=%s safety_gates_bypassed=false",
                    MARKER,
                    self._scan_deadline_arm_source or "unknown",
                    self.acquired,
                    self._instance_id,
                )
            if self._stop.is_set():
                return
            if self._scan_watchdog_cancel.wait(timeout=poll_interval):
                self._scan_deadline_exceeded = False
                return
            continue

        now = time.time()
        if eligible_since <= 0.0:
            eligible_since = now
            LOGGER.info(
                "SCAN_START_DEADLINE_V359_ELIGIBLE marker=%s deadline_s=%.0f "
                "arm_source=%s instance=%s",
                MARKER,
                deadline_s,
                self._scan_deadline_arm_source or "unknown",
                self._instance_id,
            )

        elapsed = now - eligible_since
        if elapsed >= deadline_s:
            self._scan_deadline_exceeded = True
            if now - deadline_last_logged >= deadline_rewarning_s:
                deadline_last_logged = now
                LOGGER.error(
                    "SCAN_STARTED_DEADLINE_EXCEEDED marker=%s deadline_s=%.0f "
                    "elapsed_since_engine_ready=%.1fs elapsed_since_deadline_arm=%.1fs "
                    "arm_source=%s writer_acquired=%s instance=%s",
                    MARKER,
                    deadline_s,
                    elapsed,
                    now - armed_at,
                    self._scan_deadline_arm_source or "unknown",
                    self.acquired,
                    self._instance_id,
                )
            if self._stop.is_set():
                return
            if self._scan_watchdog_cancel.wait(timeout=poll_interval):
                self._scan_deadline_exceeded = False
                return
            continue

        if self._stop.is_set():
            return
        remaining = deadline_s - elapsed
        if self._scan_watchdog_cancel.wait(
            timeout=min(poll_interval, max(0.1, remaining))
        ):
            self._scan_deadline_exceeded = False
            return


def install_import_hook() -> bool:
    try:
        authority = importlib.import_module("bot.entrypoint_writer_authority")
        cls = getattr(authority, "EntrypointWriterAuthority", None)
        if cls is None:
            os.environ[READY_ENV] = "0"
            return False

        current = getattr(cls, "_scan_started_watchdog_loop", None)
        if getattr(current, "_nija_v359", False):
            os.environ[READY_ENV] = "1"
            return True

        _readiness_aware_scan_started_watchdog_loop._nija_v359 = True  # type: ignore[attr-defined]
        _readiness_aware_scan_started_watchdog_loop._nija_v359_original = current  # type: ignore[attr-defined]
        cls._scan_started_watchdog_loop = _readiness_aware_scan_started_watchdog_loop
        os.environ[READY_ENV] = "1"
        LOGGER.critical(
            "RUNTIME_SCAN_START_READINESS_V359_READY marker=%s ready=true "
            "deadline_basis=trading_engine_ready_event core_wait_unchanged=true "
            "execution_proof_unchanged=true writer_nonce_risk_capital_position_ecel_broker_health_unchanged=true "
            "minimum_order_ack_fill_gates_unchanged=true kill_switch_unchanged=true "
            "protective_exits_unchanged=true forced_trade=false forced_activation=false "
            "execution_proof_fabricated=false safety_gates_bypassed=false",
            MARKER,
        )
        return True
    except Exception:
        os.environ[READY_ENV] = "0"
        LOGGER.exception("RUNTIME_SCAN_START_READINESS_V359_INSTALL_FAILED marker=%s", MARKER)
        return False


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "READY_ENV", "install", "install_import_hook"]
