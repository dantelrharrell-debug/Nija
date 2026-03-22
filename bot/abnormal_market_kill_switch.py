"""
NIJA Phase 3 — Abnormal Market Kill Switch
===========================================

Monitors market data in real-time and **automatically** activates the
system-wide kill switch when abnormal conditions are detected.  This is
distinct from the manual / operator-triggered kill switch: it acts as an
automated circuit-breaker for scenarios like flash crashes, exchange outages,
extreme volatility, or correlated-liquidation cascades.

Detection criteria (all configurable)
--------------------------------------
* **Flash crash**       — Price drops ≥ N% within a single candle.
* **Extreme volatility**— ATR ratio (current / baseline) exceeds threshold.
* **Volume explosion**  — Volume ≥ N× the rolling average in a single bar.
* **Bid-ask blowout**   — Spread widens beyond an acceptable limit (optional).
* **Consecutive losses**— Too many sequential losing trades in a short window.
* **API error storm**   — Rapid-fire exchange errors exceed error-rate limit.

Escalation logic
----------------
Each trigger category increments a rolling threat score.  The kill switch
fires when:

    current_threat_score  ≥  kill_threshold  (default 3.0)

This prevents a single noisy signal from halting the bot — two independent
warnings in a short time window are required.  Scores decay with a half-life
of ``score_decay_minutes`` (default 10 min).

After activation the kill switch **must be manually deactivated** via the
standard ``KillSwitch.deactivate()`` interface to resume trading.  This
prevents the bot from auto-restarting into a still-broken market.

Usage
-----
::

    from bot.abnormal_market_kill_switch import get_abnormal_market_ks

    aks = get_abnormal_market_ks()

    # Feed each closed bar:
    aks.update_market(symbol="BTC-USD", close=105_000.0,
                      high=106_000.0, low=103_000.0, volume=1_200.0,
                      spread_pct=0.0005)

    # Record trade outcomes:
    aks.record_trade(pnl_usd=-50.0, is_win=False)

    # Record API errors:
    aks.record_api_error()

    # Manual check (also called internally after update_market):
    triggered, reason = aks.check_and_trigger()

Author: NIJA Trading Systems
Version: 1.0 — Phase 3
Date: March 2026
"""

from __future__ import annotations

