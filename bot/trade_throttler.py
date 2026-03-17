"""
NIJA Trade Throttler
=====================

**Priority-2 gate** -- improves consistency by preventing overtrading through
sliding-window rate limits.

Three overlapping counters are checked before every trade entry:

* ``max_per_minute``   (default 3)  -- burst protection
* ``max_per_hour``     (default 20) -- hourly cap
* ``max_per_day``      (default 50) -- daily cap
* ``min_gap_seconds``  (default 5)  -- minimum seconds between any two trades

A trade is **allowed** only when all four limits are satisfied.  Call
``record_trade()`` after a trade executes to register it against all windows.

Usage
-----
::

    from bot.trade_throttler import get_trade_throttler

    throttler = get_trade_throttler()

    allowed, reason = throttler.check()
    if not allowed:
        logger.warning("Trade throttled: %s", reason)
        return

    # ... execute the trade ...

    throttler.record_trade(symbol="BTC-USD")

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque, Optional, Tuple

logger = logging.getLogger("nija.trade_throttler")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class ThrottlerConfig:
    """Rate-limit thresholds for the trade throttler."""

    max_per_minute: int = 3
    max_per_hour: int = 20
    max_per_day: int = 50
    min_gap_seconds: float = 5.0


# ---------------------------------------------------------------------------
# Throttler
# ---------------------------------------------------------------------------


class TradeThrottler:
    """Priority-2 gate: sliding-window rate limiter for trade entries.

    Thread-safe singleton via ``get_trade_throttler()``.
    """

    _MINUTE: float = 60.0
    _HOUR: float = 3_600.0
    _DAY: float = 86_400.0

    def __init__(self, config: Optional[ThrottlerConfig] = None) -> None:
        self._cfg = config or ThrottlerConfig()
        self._lock = threading.Lock()

        # Ring buffers of UNIX timestamps (float) for recent trades
        # maxlen = hard cap so the deque never grows unbounded
        self._ts_minute: Deque[float] = deque(maxlen=self._cfg.max_per_minute + 10)
        self._ts_hour: Deque[float] = deque(maxlen=self._cfg.max_per_hour + 10)
        self._ts_day: Deque[float] = deque(maxlen=self._cfg.max_per_day + 10)

        self._last_trade_ts: float = 0.0

        # Stats
        self._total_allowed: int = 0
        self._total_throttled: int = 0

        logger.info(
            "TradeThrottler initialised | per_min=%d | per_hr=%d | per_day=%d | gap=%.1fs",
            self._cfg.max_per_minute,
            self._cfg.max_per_hour,
            self._cfg.max_per_day,
            self._cfg.min_gap_seconds,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self) -> Tuple[bool, str]:
        """Check whether a new trade entry is within the rate limits.

        Returns
        -------
        (allowed, reason)
            ``allowed`` is ``False`` when any limit is exceeded.
        """
        now = time.monotonic()

        with self._lock:
            self._evict(now)

            # --- minimum gap between trades ---
            gap = now - self._last_trade_ts
            if gap < self._cfg.min_gap_seconds:
                remaining = self._cfg.min_gap_seconds - gap
                reason = (
                    f"Trade throttled: minimum gap {self._cfg.min_gap_seconds:.1f}s "
                    f"not elapsed (wait {remaining:.1f}s)"
                )
                self._total_throttled += 1
                logger.debug(reason)
                return False, reason

            # --- per-minute cap ---
            if len(self._ts_minute) >= self._cfg.max_per_minute:
                reason = (
                    f"Trade throttled: {self._cfg.max_per_minute} trades/min cap reached "
                    f"({len(self._ts_minute)} in last 60s)"
                )
                self._total_throttled += 1
                logger.warning(reason)
                return False, reason

            # --- per-hour cap ---
            if len(self._ts_hour) >= self._cfg.max_per_hour:
                reason = (
                    f"Trade throttled: {self._cfg.max_per_hour} trades/hr cap reached "
                    f"({len(self._ts_hour)} in last 60min)"
                )
                self._total_throttled += 1
                logger.warning(reason)
                return False, reason

            # --- per-day cap ---
            if len(self._ts_day) >= self._cfg.max_per_day:
                reason = (
                    f"Trade throttled: {self._cfg.max_per_day} trades/day cap reached "
                    f"({len(self._ts_day)} today)"
                )
                self._total_throttled += 1
                logger.warning(reason)
                return False, reason

            self._total_allowed += 1
            return True, "OK"

    def record_trade(self, symbol: str = "") -> None:
        """Register a trade that has just been submitted.

        Must be called **after** a trade executes (not before) so that the
        counters accurately reflect completed activity.

        Parameters
        ----------
        symbol:
            Optional symbol label used in logging.
        """
        now = time.monotonic()
        with self._lock:
            self._ts_minute.append(now)
            self._ts_hour.append(now)
            self._ts_day.append(now)
            self._last_trade_ts = now

        logger.info(
            "TradeThrottler: trade recorded%s | window counts: 1min=%d 1hr=%d 1day=%d",
            f" ({symbol})" if symbol else "",
            len(self._ts_minute),
            len(self._ts_hour),
            len(self._ts_day),
        )

    def get_status(self) -> dict:
        """Return a JSON-serialisable status snapshot."""
        now = time.monotonic()
        with self._lock:
            self._evict(now)
            return {
                "trades_last_minute": len(self._ts_minute),
                "trades_last_hour": len(self._ts_hour),
                "trades_today": len(self._ts_day),
                "seconds_since_last_trade": round(now - self._last_trade_ts, 1),
                "max_per_minute": self._cfg.max_per_minute,
                "max_per_hour": self._cfg.max_per_hour,
                "max_per_day": self._cfg.max_per_day,
                "min_gap_seconds": self._cfg.min_gap_seconds,
                "total_allowed": self._total_allowed,
                "total_throttled": self._total_throttled,
            }

    def reset_daily_counter(self) -> None:
        """Manually reset the daily counter (e.g. at midnight UTC)."""
        with self._lock:
            self._ts_day.clear()
        logger.info("TradeThrottler: daily counter reset")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evict(self, now: float) -> None:
        """Remove timestamps that have fallen outside their window."""
        cutoff_min = now - self._MINUTE
        cutoff_hr = now - self._HOUR
        cutoff_day = now - self._DAY

        while self._ts_minute and self._ts_minute[0] < cutoff_min:
            self._ts_minute.popleft()
        while self._ts_hour and self._ts_hour[0] < cutoff_hr:
            self._ts_hour.popleft()
        while self._ts_day and self._ts_day[0] < cutoff_day:
            self._ts_day.popleft()


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_instance: Optional[TradeThrottler] = None
_instance_lock = threading.Lock()


def get_trade_throttler(config: Optional[ThrottlerConfig] = None) -> TradeThrottler:
    """Return the process-wide :class:`TradeThrottler` singleton.

    Parameters
    ----------
    config:
        Optional configuration; only used on the **first** call.
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = TradeThrottler(config)
    return _instance
