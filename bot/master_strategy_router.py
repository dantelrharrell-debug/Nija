"""
NIJA Master Strategy Router
============================

Provides a single authoritative trading signal shared across all registered
broker accounts so that every account reacts to ONE master decision rather
than each account running its own independent strategy.

Architecture
------------
::

    ┌─────────────────────────────────────────────────────────┐
    │               MasterStrategyRouter (singleton)           │
    │                                                         │
    │  current_signal: dict | None                            │
    │                                                         │
    │  update(signal)   ← called by the MASTER/platform       │
    │                     account after analyze_market()       │
    │                                                         │
    │  get_signal()     → returns latest master signal        │
    │                     (all accounts read from here)       │
    └─────────────────────────────────────────────────────────┘

Usage
-----
::

    from bot.master_strategy_router import get_master_strategy_router

    router = get_master_strategy_router()

    # Master (platform) account — after analysis:
    router.update(analysis)

    # All accounts — replace local signal derivation:
    signal = router.get_signal()
    action = signal.get('action', 'hold') if signal else 'hold'

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("nija.master_router")


class MasterStrategyRouter:
    """
    Holds the current master trading signal and distributes it to all
    accounts so they all act on a single coordinated decision.
    """

    def __init__(self) -> None:
        self.current_signal: Optional[Dict[str, Any]] = None
        self._last_updated: Optional[str] = None
        self._lock = threading.Lock()

    def update(self, signal: Dict[str, Any]) -> None:
        """
        Store the latest signal emitted by the master (platform) strategy.

        Args:
            signal: Analysis dict from ``ApexStrategy.analyze_market()``,
                    must contain at minimum ``{'action': str}``.
        """
        with self._lock:
            self.current_signal = signal
            self._last_updated = datetime.now(timezone.utc).isoformat()
            action = signal.get('action', 'hold') if signal else 'hold'
            logger.debug(
                "[MasterRouter] signal updated → action=%s at %s",
                action, self._last_updated,
            )

    def get_signal(self) -> Optional[Dict[str, Any]]:
        """
        Return the current master signal, or *None* if no signal has been
        set yet (callers should fall back to their local analysis in that case).
        """
        with self._lock:
            return self.current_signal

    def clear(self) -> None:
        """Reset the stored signal (e.g. at the start of each trading cycle)."""
        with self._lock:
            self.current_signal = None
            self._last_updated = None

    @property
    def last_updated(self) -> Optional[str]:
        """ISO-8601 timestamp of the last ``update()`` call, or None."""
        with self._lock:
            return self._last_updated


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_ROUTER: Optional[MasterStrategyRouter] = None
_ROUTER_LOCK = threading.Lock()


def get_master_strategy_router() -> MasterStrategyRouter:
    """Return the process-wide MasterStrategyRouter singleton."""
    global _ROUTER
    with _ROUTER_LOCK:
        if _ROUTER is None:
            _ROUTER = MasterStrategyRouter()
            logger.info("[MasterRouter] singleton created — one master signal for all accounts")
    return _ROUTER
