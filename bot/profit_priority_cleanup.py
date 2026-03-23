"""
PROFIT PRIORITY CLEANUP
========================
Profit-based cleanup prioritization: when the portfolio needs positions
closed (cap enforcement, drawdown recovery, scheduled cleanup), this module
ranks positions so that **losing positions are closed first and winning
positions are preserved last**.

Rationale
---------
Naive cleanup engines close positions alphabetically or by size (smallest
first).  Neither approach considers P&L.  Closing winners first destroys
compounding upside; closing losers first is mathematically superior because:
  - Losers are already dragging portfolio equity downward.
  - Freeing capital from losers immediately reduces drawdown.
  - Capital released from losers can compound in winning trades.

Priority score formula (higher score → close first)
----------------------------------------------------
    score = (loss_weight × max(0, -pnl_pct))          # losers score high
           + (age_weight  × max(0, age_hours - min_age))  # stale positions
           + (size_weight × (1 / max(size_usd, 1)))    # smallest positions
           - (winner_bonus × max(0, pnl_pct))           # winners score low

Usage
-----
    from bot.profit_priority_cleanup import get_profit_priority_cleanup

    engine = get_profit_priority_cleanup()
    ranked = engine.rank_for_cleanup(positions)       # sorted, worst first
    to_close = engine.select_for_closure(positions, n=3)  # top-N to close

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.profit_priority_cleanup")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class CleanupPriorityConfig:
    """Weights that control how positions are ranked for closure."""

    # How strongly losses drive priority (higher → close losers faster)
    loss_weight: float = 2.0

    # Bonus subtracted from score for winning positions (keeps them open)
    winner_bonus: float = 1.5

    # Penalty for positions older than ``min_age_hours`` (stale positions)
    age_weight: float = 0.3

    # Minimum age before the age penalty kicks in (hours)
    min_age_hours: float = 4.0

    # Small-position weight (1 / size_usd) – tiny positions slightly favoured
    # for early closure to reduce fragmentation
    size_weight: float = 0.05

    # Never close a position whose pnl_pct > this value unless forced
    # (set to None to disable the winner-protection gate)
    winner_protection_threshold_pct: Optional[float] = 5.0

    # When True, positions marked ``is_open_too_long`` in their dict are given
    # an extra age penalty regardless of actual age_hours
    penalise_stale_flag: bool = True
    stale_extra_penalty: float = 5.0


# ---------------------------------------------------------------------------
# Ranked position record
# ---------------------------------------------------------------------------

@dataclass
class RankedPosition:
    """A position augmented with its computed cleanup priority score."""
    symbol: str
    size_usd: float
    pnl_pct: float
    age_hours: float
    priority_score: float           # Higher = should be closed sooner
    close_reason: str               # Human-readable explanation
    is_protected: bool = False      # True when winner protection blocked closure
    raw: Dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

class ProfitPriorityCleanup:
    """
    Rank positions by profitability so losers are closed first.

    Thread-safe singleton via ``get_profit_priority_cleanup()``.
    """

    def __init__(self, config: Optional[CleanupPriorityConfig] = None) -> None:
        self.config = config or CleanupPriorityConfig()
        self._lock = threading.Lock()
        logger.info(
            "🎯 ProfitPriorityCleanup initialised "
            "(loss_w=%.1f, winner_bonus=%.1f, age_w=%.1f)",
            self.config.loss_weight,
            self.config.winner_bonus,
            self.config.age_weight,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def rank_for_cleanup(
        self, positions: List[Dict]
    ) -> List[RankedPosition]:
        """
        Return all positions ranked from **highest priority to close** (index 0)
        to **lowest priority to close** (last index).

        Parameters
        ----------
        positions:
            Raw position dicts.  Each should contain ``symbol``,
            ``size_usd`` (or ``usd_value``), ``pnl_pct``, ``age_hours``
            (optional).

        Returns
        -------
        List[RankedPosition]
            Sorted descending by ``priority_score`` (close first → first).
        """
        with self._lock:
            ranked = [self._score(p) for p in positions]
            ranked.sort(key=lambda r: r.priority_score, reverse=True)
            self._log_ranking(ranked)
            return ranked

    def select_for_closure(
        self,
        positions: List[Dict],
        n: int,
        respect_winner_protection: bool = True,
    ) -> List[RankedPosition]:
        """
        Select the top-``n`` positions to close based on priority score.

        When ``respect_winner_protection`` is ``True``, positions whose
        ``pnl_pct`` exceeds ``winner_protection_threshold_pct`` are excluded
        from the selection unless there are no other candidates.

        Parameters
        ----------
        positions:
            Full position list.
        n:
            Number of positions to select for closure.
        respect_winner_protection:
            Honour the winner-protection threshold (default True).

        Returns
        -------
        List[RankedPosition]
            Up to ``n`` positions chosen for closure.
        """
        ranked = self.rank_for_cleanup(positions)

        cfg = self.config
        threshold = cfg.winner_protection_threshold_pct

        if respect_winner_protection and threshold is not None:
            # First pass: exclude protected winners
            non_protected = [r for r in ranked if not r.is_protected]
            if len(non_protected) >= n:
                return non_protected[:n]
            # Not enough non-protected – fall through to full ranked list
            logger.warning(
                "⚠️  ProfitPriorityCleanup: only %d non-protected positions "
                "available but %d requested – including protected winners",
                len(non_protected), n,
            )

        return ranked[:n]

    def get_cleanup_summary(self, positions: List[Dict]) -> Dict:
        """
        Return a dict summarising the portfolio's cleanup priority landscape.

        Useful for dashboards and logging.
        """
        ranked = self.rank_for_cleanup(positions)
        total = len(ranked)
        losers = [r for r in ranked if r.pnl_pct < 0]
        winners = [r for r in ranked if r.pnl_pct > 0]
        protected = [r for r in ranked if r.is_protected]

        return {
            "total_positions": total,
            "losers": len(losers),
            "winners": len(winners),
            "protected_winners": len(protected),
            "top_close_candidates": [r.symbol for r in ranked[:5]],
            "worst_pnl_pct": min((r.pnl_pct for r in ranked), default=0.0),
            "best_pnl_pct": max((r.pnl_pct for r in ranked), default=0.0),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score(self, position: Dict) -> RankedPosition:
        """Compute the cleanup priority score for a single position."""
        cfg = self.config

        symbol = position.get("symbol", "UNKNOWN")
        size_usd = float(position.get("size_usd") or position.get("usd_value") or 0)
        pnl_pct = float(position.get("pnl_pct") or 0)
        age_hours = float(position.get("age_hours") or 0)
        is_stale = bool(position.get("is_open_too_long", False))

        reasons: List[str] = []
        score: float = 0.0

        # ── Loss penalty (biggest driver for losers) ───────────────────────
        if pnl_pct < 0:
            loss_contribution = cfg.loss_weight * abs(pnl_pct)
            score += loss_contribution
            reasons.append(f"loss={pnl_pct:+.2f}% (+{loss_contribution:.2f}pts)")

        # ── Winner deduction (keep profitable positions open) ──────────────
        if pnl_pct > 0:
            winner_deduction = cfg.winner_bonus * pnl_pct
            score -= winner_deduction
            reasons.append(f"profit={pnl_pct:+.2f}% (-{winner_deduction:.2f}pts)")

        # ── Age penalty (close stale positions) ───────────────────────────
        if age_hours > cfg.min_age_hours:
            age_contribution = cfg.age_weight * (age_hours - cfg.min_age_hours)
            score += age_contribution
            reasons.append(f"age={age_hours:.1f}h (+{age_contribution:.2f}pts)")

        # ── Stale flag extra penalty ──────────────────────────────────────
        if cfg.penalise_stale_flag and is_stale:
            score += cfg.stale_extra_penalty
            reasons.append(f"stale_flag (+{cfg.stale_extra_penalty:.2f}pts)")

        # ── Size weight (tiny positions slightly preferred for closure) ────
        if size_usd > 0:
            size_contribution = cfg.size_weight * (1.0 / size_usd)
            score += size_contribution
            reasons.append(f"size=${size_usd:.2f} (+{size_contribution:.4f}pts)")

        # ── Winner protection check ───────────────────────────────────────
        threshold = cfg.winner_protection_threshold_pct
        is_protected = (
            threshold is not None
            and pnl_pct >= threshold
        )

        close_reason = " | ".join(reasons) if reasons else "neutral"

        return RankedPosition(
            symbol=symbol,
            size_usd=size_usd,
            pnl_pct=pnl_pct,
            age_hours=age_hours,
            priority_score=round(score, 6),
            close_reason=close_reason,
            is_protected=is_protected,
            raw=position,
        )

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log_ranking(self, ranked: List[RankedPosition]) -> None:
        if not ranked:
            return
        logger.debug("📊 ProfitPriorityCleanup ranking (%d positions):", len(ranked))
        for i, r in enumerate(ranked[:10]):  # Log top 10 only
            prot = " [PROTECTED]" if r.is_protected else ""
            logger.debug(
                "   #%d %s score=%.4f pnl=%+.2f%% age=%.1fh%s",
                i + 1, r.symbol, r.priority_score, r.pnl_pct, r.age_hours, prot,
            )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[ProfitPriorityCleanup] = None
_instance_lock = threading.Lock()


def get_profit_priority_cleanup(
    config: Optional[CleanupPriorityConfig] = None,
) -> ProfitPriorityCleanup:
    """
    Return the process-wide ProfitPriorityCleanup singleton.

    ``config`` is applied only on the first call; subsequent calls return the
    existing instance.
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = ProfitPriorityCleanup(config)
    return _instance
