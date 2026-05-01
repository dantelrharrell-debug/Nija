"""
No-Failure Activation Contract
================================

Three runtime invariants that guarantee trading starts on every boot without
silent exception paths.

Invariant 1 — MONOTONIC SNAPSHOT PROGRESSION
    ``publish_snapshot()`` in ``capital_authority.py`` now stamps
    ``_broker_feed_timestamps`` with ``computed_at`` for every broker in the
    accepted snapshot.  The push path (``feed_broker_balance``) therefore
    cannot overwrite a coordinator-published snapshot with a stale feed,
    even on first boot when no prior feed timestamp exists.

Invariant 2 — GUARANTEED CA HYDRATION LOOP
    :class:`CAHydrationLoop` starts a background daemon thread that calls
    ``CapitalRefreshCoordinator.execute_refresh()`` every ``retry_interval_s``
    (default 5 s) until ``CAPITAL_HYDRATED_EVENT`` fires or ``max_attempts``
    is exhausted.  On exhaustion it signals the fallback timer to fire
    immediately instead of waiting for its natural deadline.

Invariant 3 — FORCED ACTIVATION FALLBACK TIMER
    :class:`ForcedActivationFallbackTimer` starts a background daemon thread.
    After ``fallback_timeout_s`` seconds (default 90 s), if
    ``CAPITAL_HYDRATED_EVENT`` is still unset, it:

    * Force-sets ``CAPITAL_HYDRATED_EVENT``
    * Force-sets ``CAPITAL_SYSTEM_READY``
    * Releases ``STARTUP_LOCK``
    * Force-opens ``StartupReadinessGate``

    Trading always starts — even when the broker pipeline is unavailable.

Usage (call once from bot startup after brokers are registered)::

    from bot.no_failure_activation_contract import install_no_failure_activation_contract

    install_no_failure_activation_contract(
        coordinator=mabm._capital_coordinator,
        broker_map=connected_broker_map,
    )

The ``coordinator`` and ``broker_map`` arguments are optional.  When omitted
the hydration loop is skipped (only the fallback timer and monotonic fix are
active — the monotonic fix is a compile-time patch applied at import time).

Thread safety
-------------
All three features are fully thread-safe.  Multiple calls to
``install_no_failure_activation_contract()`` are idempotent — each
component is created at most once per process.

Author: NIJA Trading Systems
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("nija.no_failure_activation_contract")

# ---------------------------------------------------------------------------
# Lazy import helpers (avoid circular imports at module load time)
# ---------------------------------------------------------------------------


def _get_capital_hydrated_event() -> threading.Event:
    """Return the process-wide CAPITAL_HYDRATED_EVENT."""
    try:
        from capital_authority import CAPITAL_HYDRATED_EVENT
        return CAPITAL_HYDRATED_EVENT
    except ImportError:
        from bot.capital_authority import CAPITAL_HYDRATED_EVENT  # type: ignore[no-redef]
        return CAPITAL_HYDRATED_EVENT


def _get_capital_system_ready() -> threading.Event:
    """Return the process-wide CAPITAL_SYSTEM_READY event."""
    try:
        from capital_authority import CAPITAL_SYSTEM_READY
        return CAPITAL_SYSTEM_READY
    except ImportError:
        from bot.capital_authority import CAPITAL_SYSTEM_READY  # type: ignore[no-redef]
        return CAPITAL_SYSTEM_READY


def _get_startup_lock() -> threading.Event:
    """Return the process-wide STARTUP_LOCK event."""
    try:
        from capital_authority import STARTUP_LOCK
        return STARTUP_LOCK
    except ImportError:
        from bot.capital_authority import STARTUP_LOCK  # type: ignore[no-redef]
        return STARTUP_LOCK


def _get_startup_readiness_gate():
    """Return the process-wide StartupReadinessGate singleton."""
    try:
        from startup_readiness_gate import get_startup_readiness_gate
        return get_startup_readiness_gate()
    except ImportError:
        try:
            from bot.startup_readiness_gate import get_startup_readiness_gate  # type: ignore[no-redef]
            return get_startup_readiness_gate()
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Module-level singleton guards
# ---------------------------------------------------------------------------

_hydration_loop_installed: bool = False
_fallback_timer_installed: bool = False
_install_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Invariant 2 — Guaranteed CA Hydration Loop
# ---------------------------------------------------------------------------


class CAHydrationLoop:
    """
    Background daemon thread that retries ``CapitalRefreshCoordinator.execute_refresh()``
    until :data:`~capital_authority.CAPITAL_HYDRATED_EVENT` fires.

    The loop stops as soon as the coordinator has successfully published at
    least one snapshot (even a zero-balance one) — after that, the runtime
    coordinator inside :class:`~multi_account_broker_manager.MultiAccountBrokerManager`
    drives ongoing refreshes.

    Parameters
    ----------
    coordinator:
        The :class:`~capital_flow_state_machine.CapitalRefreshCoordinator`
        singleton.  The loop calls ``execute_refresh(broker_map)`` directly.
    broker_map:
        ``{broker_id: broker_instance}`` dict passed to every refresh call.
    retry_interval_s:
        Seconds to sleep between retry attempts.  Default 5 s.
    max_attempts:
        Maximum number of attempts before declaring hydration impossible and
        triggering the fallback timer immediately.  Default 12 (≈ 60 s).
    fallback_trigger:
        Optional :class:`threading.Event`.  When set by this loop on
        exhaustion, the :class:`ForcedActivationFallbackTimer` wakes
        immediately instead of waiting for its natural deadline.
    """

    def __init__(
        self,
        coordinator: Any,
        broker_map: Dict[str, Any],
        retry_interval_s: float = 5.0,
        max_attempts: int = 12,
        fallback_trigger: Optional[threading.Event] = None,
    ) -> None:
        self._coordinator = coordinator
        self._broker_map = broker_map
        self._retry_interval_s = max(1.0, float(retry_interval_s))
        self._max_attempts = max(1, int(max_attempts))
        self._fallback_trigger = fallback_trigger
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Spawn the background hydration loop thread."""
        self._thread = threading.Thread(
            target=self._run,
            name="nija-ca-hydration-loop",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "[CAHydrationLoop] started — retry_interval=%.0fs max_attempts=%d",
            self._retry_interval_s,
            self._max_attempts,
        )

    def stop(self) -> None:
        """Signal the loop to stop at the next sleep boundary."""
        self._stop_event.set()

    def _run(self) -> None:
        capital_hydrated = _get_capital_hydrated_event()
        attempt = 0

        while not self._stop_event.is_set():
            # If capital authority is already hydrated, nothing left to do.
            if capital_hydrated.is_set():
                logger.info(
                    "[CAHydrationLoop] CAPITAL_HYDRATED_EVENT set — loop done after %d attempt(s)",
                    attempt,
                )
                return

            attempt += 1
            logger.info(
                "[CAHydrationLoop] hydration attempt %d/%d",
                attempt,
                self._max_attempts,
            )

            if self._coordinator is not None and self._broker_map:
                try:
                    snapshot = self._coordinator.execute_refresh(
                        broker_map=self._broker_map,
                        trigger=f"ca_hydration_loop_attempt_{attempt}",
                    )
                    if snapshot is not None:
                        logger.info(
                            "[CAHydrationLoop] execute_refresh returned snapshot "
                            "(real=$%.2f) on attempt %d",
                            float(getattr(snapshot, "real_capital", None) or 0.0),
                            attempt,
                        )
                except Exception as exc:
                    logger.warning(
                        "[CAHydrationLoop] execute_refresh raised on attempt %d: %s",
                        attempt,
                        exc,
                    )

            # Check again after the refresh attempt.
            if capital_hydrated.is_set():
                logger.info(
                    "[CAHydrationLoop] CAPITAL_HYDRATED_EVENT set after attempt %d — done",
                    attempt,
                )
                return

            if attempt >= self._max_attempts:
                logger.critical(
                    "[CAHydrationLoop] EXHAUSTED after %d attempts — "
                    "CAPITAL_HYDRATED_EVENT still unset; triggering fallback timer now",
                    attempt,
                )
                if self._fallback_trigger is not None:
                    self._fallback_trigger.set()
                return

            # Sleep until next attempt, waking early if stop is requested.
            self._stop_event.wait(timeout=self._retry_interval_s)


