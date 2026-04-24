"""
NIJA Self-Learning Engine
==========================

Tracks every trade outcome and continuously adjusts the bot's behaviour to
maximise win rate and profitability over time — without any external ML
framework.

What it learns
--------------
1. **Indicator weights** — Which RSI configuration (fast / slow), ATR
   multiplier, or signal combination drives the best outcomes?
2. **Entry timing** — How many bars after a signal fires is the optimal
   entry window?
3. **Stop-loss behaviour** — Does a wider or tighter stop-loss produce better
   risk-adjusted returns for each market condition?

Learning mechanism
------------------
All adjustments use **Exponential Moving Average (EMA) credit assignment**:

* Each trade carries a *feature fingerprint* (regime, indicator snapshot,
  entry timing class, stop-loss tier).
* After the trade closes the engine credits or debits each feature EMA
  proportional to the trade's P&L.
* The adjusted EMA values are normalised into *multipliers* (0.70 – 1.30)
  that downstream systems can query.

No training data or pre-trained model is required — the engine bootstraps
from scratch and improves with every trade.

Architecture
------------
::

    ┌────────────────────────────────────────────────────────────────┐
    │                   SelfLearningEngine                           │
    │                                                                │
    │  record_entry(features)  →  token (UUID)                      │
    │  record_outcome(token, pnl, won)  →  updates EMA weights      │
    │                                                                │
    │  get_indicator_weight(name)   →  float [0.70, 1.30]           │
    │  get_entry_timing_score(cls)  →  float [0.70, 1.30]           │
    │  get_stop_loss_multiplier(tier) → float [0.80, 1.30]          │
    │                                                                │
    │  Persistence: data/self_learning_engine.json                  │
    └────────────────────────────────────────────────────────────────┘

Usage
-----
::

    from bot.self_learning_engine import get_self_learning_engine

    engine = get_self_learning_engine()

    # Before entering a trade — record current feature state:
    token = engine.record_entry(
        indicator_names=["RSI_9", "RSI_14"],
        entry_timing_class="immediate",  # "immediate"|"delayed_1"|"delayed_2+"
        stop_loss_tier="normal",         # "tight"|"normal"|"wide"
        regime="BULL",
        extra={"atr_ratio": 1.2},
    )

    # After the trade closes:
    engine.record_outcome(token=token, pnl_usd=+85.0, won=True)

    # Query learned weights before sizing the next trade:
    rsi9_weight  = engine.get_indicator_weight("RSI_9")   # e.g. 1.12
    timing_score = engine.get_entry_timing_score("immediate")
    stop_mult    = engine.get_stop_loss_multiplier("normal")

    # Summary:
    print(engine.get_report())

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.self_learning_engine")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_DATA_DIR: str = "data"
EMA_DECAY: float = 0.08          # Higher → forgets faster (more reactive)
MULTIPLIER_MIN: float = 0.70
MULTIPLIER_MAX: float = 1.30
MIN_TRADES_TO_ADJUST: int = 5    # Require at least N trades before adjusting

# Entry timing classes
TIMING_CLASSES = ("immediate", "delayed_1", "delayed_2+")
# Stop-loss tiers
STOP_TIERS = ("tight", "normal", "wide")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class _EntryRecord:
    """Pending entry waiting for an outcome."""
    token: str
    ts: str
    indicator_names: List[str]
    entry_timing_class: str
    stop_loss_tier: str
    regime: str
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class _FeatureStats:
    """EMA credit stats for a single feature value."""
    name: str
    ema_pnl: float = 0.0          # EMA of P&L when this feature was active
    ema_win_rate: float = 0.5     # EMA of win rate
    trade_count: int = 0

    def update(self, pnl_usd: float, won: bool) -> None:
        self.ema_pnl = self.ema_pnl * (1 - EMA_DECAY) + pnl_usd * EMA_DECAY
        self.ema_win_rate = self.ema_win_rate * (1 - EMA_DECAY) + (1.0 if won else 0.0) * EMA_DECAY
        self.trade_count += 1

    def multiplier(self) -> float:
        """Normalise EMA signal into [MULTIPLIER_MIN, MULTIPLIER_MAX]."""
        if self.trade_count < MIN_TRADES_TO_ADJUST:
            return 1.0
        # Blend P&L component (normalised around $0, reference $100) with win rate
        pnl_norm = max(-1.0, min(1.0, self.ema_pnl / 100.0))
        wr_norm = (self.ema_win_rate - 0.5) * 2.0   # maps 0..1 → -1..+1
        combined = 0.6 * pnl_norm + 0.4 * wr_norm
        # Scale to multiplier range
        mult = 1.0 + combined * (MULTIPLIER_MAX - 1.0)
        return max(MULTIPLIER_MIN, min(MULTIPLIER_MAX, mult))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "ema_pnl": self.ema_pnl,
            "ema_win_rate": self.ema_win_rate,
            "trade_count": self.trade_count,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "_FeatureStats":
        obj = cls(name=d["name"])
        obj.ema_pnl = float(d.get("ema_pnl", 0.0))
        obj.ema_win_rate = float(d.get("ema_win_rate", 0.5))
        obj.trade_count = int(d.get("trade_count", 0))
        return obj


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class SelfLearningEngine:
    """
    Self-learning trade outcome tracker that continuously adjusts indicator
    weights, entry timing preferences, and stop-loss behaviour.
    """

    def __init__(self, data_dir: Optional[str] = None) -> None:
        self._data_dir = Path(data_dir or DEFAULT_DATA_DIR)
        self._data_dir.mkdir(parents=True, exist_ok=True)

        # Feature stat tables
        self._indicator_stats: Dict[str, _FeatureStats] = {}
        self._timing_stats: Dict[str, _FeatureStats] = {
            t: _FeatureStats(name=t) for t in TIMING_CLASSES
        }
        self._stop_stats: Dict[str, _FeatureStats] = {
            t: _FeatureStats(name=t) for t in STOP_TIERS
        }
        self._regime_stats: Dict[str, _FeatureStats] = {}

        # Pending entries awaiting outcomes
        self._pending: Dict[str, _EntryRecord] = {}

        # Summary counters
        self._total_trades: int = 0
        self._total_wins: int = 0

        self._lock = threading.Lock()
        self._load_state()
        logger.info("SelfLearningEngine initialised (data_dir=%s)", self._data_dir)

    # ------------------------------------------------------------------
    # Public API — trade lifecycle
    # ------------------------------------------------------------------

    def record_entry(
        self,
        indicator_names: List[str],
        entry_timing_class: str = "immediate",
        stop_loss_tier: str = "normal",
        regime: str = "UNKNOWN",
        extra: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Record that a trade entry has been taken with the given features.

        Returns a token (UUID string) that must be passed to
        :meth:`record_outcome` when the trade closes.
        """
        token = str(uuid.uuid4())
        rec = _EntryRecord(
            token=token,
            ts=datetime.now(timezone.utc).isoformat(),
            indicator_names=list(indicator_names),
            entry_timing_class=entry_timing_class,
            stop_loss_tier=stop_loss_tier,
            regime=regime,
            extra=extra or {},
        )
        with self._lock:
            self._pending[token] = rec
        return token

    def record_outcome(self, token: str, pnl_usd: float, won: bool) -> bool:
        """
        Record the outcome of a previously registered trade entry.

        Parameters
        ----------
        token   : Token returned by :meth:`record_entry`.
        pnl_usd : Realised profit/loss in USD.
        won     : True if the trade closed in profit.

        Returns
        -------
        True if the token was found and processed; False if unknown.
        """
        with self._lock:
            rec = self._pending.pop(token, None)
            if rec is None:
                logger.warning("SelfLearningEngine.record_outcome: unknown token %s", token)
                return False

            # Update indicator weights
            for ind in rec.indicator_names:
                if ind not in self._indicator_stats:
                    self._indicator_stats[ind] = _FeatureStats(name=ind)
                self._indicator_stats[ind].update(pnl_usd, won)

            # Update entry timing
            tc = rec.entry_timing_class if rec.entry_timing_class in TIMING_CLASSES else "immediate"
            self._timing_stats[tc].update(pnl_usd, won)

            # Update stop-loss tier
            st = rec.stop_loss_tier if rec.stop_loss_tier in STOP_TIERS else "normal"
            self._stop_stats[st].update(pnl_usd, won)

            # Update regime stats
            rg = rec.regime or "UNKNOWN"
            if rg not in self._regime_stats:
                self._regime_stats[rg] = _FeatureStats(name=rg)
            self._regime_stats[rg].update(pnl_usd, won)

            self._total_trades += 1
            if won:
                self._total_wins += 1

        self._save_state()
        logger.debug(
            "SelfLearningEngine: outcome recorded token=%s pnl=%.2f won=%s "
            "(total=%d win_rate=%.1f%%)",
            token[:8], pnl_usd, won,
            self._total_trades,
            100.0 * self._total_wins / max(self._total_trades, 1),
        )
        return True

    # ------------------------------------------------------------------
    # Public API — learned multipliers
    # ------------------------------------------------------------------

    def get_indicator_weight(self, indicator_name: str) -> float:
        """
        Return the learned weight multiplier for an indicator (1.0 = neutral).

        Higher values mean this indicator has been more reliable historically.
        Range: [0.70, 1.30].
        """
        with self._lock:
            stats = self._indicator_stats.get(indicator_name)
        return stats.multiplier() if stats else 1.0

    def get_entry_timing_score(self, timing_class: str) -> float:
        """
        Return the learned score multiplier for an entry timing class.

        Range: [0.70, 1.30].
        """
        with self._lock:
            stats = self._timing_stats.get(timing_class)
        return stats.multiplier() if stats else 1.0

    def get_stop_loss_multiplier(self, stop_tier: str) -> float:
        """
        Return the learned multiplier that should be applied to the stop-loss
        distance for the given stop tier.

        Values > 1.0 suggest widening the stop; < 1.0 suggest tightening.
        Range: [0.70, 1.30].
        """
        with self._lock:
            stats = self._stop_stats.get(stop_tier)
        return stats.multiplier() if stats else 1.0

    def get_regime_multiplier(self, regime: str) -> float:
        """
        Return the learned performance multiplier for a market regime.

        Range: [0.70, 1.30].
        """
        with self._lock:
            stats = self._regime_stats.get(regime)
        return stats.multiplier() if stats else 1.0

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_report(self) -> str:
        """Human-readable summary of learned weights."""
        with self._lock:
            total = self._total_trades
            wins = self._total_wins
            wr = wins / total if total > 0 else 0.0

            ind_lines = [
                f"    {n:<20} mult={s.multiplier():.3f}  trades={s.trade_count}"
                for n, s in sorted(self._indicator_stats.items())
            ]
            timing_lines = [
                f"    {n:<20} mult={s.multiplier():.3f}  trades={s.trade_count}"
                for n, s in self._timing_stats.items()
            ]
            stop_lines = [
                f"    {n:<20} mult={s.multiplier():.3f}  trades={s.trade_count}"
                for n, s in self._stop_stats.items()
            ]

        lines = [
            "═══════════════════════════════════════════════════",
            "  NIJA Self-Learning Engine",
            "═══════════════════════════════════════════════════",
            f"  Total trades : {total}",
            f"  Win rate     : {wr:.1%}",
            "───────────────────────────────────────────────────",
            "  Indicator weights:",
        ]
        lines.extend(ind_lines if ind_lines else ["    (none yet)"])
        lines += [
            "───────────────────────────────────────────────────",
            "  Entry timing scores:",
        ]
        lines.extend(timing_lines)
        lines += [
            "───────────────────────────────────────────────────",
            "  Stop-loss multipliers:",
        ]
        lines.extend(stop_lines)
        lines.append("═══════════════════════════════════════════════════")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        path = self._data_dir / "self_learning_engine.json"
        try:
            with self._lock:
                state = {
                    "total_trades": self._total_trades,
                    "total_wins": self._total_wins,
                    "indicator_stats": {
                        k: v.to_dict() for k, v in self._indicator_stats.items()
                    },
                    "timing_stats": {
                        k: v.to_dict() for k, v in self._timing_stats.items()
                    },
                    "stop_stats": {
                        k: v.to_dict() for k, v in self._stop_stats.items()
                    },
                    "regime_stats": {
                        k: v.to_dict() for k, v in self._regime_stats.items()
                    },
                }
            path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("SelfLearningEngine: save failed: %s", exc)

    def _load_state(self) -> None:
        path = self._data_dir / "self_learning_engine.json"
        if not path.exists():
            return
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            self._total_trades = int(state.get("total_trades", 0))
            self._total_wins = int(state.get("total_wins", 0))
            for k, v in state.get("indicator_stats", {}).items():
                self._indicator_stats[k] = _FeatureStats.from_dict(v)
            for k, v in state.get("timing_stats", {}).items():
                self._timing_stats[k] = _FeatureStats.from_dict(v)
            for k, v in state.get("stop_stats", {}).items():
                self._stop_stats[k] = _FeatureStats.from_dict(v)
            for k, v in state.get("regime_stats", {}).items():
                self._regime_stats[k] = _FeatureStats.from_dict(v)
            logger.info(
                "SelfLearningEngine: loaded state (%d trades)", self._total_trades
            )
        except Exception as exc:
            logger.warning("SelfLearningEngine: load failed: %s", exc)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_INSTANCE: Optional[SelfLearningEngine] = None
_INSTANCE_LOCK = threading.Lock()


def get_self_learning_engine(data_dir: Optional[str] = None) -> SelfLearningEngine:
    """Thread-safe singleton accessor."""
    global _INSTANCE
    with _INSTANCE_LOCK:
        if _INSTANCE is None:
            _INSTANCE = SelfLearningEngine(data_dir=data_dir)
    return _INSTANCE
