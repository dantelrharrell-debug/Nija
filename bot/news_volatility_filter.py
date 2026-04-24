"""
NIJA Phase 3 — News / Event Volatility Filter
===============================================

Detects abnormal price and volume spikes that are characteristic of news
events, economic releases, or black-swan moments and suppresses new entries
during these high-risk windows.

Two complementary detection mechanisms
----------------------------------------
1. **Automatic spike detection** — monitors rolling price returns and volume
   to spot sudden deviations beyond configurable z-score thresholds.  No
   external data feed required.

2. **Manual event injection** — operators (or a future news-API integration)
   can call ``register_event()`` to mark a known event time and impose a
   trading cooldown around it.

Cooldown behaviour
------------------
* Entry cooldown triggers when a spike or event is detected.
* The cooldown window is configurable (default 5 minutes).
* Multiple events extend the cooldown from the most recent trigger.
* After the cooldown the filter automatically clears and normal trading resumes.

Usage
-----
::

    from bot.news_volatility_filter import get_news_volatility_filter

    filt = get_news_volatility_filter()

    # Feed each closed bar (price + volume):
    filt.update(symbol="BTC-USD", close=105_000.0, volume=1_500.0)

    # Check before entry:
    ok, reason = filt.can_enter(symbol="BTC-USD")
    if not ok:
        logger.warning("Entry blocked: %s", reason)

    # Manual event (e.g. FOMC announcement):
    filt.register_event("FOMC rate decision", impact="HIGH")

Author: NIJA Trading Systems
Version: 1.0 — Phase 3
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Deque, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.news_volatility_filter")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class NewsVolatilityConfig:
    # ── Spike detection ──────────────────────────────────────────────────
    # Rolling window (bars) used to compute baseline volatility / volume
    rolling_window: int = 20

    # z-score threshold above which a bar is considered a spike
    price_spike_zscore: float = 3.0
    volume_spike_zscore: float = 3.5

    # Minimum absolute price return (%) to even consider a spike
    min_price_move_pct: float = 1.5   # ignore tiny moves even if z-score high

    # ── Cooldown ─────────────────────────────────────────────────────────
    # How long to suppress entries after a spike / event (minutes)
    cooldown_minutes: float = 5.0

    # Extra cooldown for HIGH-impact events registered manually
    high_impact_cooldown_minutes: float = 15.0

    # ── Per-symbol tracking ───────────────────────────────────────────────
    # Track each symbol independently (True) or use a global cooldown (False)
    per_symbol: bool = True


# ---------------------------------------------------------------------------
# Internal state per symbol
# ---------------------------------------------------------------------------

@dataclass
class _SymbolState:
    closes: Deque[float] = field(default_factory=lambda: deque(maxlen=100))
    volumes: Deque[float] = field(default_factory=lambda: deque(maxlen=100))
    cooldown_until: Optional[datetime] = None
    last_spike_reason: str = ""
    spike_count: int = 0


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class NewsVolatilityFilter:
    """
    Combined automatic spike detector + manual event injector.

    Thread-safe.
    """

    def __init__(self, config: Optional[NewsVolatilityConfig] = None) -> None:
        self._cfg = config or NewsVolatilityConfig()
        self._lock = threading.Lock()

        # Per-symbol state
        self._symbols: Dict[str, _SymbolState] = {}

        # Global events (affect all symbols)
        self._global_events: List[Tuple[datetime, str, str]] = []  # (time, name, impact)
        self._global_cooldown_until: Optional[datetime] = None

        logger.info(
            "✅ NewsVolatilityFilter initialised  "
            "spike_z=%.1f  vol_z=%.1f  cooldown=%.1fmin",
            self._cfg.price_spike_zscore,
            self._cfg.volume_spike_zscore,
            self._cfg.cooldown_minutes,
        )

    # ------------------------------------------------------------------
    # Feed data
    # ------------------------------------------------------------------

    def update(
        self,
        symbol: str,
        close: float,
        volume: float = 0.0,
    ) -> bool:
        """
        Feed a new closed bar.  Returns True if a spike was detected.

        Call this for every completed candle of every symbol you trade.
        """
        with self._lock:
            state = self._get_state(symbol)

            spike_detected = False
            spike_reason = ""

            # Only check after we have enough history
            if len(state.closes) >= self._cfg.rolling_window:
                # ── Price return spike ────────────────────────────────────
                prev_close = state.closes[-1]
                if prev_close > 0:
                    ret_pct = abs(close - prev_close) / prev_close * 100.0
                    if ret_pct >= self._cfg.min_price_move_pct:
                        mean_ret, std_ret = self._stats(
                            [abs(c2 - c1) / c1 * 100.0
                             for c1, c2 in zip(list(state.closes)[:-1],
                                               list(state.closes)[1:])
                             if c1 > 0]
                        )
                        if std_ret > 0:
                            z = (ret_pct - mean_ret) / std_ret
                            if z >= self._cfg.price_spike_zscore:
                                spike_detected = True
                                spike_reason = (
                                    f"Price spike z={z:.1f} "
                                    f"({ret_pct:.2f}% move on {symbol})"
                                )

                # ── Volume spike ──────────────────────────────────────────
                if not spike_detected and volume > 0 and len(state.volumes) >= self._cfg.rolling_window:
                    mean_vol, std_vol = self._stats(list(state.volumes))
                    if std_vol > 0:
                        z_vol = (volume - mean_vol) / std_vol
                        if z_vol >= self._cfg.volume_spike_zscore:
                            spike_detected = True
                            spike_reason = (
                                f"Volume spike z={z_vol:.1f} "
                                f"on {symbol}"
                            )

            # Update history
            state.closes.append(close)
            if volume > 0:
                state.volumes.append(volume)

            if spike_detected:
                state.spike_count += 1
                state.last_spike_reason = spike_reason
                cooldown_end = datetime.utcnow() + timedelta(
                    minutes=self._cfg.cooldown_minutes
                )
                state.cooldown_until = cooldown_end
                logger.warning(
                    "⚠️ Volatility spike detected on %s — entry cooldown until %s  [%s]",
                    symbol, cooldown_end.strftime("%H:%M:%S"), spike_reason,
                )

            return spike_detected

    # ------------------------------------------------------------------
    # Manual event injection
    # ------------------------------------------------------------------

    def register_event(
        self,
        name: str,
        impact: str = "HIGH",
        event_time: Optional[datetime] = None,
    ) -> None:
        """
        Manually register a news / economic event.

        ``impact`` should be "HIGH", "MEDIUM", or "LOW".
        HIGH events use the extended ``high_impact_cooldown_minutes``.
        """
        with self._lock:
            ts = event_time or datetime.utcnow()
            self._global_events.append((ts, name, impact.upper()))

            cooldown_mins = (
                self._cfg.high_impact_cooldown_minutes
                if impact.upper() == "HIGH"
                else self._cfg.cooldown_minutes
            )
            cooldown_end = ts + timedelta(minutes=cooldown_mins)
            if (
                self._global_cooldown_until is None
                or cooldown_end > self._global_cooldown_until
            ):
                self._global_cooldown_until = cooldown_end

            logger.warning(
                "📰 News event registered: '%s' [%s]  "
                "global entry cooldown until %s",
                name, impact.upper(),
                cooldown_end.strftime("%H:%M:%S UTC"),
            )

    # ------------------------------------------------------------------
    # Entry gate
    # ------------------------------------------------------------------

    def can_enter(self, symbol: Optional[str] = None) -> Tuple[bool, str]:
        """
        Check whether entries are allowed right now.

        ``symbol`` is optional — if None, only the global cooldown is checked.

        Returns ``(True, "ok")`` when entries are allowed, or
        ``(False, reason)`` when they are blocked.
        """
        now = datetime.utcnow()
        with self._lock:
            # Global cooldown
            if (
                self._global_cooldown_until is not None
                and now < self._global_cooldown_until
            ):
                remaining = (self._global_cooldown_until - now).total_seconds()
                return False, (
                    f"Global news/event cooldown active — "
                    f"{remaining:.0f}s remaining"
                )

            # Per-symbol cooldown
            if symbol and self._cfg.per_symbol:
                state = self._symbols.get(symbol)
                if (
                    state is not None
                    and state.cooldown_until is not None
                    and now < state.cooldown_until
                ):
                    remaining = (state.cooldown_until - now).total_seconds()
                    return False, (
                        f"Volatility cooldown on {symbol} — "
                        f"{remaining:.0f}s remaining  "
                        f"[{state.last_spike_reason}]"
                    )

        return True, "ok"

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_status(self) -> Dict:
        """Return a human-readable status dict."""
        now = datetime.utcnow()
        with self._lock:
            return {
                "global_cooldown_active": (
                    self._global_cooldown_until is not None
                    and now < self._global_cooldown_until
                ),
                "global_cooldown_until": (
                    self._global_cooldown_until.isoformat()
                    if self._global_cooldown_until else None
                ),
                "recent_events": [
                    {"time": ts.isoformat(), "name": name, "impact": impact}
                    for ts, name, impact in self._global_events[-5:]
                ],
                "symbols_in_cooldown": [
                    sym
                    for sym, state in self._symbols.items()
                    if state.cooldown_until and now < state.cooldown_until
                ],
                "total_spikes_detected": sum(
                    s.spike_count for s in self._symbols.values()
                ),
            }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_state(self, symbol: str) -> _SymbolState:
        if symbol not in self._symbols:
            self._symbols[symbol] = _SymbolState()
        return self._symbols[symbol]

    @staticmethod
    def _stats(values: List[float]) -> Tuple[float, float]:
        """Return (mean, std) for a list of values."""
        if not values:
            return 0.0, 0.0
        n = len(values)
        mean = sum(values) / n
        variance = sum((v - mean) ** 2 for v in values) / n
        std = variance ** 0.5
        return mean, std


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[NewsVolatilityFilter] = None
_instance_lock = threading.Lock()


def get_news_volatility_filter(
    config: Optional[NewsVolatilityConfig] = None,
) -> NewsVolatilityFilter:
    """Return the process-wide singleton NewsVolatilityFilter."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = NewsVolatilityFilter(config=config)
    return _instance
