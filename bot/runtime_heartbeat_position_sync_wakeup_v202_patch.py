"""Wake the heartbeat verifier when authoritative position sync completes v202.

Production v201 on 2026-08-23 proved that the live heartbeat scheduler was armed,
but the post-core activation budget could still expire after the final structural
position-sync gate became ready. TradingStrategy's heartbeat runner normally
sleeps for 15 seconds after a failed probe. In the observed failure,
``position_sync_ready`` became true only about 1.5 seconds before the bounded
post-core deadline, so the next genuine probe could not run before startup
failed closed.

v202 preserves the configured retry cadence for ordinary heartbeat failures. It
only wakes that sleep early when the canonical readiness table changes
``position_sync_ready`` from false to true while the runner is already waiting.
The immediate retry still executes the unchanged heartbeat probe path and every
writer, nonce, risk, kill-switch, broker-health, sizing, min-notional, order,
fill, reconciliation, and capital gate remains authoritative. No readiness or
execution proof is fabricated and no activation state is forced.

Production evidence on 2026-09-06 also proved that an ACK-timeout heartbeat BUY
can later reconcile as a real exchange fill. Therefore v202 now enforces the
operator's explicit ``NIJA_ALLOW_LIVE_HEARTBEAT_ORDERS`` opt-in at both the
runner and executor boundaries. If that opt-in is false, no capital-bearing
heartbeat order may be submitted even when another runtime patch directly calls
``_execute_heartbeat_trade``. Read-only authenticated fill recovery remains
available through the canonical Kraken QueryOrders proof path.
"""
from __future__ import annotations

import importlib
import logging
import os
import time
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_heartbeat_position_sync_wakeup_v202")
MARKER = "20260823-heartbeat-position-sync-wakeup-v202"
SAFETY_MARKER = "20260906-live-heartbeat-explicit-optin-v374"
_READY_FLAG = "NIJA_HEARTBEAT_POSITION_SYNC_WAKEUP_V202_READY"
_PATCH_ATTR = "_nija_heartbeat_position_sync_wakeup_v202"
_EXECUTOR_GUARD_ATTR = "_nija_live_heartbeat_explicit_optin_v374"
_POLL_S = 0.25
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _live_heartbeat_orders_allowed() -> bool:
    """Return true only for the explicit capital-bearing heartbeat opt-in."""
    return str(os.environ.get("NIJA_ALLOW_LIVE_HEARTBEAT_ORDERS", "false") or "").strip().lower() in _TRUE


def _position_sync_ready() -> tuple[bool, bool]:
    """Return ``(known, ready)`` from the canonical readiness table."""
    try:
        readiness = importlib.import_module("bot.readiness_table")
        snapshot = getattr(readiness, "snapshot", None)
        if not callable(snapshot):
            return False, False
        table = snapshot()
        if not isinstance(table, dict) or "position_sync_ready" not in table:
            return False, False
        return True, bool(table.get("position_sync_ready"))
    except Exception:
        return False, False


def _wait_for_retry_or_position_sync(sleep_s: float) -> bool:
    """Sleep normally, but wake if position sync transitions false -> true.

    Returns True only when the sleep was shortened by that real readiness
    transition. Unknown/missing readiness preserves the original sleep.
    """
    duration = max(0.0, float(sleep_s or 0.0))
    if duration <= 0.0:
        return False

    known, ready = _position_sync_ready()
    if not known or ready:
        time.sleep(duration)
        return False

    deadline = time.monotonic() + duration
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0.0:
            return False
        time.sleep(min(_POLL_S, remaining))
        current_known, current_ready = _position_sync_ready()
        if current_known and current_ready:
            return True


