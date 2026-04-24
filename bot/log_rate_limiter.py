"""
NIJA Log Rate Limiter
======================

Prevents high-frequency log flooding that can degrade system performance during
rapid market scans (732+ symbols every 2.5 minutes).

The limiter works by associating a *key* (typically a combination of symbol,
message category, and log level) with a cooldown window.  Subsequent calls for
the same key within the window are counted but silently suppressed; when the
window expires the suppression count is flushed as a single summary line so
nothing is completely lost.

Design principles:
- Zero external dependencies (stdlib only).
- Thread-safe for multi-threaded scan loops.
- Low overhead on the hot path (dict lookup + monotonic clock read).
- Singleton via ``get_log_rate_limiter()`` – one shared instance per process.

Usage
-----
::

    from bot.log_rate_limiter import get_log_rate_limiter

    _rl = get_log_rate_limiter()

    # Throttle an INFO message to at most once every 30 s per symbol
    if _rl.allow("scan_signal", symbol, window_seconds=30):
        logger.info("   📈 %s: signal detected …", symbol)

    # With automatic suppression-count summary (recommended)
    allowed, suppressed = _rl.allow_with_count("scan_signal", symbol, window_seconds=30)
    if allowed:
        if suppressed:
            logger.debug("   (suppressed %d duplicate messages for %s)", suppressed, symbol)
        logger.info("   📈 %s: signal detected …", symbol)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

logger = logging.getLogger("nija.log_rate_limiter")

# ---------------------------------------------------------------------------
# Silent-mode globals
# ---------------------------------------------------------------------------

#: When True, all window_seconds values are multiplied by
#: ``SILENT_MODE_MULTIPLIER`` so only very slow-changing summaries get through.
#: Activate via the ``NIJA_SILENT_MODE=1`` environment variable or by calling
#: :func:`enable_silent_mode` at runtime.
_silent_mode: bool = os.environ.get("NIJA_SILENT_MODE", "0").strip() in ("1", "true", "yes")

#: How much to stretch every throttle window when silent mode is active.
#: Override via ``NIJA_SILENT_MODE_MULTIPLIER`` (default 10×).
SILENT_MODE_MULTIPLIER: float = float(
    os.environ.get("NIJA_SILENT_MODE_MULTIPLIER", "10.0")
)

_silent_lock = threading.Lock()


def enable_silent_mode() -> None:
    """Activate silent mode: all throttle windows are stretched by SILENT_MODE_MULTIPLIER."""
    global _silent_mode
    with _silent_lock:
        _silent_mode = True
    logger.info(
        "🔇 LogRateLimiter: silent mode ENABLED (window multiplier=%.0f×)",
        SILENT_MODE_MULTIPLIER,
    )


def disable_silent_mode() -> None:
    """Deactivate silent mode: throttle windows revert to their caller-specified values."""
    global _silent_mode
    with _silent_lock:
        _silent_mode = False
    logger.info("🔊 LogRateLimiter: silent mode DISABLED")

# ---------------------------------------------------------------------------
# Per-key state
# ---------------------------------------------------------------------------

@dataclass
class _KeyState:
    """Internal state tracked for a single throttle key."""
    last_allowed_ts: float = 0.0   # monotonic timestamp of the last allowed emit
    suppressed_count: int = 0       # messages suppressed since last allowed emit


# ---------------------------------------------------------------------------
# LogRateLimiter
# ---------------------------------------------------------------------------

class LogRateLimiter:
    """
    Thread-safe per-key log-rate limiter.

    Each *key* is a string that groups related log messages (e.g.
    ``"scan_signal:BTC-USD"``).  At most one message per key is allowed
    through within *window_seconds*.  All subsequent calls within the window
    are counted as suppressed.  When the window expires, ``allow()`` returns
    ``True`` again and ``allow_with_count()`` returns the suppression count
    so callers can emit an optional summary line.
    """

    def __init__(self, default_window_seconds: float = 60.0) -> None:
        """
        Args:
            default_window_seconds: Default cooldown when callers omit
                ``window_seconds``.  Individual calls may override this.
        """
        self._default_window = default_window_seconds
        self._states: Dict[str, _KeyState] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    def allow(
        self,
        category: str,
        key: str = "",
        window_seconds: Optional[float] = None,
    ) -> bool:
        """
        Return ``True`` if the log message should be emitted.

        Args:
            category:       Message category (e.g. ``"scan_signal"``).
            key:            Optional per-instance key (e.g. a symbol name).
                            Combined with *category* to form the throttle key.
            window_seconds: Override the default cooldown for this call.

        Returns:
            ``True``  → caller should emit the log message.
            ``False`` → message is suppressed (caller should skip logging).
        """
        allowed, _ = self.allow_with_count(category, key, window_seconds)
        return allowed

    def allow_with_count(
        self,
        category: str,
        key: str = "",
        window_seconds: Optional[float] = None,
    ) -> Tuple[bool, int]:
        """
        Return ``(allowed, suppressed_since_last_emit)``.

        When ``allowed`` is ``True`` the returned ``suppressed_since_last_emit``
        is the number of messages that were silently dropped since the previous
        allowed emit so callers can optionally emit a summary line.

        Args:
            category:       Message category string.
            key:            Per-instance key (e.g. symbol).
            window_seconds: Cooldown override.

        Returns:
            ``(True, N)``  → emit allowed; N messages were suppressed before this.
            ``(False, 0)`` → suppressed; suppression count not yet flushed.
        """
        window = window_seconds if window_seconds is not None else self._default_window
        # In silent mode stretch every window by the global multiplier so only
        # slow-changing summary lines get through and verbose scan noise is muted.
        with _silent_lock:
            if _silent_mode:
                window = window * SILENT_MODE_MULTIPLIER
        composite_key = f"{category}:{key}" if key else category
        now = time.monotonic()

        with self._lock:
            state = self._states.get(composite_key)
            if state is None:
                state = _KeyState()
                self._states[composite_key] = state

            elapsed = now - state.last_allowed_ts
            if elapsed >= window:
                # Window expired — allow this message
                suppressed = state.suppressed_count
                state.last_allowed_ts = now
                state.suppressed_count = 0
                return True, suppressed
            else:
                # Still within window — suppress
                state.suppressed_count += 1
                return False, 0

    def reset(self, category: str, key: str = "") -> None:
        """Force-expire the window for *category*/*key* so the next call is always allowed."""
        composite_key = f"{category}:{key}" if key else category
        with self._lock:
            if composite_key in self._states:
                self._states[composite_key].last_allowed_ts = 0.0
                self._states[composite_key].suppressed_count = 0

    def reset_all(self) -> None:
        """Clear all throttle state (useful on strategy restart or hard reset)."""
        with self._lock:
            self._states.clear()

    def get_stats(self) -> Dict[str, Dict]:
        """Return a snapshot of all active throttle keys for diagnostics."""
        now = time.monotonic()
        with self._lock:
            return {
                k: {
                    "suppressed": s.suppressed_count,
                    "seconds_since_last_emit": round(now - s.last_allowed_ts, 1),
                }
                for k, s in self._states.items()
            }

    def total_suppressed(self) -> int:
        """Return the total number of messages currently suppressed across all keys."""
        with self._lock:
            return sum(s.suppressed_count for s in self._states.values())


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_instance: Optional[LogRateLimiter] = None
_instance_lock = threading.Lock()


def get_log_rate_limiter(
    default_window_seconds: float = 60.0,
) -> LogRateLimiter:
    """
    Return the process-wide ``LogRateLimiter`` singleton.

    Args:
        default_window_seconds: Used only on the *first* call to set the
            default window.  Subsequent calls return the existing instance
            regardless of this argument.
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = LogRateLimiter(
                    default_window_seconds=default_window_seconds
                )
                logger.debug(
                    "LogRateLimiter initialized (default_window=%.0fs)",
                    default_window_seconds,
                )
    return _instance