import logging
import math
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Deque, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.abnormal_market_kill_switch")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class AbnormalMarketConfig:
    # ── Flash-crash detection ────────────────────────────────────────────
    flash_crash_pct: float = 5.0       # single-candle drop/rise this % → score += 1.5
    flash_crash_score: float = 1.5

    # ── Extreme volatility (ATR ratio) ──────────────────────────────────
    atr_period: int = 14
    extreme_atr_ratio: float = 4.0     # current ATR / baseline ATR > 4× → score += 1.0
    extreme_atr_score: float = 1.0

    # ── Volume explosion ─────────────────────────────────────────────────
    volume_window: int = 20
    volume_explosion_multiplier: float = 10.0   # 10× average volume → score += 0.75
    volume_explosion_score: float = 0.75

    # ── Spread blowout (if spread data is available) ─────────────────────
    max_spread_pct: float = 0.02       # 2 % spread → score += 0.5
    spread_blowout_score: float = 0.5

    # ── Consecutive losses circuit ────────────────────────────────────────
    max_consecutive_losses: int = 7    # 7 in a row → score += 1.0
    consecutive_loss_score: float = 1.0

    # ── API error storm ───────────────────────────────────────────────────
    api_error_window_seconds: int = 60  # rolling window
    api_error_threshold: int = 10       # ≥10 errors in window → score += 1.5
    api_error_storm_score: float = 1.5

    # ── Kill threshold ────────────────────────────────────────────────────
    kill_threshold: float = 3.0        # cumulative threat score to fire kill switch

    # ── Score decay ───────────────────────────────────────────────────────
    score_decay_minutes: float = 10.0  # half-life for threat score decay

    # ── ATR baseline window ───────────────────────────────────────────────
    atr_baseline_window: int = 50


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class AbnormalMarketKillSwitch:
    """
    Automated kill switch that fires on abnormal market / system conditions.

    Integrates with the existing :class:`~bot.kill_switch.KillSwitch` via a
    lazy import so the module can be used standalone in tests without the full
    bot stack.
    """

    def __init__(self, config: Optional[AbnormalMarketConfig] = None) -> None:
        self._cfg = config or AbnormalMarketConfig()
        self._lock = threading.Lock()

        # Per-symbol OHLCV history for ATR / volume baseline
        self._sym_closes: Dict[str, Deque[float]] = {}
        self._sym_highs:  Dict[str, Deque[float]] = {}
        self._sym_lows:   Dict[str, Deque[float]] = {}
        self._sym_vols:   Dict[str, Deque[float]] = {}

        # Threat score with timestamps for decay
        self._score_events: Deque[Tuple[datetime, float, str]] = deque(maxlen=200)

        # Consecutive loss tracking
        self._consecutive_losses: int = 0

        # API error timestamps
        self._api_errors: Deque[datetime] = deque(maxlen=500)

        # Activation state
        self._activated: bool = False
        self._activation_reason: str = ""

        logger.info(
            "✅ AbnormalMarketKillSwitch initialised  "
            "kill_threshold=%.1f  decay=%.0fmin",
            self._cfg.kill_threshold,
            self._cfg.score_decay_minutes,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_market(
        self,
        symbol: str,
        close: float,
        high: float,
        low: float,
        volume: float = 0.0,
        spread_pct: float = 0.0,
    ) -> None:
        """
        Feed a newly closed bar for ``symbol``.

        Internally checks for flash-crash, extreme volatility, volume
        explosion, and spread blowout.  Calls ``check_and_trigger()``
        automatically at the end.
        """
        with self._lock:
            if self._activated:
                return  # Already fired — nothing to do

            # Initialise per-symbol buffers
            if symbol not in self._sym_closes:
                maxlen = max(self._cfg.atr_baseline_window + 5, 100)
                self._sym_closes[symbol] = deque(maxlen=maxlen)
                self._sym_highs[symbol]  = deque(maxlen=maxlen)
                self._sym_lows[symbol]   = deque(maxlen=maxlen)
                self._sym_vols[symbol]   = deque(maxlen=maxlen)

            closes = self._sym_closes[symbol]
            highs  = self._sym_highs[symbol]
            lows   = self._sym_lows[symbol]
            vols   = self._sym_vols[symbol]

            # ── Flash-crash / spike ───────────────────────────────────────
            if closes:
                prev_close = closes[-1]
                if prev_close > 0:
                    move_pct = abs(close - prev_close) / prev_close * 100.0
                    if move_pct >= self._cfg.flash_crash_pct:
                        reason = (
                            f"Flash crash/spike on {symbol}: "
                            f"{move_pct:.2f}% move in single candle"
                        )
                        self._add_score(self._cfg.flash_crash_score, reason)

            # Append new bar
            closes.append(close)
            highs.append(high)
            lows.append(low)
            if volume > 0:
                vols.append(volume)

            # ── Extreme ATR ───────────────────────────────────────────────
            if len(closes) >= self._cfg.atr_period + self._cfg.atr_baseline_window:
                current_atr = self._calc_atr(
                    list(highs)[-self._cfg.atr_period:],
                    list(lows)[-self._cfg.atr_period:],
                    list(closes)[-self._cfg.atr_period - 1: -1],
                )
                baseline_atr = self._calc_atr(
                    list(highs)[-(self._cfg.atr_period + self._cfg.atr_baseline_window):
                                -self._cfg.atr_baseline_window],
                    list(lows)[-(self._cfg.atr_period + self._cfg.atr_baseline_window):
                               -self._cfg.atr_baseline_window],
                    list(closes)[-(self._cfg.atr_period + self._cfg.atr_baseline_window + 1):
                                 -self._cfg.atr_baseline_window - 1],
                )
                if baseline_atr > 0:
                    ratio = current_atr / baseline_atr
                    if ratio >= self._cfg.extreme_atr_ratio:
                        reason = (
                            f"Extreme volatility on {symbol}: "
                            f"ATR ratio={ratio:.1f}× baseline"
                        )
                        self._add_score(self._cfg.extreme_atr_score, reason)

            # ── Volume explosion ──────────────────────────────────────────
            if (
                volume > 0
                and len(vols) >= self._cfg.volume_window + 1
            ):
                baseline_vols = list(vols)[-(self._cfg.volume_window + 1): -1]
                if baseline_vols:
                    mean_vol = sum(baseline_vols) / len(baseline_vols)
                    if mean_vol > 0:
                        vol_ratio = volume / mean_vol
                        if vol_ratio >= self._cfg.volume_explosion_multiplier:
                            reason = (
                                f"Volume explosion on {symbol}: "
                                f"{vol_ratio:.1f}× average volume"
                            )
                            self._add_score(self._cfg.volume_explosion_score, reason)

            # ── Spread blowout ────────────────────────────────────────────
            if spread_pct > 0 and spread_pct >= self._cfg.max_spread_pct:
                reason = (
                    f"Spread blowout on {symbol}: "
                    f"spread={spread_pct*100:.2f}%"
                )
                self._add_score(self._cfg.spread_blowout_score, reason)

        # Check outside lock to allow other threads to proceed
        self.check_and_trigger()

    def record_trade(self, pnl_usd: float, is_win: bool) -> None:
        """Feed trade result for consecutive-loss detection."""
        with self._lock:
            if self._activated:
                return
            if not is_win:
                self._consecutive_losses += 1
                if self._consecutive_losses >= self._cfg.max_consecutive_losses:
                    reason = (
                        f"{self._consecutive_losses} consecutive losses — "
                        "abnormal strategy behaviour"
                    )
                    self._add_score(self._cfg.consecutive_loss_score, reason)
            else:
                self._consecutive_losses = 0

    def record_api_error(self) -> None:
        """Record a broker/exchange API error for storm detection."""
        with self._lock:
            if self._activated:
                return
            now = datetime.utcnow()
            self._api_errors.append(now)

            # Count errors within the window
            cutoff = now - timedelta(seconds=self._cfg.api_error_window_seconds)
            recent = sum(1 for t in self._api_errors if t >= cutoff)
            if recent >= self._cfg.api_error_threshold:
                reason = (
                    f"API error storm: {recent} errors in "
                    f"{self._cfg.api_error_window_seconds}s"
                )
                self._add_score(self._cfg.api_error_storm_score, reason)

    def check_and_trigger(self) -> Tuple[bool, str]:
        """
        Evaluate the current threat score and trigger the kill switch if needed.

        Returns ``(triggered, reason)``.  Safe to call frequently.
        """
        with self._lock:
            if self._activated:
                return True, self._activation_reason

            score = self._current_score()
            if score < self._cfg.kill_threshold:
                return False, f"Threat score={score:.2f} (threshold={self._cfg.kill_threshold})"

            # Compile reason from recent score events
            top_reasons = [
                f"{pts:.2f}pt {rsn}"
                for _, pts, rsn in sorted(
                    self._score_events, key=lambda x: x[1], reverse=True
                )[:3]
            ]
            reason = (
                f"Abnormal market conditions — "
                f"threat score={score:.2f} ≥ {self._cfg.kill_threshold}. "
                f"Triggers: {'; '.join(top_reasons)}"
            )
            self._activated = True
            self._activation_reason = reason

        # Fire kill switch (outside main lock to avoid deadlock)
        logger.critical(
            "🚨 ABNORMAL MARKET KILL SWITCH ACTIVATED: %s", reason
        )
        try:
            from kill_switch import get_kill_switch
        except ImportError:
            try:
                from bot.kill_switch import get_kill_switch
            except ImportError:
                get_kill_switch = None  # type: ignore

        if get_kill_switch is not None:
            try:
                ks = get_kill_switch()
                if not ks.is_active():
                    ks.activate(reason, source="ABNORMAL_MARKET_KILL_SWITCH")
            except Exception as exc:
                logger.error("❌ Failed to activate kill switch: %s", exc)

        return True, reason

    def get_status(self) -> Dict:
        """Return a human-readable status dict."""
        with self._lock:
            score = self._current_score()
            return {
                "activated": self._activated,
                "activation_reason": self._activation_reason,
                "current_threat_score": round(score, 3),
                "kill_threshold": self._cfg.kill_threshold,
                "consecutive_losses": self._consecutive_losses,
                "recent_score_events": [
                    {"time": ts.isoformat(), "score": pts, "reason": rsn}
                    for ts, pts, rsn in list(self._score_events)[-5:]
                ],
            }

    def reset(self) -> None:
        """
        Reset the abnormal market detector state.

        Does NOT deactivate the underlying KillSwitch — that must be done
        explicitly by an operator.
        """
        with self._lock:
            self._score_events.clear()
            self._consecutive_losses = 0
            self._api_errors.clear()
            self._activated = False
            self._activation_reason = ""
        logger.info("🔄 AbnormalMarketKillSwitch state reset")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _add_score(self, points: float, reason: str) -> None:
        """Add a threat score event (must be called with self._lock held)."""
        logger.warning("⚠️ Threat score +%.2f: %s", points, reason)
        self._score_events.append((datetime.utcnow(), points, reason))

    def _current_score(self) -> float:
        """
        Calculate the current cumulative threat score with exponential decay.
        Must be called with self._lock held.
        """
        now = datetime.utcnow()
        half_life = self._cfg.score_decay_minutes * 60.0  # seconds
        total = 0.0
        for ts, pts, _ in self._score_events:
            age_seconds = (now - ts).total_seconds()
            decayed = pts * math.exp(-0.693 * age_seconds / half_life)
            total += decayed
        return total

    @staticmethod
    def _calc_atr(
        highs: List[float],
        lows: List[float],
        prev_closes: List[float],
    ) -> float:
        """Simple ATR calculation."""
        if not highs or not lows or not prev_closes:
            return 0.0
        trs = []
        for h, lo, pc in zip(highs, lows, prev_closes):
            tr = max(h - lo, abs(h - pc), abs(lo - pc))
            trs.append(tr)
        return sum(trs) / len(trs) if trs else 0.0


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[AbnormalMarketKillSwitch] = None
_instance_lock = threading.Lock()


def get_abnormal_market_ks(
    config: Optional[AbnormalMarketConfig] = None,
) -> AbnormalMarketKillSwitch:
    """Return the process-wide singleton AbnormalMarketKillSwitch."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = AbnormalMarketKillSwitch(config=config)
    return _instance