def _patch_executor_guard(strategy_module: Any | None = None) -> bool:
    """Fail closed before any capital-bearing heartbeat order can be built."""
    try:
        strategy_module = strategy_module or importlib.import_module("bot.trading_strategy")
    except Exception as exc:
        LOGGER.critical(
            "HEARTBEAT_OPTIN_GUARD_V374_FAILED marker=%s reason=strategy_import error=%s:%s trading_fail_closed=true",
            SAFETY_MARKER,
            type(exc).__name__,
            exc,
        )
        return False

    cls = getattr(strategy_module, "TradingStrategy", None)
    current = getattr(cls, "_execute_heartbeat_trade", None) if isinstance(cls, type) else None
    if not callable(current):
        return False
    if bool(getattr(current, _EXECUTOR_GUARD_ATTR, False)):
        return True

    strategy_logger = getattr(strategy_module, "logger", LOGGER)

    @wraps(current)
    def _execute_heartbeat_trade_guarded(self: Any) -> bool:
        if not _live_heartbeat_orders_allowed():
            if not bool(getattr(self, "_nija_heartbeat_optin_block_logged_v374", False)):
                setattr(self, "_nija_heartbeat_optin_block_logged_v374", True)
                strategy_logger.critical(
                    "HEARTBEAT_LIVE_ORDER_V374_BLOCKED marker=%s reason=NIJA_ALLOW_LIVE_HEARTBEAT_ORDERS_false "
                    "order_submitted=false retry_suppressed=true execution_marker_written=false "
                    "read_only_fill_recovery_preserved=true forced_trade=false safety_gates_bypassed=false",
                    SAFETY_MARKER,
                )
            try:
                with self._heartbeat_trade_lock:
                    self._heartbeat_trade_success = False
                    self._heartbeat_trade_completed = False
            except Exception:
                pass
            return False
        return bool(current(self))

    setattr(_execute_heartbeat_trade_guarded, _EXECUTOR_GUARD_ATTR, True)
    setattr(_execute_heartbeat_trade_guarded, "__wrapped__", current)
    setattr(cls, "_execute_heartbeat_trade", _execute_heartbeat_trade_guarded)
    return True


