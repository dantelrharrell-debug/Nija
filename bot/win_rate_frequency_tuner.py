"""
NIJA Win-Rate / Frequency Tuner
=================================

Real money is made at the **intersection** of win rate and trade frequency.
Neither metric alone is enough:

* A 90% win rate on 1 trade a week earns very little.
* 20 trades a day at 40% win rate can destroy an account.
* The sweet spot is the highest Expected Value *per hour* (EV/hr).

How it works
------------
The engine observes every closed trade and maintains a rolling window of
outcomes.  From those it derives:

  win_rate        Rolling win percentage over the last ``WINDOW_SIZE`` trades.
  avg_win_usd     Rolling average profit on winning trades (USD).
  avg_loss_usd    Rolling average loss on losing trades (USD, positive).
  trades_per_hour Trade frequency measured over the last 24 h of real time.
  ev_per_trade    win_rate × avg_win − (1 − win_rate) × avg_loss
  ev_per_hour     ev_per_trade × trades_per_hour

Using those metrics it selects one of four ``FrequencyMode`` states and
emits a ``confidence_delta`` that the caller should add to the base
confidence gate before feeding it into the sniper / entry filter:

  QUALITY     Win rate is strong (≥ WIN_RATE_QUALITY) AND frequency is
              adequate.  No change — keep the gate tight.

  BALANCED    Win rate is in the neutral band.  No change.

  LOOSEN      Win rate is healthy (≥ WIN_RATE_LOOSEN_OK) but frequency is
              below ``MIN_TRADES_PER_HOUR`` target.  Loosen the confidence
              gate slightly so more valid setups pass through.

  TIGHTEN     Win rate has fallen below ``WIN_RATE_TIGHTEN``.  Raise the
              confidence gate to protect capital and recover the edge.

The delta is bounded by ``MAX_CONFIDENCE_DELTA`` so the engine can never
override the sniper filter completely — it nudges rather than controls.

Integration
-----------
::

    # After a trade closes:
    from bot.win_rate_frequency_tuner import get_win_rate_frequency_tuner
    tuner = get_win_rate_frequency_tuner()
    tuner.record_trade(pnl_usd=12.50, is_win=True)

    # Before the sniper / confidence gate:
    params = tuner.get_params()
    effective_confidence = max(0.0, min(1.0, raw_confidence + params.confidence_delta))

    # Reporting / dashboard:
    report = tuner.get_report()

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import threading
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Deque, Dict, List, Optional

logger = logging.getLogger("nija.win_rate_frequency_tuner")

# ---------------------------------------------------------------------------
# Tuneable constants
# ---------------------------------------------------------------------------

# Rolling window: how many recent trades to evaluate
WINDOW_SIZE: int = 30

# Minimum trades before the engine starts nudging thresholds
MIN_TRADES_BEFORE_TUNING: int = 10

# Win-rate thresholds
# Tuned for the $25/day target at micro balances ($74 → $1K growth path):
#   • TIGHTEN raised 0.45 → 0.48 so the gate tightens before win rate erodes
#     too far, protecting compounding gains earlier.
#   • QUALITY kept at 0.65 — the optimal target win rate for sustainable edge.
WIN_RATE_QUALITY: float = 0.65    # ≥ 65% → QUALITY mode (stay tight)
WIN_RATE_LOOSEN_OK: float = 0.55  # ≥ 55% win rate is healthy enough to accept more trades
WIN_RATE_TIGHTEN: float = 0.48    # < 48% → TIGHTEN mode (raised from 0.45 to protect capital sooner)

# Target trade frequency (trades per hour, measured over a 24-h rolling window).
# Tuned for micro accounts: targeting ~15 quality trades/day = 0.625 trades/hr on
# a 24-h window.  Set to 0.7 so LOOSEN activates when frequency drops below that,
# keeping daily trade count close to the minimum needed to hit $25/day.
MIN_TRADES_PER_HOUR: float = 0.7   # trigger LOOSEN if below ~17 trades/24 h

# Maximum nudge applied to the confidence gate in either direction.
# Keep it small — the goal is to tune, not to override the entry signal.
MAX_CONFIDENCE_DELTA: float = 0.12   # ±12 pp absolute maximum
LOOSEN_STEP: float = 0.02            # nudge down per LOOSEN activation (finer, was 0.03)
TIGHTEN_STEP: float = 0.04           # nudge up per TIGHTEN activation

# Frequency measurement window (seconds)
FREQUENCY_WINDOW_SECONDS: float = 24 * 3600   # 24 h

# State persistence path (relative to repo root; can be overridden)
DEFAULT_STATE_PATH: str = "/tmp/nija_win_rate_frequency_tuner.json"
DEFAULT_AUDIT_PATH: str = "/tmp/nija_win_rate_frequency_tuner_audit.jsonl"


# ---------------------------------------------------------------------------
# Enumerations & data classes
# ---------------------------------------------------------------------------

class FrequencyMode(str, Enum):
    """Operating mode selected by the tuner based on current performance."""
    QUALITY   = "QUALITY"    # win rate strong & frequency adequate — hold tight
    BALANCED  = "BALANCED"   # neutral band — no nudge
    LOOSEN    = "LOOSEN"     # win rate ok but under-trading — loosen gate
    TIGHTEN   = "TIGHTEN"    # win rate too low — tighten gate


@dataclass
class TradeSample:
    """Minimal record kept in the rolling window."""
    pnl_usd: float
    is_win: bool
    timestamp: str   # ISO-8601


@dataclass
class FrequencyTuneParams:
    """
    Live parameters emitted by the tuner.  Apply ``confidence_delta`` to the
    raw signal confidence before passing it into the entry gate.
    """
    mode: FrequencyMode
    win_rate: float            # rolling win-rate in window (0–1)
    trades_in_window: int      # number of trades in the rolling window
    trades_per_hour: float     # observed trade frequency (24 h)
    avg_win_usd: float         # average winning trade (USD)
    avg_loss_usd: float        # average losing trade (USD, positive)
    ev_per_trade: float        # expected value per trade (USD)
    ev_per_hour: float         # expected value per hour (USD)
    confidence_delta: float    # add this to base confidence gate (−MAX … +MAX)
    reason: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

class WinRateFrequencyTuner:
    """
    Continuously tunes the confidence gate to maximise EV-per-hour.

    Thread-safe: all public methods hold ``_lock``.
    """

    def __init__(
        self,
        window_size: int = WINDOW_SIZE,
        min_trades_before_tuning: int = MIN_TRADES_BEFORE_TUNING,
        win_rate_quality: float = WIN_RATE_QUALITY,
        win_rate_loosen_ok: float = WIN_RATE_LOOSEN_OK,
        win_rate_tighten: float = WIN_RATE_TIGHTEN,
        min_trades_per_hour: float = MIN_TRADES_PER_HOUR,
        max_confidence_delta: float = MAX_CONFIDENCE_DELTA,
        loosen_step: float = LOOSEN_STEP,
        tighten_step: float = TIGHTEN_STEP,
        state_path: str = DEFAULT_STATE_PATH,
        audit_path: str = DEFAULT_AUDIT_PATH,
    ) -> None:
        self._window_size = window_size
        self._min_trades = min_trades_before_tuning
        self._wr_quality = win_rate_quality
        self._wr_loosen_ok = win_rate_loosen_ok
        self._wr_tighten = win_rate_tighten
        self._min_freq = min_trades_per_hour
        self._max_delta = max_confidence_delta
        self._loosen_step = loosen_step
        self._tighten_step = tighten_step
        self._state_path = Path(state_path)
        self._audit_path = Path(audit_path)

        self._lock = threading.Lock()

        # Rolling outcome window (last N trades)
        self._window: Deque[TradeSample] = deque(maxlen=window_size)

        # Timestamp deque used for frequency measurement (ISO strings)
        self._timestamps: Deque[str] = deque(maxlen=1000)

        # Running confidence delta (accumulated nudge, clamped to ±max_delta)
        self._confidence_delta: float = 0.0

        # Total trade count across all sessions
        self._total_trades: int = 0

        # Cache last emitted params
        self._last_params: Optional[FrequencyTuneParams] = None

        self._load_state()
        logger.info(
            "📊 WinRateFrequencyTuner initialised | window=%d min_trades=%d "
            "wr_thresholds=[tighten<%.0f%% loosen_ok≥%.0f%% quality≥%.0f%%] "
            "min_freq=%.1f/hr max_delta=±%.2f",
            window_size, min_trades_before_tuning,
            win_rate_tighten * 100, win_rate_loosen_ok * 100, win_rate_quality * 100,
            min_trades_per_hour, max_confidence_delta,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_trade(self, pnl_usd: float, is_win: bool) -> FrequencyTuneParams:
        """
        Register one closed trade and recompute tuning parameters.

        Parameters
        ----------
        pnl_usd:  Realised profit (positive) or loss (negative) in USD.
        is_win:   Whether the trade is classified as a win.

        Returns the updated ``FrequencyTuneParams``.
        """
        with self._lock:
            ts = datetime.now(timezone.utc).isoformat()
            sample = TradeSample(pnl_usd=pnl_usd, is_win=is_win, timestamp=ts)
            self._window.append(sample)
            self._timestamps.append(ts)
            self._total_trades += 1

            params = self._compute_params()
            self._confidence_delta = params.confidence_delta
            self._last_params = params

            self._save_state()
            self._write_audit(pnl_usd, is_win, params)

            logger.info(
                "📊 WinRateFreq [#%d] is_win=%s pnl=$%.2f | "
                "wr=%.0f%% freq=%.2f/hr ev_trade=$%.2f ev_hr=$%.2f | "
                "mode=%s delta=%+.3f",
                self._total_trades,
                "✅" if is_win else "❌",
                pnl_usd,
                params.win_rate * 100,
                params.trades_per_hour,
                params.ev_per_trade,
                params.ev_per_hour,
                params.mode.value,
                params.confidence_delta,
            )
            return params

    def get_params(self) -> FrequencyTuneParams:
        """Return the most recently computed parameters (no trade required)."""
        with self._lock:
            if self._last_params is None:
                self._last_params = self._compute_params()
            return self._last_params

    def get_report(self) -> Dict:
        """Return a dashboard-friendly summary dict."""
        with self._lock:
            p = self._last_params or self._compute_params()
            return {
                "mode": p.mode.value,
                "win_rate_pct": round(p.win_rate * 100, 1),
                "trades_in_window": p.trades_in_window,
                "trades_per_hour": round(p.trades_per_hour, 3),
                "avg_win_usd": round(p.avg_win_usd, 4),
                "avg_loss_usd": round(p.avg_loss_usd, 4),
                "ev_per_trade_usd": round(p.ev_per_trade, 4),
                "ev_per_hour_usd": round(p.ev_per_hour, 4),
                "confidence_delta": round(p.confidence_delta, 4),
                "total_trades_all_time": self._total_trades,
                "reason": p.reason,
                "timestamp": p.timestamp,
            }

    # ------------------------------------------------------------------
    # Internal computation
    # ------------------------------------------------------------------

    def _compute_params(self) -> FrequencyTuneParams:
        """Derive all metrics and select the FrequencyMode."""
        samples = list(self._window)
        n = len(samples)

        # --- Basic stats -------------------------------------------------
        if n == 0:
            return FrequencyTuneParams(
                mode=FrequencyMode.BALANCED,
                win_rate=0.0,
                trades_in_window=0,
                trades_per_hour=0.0,
                avg_win_usd=0.0,
                avg_loss_usd=0.0,
                ev_per_trade=0.0,
                ev_per_hour=0.0,
                confidence_delta=0.0,
                reason="Insufficient data — no trades recorded yet.",
            )

        wins = [s for s in samples if s.is_win]
        losses = [s for s in samples if not s.is_win]

        win_rate = len(wins) / n
        avg_win = sum(s.pnl_usd for s in wins) / len(wins) if wins else 0.0
        avg_loss = abs(sum(s.pnl_usd for s in losses) / len(losses)) if losses else 0.0

        ev_per_trade = win_rate * avg_win - (1.0 - win_rate) * avg_loss

        # --- Frequency (trades per hour over last 24 h real-time) --------
        trades_per_hour = self._compute_frequency()
        ev_per_hour = ev_per_trade * trades_per_hour

        # --- Not enough data yet to tune ---------------------------------
        if n < self._min_trades:
            return FrequencyTuneParams(
                mode=FrequencyMode.BALANCED,
                win_rate=win_rate,
                trades_in_window=n,
                trades_per_hour=trades_per_hour,
                avg_win_usd=avg_win,
                avg_loss_usd=avg_loss,
                ev_per_trade=ev_per_trade,
                ev_per_hour=ev_per_hour,
                confidence_delta=0.0,
                reason=(
                    f"Warming up ({n}/{self._min_trades} trades). "
                    "No threshold nudge applied yet."
                ),
            )

        # --- Mode selection ----------------------------------------------
        if win_rate < self._wr_tighten:
            # Win rate too low — tighten the gate to recover the edge
            delta = min(self._max_delta, self._confidence_delta + self._tighten_step)
            mode = FrequencyMode.TIGHTEN
            reason = (
                f"Win rate {win_rate:.0%} < tighten threshold {self._wr_tighten:.0%}. "
                f"Raising confidence gate by +{self._tighten_step:.2f} to protect capital "
                f"and rebuild edge. EV/hr=${ev_per_hour:.2f}"
            )

        elif win_rate >= self._wr_loosen_ok and trades_per_hour < self._min_freq:
            # Win rate is healthy but we're under-trading — loosen gate slightly
            delta = max(-self._max_delta, self._confidence_delta - self._loosen_step)
            mode = FrequencyMode.LOOSEN
            reason = (
                f"Win rate {win_rate:.0%} ≥ {self._wr_loosen_ok:.0%} but only "
                f"{trades_per_hour:.2f} trades/hr (target ≥ {self._min_freq:.1f}). "
                f"Lowering confidence gate by -{self._loosen_step:.2f} to capture more "
                f"valid setups. EV/hr=${ev_per_hour:.2f}"
            )

        elif win_rate >= self._wr_quality and trades_per_hour >= self._min_freq:
            # Strong win rate AND adequate frequency — no change needed
            delta = self._confidence_delta  # keep current delta
            mode = FrequencyMode.QUALITY
            reason = (
                f"Win rate {win_rate:.0%} ≥ quality threshold {self._wr_quality:.0%} "
                f"with {trades_per_hour:.2f} trades/hr. "
                f"Optimal zone — holding current gate. EV/hr=${ev_per_hour:.2f}"
            )

        else:
            # Neutral band
            delta = self._confidence_delta  # keep current delta
            mode = FrequencyMode.BALANCED
            reason = (
                f"Win rate {win_rate:.0%} in neutral band [{self._wr_tighten:.0%}, "
                f"{self._wr_quality:.0%}). "
                f"Freq={trades_per_hour:.2f}/hr. No nudge. EV/hr=${ev_per_hour:.2f}"
            )

        # Clamp delta to ±max
        delta = max(-self._max_delta, min(self._max_delta, delta))

        return FrequencyTuneParams(
            mode=mode,
            win_rate=win_rate,
            trades_in_window=n,
            trades_per_hour=trades_per_hour,
            avg_win_usd=avg_win,
            avg_loss_usd=avg_loss,
            ev_per_trade=ev_per_trade,
            ev_per_hour=ev_per_hour,
            confidence_delta=delta,
            reason=reason,
        )

    def _compute_frequency(self) -> float:
        """Compute trades-per-hour from the timestamp deque (24-h window)."""
        if len(self._timestamps) < 2:
            return 0.0
        now = datetime.now(timezone.utc)
        cutoff = now.timestamp() - FREQUENCY_WINDOW_SECONDS
        recent = [
            ts for ts in self._timestamps
            if self._parse_ts(ts) >= cutoff
        ]
        if not recent:
            return 0.0
        hours = FREQUENCY_WINDOW_SECONDS / 3600.0
        return len(recent) / hours

    @staticmethod
    def _parse_ts(ts: str) -> float:
        """Return POSIX timestamp from an ISO-8601 string, or 0.0 on error."""
        try:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            return 0.0

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        """Persist rolling state to disk for restart continuity."""
        try:
            state = {
                "total_trades": self._total_trades,
                "confidence_delta": self._confidence_delta,
                "window": [asdict(s) for s in self._window],
                "timestamps": list(self._timestamps),
            }
            self._state_path.write_text(json.dumps(state, indent=2))
        except Exception as exc:
            logger.debug("WinRateFrequencyTuner: failed to save state: %s", exc)

    def _load_state(self) -> None:
        """Restore state from disk if a previous session file exists."""
        try:
            if not self._state_path.exists():
                return
            state = json.loads(self._state_path.read_text())
            self._total_trades = int(state.get("total_trades", 0))
            self._confidence_delta = float(state.get("confidence_delta", 0.0))
            for rec in state.get("window", []):
                self._window.append(
                    TradeSample(
                        pnl_usd=float(rec["pnl_usd"]),
                        is_win=bool(rec["is_win"]),
                        timestamp=str(rec["timestamp"]),
                    )
                )
            for ts in state.get("timestamps", []):
                self._timestamps.append(ts)
            logger.info(
                "📊 WinRateFrequencyTuner: restored state "
                "(total=%d window=%d delta=%+.3f)",
                self._total_trades, len(self._window), self._confidence_delta,
            )
        except Exception as exc:
            logger.debug("WinRateFrequencyTuner: failed to load state: %s", exc)

    def _write_audit(self, pnl_usd: float, is_win: bool, params: FrequencyTuneParams) -> None:
        """Append one JSONL audit record for observability."""
        try:
            record = {
                "ts": params.timestamp,
                "trade": self._total_trades,
                "pnl_usd": round(pnl_usd, 6),
                "is_win": is_win,
                **asdict(params),
                "mode": params.mode.value,
            }
            with self._audit_path.open("a") as fh:
                fh.write(json.dumps(record) + "\n")
        except Exception as exc:
            logger.debug("WinRateFrequencyTuner: audit write failed: %s", exc)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[WinRateFrequencyTuner] = None
_instance_lock = threading.Lock()


def get_win_rate_frequency_tuner(
    window_size: int = WINDOW_SIZE,
    min_trades_before_tuning: int = MIN_TRADES_BEFORE_TUNING,
    win_rate_quality: float = WIN_RATE_QUALITY,
    win_rate_loosen_ok: float = WIN_RATE_LOOSEN_OK,
    win_rate_tighten: float = WIN_RATE_TIGHTEN,
    min_trades_per_hour: float = MIN_TRADES_PER_HOUR,
    max_confidence_delta: float = MAX_CONFIDENCE_DELTA,
    loosen_step: float = LOOSEN_STEP,
    tighten_step: float = TIGHTEN_STEP,
) -> WinRateFrequencyTuner:
    """
    Return the process-wide ``WinRateFrequencyTuner`` singleton.

    Configuration is applied only on the **first** call; subsequent calls
    return the existing instance unchanged.
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = WinRateFrequencyTuner(
                    window_size=window_size,
                    min_trades_before_tuning=min_trades_before_tuning,
                    win_rate_quality=win_rate_quality,
                    win_rate_loosen_ok=win_rate_loosen_ok,
                    win_rate_tighten=win_rate_tighten,
                    min_trades_per_hour=min_trades_per_hour,
                    max_confidence_delta=max_confidence_delta,
                    loosen_step=loosen_step,
                    tighten_step=tighten_step,
                )
    return _instance
