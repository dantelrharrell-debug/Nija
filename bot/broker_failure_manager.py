# bot/broker_failure_manager.py
"""NIJA broker failure manager.

Tracks broker-local health and reconnect backoff. A failed venue is halted in its
own broker cell; its capital share is left idle and is never redistributed to
another brokerage account.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.supervisor")

FAILURE_THRESHOLD: int = int(os.environ.get("NIJA_BROKER_FAILURE_THRESHOLD", "5"))
_BACKOFF_SCHEDULE: List[float] = [15.0, 30.0, 60.0]


@dataclass
class _BrokerState:
    name: str
    initial_allocation: float = 1.0
    consecutive_errors: int = 0
    total_errors: int = 0
    total_successes: int = 0
    is_dead: bool = False
    dead_since: Optional[float] = None
    retry_attempts: int = 0
    last_retry_time: Optional[float] = None
    last_error_reason: str = ""


def _halt_broker_cell(broker_name: str, reason: str) -> None:
    """Best-effort synchronization to the canonical broker-cell boundary."""
    try:
        from bot.broker_isolation_registry import get_broker_isolation_registry
        get_broker_isolation_registry().halt_cell(
            broker_name,
            f"broker_failure_manager:{reason or 'failure_threshold'}",
        )
    except Exception as exc:
        logger.warning(
            "BROKER_FAILURE_CELL_HALT_SYNC_FAILED broker=%s error=%s:%s",
            broker_name,
            type(exc).__name__,
            exc,
        )


def _resume_broker_cell(broker_name: str) -> None:
    """Best-effort synchronization after a proven broker recovery."""
    try:
        from bot.broker_isolation_registry import get_broker_isolation_registry
        get_broker_isolation_registry().resume_cell(broker_name)
    except Exception as exc:
        logger.warning(
            "BROKER_FAILURE_CELL_RESUME_SYNC_FAILED broker=%s error=%s:%s",
            broker_name,
            type(exc).__name__,
            exc,
        )


class BrokerFailureManager:
    """Thread-safe, venue-local broker health/circuit manager."""

    def __init__(self, failure_threshold: int = FAILURE_THRESHOLD) -> None:
        self._failure_threshold = max(1, int(failure_threshold))
        self._states: Dict[str, _BrokerState] = {}
        self._lock = threading.RLock()

    def register_broker(self, broker_name: str, initial_allocation: float = 1.0) -> None:
        name = str(broker_name).lower()
        with self._lock:
            if name not in self._states:
                self._states[name] = _BrokerState(
                    name=name,
                    initial_allocation=max(0.0, float(initial_allocation)),
                )
                logger.info(
                    "BrokerFailureManager registered broker=%s local_capital_share=%.4f threshold=%d",
                    name,
                    initial_allocation,
                    self._failure_threshold,
                )

    def record_error(self, broker_name: str, reason: str = "") -> bool:
        name = str(broker_name).lower()
        newly_dead = False
        last_reason = str(reason or "")[:200]
        with self._lock:
            state = self._get_or_create(name)
            state.consecutive_errors += 1
            state.total_errors += 1
            if last_reason:
                state.last_error_reason = last_reason
            if not state.is_dead and state.consecutive_errors >= self._failure_threshold:
                state.is_dead = True
                state.dead_since = time.monotonic()
                state.retry_attempts = 0
                newly_dead = True
                logger.error(
                    "BROKER_LOCAL_CIRCUIT_OPEN broker=%s errors=%d reason=%s capital_redistributed=false",
                    name,
                    state.consecutive_errors,
                    state.last_error_reason or "unspecified",
                )
            else:
                logger.warning(
                    "BROKER_LOCAL_FAILURE broker=%s error_count=%d/%d reason=%s",
                    name,
                    state.consecutive_errors,
                    self._failure_threshold,
                    last_reason or "unspecified",
                )
        if newly_dead:
            _halt_broker_cell(name, last_reason)
        return newly_dead

    def record_success(self, broker_name: str) -> bool:
        name = str(broker_name).lower()
        revived = False
        with self._lock:
            state = self._get_or_create(name)
            state.total_successes += 1
            revived = state.is_dead
            state.consecutive_errors = 0
            state.last_error_reason = ""
            if revived:
                state.is_dead = False
                state.dead_since = None
                state.retry_attempts = 0
                logger.info(
                    "BROKER_LOCAL_CIRCUIT_RECOVERED broker=%s capital_redistributed=false",
                    name,
                )
        if revived:
            _resume_broker_cell(name)
        return revived

    def is_dead(self, broker_name: str) -> bool:
        with self._lock:
            state = self._states.get(str(broker_name).lower())
            return bool(state.is_dead) if state else False

    def get_retry_delay(self, broker_name: str) -> float:
        name = str(broker_name).lower()
        with self._lock:
            state = self._get_or_create(name)
            idx = min(state.retry_attempts, len(_BACKOFF_SCHEDULE) - 1)
            delay = _BACKOFF_SCHEDULE[idx]
            state.retry_attempts += 1
            state.last_retry_time = time.monotonic()
            return delay

    def revive_broker(self, broker_name: str) -> None:
        name = str(broker_name).lower()
        was_dead = False
        with self._lock:
            state = self._get_or_create(name)
            was_dead = state.is_dead
            state.is_dead = False
            state.consecutive_errors = 0
            state.dead_since = None
            state.retry_attempts = 0
            state.last_error_reason = ""
        if was_dead:
            logger.info("BROKER_LOCAL_MANUAL_REVIVE broker=%s", name)
            _resume_broker_cell(name)

    def _baseline_allocation_weights_locked(self) -> Dict[str, float]:
        """Preserve original shares; dead-broker shares become idle, never reassigned."""
        baseline_total = sum(max(0.0, s.initial_allocation) for s in self._states.values())
        if baseline_total <= 0.0:
            return {name: 0.0 for name in self._states}
        return {
            name: (0.0 if state.is_dead else max(0.0, state.initial_allocation) / baseline_total)
            for name, state in self._states.items()
        }

    def get_active_allocation_weights(self) -> Dict[str, float]:
        """Return non-dead brokers' preserved baseline shares.

        Values intentionally may sum to less than 1.0. The missing fraction is
        capital belonging to failed venues and remains idle rather than moving
        to another broker.
        """
        with self._lock:
            weights = self._baseline_allocation_weights_locked()
            return {name: weight for name, weight in weights.items() if weight > 0.0}

    def get_active_dead_lists(self) -> Tuple[List[str], List[str]]:
        with self._lock:
            active = sorted(name for name, state in self._states.items() if not state.is_dead)
            dead = sorted(name for name, state in self._states.items() if state.is_dead)
            return active, dead

    def get_consecutive_errors(self, broker_name: str) -> int:
        with self._lock:
            state = self._states.get(str(broker_name).lower())
            return state.consecutive_errors if state else 0

    def log_active_dead_banner(self) -> None:
        with self._lock:
            weights = self._baseline_allocation_weights_locked()
            active = [(name, weights.get(name, 0.0)) for name, state in self._states.items() if not state.is_dead]
            dead = [(name, state) for name, state in self._states.items() if state.is_dead]

        line = "-" * 60
        logger.info(line)
        logger.info("BROKER FAILURE MANAGER - VENUE-LOCAL STATUS")
        logger.info("Capital redistribution across brokers: DISABLED")
        for name, weight in sorted(active):
            logger.info("ACTIVE broker=%s preserved_capital_share=%.1f%%", name, weight * 100.0)
        for name, state in sorted(dead):
            logger.info(
                "DEAD broker=%s errors=%d preserved_capital_share=IDLE reason=%s",
                name,
                state.consecutive_errors,
                state.last_error_reason or "n/a",
            )
        logger.info(line)

    def get_status(self) -> Dict:
        with self._lock:
            weights = self._baseline_allocation_weights_locked()
            return {
                name: {
                    "is_dead": state.is_dead,
                    "consecutive_errors": state.consecutive_errors,
                    "total_errors": state.total_errors,
                    "total_successes": state.total_successes,
                    "last_error_reason": state.last_error_reason,
                    "retry_attempts": state.retry_attempts,
                    "allocation_weight": weights.get(name, 0.0),
                    "capital_redistributed": False,
                }
                for name, state in self._states.items()
            }

    def _get_or_create(self, broker_name: str) -> _BrokerState:
        name = str(broker_name).lower()
        if name not in self._states:
            self._states[name] = _BrokerState(name=name)
        return self._states[name]


_instance: Optional[BrokerFailureManager] = None
_instance_lock = threading.Lock()


def get_broker_failure_manager(failure_threshold: Optional[int] = None) -> BrokerFailureManager:
    global _instance
    with _instance_lock:
        if _instance is None:
            threshold = failure_threshold if failure_threshold is not None else FAILURE_THRESHOLD
            _instance = BrokerFailureManager(failure_threshold=threshold)
            logger.info("BrokerFailureManager singleton created threshold=%d", threshold)
        return _instance


def reset_broker_failure_manager() -> None:
    global _instance
    with _instance_lock:
        _instance = None