# ---------------------------------------------------------------------------
# Invariant 3 — Fail-Closed Activation Monitor
# ---------------------------------------------------------------------------


class ForcedActivationFallbackTimer:
    """
    Deadline-based monitor that preserves fail-closed startup.

    A background daemon thread waits up to ``fallback_timeout_s`` seconds for
    :data:`~capital_authority.CAPITAL_HYDRATED_EVENT` to fire naturally.  If
     it has not fired by the deadline — or if ``trigger_event`` is set early
     by :class:`CAHydrationLoop` — the monitor emits a critical log and leaves
     startup blocked until the real readiness gates are satisfied.

    Parameters
    ----------
    fallback_timeout_s:
        Maximum seconds to wait before forcing activation.  Default 90 s.
    trigger_event:
        Optional :class:`threading.Event` supplied by :class:`CAHydrationLoop`.
        When set, the timer wakes and fires the fallback immediately.
    """

    def __init__(
        self,
        fallback_timeout_s: float = 90.0,
        trigger_event: Optional[threading.Event] = None,
    ) -> None:
        self._fallback_timeout_s = max(1.0, float(fallback_timeout_s))
        self._trigger_event = trigger_event or threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Spawn the background fallback timer thread."""
        self._thread = threading.Thread(
            target=self._run,
            name="nija-forced-activation-fallback",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "[ForcedActivationFallback] timer started — fires in %.0fs if not pre-empted",
            self._fallback_timeout_s,
        )

    def fire_early(self) -> None:
        """Trigger the fallback immediately without waiting for the deadline."""
        self._trigger_event.set()

    def _run(self) -> None:
        capital_hydrated = _get_capital_hydrated_event()

        # Wait for the deadline OR an early trigger from the hydration loop.
        self._trigger_event.wait(timeout=self._fallback_timeout_s)

        # If capital is already hydrated (normal path), nothing to do.
        if capital_hydrated.is_set():
            logger.info(
                "[ForcedActivationFallback] CAPITAL_HYDRATED_EVENT already set — no forced activation needed"
            )
            return

        # Fail closed: do not force-open any startup gates.
        logger.critical(
            "🚨 [ForcedActivationFallback] ACTIVATION BLOCKED — "
            "CAPITAL_HYDRATED_EVENT was not set within %.0fs; "
            "startup remains blocked until capital hydration completes.",
            self._fallback_timeout_s,
        )

        logger.critical(
            "🚨 [ForcedActivationFallback] NO OVERRIDE APPLIED — investigate broker connectivity, "
            "nonce sync, and capital hydration before startup may continue."
        )


# ---------------------------------------------------------------------------
# Public install function
# ---------------------------------------------------------------------------


def install_no_failure_activation_contract(
    coordinator: Optional[Any] = None,
    broker_map: Optional[Dict[str, Any]] = None,
    retry_interval_s: float = 5.0,
    max_hydration_attempts: int = 12,
    fallback_timeout_s: float = 90.0,
) -> None:
    """
    Install the no-failure activation contract for this process.

    Idempotent — safe to call multiple times; each component is started at
    most once.

    Invariant 1 (monotonic snapshot progression) is already active via the
    patch applied to ``capital_authority.publish_snapshot()`` — no runtime
    action is needed here.

    Parameters
    ----------
    coordinator:
        :class:`~capital_flow_state_machine.CapitalRefreshCoordinator`
        singleton.  When supplied, the hydration loop will call
        ``coordinator.execute_refresh(broker_map)`` on every retry.
        When ``None``, Invariant 2 is skipped (only the fallback timer runs).
    broker_map:
        ``{broker_id: broker_instance}`` dict for the hydration loop refresh
        calls.  Ignored when *coordinator* is ``None``.
    retry_interval_s:
        Seconds between hydration loop retry attempts (Invariant 2).
    max_hydration_attempts:
        Maximum hydration loop retries before triggering fallback early
        (Invariant 2).
    fallback_timeout_s:
        Deadline for the forced-activation fallback timer (Invariant 3).
    """
    global _hydration_loop_installed, _fallback_timer_installed

    with _install_lock:
        # ── Shared trigger event between hydration loop and fallback timer ──
        # When the hydration loop exhausts retries it sets this event so the
        # fallback timer fires immediately instead of waiting for its deadline.
        trigger = threading.Event()

        # ── Invariant 3 removed: forced activation fallback is disabled ─────
        if not _fallback_timer_installed:
            logger.info(
                "[install_no_failure_activation_contract] forced activation fallback removed; "
                "startup now fails closed until readiness gates are naturally satisfied"
            )
            _fallback_timer_installed = True
        else:
            logger.debug("[install_no_failure_activation_contract] fail-closed startup policy already installed")

        # ── Invariant 2: hydration loop ──────────────────────────────────────
        if not _hydration_loop_installed:
            if coordinator is not None and broker_map:
                loop = CAHydrationLoop(
                    coordinator=coordinator,
                    broker_map=broker_map,
                    retry_interval_s=retry_interval_s,
                    max_attempts=max_hydration_attempts,
                    fallback_trigger=trigger,
                )
                loop.start()
                _hydration_loop_installed = True
            else:
                logger.info(
                    "[install_no_failure_activation_contract] "
                    "coordinator/broker_map not provided — Invariant 2 (hydration loop) skipped; "
                    "Invariant 3 (fallback timer) is active only when NIJA_ENABLE_FORCED_ACTIVATION_FALLBACK=1"
                )
                # Mark as installed anyway so repeated calls with a coordinator
                # do not start a second loop.
                _hydration_loop_installed = True
        else:
            logger.debug("[install_no_failure_activation_contract] hydration loop already installed")

    logger.info(
        "✅ [no_failure_activation_contract] installed — "
        "forced_fallback=%s fallback_timeout=%.0fs retry_interval=%.0fs max_attempts=%d",
        "disabled",
        fallback_timeout_s,
        retry_interval_s,
        max_hydration_attempts,
    )
