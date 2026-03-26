"""
NIJA Session Awareness
========================
Adjusts entry confidence and position sizing based on the current UTC
time-of-day trading session.

Session table (all times UTC):

    DEAD_ZONE    00-05   crypto weekend/weeknight dead zone
                         confidence -0.08 | size x0.70
    ASIA_ACTIVE  05-08   Asia market activity begins
                         confidence -0.03 | size x0.90
    LONDON_OPEN  08-10   London open -- elevated volatility
                         confidence +0.05 | size x1.10
    LONDON_PEAK  10-12   London peak liquidity window
                         confidence +0.03 | size x1.05
    LUNCH_LAG    12-14   London--US crossover lull
                         confidence -0.05 | size x0.85
    US_OPEN      14-16   US market open -- highest volatility window
                         confidence +0.08 | size x1.15
    US_PEAK      16-19   US peak session
                         confidence +0.05 | size x1.10
    US_CLOSE     19-22   US session wind-down
                         confidence -0.02 | size x0.95
    NIGHT        22-24   Late-night global lull
                         confidence -0.06 | size x0.75

Usage
-----
    from bot.session_awareness import get_session_awareness

    sa  = get_session_awareness()
    ses = sa.get_session()          # uses current UTC hour

    # Apply to sniper confidence
    sf_confidence = min(1.0, sf_confidence + ses.confidence_delta)

    # Apply to position size
    position_size *= ses.size_multiplier
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("nija.session_awareness")


# ---------------------------------------------------------------------------
# Session config dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SessionConfig:
    """Trading parameters for a single UTC time window."""
    name: str
    hour_start: int        # inclusive [0-23]
    hour_end: int          # exclusive [1-24]
    confidence_delta: float
    size_multiplier: float
    description: str


# ---------------------------------------------------------------------------
# Session table
# ---------------------------------------------------------------------------

_SESSIONS = (
    SessionConfig("DEAD_ZONE",    0,  5, -0.08, 0.70, "Crypto dead zone -- low volume"),
    SessionConfig("ASIA_ACTIVE",  5,  8, -0.03, 0.90, "Asia markets active"),
    SessionConfig("LONDON_OPEN",  8, 10, +0.05, 1.10, "London open -- elevated volatility"),
    SessionConfig("LONDON_PEAK", 10, 12, +0.03, 1.05, "London peak liquidity"),
    SessionConfig("LUNCH_LAG",   12, 14, -0.05, 0.85, "London-US crossover lull"),
    SessionConfig("US_OPEN",     14, 16, +0.08, 1.15, "US market open -- peak volatility"),
    SessionConfig("US_PEAK",     16, 19, +0.05, 1.10, "US peak session"),
    SessionConfig("US_CLOSE",    19, 22, -0.02, 0.95, "US session wind-down"),
    SessionConfig("NIGHT",       22, 24, -0.06, 0.75, "Late-night global lull"),
)

_NEUTRAL = SessionConfig("NEUTRAL", 0, 24, 0.0, 1.0, "Neutral fallback")


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class SessionAwareness:
    """
    Thread-safe trading session detector.

    Call ``get_session(hour_utc)`` to obtain the active SessionConfig and
    read its ``confidence_delta`` and ``size_multiplier`` fields.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_session_name: str = ""
        logger.info(
            "✅ SessionAwareness initialised — %d sessions configured",
            len(_SESSIONS),
        )

    def get_session(self, hour_utc: Optional[int] = None) -> SessionConfig:
        """
        Return the SessionConfig for the given UTC hour.

        Args:
            hour_utc: UTC hour (0-23). Uses ``datetime.now(UTC).hour`` if None.

        Returns:
            The matching SessionConfig, or the neutral fallback.
        """
        if hour_utc is None:
            hour_utc = datetime.now(timezone.utc).hour

        for session in _SESSIONS:
            if session.hour_start <= hour_utc < session.hour_end:
                with self._lock:
                    if session.name != self._last_session_name:
                        self._last_session_name = session.name
                        logger.info(
                            "Session -> %s (%02d:00 UTC)  "
                            "conf_delta=%+.2f  size_mult=%.2fx  [%s]",
                            session.name, hour_utc,
                            session.confidence_delta,
                            session.size_multiplier,
                            session.description,
                        )
                return session

        return _NEUTRAL

    def get_report(self) -> dict:
        """Return a JSON-serialisable snapshot of the current session."""
        session = self.get_session()
        return {
            "current_session":  session.name,
            "hour_utc":         datetime.now(timezone.utc).hour,
            "confidence_delta": session.confidence_delta,
            "size_multiplier":  session.size_multiplier,
            "description":      session.description,
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[SessionAwareness] = None
_lock = threading.Lock()


def get_session_awareness() -> SessionAwareness:
    """Return the process-wide singleton SessionAwareness."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = SessionAwareness()
    return _instance