def _patch_runner() -> bool:
    try:
        strategy_module = importlib.import_module("bot.trading_strategy")
    except Exception as exc:
        LOGGER.critical(
            "HEARTBEAT_POSITION_SYNC_WAKEUP_V202_FAILED marker=%s reason=strategy_import "
            "error=%s:%s trading_fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False

    if not _patch_executor_guard(strategy_module):
        return False

    cls = getattr(strategy_module, "TradingStrategy", None)
    current = getattr(cls, "_heartbeat_trade_runner", None) if isinstance(cls, type) else None
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    strategy_logger = getattr(strategy_module, "logger", LOGGER)
    rate_limited_info = getattr(strategy_module, "_heartbeat_rate_limited_info", None)

    @wraps(current)
    def _heartbeat_trade_runner_v202(self: Any) -> None:
        if not _live_heartbeat_orders_allowed():
            strategy_logger.critical(
                "HEARTBEAT_RUNNER_V374_STOPPED marker=%s reason=NIJA_ALLOW_LIVE_HEARTBEAT_ORDERS_false "
                "capital_bearing_retry_loop=false order_submitted=false read_only_execution_proof_recovery_preserved=true",
                SAFETY_MARKER,
            )
            try:
                with self._heartbeat_trade_lock:
                    self._heartbeat_trade_success = False
                    self._heartbeat_trade_completed = False
            except Exception:
                pass
            return

        first_delay_s = max(
            0.0,
            float(getattr(strategy_module, "_HEARTBEAT_TRADE_FIRST_ATTEMPT_DELAY_S", 0.0) or 0.0),
        )
        retry_interval_s = max(
            1.0,
            float(getattr(strategy_module, "_HEARTBEAT_TRADE_INTERVAL_S", 15.0) or 15.0),
        )
        retry_backoff_max_s = max(
            retry_interval_s,
            float(getattr(strategy_module, "_HEARTBEAT_RETRY_BACKOFF_MAX_S", 120.0) or 120.0),
        )
        retry_backoff_enabled = bool(
            getattr(strategy_module, "_HEARTBEAT_RETRY_BACKOFF_ENABLED", False)
        )

        if first_delay_s > 0.0:
            if callable(rate_limited_info):
                rate_limited_info(
                    "heartbeat_runner_delay",
                    "runner",
                    60.0,
                    "💓 Heartbeat trade runner sleeping %.0fs before first attempt",
                    first_delay_s,
                )
            time.sleep(first_delay_s)

        attempt = 1
        while True:
            if not _live_heartbeat_orders_allowed():
                strategy_logger.critical(
                    "HEARTBEAT_RUNNER_V374_STOPPED marker=%s reason=optin_revoked_during_runtime "
                    "capital_bearing_retry_loop=false order_submitted=false",
                    SAFETY_MARKER,
                )
                return
            try:
                success = bool(self._execute_heartbeat_trade())
                with self._heartbeat_trade_lock:
                    self._heartbeat_trade_success = success
                    self._heartbeat_trade_completed = success
                if success:
                    strategy_logger.info(
                        "✅ Heartbeat trade PASSED — bot confirmed ready for live trading"
                    )
                    return

                sleep_s = retry_interval_s
                if retry_backoff_enabled:
                    sleep_s = min(
                        retry_backoff_max_s,
                        retry_interval_s * float(2 ** min(attempt - 1, 10)),
                    )
                if callable(rate_limited_info):
                    rate_limited_info(
                        "heartbeat_runner_retry",
                        "runner",
                        max(10.0, retry_interval_s),
                        "❌ Heartbeat trade FAILED on attempt %d — retrying in %.0fs",
                        attempt,
                        sleep_s,
                    )
                strategy_logger.error(
                    "❌ Heartbeat trade FAILED on attempt %d — retrying in %.0fs",
                    attempt,
                    sleep_s,
                )
            except Exception as exc:
                strategy_logger.error(
                    "❌ Heartbeat trade runner raised on attempt %d: %s",
                    attempt,
                    exc,
                    exc_info=True,
                )
                with self._heartbeat_trade_lock:
                    self._heartbeat_trade_success = False
                    self._heartbeat_trade_completed = False
                sleep_s = retry_interval_s
                if retry_backoff_enabled:
                    sleep_s = min(
                        retry_backoff_max_s,
                        retry_interval_s * float(2 ** min(attempt - 1, 10)),
                    )

            attempt += 1
            woke_early = _wait_for_retry_or_position_sync(sleep_s)
            if woke_early:
                LOGGER.critical(
                    "HEARTBEAT_POSITION_SYNC_WAKEUP_V202_TRIGGERED marker=%s "
                    "next_attempt=%d position_sync_transition=false_to_true "
                    "configured_retry_s=%.3f readiness_fabricated=false "
                    "execution_authority_granted=false proof_fabricated=false "
                    "writer_nonce_risk_killswitch_capital_order_fill_gates_unchanged=true",
                    MARKER,
                    attempt,
                    sleep_s,
                )

    setattr(_heartbeat_trade_runner_v202, _PATCH_ATTR, True)
    setattr(_heartbeat_trade_runner_v202, "__wrapped__", current)
    setattr(cls, "_heartbeat_trade_runner", _heartbeat_trade_runner_v202)
    return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_heartbeat_position_sync_wakeup_v202"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    executor_ok = _patch_executor_guard()
    runner_ok = _patch_runner()
    manifest_ok = _patch_release_manifest()
    ready = bool(executor_ok and runner_ok and manifest_ok)
    os.environ[_READY_FLAG] = "1" if ready else "0"
    if not ready:
        LOGGER.critical(
            "HEARTBEAT_POSITION_SYNC_WAKEUP_V202_FAILED marker=%s executor_guard=%s runner=%s manifest=%s "
            "trading_fail_closed=true",
            MARKER,
            str(executor_ok).lower(),
            str(runner_ok).lower(),
            str(manifest_ok).lower(),
        )
        return False
    LOGGER.critical(
        "HEARTBEAT_POSITION_SYNC_WAKEUP_V202_READY marker=%s ready=true "
        "wake_condition=position_sync_false_to_true normal_retry_cadence_unchanged=true "
        "live_heartbeat_explicit_optin_guard=true optin_env=NIJA_ALLOW_LIVE_HEARTBEAT_ORDERS "
        "readiness_fabricated=false execution_authority_granted=false proof_fabricated=false "
        "forced_activation=false writer_nonce_risk_killswitch_reconciliation_capital_order_fill_gates_unchanged=true "
        "safety_gates_bypassed=false",
        MARKER,
    )
    return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "SAFETY_MARKER",
    "install",
    "install_import_hook",
    "_live_heartbeat_orders_allowed",
    "_position_sync_ready",
    "_wait_for_retry_or_position_sync",
    "_patch_executor_guard",
]
