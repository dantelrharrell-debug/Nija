"""
No-Failure Activation Contract
================================

Runtime startup hydration helpers.

Safety rule for live Redis deployments
--------------------------------------
A live Redis deployment must fail closed. ``FORCE_TRADE`` and related operator
flags may request extra diagnostics, but they must never force-set readiness
keys, release the startup lock, or bypass distributed writer authority.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("nija.no_failure_activation_contract")
_TRUTHY = {"1", "true", "yes", "on", "enabled", "y"}
_FORCE_FLAGS = ("FORCE_TRADE", "FORCE_TRADE_MODE", "FORCE_LIVE_TRANSITION", "NIJA_FORCE_ACTIVATION")


# ---------------------------------------------------------------------------
# Environment / policy helpers
# ---------------------------------------------------------------------------


def _truthy(name: str, default: str = "") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUTHY


def _redis_configured() -> bool:
    return bool(
        str(os.environ.get("NIJA_REDIS_URL", "")).strip()
        or str(os.environ.get("REDIS_URL", "")).strip()
        or str(os.environ.get("REDIS_PRIVATE_URL", "")).strip()
        or str(os.environ.get("REDIS_PUBLIC_URL", "")).strip()
    )


def _live_mode() -> bool:
    return not _truthy("DRY_RUN_MODE") and not _truthy("PAPER_MODE")


def _live_redis_mode() -> bool:
    return _live_mode() and _redis_configured()


def _force_requested() -> bool:
    return any(_truthy(flag) for flag in _FORCE_FLAGS)


def _sanitize_live_force_flags(reason: str) -> bool:
    """Clear force flags in live Redis mode and return True if anything changed."""
    if not _live_redis_mode():
        return False
    cleared: list[str] = []
    for flag in _FORCE_FLAGS:
        if _truthy(flag):
            os.environ[flag] = "false"
            cleared.append(flag)
    if cleared:
        logger.critical(
            "LIVE_REDIS_FORCE_ACTIVATION_BLOCKED reason=%s cleared=%s — startup remains fail-closed",
            reason,
            ",".join(cleared),
        )
        return True
    return False


def _forced_activation_allowed() -> bool:
    """Return True only for explicitly allowed non-live-Redis recovery flows."""
    _sanitize_live_force_flags("policy_check")
    if _live_redis_mode():
        return False
    return _force_requested() and _truthy("NIJA_ALLOW_FORCED_ACTIVATION_FALLBACK")


# ---------------------------------------------------------------------------
# Lazy import helpers (avoid circular imports at module load time)
# ---------------------------------------------------------------------------


def _get_capital_hydrated_event() -> threading.Event:
    try:
        from capital_authority import CAPITAL_HYDRATED_EVENT
        return CAPITAL_HYDRATED_EVENT
    except ImportError:
        from bot.capital_authority import CAPITAL_HYDRATED_EVENT  # type: ignore[no-redef]
        return CAPITAL_HYDRATED_EVENT


def _get_capital_system_ready() -> threading.Event:
    try:
        from capital_authority import CAPITAL_SYSTEM_READY
        return CAPITAL_SYSTEM_READY
    except ImportError:
        from bot.capital_authority import CAPITAL_SYSTEM_READY  # type: ignore[no-redef]
        return CAPITAL_SYSTEM_READY


def _get_startup_lock() -> threading.Event:
    try:
        from capital_authority import STARTUP_LOCK
        return STARTUP_LOCK
    except ImportError:
        from bot.capital_authority import STARTUP_LOCK  # type: ignore[no-redef]
        return STARTUP_LOCK


def _get_readiness_table():
    try:
        from bot.readiness_table import mark_ready, snapshot
        return mark_ready, snapshot
    except ImportError:
        try:
            from readiness_table import mark_ready, snapshot  # type: ignore[import]
            return mark_ready, snapshot
        except ImportError:
            return None, None


# ---------------------------------------------------------------------------
# Module-level singleton guards
# ---------------------------------------------------------------------------

_hydration_loop_installed: bool = False
_fallback_timer_installed: bool = False
_install_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Guaranteed CA Hydration Loop
# ---------------------------------------------------------------------------


class CAHydrationLoop:
    """Background loop that retries CapitalRefreshCoordinator.execute_refresh()."""

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
        self._stop_event.set()

    def _run(self) -> None:
        capital_hydrated = _get_capital_hydrated_event()
        attempt = 0
        bootstrap_balance_probe = None
        try:
            from bot.bootstrap_utils import resolve_bootstrap_balance_probe
            bootstrap_balance_probe = resolve_bootstrap_balance_probe()
        except ImportError:
            bootstrap_balance_probe = None

        while not self._stop_event.is_set():
            _sanitize_live_force_flags("hydration_loop")
            if bootstrap_balance_probe is not None and bootstrap_balance_probe():
                logger.info("Stopping startup balance loop")
                logger.debug(
                    "[CAHydrationLoop] bootstrap FSM reports BALANCE_HYDRATED — exiting hydration loop"
                )
                return
            if capital_hydrated.is_set():
                logger.info(
                    "[CAHydrationLoop] CAPITAL_HYDRATED_EVENT set — loop done after %d attempt(s)",
                    attempt,
                )
                return

            attempt += 1
            logger.info("[CAHydrationLoop] hydration attempt %d/%d", attempt, self._max_attempts)

            if self._coordinator is not None and self._broker_map:
                try:
                    snapshot = self._coordinator.execute_refresh(
                        broker_map=self._broker_map,
                        trigger=f"ca_hydration_loop_attempt_{attempt}",
                    )
                    if snapshot is not None:
                        logger.info(
                            "[CAHydrationLoop] execute_refresh returned snapshot (real=$%.2f) on attempt %d",
                            float(getattr(snapshot, "real_capital", None) or 0.0),
                            attempt,
                        )
                except Exception as exc:
                    logger.warning(
                        "[CAHydrationLoop] execute_refresh raised on attempt %d: %s",
                        attempt,
                        exc,
                    )

            if capital_hydrated.is_set():
                logger.info(
                    "[CAHydrationLoop] CAPITAL_HYDRATED_EVENT set after attempt %d — done",
                    attempt,
                )
                return
            if attempt >= self._max_attempts:
                logger.critical(
                    "[CAHydrationLoop] EXHAUSTED after %d attempts — CAPITAL_HYDRATED_EVENT still unset",
                    attempt,
                )
                if self._fallback_trigger is not None and _forced_activation_allowed():
                    self._fallback_trigger.set()
                else:
                    logger.critical(
                        "[CAHydrationLoop] fallback trigger suppressed — forced activation is not allowed by policy"
                    )
                return

            self._stop_event.wait(timeout=self._retry_interval_s)


# ---------------------------------------------------------------------------
# Fail-Closed Activation Monitor
# ---------------------------------------------------------------------------


class ForcedActivationFallbackTimer:
    """Deadline monitor that never force-opens live Redis startup gates."""

    def __init__(
        self,
        fallback_timeout_s: float = 90.0,
        trigger_event: Optional[threading.Event] = None,
    ) -> None:
        self._fallback_timeout_s = max(1.0, float(fallback_timeout_s))
        self._trigger_event = trigger_event or threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run,
            name="nija-forced-activation-fallback",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "[ForcedActivationFallback] timer started — deadline=%.0fs policy=fail_closed_live_redis",
            self._fallback_timeout_s,
        )

    def fire_early(self) -> None:
        self._trigger_event.set()

    def _run(self) -> None:
        capital_hydrated = _get_capital_hydrated_event()
        self._trigger_event.wait(timeout=self._fallback_timeout_s)

        if capital_hydrated.is_set():
            logger.info(
                "[ForcedActivationFallback] CAPITAL_HYDRATED_EVENT already set — no fallback needed"
            )
            return

        if _forced_activation_allowed():
            logger.warning(
                "⚠️ [ForcedActivationFallback] non-live-Redis forced fallback explicitly allowed — setting startup gates"
            )
            try:
                capital_hydrated.set()
                _get_capital_system_ready().set()
                _get_startup_lock().set()
                rt_mark_ready, _ = _get_readiness_table()
                if rt_mark_ready is not None:
                    for key in (
                        "broker_connected",
                        "balance_hydrated",
                        "capital_ready",
                        "risk_ready",
                        "strategy_ready",
                        "execution_ready",
                        "nonce_ready",
                        "bootstrap_ready",
                    ):
                        rt_mark_ready(key)
            except Exception as exc:
                logger.warning("[ForcedActivationFallback] allowed fallback failed: %s", exc)
            return

        logger.critical(
            "🚨 [ForcedActivationFallback] ACTIVATION BLOCKED — CAPITAL_HYDRATED_EVENT was not set within %.0fs; startup remains fail-closed until real readiness gates pass.",
            self._fallback_timeout_s,
        )
        logger.critical(
            "🚨 [ForcedActivationFallback] NO OVERRIDE APPLIED — FORCE_TRADE cannot force-open live Redis startup gates."
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
    """Install startup hydration helpers exactly once per process."""
    global _hydration_loop_installed, _fallback_timer_installed

    _sanitize_live_force_flags("install")
    force_requested = _force_requested()
    force_allowed = _forced_activation_allowed()

    with _install_lock:
        trigger = threading.Event()

        if not _fallback_timer_installed:
            if force_allowed:
                logger.warning(
                    "⚠️ [install_no_failure_activation_contract] forced fallback enabled for non-live-Redis recovery only"
                )
                fallback_timer = ForcedActivationFallbackTimer(
                    fallback_timeout_s=fallback_timeout_s,
                    trigger_event=trigger,
                )
                fallback_timer.start()
            else:
                if force_requested:
                    logger.critical(
                        "LIVE_REDIS_FORCE_ACTIVATION_SUPPRESSED — FORCE_TRADE requested but fallback timer not started"
                    )
                logger.info(
                    "[install_no_failure_activation_contract] forced activation fallback disabled; startup fails closed until readiness gates are naturally satisfied"
                )
            _fallback_timer_installed = True
        else:
            logger.debug("[install_no_failure_activation_contract] fallback timer policy already installed")

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
                    "[install_no_failure_activation_contract] coordinator/broker_map not provided — hydration loop skipped"
                )
                _hydration_loop_installed = True
        else:
            logger.debug("[install_no_failure_activation_contract] hydration loop already installed")

    logger.info(
        "✅ [no_failure_activation_contract] installed — force_requested=%s forced_fallback=%s fallback_timeout=%.0fs retry_interval=%.0fs max_attempts=%d live_redis=%s",
        force_requested,
        "enabled" if force_allowed else "disabled",
        fallback_timeout_s,
        retry_interval_s,
        max_hydration_attempts,
        _live_redis_mode(),
    )
