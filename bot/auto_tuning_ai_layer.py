"""
NIJA Auto-Tuning AI Layer
==========================

Closes the performance-feedback loop by automatically adjusting every key
trading threshold in real-time based on the bot's own win/loss history:

  Winning streak  →  increases aggression
      (loosen entry filters, larger positions, wider take-profit targets)

  Losing streak   →  tightens control
      (stricter filters, smaller positions, tighter stops, wider stop-loss
       distance to avoid premature exits in volatile chop)

Design goals
------------
* **Zero human intervention** – the layer adjusts itself continuously.
* **Safety-bounded** – every parameter has hard min/max guards so the engine
  can never push the bot into dangerous territory.
* **Incremental** – tune-level changes by at most ±1 step per evaluation to
  prevent overcorrection.
* **Auditable** – every adjustment is persisted to a JSONL audit file with
  full metrics snapshot.

Performance scoring
--------------------
The engine keeps a rolling window of the last ``WINDOW_SIZE`` trades and
derives a **tune level** from -3 (most conservative) to +3 (most aggressive)
using two primary signals:

  1. **Rolling win-rate** over the window.
  2. **Consecutive win / loss streak** since the last direction change.

Tune-level table:

  Level │ Condition (wins first, losses take priority)
  ──────┼────────────────────────────────────────────────────────────────
    +3  │ win_rate ≥ WIN_RATE_L3  AND streak ≥ STREAK_L3_MIN
    +2  │ win_rate ≥ WIN_RATE_L2  OR  win_streak ≥ STREAK_L2_WIN
    +1  │ win_rate ≥ WIN_RATE_L1
     0  │ win_rate in neutral band
    -1  │ win_rate ≤ LOSS_RATE_L1
    -2  │ win_rate ≤ LOSS_RATE_L2  OR  loss_streak ≥ STREAK_L2_LOSS
    -3  │ win_rate ≤ LOSS_RATE_L3  AND loss_streak ≥ STREAK_L3_MIN

Parameter multipliers / deltas per tune level:

  Level │ pos_size_mult │ conf_delta │ sl_mult │ tp_mult │ rsi_adj │ adx_adj
  ──────┼───────────────┼────────────┼─────────┼─────────┼─────────┼────────
    +3  │    1.30×      │  -0.08     │  0.85×  │  1.15×  │  +5 pts │  -5 pts
    +2  │    1.20×      │  -0.05     │  0.90×  │  1.10×  │  +3 pts │  -3 pts
    +1  │    1.10×      │  -0.03     │  0.95×  │  1.05×  │  +2 pts │  -2 pts
     0  │    1.00×      │   0.00     │  1.00×  │  1.00×  │   0 pts │   0 pts
    -1  │    0.90×      │  +0.03     │  1.05×  │  0.97×  │  -2 pts │  +2 pts
    -2  │    0.75×      │  +0.06     │  1.15×  │  0.93×  │  -3 pts │  +4 pts
    -3  │    0.60×      │  +0.10     │  1.25×  │  0.90×  │  -5 pts │  +6 pts

Usage
------
::

    from bot.auto_tuning_ai_layer import get_auto_tuning_ai_layer

    layer = get_auto_tuning_ai_layer()

    # After every trade close:
    layer.record_trade(pnl_usd=12.50, is_win=True)

    # Before entry — retrieve live tuned parameters:
    tuned = layer.get_tuned_params()

    # Scale position size:
    position_size *= tuned.position_size_multiplier

    # Adjust stop-loss distance:
    sl_distance *= tuned.stop_loss_multiplier

    # Adjust minimum confidence gate:
    effective_confidence = min_confidence + tuned.confidence_threshold_delta

    # Dashboard report:
    report = layer.get_report()

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import threading
from collections import deque
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Dict, List, Optional

logger = logging.getLogger("nija.auto_tuning_ai")

# ---------------------------------------------------------------------------
# Window / scoring constants
# ---------------------------------------------------------------------------

# How many recent trades to consider for win-rate calculation
WINDOW_SIZE: int = 20

# Minimum trades in the window before the engine starts adjusting thresholds
# (avoids reacting to tiny samples at bot startup)
MIN_TRADES_BEFORE_TUNING: int = 5

# Win-rate thresholds that trigger positive tune levels (aggression increase)
WIN_RATE_L1: float = 0.60   # ≥ 60% → +1
WIN_RATE_L2: float = 0.65   # ≥ 65% → +2
WIN_RATE_L3: float = 0.70   # ≥ 70% → +3

# Win-rate thresholds that trigger negative tune levels (tighten)
LOSS_RATE_L1: float = 0.45  # ≤ 45% → -1
LOSS_RATE_L2: float = 0.40  # ≤ 40% → -2
LOSS_RATE_L3: float = 0.35  # ≤ 35% → -3

# Consecutive-streak thresholds
STREAK_L2_WIN: int = 4    # ≥ 4 consecutive wins  → at least +2
STREAK_L2_LOSS: int = 3   # ≥ 3 consecutive losses → at least -2
STREAK_L3_MIN: int = 5    # ≥ 5 consecutive (same dir) qualifies level 3 threshold

# Maximum allowed tune-level step change per evaluation cycle
# (prevents jumping from 0 → +3 in a single trade)
MAX_LEVEL_STEP: int = 1

# ---------------------------------------------------------------------------
# Parameter adjustment tables (indexed by tune level: -3 … +3)
# ---------------------------------------------------------------------------

_TUNE_PARAMS: Dict[int, Dict[str, float]] = {
    +3: dict(
        position_size_multiplier=1.30,
        confidence_threshold_delta=-0.08,
        stop_loss_multiplier=0.85,
        take_profit_multiplier=1.15,
        rsi_band_adjustment=+5.0,
        adx_threshold_delta=-5.0,
    ),
    +2: dict(
        position_size_multiplier=1.20,
        confidence_threshold_delta=-0.05,
        stop_loss_multiplier=0.90,
        take_profit_multiplier=1.10,
        rsi_band_adjustment=+3.0,
        adx_threshold_delta=-3.0,
    ),
    +1: dict(
        position_size_multiplier=1.10,
        confidence_threshold_delta=-0.03,
        stop_loss_multiplier=0.95,
        take_profit_multiplier=1.05,
        rsi_band_adjustment=+2.0,
        adx_threshold_delta=-2.0,
    ),
    0: dict(
        position_size_multiplier=1.00,
        confidence_threshold_delta=0.00,
        stop_loss_multiplier=1.00,
        take_profit_multiplier=1.00,
        rsi_band_adjustment=0.0,
        adx_threshold_delta=0.0,
    ),
    -1: dict(
        position_size_multiplier=0.90,
        confidence_threshold_delta=+0.03,
        stop_loss_multiplier=1.05,
        take_profit_multiplier=0.97,
        rsi_band_adjustment=-2.0,
        adx_threshold_delta=+2.0,
    ),
    -2: dict(
        position_size_multiplier=0.75,
        confidence_threshold_delta=+0.06,
        stop_loss_multiplier=1.15,
        take_profit_multiplier=0.93,
        rsi_band_adjustment=-3.0,
        adx_threshold_delta=+4.0,
    ),
    -3: dict(
        position_size_multiplier=0.60,
        confidence_threshold_delta=+0.10,
        stop_loss_multiplier=1.25,
        take_profit_multiplier=0.90,
        rsi_band_adjustment=-5.0,
        adx_threshold_delta=+6.0,
    ),
}

# Human-readable labels per level for logging
_LEVEL_LABELS: Dict[int, str] = {
    +3: "🚀 MAX AGGRESSION",
    +2: "⚡ HIGH AGGRESSION",
    +1: "📈 SLIGHT AGGRESSION",
     0: "⚖️  NEUTRAL",
    -1: "🛡️  SLIGHT CAUTION",
    -2: "⚠️  HIGH CAUTION",
    -3: "🔒 MAX CAUTION",
}

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class TradeSummary:
    """Minimal record of a single closed trade kept in the rolling window."""

    pnl_usd: float
    is_win: bool
    timestamp: str


@dataclass
class TunedParams:
    """
    Live parameter adjustments derived from recent performance.

    All values are ready to apply directly in entry-decision logic.
    """

    tune_level: int                    # -3 … +3
    level_label: str                   # human-readable description
    win_rate: float                    # rolling win-rate (0–1)
    window_trades: int                 # number of trades in the window
    consecutive_wins: int              # current winning streak
    consecutive_losses: int            # current losing streak

    # Multipliers / deltas to apply
    position_size_multiplier: float    # multiply current position size by this
    confidence_threshold_delta: float  # add to min_signal_confidence
    stop_loss_multiplier: float        # multiply stop-loss distance by this
    take_profit_multiplier: float      # multiply take-profit distance by this
    rsi_band_adjustment: float         # add to RSI entry band boundaries
    adx_threshold_delta: float         # add to ADX threshold

    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------


class AutoTuningAILayer:
    """
    Tracks recent trade outcomes and continuously adjusts trading thresholds.

    Thread-safe: all public methods acquire ``_lock``.
    """

    DATA_DIR = Path(__file__).parent.parent / "data"
    STATE_FILE = DATA_DIR / "auto_tuning_ai_state.json"
    AUDIT_FILE = DATA_DIR / "auto_tuning_ai_audit.jsonl"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._window: Deque[TradeSummary] = deque(maxlen=WINDOW_SIZE)
        self._tune_level: int = 0
        self._total_trades: int = 0

        # Consecutive streak tracking
        self._consecutive_wins: int = 0
        self._consecutive_losses: int = 0

        self._last_params: Optional[TunedParams] = None

        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._load_state()

        logger.info(
            "✅ AutoTuningAILayer initialized "
            "(window=%d, min_trades=%d, level=%d)",
            WINDOW_SIZE,
            MIN_TRADES_BEFORE_TUNING,
            self._tune_level,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_trade(self, pnl_usd: float, is_win: bool) -> TunedParams:
        """
        Record a completed trade and re-evaluate the tune level.

        Parameters
        ----------
        pnl_usd:
            Realised profit or loss in USD (negative = loss).
        is_win:
            True when the trade was profitable.

        Returns
        -------
        TunedParams
            The updated tuned parameters after this trade.
        """
        with self._lock:
            entry = TradeSummary(
                pnl_usd=pnl_usd,
                is_win=is_win,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            self._window.append(entry)
            self._total_trades += 1

            # Update streak counters
            if is_win:
                self._consecutive_wins += 1
                self._consecutive_losses = 0
            else:
                self._consecutive_losses += 1
                self._consecutive_wins = 0

            # Re-evaluate tune level with incremental step guard
            new_level = self._compute_level()
            self._tune_level = self._apply_step_guard(self._tune_level, new_level)

            params = self._build_params()
            self._last_params = params

            # Persist and audit
            self._save_state()
            self._write_audit(pnl_usd, is_win, params)

            logger.info(
                "🤖 AutoTuning [trade #%d] is_win=%s pnl=$%.4f | "
                "window=%d trades win_rate=%.1f%% streak=W%d/L%d | "
                "level=%+d (%s) | size×%.2f conf%+.2f sl×%.2f tp×%.2f",
                self._total_trades,
                "✅" if is_win else "❌",
                pnl_usd,
                len(self._window),
                self._win_rate() * 100,
                self._consecutive_wins,
                self._consecutive_losses,
                self._tune_level,
                params.level_label,
                params.position_size_multiplier,
                params.confidence_threshold_delta,
                params.stop_loss_multiplier,
                params.take_profit_multiplier,
            )

            return params

    def get_tuned_params(self) -> TunedParams:
        """Return the current tuned parameters without recording a trade."""
        with self._lock:
            params = self._build_params()
            self._last_params = params
            return params

    def get_report(self) -> Dict:
        """Return a snapshot dict suitable for dashboards / JSON logging."""
        with self._lock:
            params = self._build_params()
            return {
                "tune_level": params.tune_level,
                "level_label": params.level_label,
                "win_rate_pct": round(params.win_rate * 100, 1),
                "window_trades": params.window_trades,
                "total_trades": self._total_trades,
                "consecutive_wins": params.consecutive_wins,
                "consecutive_losses": params.consecutive_losses,
                "position_size_multiplier": params.position_size_multiplier,
                "confidence_threshold_delta": params.confidence_threshold_delta,
                "stop_loss_multiplier": params.stop_loss_multiplier,
                "take_profit_multiplier": params.take_profit_multiplier,
                "rsi_band_adjustment": params.rsi_band_adjustment,
                "adx_threshold_delta": params.adx_threshold_delta,
                "timestamp": params.timestamp,
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _win_rate(self) -> float:
        """Rolling win-rate over the current window (returns 0.5 if empty)."""
        if not self._window:
            return 0.5
        wins = sum(1 for t in self._window if t.is_win)
        return wins / len(self._window)

    def _compute_level(self) -> int:
        """
        Compute the target tune level from current window metrics.

        Losing conditions take priority over winning conditions to ensure
        capital protection is never compromised.
        """
        n = len(self._window)
        if n < MIN_TRADES_BEFORE_TUNING:
            return 0

        wr = self._win_rate()
        cw = self._consecutive_wins
        cl = self._consecutive_losses

        # ── Losing / de-risk conditions (evaluated first) ────────────────
        if wr <= LOSS_RATE_L3 and cl >= STREAK_L3_MIN:
            return -3
        if wr <= LOSS_RATE_L2 or cl >= STREAK_L2_LOSS:
            return -2
        if wr <= LOSS_RATE_L1:
            return -1

        # ── Winning / aggression conditions ──────────────────────────────
        if wr >= WIN_RATE_L3 and cw >= STREAK_L3_MIN:
            return +3
        if wr >= WIN_RATE_L2 or cw >= STREAK_L2_WIN:
            return +2
        if wr >= WIN_RATE_L1:
            return +1

        return 0

    @staticmethod
    def _apply_step_guard(current: int, target: int) -> int:
        """
        Allow the tune level to move by at most MAX_LEVEL_STEP per trade
        so the engine cannot jump from 0 → ±3 in a single cycle.
        """
        if target > current:
            return min(target, current + MAX_LEVEL_STEP)
        if target < current:
            return max(target, current - MAX_LEVEL_STEP)
        return current

    def _build_params(self) -> TunedParams:
        """Construct a TunedParams from the current tune level and window."""
        level = self._tune_level
        p = _TUNE_PARAMS[level]
        return TunedParams(
            tune_level=level,
            level_label=_LEVEL_LABELS[level],
            win_rate=self._win_rate(),
            window_trades=len(self._window),
            consecutive_wins=self._consecutive_wins,
            consecutive_losses=self._consecutive_losses,
            position_size_multiplier=p["position_size_multiplier"],
            confidence_threshold_delta=p["confidence_threshold_delta"],
            stop_loss_multiplier=p["stop_loss_multiplier"],
            take_profit_multiplier=p["take_profit_multiplier"],
            rsi_band_adjustment=p["rsi_band_adjustment"],
            adx_threshold_delta=p["adx_threshold_delta"],
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        """Persist engine state to disk for restart continuity."""
        try:
            state = {
                "tune_level": self._tune_level,
                "total_trades": self._total_trades,
                "consecutive_wins": self._consecutive_wins,
                "consecutive_losses": self._consecutive_losses,
                "window": [asdict(t) for t in self._window],
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }
            tmp = self.STATE_FILE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(state, indent=2))
            tmp.replace(self.STATE_FILE)
        except Exception as exc:
            logger.debug("AutoTuningAI state save failed: %s", exc)

    def _load_state(self) -> None:
        """Restore engine state from disk if a previous session exists."""
        if not self.STATE_FILE.exists():
            return
        try:
            state = json.loads(self.STATE_FILE.read_text())
            self._tune_level = int(state.get("tune_level", 0))
            self._total_trades = int(state.get("total_trades", 0))
            self._consecutive_wins = int(state.get("consecutive_wins", 0))
            self._consecutive_losses = int(state.get("consecutive_losses", 0))
            for t in state.get("window", []):
                self._window.append(
                    TradeSummary(
                        pnl_usd=float(t.get("pnl_usd", 0.0)),
                        is_win=bool(t.get("is_win", False)),
                        timestamp=t.get("timestamp", ""),
                    )
                )
            logger.info(
                "📂 AutoTuningAI state restored "
                "(level=%+d, total_trades=%d, window=%d)",
                self._tune_level,
                self._total_trades,
                len(self._window),
            )
        except Exception as exc:
            logger.warning("AutoTuningAI state load failed (starting fresh): %s", exc)

    def _write_audit(
        self, pnl_usd: float, is_win: bool, params: TunedParams
    ) -> None:
        """Append one audit record to the JSONL audit file."""
        try:
            record = {
                "timestamp": params.timestamp,
                "trade_pnl_usd": pnl_usd,
                "is_win": is_win,
                "total_trades": self._total_trades,
                "window_size": len(self._window),
                **asdict(params),
            }
            with self.AUDIT_FILE.open("a") as fh:
                fh.write(json.dumps(record) + "\n")
        except Exception as exc:
            logger.debug("AutoTuningAI audit write failed: %s", exc)


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_layer_instance: Optional[AutoTuningAILayer] = None
_layer_lock = threading.Lock()


def get_auto_tuning_ai_layer() -> AutoTuningAILayer:
    """Return the singleton :class:`AutoTuningAILayer`."""
    global _layer_instance
    if _layer_instance is None:
        with _layer_lock:
            if _layer_instance is None:
                _layer_instance = AutoTuningAILayer()
    return _layer_instance
