"""
Reinvest Meta-Learner
=====================

Learns which market / portfolio conditions produce the best reinvestment
returns.  Every time recycled capital is committed to a strategy the learner
records the environmental *fingerprint* (regime, volatility tier, win-rate
tier, pool-size tier) alongside the resulting P&L.  EMA-smoothed scores are
maintained per fingerprint so future reinvestment decisions can be scaled by
how favourable the current conditions historically are.

How it works
------------
1. **Record entry** – Before capital is deployed the caller captures the
   current conditions and receives a *tracking token*::

       token = learner.record_entry(
           regime="BULL_TRENDING",
           volatility="MINOR",
           win_rate_tier="HIGH",
           pool_tier="MEDIUM",
           amount_usd=150.0,
           strategy="ApexTrend",
       )

2. **Record outcome** – When the trade closes the outcome is fed back::

       learner.record_outcome(token, pnl=18.5, won=True)

3. **Query condition quality** – Before allocating capital query how good the
   current conditions are::

       score, confidence = learner.get_condition_score(
           regime="BULL_TRENDING",
           volatility="MINOR",
           win_rate_tier="HIGH",
           pool_tier="MEDIUM",
       )
       # score ∈ [0, 1] — higher is better
       # confidence ∈ [0, 1] — rises with number of observations

4. **Quality multiplier** – Convenience wrapper for the recycling engine::

       mult = learner.get_quality_multiplier(...)
       # Returns a float in [CONDITION_QUALITY_MIN, CONDITION_QUALITY_MAX]
       # that can be applied to scale the effective reinvestment pool.

Condition dimensions
--------------------
* **regime** – BULL_TRENDING · BEAR_TRENDING · RANGING · VOLATILE · CRISIS · UNKNOWN
* **volatility** – CALM · MINOR · MODERATE · SEVERE · EXTREME
* **win_rate_tier** – LOW (<40 %) · MODERATE (40–60 %) · HIGH (>60 %)
* **pool_tier** – MICRO (<$10) · SMALL ($10–$100) · MEDIUM ($100–$1 000) · LARGE (>$1 000)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.reinvest_meta_learner")

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

EMA_DECAY: float = 0.88
"""EMA smoothing factor — higher keeps older data longer."""

MIN_TRADES_FOR_CONFIDENCE: int = 5
"""Number of observations before confidence starts saturating."""

CONFIDENCE_SATURATION_TRADES: int = 30
"""Number of observations at which confidence reaches ~1.0."""

#: Condition quality multiplier bounds.  The multiplier is applied to the
#: effective recycling pool so allocations are scaled up/down by condition.
CONDITION_QUALITY_MIN: float = 0.70
CONDITION_QUALITY_MAX: float = 1.20

#: Maximum pending tokens kept in memory (prevents unbounded growth).
MAX_PENDING_TOKENS: int = 1_000

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _classify_pool_tier(pool_usd: float) -> str:
    """Bucket pool balance into a discrete tier label."""
    if pool_usd < 10.0:
        return "MICRO"
    if pool_usd < 100.0:
        return "SMALL"
    if pool_usd < 1_000.0:
        return "MEDIUM"
    return "LARGE"


def _classify_win_rate_tier(win_rate: float) -> str:
    """Bucket a rolling win-rate fraction into LOW / MODERATE / HIGH."""
    if win_rate < 0.40:
        return "LOW"
    if win_rate <= 0.60:
        return "MODERATE"
    return "HIGH"


def _make_fingerprint(
    regime: str,
    volatility: str,
    win_rate_tier: str,
    pool_tier: str,
    strategy: str = "",
) -> str:
    """
    Build a compact string key from the four condition dimensions.

    An optional *strategy* dimension allows per-strategy differentiation;
    pass ``""`` to collapse all strategies into a single fingerprint.
    """
    parts = [
        regime.upper() or "UNKNOWN",
        volatility.upper() or "CALM",
        win_rate_tier.upper() or "MODERATE",
        pool_tier.upper() or "SMALL",
    ]
    if strategy:
        parts.append(strategy)
    return "|".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ConditionStats:
    """EMA-smoothed performance statistics for one condition fingerprint."""

    fingerprint: str
    ema_return_pct: float = 0.0    # EMA of return-on-reinvested-capital %
    ema_win_rate: float = 0.5      # EMA of trade win-rate
    ema_pf: float = 1.0            # EMA of profit factor
    ema_sharpe: float = 0.0        # rough Sharpe proxy
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    trades: int = 0
    last_updated: str = ""

    @property
    def composite_score(self) -> float:
        """
        0–1 score blending win-rate, return, and profit-factor.

        Identical construction to ``StrategyRegimeStats.composite_score``
        in meta_learning_optimizer.py for consistency.
        """
        wr_part     = self.ema_win_rate
        ret_part    = math.tanh(self.ema_return_pct / 5.0)   # 5 % return → ~0.76
        pf_part     = math.tanh((self.ema_pf - 1.0) / 1.0)  # PF=2.0 → ~0.76
        sharpe_part = math.tanh(self.ema_sharpe / 2.0)
        raw = (
            wr_part    * 0.30
            + ret_part * 0.25
            + pf_part  * 0.25
            + sharpe_part * 0.20
        )
        return max(0.01, min(1.0, raw))

    @property
    def confidence(self) -> float:
        """
        0–1 confidence that rises with the number of observations.

        Below ``MIN_TRADES_FOR_CONFIDENCE`` the confidence is very low so
        novel fingerprints contribute little to allocation decisions.
        """
        if self.trades < MIN_TRADES_FOR_CONFIDENCE:
            return self.trades / (MIN_TRADES_FOR_CONFIDENCE * 2)
        return min(1.0, self.trades / CONFIDENCE_SATURATION_TRADES)


@dataclass
class PendingReinvest:
    """A reinvestment entry awaiting its outcome."""

    token: str
    fingerprint: str
    amount_usd: float
    timestamp: str


# ─────────────────────────────────────────────────────────────────────────────
# Core class
# ─────────────────────────────────────────────────────────────────────────────


class ReinvestMetaLearner:
    """
    Meta-learning engine that tracks which conditions produce the best
    reinvestment returns and surfaces that knowledge as a quality multiplier.

    Parameters
    ----------
    state_path : str
        JSON path for persistence across restarts.
    ema_decay : float
        EMA smoothing factor (≥ 0, < 1).  Higher values weight older trades
        more heavily; lower values adapt faster to recent data.
    """

    def __init__(
        self,
        state_path: str = "data/reinvest_meta_state.json",
        ema_decay: float = EMA_DECAY,
    ) -> None:
        self.state_path = state_path
        self.ema_decay = ema_decay
        self._lock = threading.RLock()

        # fingerprint → ConditionStats
        self._stats: Dict[str, ConditionStats] = {}
        # token → PendingReinvest (entries awaiting outcome)
        self._pending: Dict[str, PendingReinvest] = {}

        self._load_state()
        logger.info(
            "🔬 ReinvestMetaLearner ready | ema_decay=%.2f | fingerprints=%d",
            ema_decay, len(self._stats),
        )

    # ── Recording ─────────────────────────────────────────────────────────────

    def record_entry(
        self,
        regime: str,
        volatility: str,
        win_rate_tier: str,
        pool_tier: str,
        amount_usd: float,
        strategy: str = "",
    ) -> str:
        """
        Register a reinvestment event and return a tracking token.

        Call this **before** committing recycled capital.  Pass the returned
        token to :meth:`record_outcome` once the trade closes.

        Parameters
        ----------
        regime : str
            Current market regime (e.g. ``"BULL_TRENDING"``).
        volatility : str
            Current volatility tier (e.g. ``"MINOR"``).
        win_rate_tier : str
            Current strategy win-rate tier (``"LOW"`` / ``"MODERATE"`` / ``"HIGH"``).
        pool_tier : str
            Current pool-size tier (``"MICRO"`` / ``"SMALL"`` / ``"MEDIUM"`` / ``"LARGE"``).
        amount_usd : float
            Dollar amount being reinvested.
        strategy : str
            Optional strategy name for per-strategy differentiation.

        Returns
        -------
        str
            Unique tracking token (UUID4).
        """
        fingerprint = _make_fingerprint(regime, volatility, win_rate_tier, pool_tier, strategy)
        token = str(uuid.uuid4())

        pending = PendingReinvest(
            token=token,
            fingerprint=fingerprint,
            amount_usd=max(0.0, amount_usd),
            timestamp=_now(),
        )

        with self._lock:
            # Evict oldest pending tokens to bound memory usage
            if len(self._pending) >= MAX_PENDING_TOKENS:
                oldest = sorted(self._pending.values(), key=lambda p: p.timestamp)
                for p in oldest[: len(self._pending) - MAX_PENDING_TOKENS + 1]:
                    del self._pending[p.token]

            self._pending[token] = pending

        logger.debug(
            "[ReinvestMeta] Entry recorded | fingerprint=%s | amount=$%.2f | token=%s",
            fingerprint, amount_usd, token[:8],
        )
        return token

    def record_outcome(
        self,
        token: str,
        pnl: float,
        won: bool,
    ) -> None:
        """
        Record the outcome of a previously registered reinvestment.

        Parameters
        ----------
        token : str
            The token returned by :meth:`record_entry`.
        pnl : float
            P&L in USD (positive = profit, negative = loss).
        won : bool
            Whether the trade was a winner (used for win-rate tracking).
        """
        with self._lock:
            pending = self._pending.pop(token, None)
            if pending is None:
                logger.debug(
                    "[ReinvestMeta] Unknown or expired token %s — outcome ignored.", token[:8]
                )
                return

            stats = self._get_or_create_stats(pending.fingerprint)
            α = 1.0 - self.ema_decay

            # Return as % of reinvested capital
            ret_pct = (pnl / pending.amount_usd * 100.0) if pending.amount_usd > 0 else 0.0

            stats.ema_return_pct = self.ema_decay * stats.ema_return_pct + α * ret_pct
            stats.ema_win_rate   = self.ema_decay * stats.ema_win_rate   + α * float(won)

            if pnl > 0:
                stats.gross_profit += pnl
            else:
                stats.gross_loss += abs(pnl)

            pf = stats.gross_profit / stats.gross_loss if stats.gross_loss > 0 else 2.0
            stats.ema_pf = self.ema_decay * stats.ema_pf + α * pf

            # Rough Sharpe proxy: return / vol (vol proxied by |ema_return|)
            vol_proxy = max(0.01, abs(stats.ema_return_pct))
            stats.ema_sharpe = stats.ema_return_pct / vol_proxy

            stats.trades += 1
            stats.last_updated = _now()

            self._save_state()

        logger.debug(
            "[ReinvestMeta] Outcome recorded | fingerprint=%s | pnl=$%.2f | won=%s | score=%.3f",
            pending.fingerprint, pnl, won, stats.composite_score,
        )

    # ── Querying ──────────────────────────────────────────────────────────────

    def get_condition_score(
        self,
        regime: str,
        volatility: str,
        win_rate_tier: str,
        pool_tier: str,
        strategy: str = "",
    ) -> Tuple[float, float]:
        """
        Return ``(score, confidence)`` for the given condition fingerprint.

        * **score** – composite 0–1 quality score (higher = historically better).
          Returns 0.5 (neutral) if no data exists for the fingerprint.
        * **confidence** – 0–1 reliability of the score.
          Returns 0.0 if no data exists.

        Parameters
        ----------
        regime : str
            Current market regime.
        volatility : str
            Current volatility tier.
        win_rate_tier : str
            Current win-rate tier.
        pool_tier : str
            Current pool-size tier.
        strategy : str
            Optional strategy name.

        Returns
        -------
        tuple[float, float]
            ``(score, confidence)`` both in [0, 1].
        """
        fingerprint = _make_fingerprint(regime, volatility, win_rate_tier, pool_tier, strategy)
        with self._lock:
            stats = self._stats.get(fingerprint)
            if stats is None:
                return 0.5, 0.0   # neutral score, zero confidence
            return stats.composite_score, stats.confidence

    def get_quality_multiplier(
        self,
        regime: str,
        volatility: str,
        win_rate_tier: str,
        pool_tier: str,
        strategy: str = "",
    ) -> float:
        """
        Return a reinvestment size multiplier based on learned condition quality.

        The multiplier linearly maps the condition score to
        ``[CONDITION_QUALITY_MIN, CONDITION_QUALITY_MAX]``.  When confidence is
        low the multiplier is blended toward 1.0 (neutral) to avoid acting on
        insufficient data.

        Returns
        -------
        float
            Multiplier in ``[CONDITION_QUALITY_MIN, CONDITION_QUALITY_MAX]``.
        """
        score, confidence = self.get_condition_score(
            regime, volatility, win_rate_tier, pool_tier, strategy
        )

        # Map score [0, 1] → [CONDITION_QUALITY_MIN, CONDITION_QUALITY_MAX]
        raw_mult = CONDITION_QUALITY_MIN + score * (CONDITION_QUALITY_MAX - CONDITION_QUALITY_MIN)

        # Blend toward neutral (1.0) proportionally to lack of confidence
        blended = confidence * raw_mult + (1.0 - confidence) * 1.0

        return round(max(CONDITION_QUALITY_MIN, min(CONDITION_QUALITY_MAX, blended)), 4)

    def get_best_conditions(self, top_n: int = 10) -> List[Dict[str, Any]]:
        """
        Return the top-*n* condition fingerprints by composite score.

        Only fingerprints with at least ``MIN_TRADES_FOR_CONFIDENCE`` trades
        are returned so noise from single observations is filtered out.

        Returns
        -------
        list[dict]
            Sorted descending by composite score.  Each entry contains:
            ``fingerprint``, ``score``, ``confidence``, ``trades``,
            ``ema_return_pct``, ``ema_win_rate``, ``ema_pf``.
        """
        with self._lock:
            eligible = [
                s for s in self._stats.values()
                if s.trades >= MIN_TRADES_FOR_CONFIDENCE
            ]
        eligible.sort(key=lambda s: s.composite_score, reverse=True)
        return [
            {
                "fingerprint":    s.fingerprint,
                "score":          round(s.composite_score, 4),
                "confidence":     round(s.confidence, 4),
                "trades":         s.trades,
                "ema_return_pct": round(s.ema_return_pct, 4),
                "ema_win_rate":   round(s.ema_win_rate, 4),
                "ema_pf":         round(s.ema_pf, 4),
            }
            for s in eligible[:top_n]
        ]

    def get_worst_conditions(self, top_n: int = 5) -> List[Dict[str, Any]]:
        """
        Return the *top_n* worst condition fingerprints (lowest composite score).

        Only fingerprints with at least ``MIN_TRADES_FOR_CONFIDENCE`` trades
        are included.

        Returns
        -------
        list[dict]
            Sorted ascending by composite score (worst first).
        """
        with self._lock:
            eligible = [
                s for s in self._stats.values()
                if s.trades >= MIN_TRADES_FOR_CONFIDENCE
            ]
        eligible.sort(key=lambda s: s.composite_score)
        return [
            {
                "fingerprint":    s.fingerprint,
                "score":          round(s.composite_score, 4),
                "confidence":     round(s.confidence, 4),
                "trades":         s.trades,
                "ema_return_pct": round(s.ema_return_pct, 4),
                "ema_win_rate":   round(s.ema_win_rate, 4),
                "ema_pf":         round(s.ema_pf, 4),
            }
            for s in eligible[:top_n]
        ]

    # ── Status / reporting ────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """Return a structured status dict for dashboards and APIs."""
        with self._lock:
            total = len(self._stats)
            mature = sum(1 for s in self._stats.values() if s.trades >= MIN_TRADES_FOR_CONFIDENCE)
            total_trades = sum(s.trades for s in self._stats.values())
            pending_count = len(self._pending)

        best  = self.get_best_conditions(top_n=3)
        worst = self.get_worst_conditions(top_n=3)

        return {
            "total_fingerprints":  total,
            "mature_fingerprints": mature,
            "total_trades_recorded": total_trades,
            "pending_outcomes":    pending_count,
            "ema_decay":           self.ema_decay,
            "best_conditions":     best,
            "worst_conditions":    worst,
        }

    def get_report(self) -> str:
        """Return a human-readable text report of learned condition scores."""
        s = self.status()
        lines = [
            "=" * 70,
            "  🔬  REINVEST META-LEARNER — CONDITION REPORT",
            "=" * 70,
            f"  Total Fingerprints     : {s['total_fingerprints']}",
            f"  Mature (≥{MIN_TRADES_FOR_CONFIDENCE} trades)    : {s['mature_fingerprints']}",
            f"  Total Trades Recorded  : {s['total_trades_recorded']}",
            f"  Pending Outcomes       : {s['pending_outcomes']}",
            "",
            "  Best Conditions:",
        ]
        for entry in s["best_conditions"]:
            lines.append(
                f"    {entry['fingerprint']:<55}  score={entry['score']:.3f}  "
                f"conf={entry['confidence']:.2f}  trades={entry['trades']}"
            )
        if not s["best_conditions"]:
            lines.append("    (insufficient data)")

        lines += ["", "  Worst Conditions:"]
        for entry in s["worst_conditions"]:
            lines.append(
                f"    {entry['fingerprint']:<55}  score={entry['score']:.3f}  "
                f"conf={entry['confidence']:.2f}  trades={entry['trades']}"
            )
        if not s["worst_conditions"]:
            lines.append("    (insufficient data)")

        lines.append("=" * 70)
        return "\n".join(lines)

    # ── Internals ─────────────────────────────────────────────────────────────

    def _get_or_create_stats(self, fingerprint: str) -> ConditionStats:
        if fingerprint not in self._stats:
            self._stats[fingerprint] = ConditionStats(fingerprint=fingerprint)
        return self._stats[fingerprint]

    def _load_state(self) -> None:
        try:
            if os.path.exists(self.state_path):
                with open(self.state_path) as fh:
                    data = json.load(fh)
                for fp, sd in data.get("stats", {}).items():
                    self._stats[fp] = ConditionStats(**{
                        k: v for k, v in sd.items()
                        if k in ConditionStats.__dataclass_fields__
                    })
                logger.info(
                    "[ReinvestMeta] State restored from %s | fingerprints=%d",
                    self.state_path, len(self._stats),
                )
        except Exception as exc:
            logger.warning(
                "[ReinvestMeta] Could not load state (%s) — starting fresh.", exc
            )

    def _save_state(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
            payload = {
                "stats": {fp: asdict(s) for fp, s in self._stats.items()},
                "saved_at": _now(),
            }
            with open(self.state_path, "w") as fh:
                json.dump(payload, fh, indent=2)
        except Exception as exc:
            logger.warning("[ReinvestMeta] Could not persist state: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

_learner_instance: Optional[ReinvestMetaLearner] = None
_learner_lock = threading.Lock()


def get_reinvest_meta_learner(
    state_path: str = "data/reinvest_meta_state.json",
    **kwargs: Any,
) -> ReinvestMetaLearner:
    """Return the process-wide :class:`ReinvestMetaLearner` singleton."""
    global _learner_instance
    with _learner_lock:
        if _learner_instance is None:
            _learner_instance = ReinvestMetaLearner(state_path=state_path, **kwargs)
    return _learner_instance


# ─────────────────────────────────────────────────────────────────────────────
# Convenience helpers (used by CapitalRecyclingEngine)
# ─────────────────────────────────────────────────────────────────────────────


def classify_pool_tier(pool_usd: float) -> str:
    """Public alias for :func:`_classify_pool_tier`."""
    return _classify_pool_tier(pool_usd)


def classify_win_rate_tier(win_rate: float) -> str:
    """Public alias for :func:`_classify_win_rate_tier`."""
    return _classify_win_rate_tier(win_rate)
