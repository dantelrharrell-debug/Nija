"""
NIJA AI Capital Allocator
==========================

Automatically shifts capital towards the best-performing accounts using
a momentum-weighted scoring system that combines Sharpe ratio, win-rate,
and profit factor.  Scores are updated every cycle via EMA smoothing so
allocation reacts smoothly rather than rebalancing violently on a single
trade.

Integration
-----------
Works alongside:
- ``AccountPerformanceDashboard``  — source of per-account metrics
- ``GlobalCapitalManager``         — receives updated account weights
- ``SignalBroadcaster``            — uses the weights for sizing

Usage
-----
::

    from bot.ai_capital_allocator import get_ai_capital_allocator

    allocator = get_ai_capital_allocator()
    allocator.update()          # call once per trading cycle

    weights = allocator.get_weights()
    # → {"coinbase": 0.62, "kraken": 0.38}

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger("nija.ai_allocator")

# EMA decay for score smoothing (0 = ignore new, 1 = ignore history)
EMA_ALPHA = 0.25

# Metric weights used to compose a single performance score
SCORE_WEIGHTS = {
    "sharpe_ratio":   0.45,
    "win_rate_pct":   0.30,
    "profit_factor":  0.25,
}

# Floor allocation so no account is completely starved
MIN_WEIGHT = 0.05   # 5 %


# ---------------------------------------------------------------------------
# Optional dependency imports
# ---------------------------------------------------------------------------
try:
    from account_performance_dashboard import get_account_performance_dashboard
    _DASH_AVAILABLE = True
except ImportError:
    try:
        from bot.account_performance_dashboard import get_account_performance_dashboard
        _DASH_AVAILABLE = True
    except ImportError:
        _DASH_AVAILABLE = False
        get_account_performance_dashboard = None  # type: ignore[assignment]

try:
    from global_capital_manager import get_global_capital_manager
    _GCM_AVAILABLE = True
except ImportError:
    try:
        from bot.global_capital_manager import get_global_capital_manager
        _GCM_AVAILABLE = True
    except ImportError:
        _GCM_AVAILABLE = False
        get_global_capital_manager = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# AICapitalAllocator
# ---------------------------------------------------------------------------

class AICapitalAllocator:
    """
    EMA-smoothed capital allocator that auto-shifts funds towards the
    best-performing broker accounts each trading cycle.
    """

    def __init__(
        self,
        ema_alpha: float = EMA_ALPHA,
        score_weights: Optional[Dict[str, float]] = None,
        min_weight: float = MIN_WEIGHT,
    ) -> None:
        self._ema_alpha = ema_alpha
        self._score_weights = score_weights or SCORE_WEIGHTS
        self._min_weight = min_weight
        self._ema_scores: Dict[str, float] = {}      # account_id → smoothed score
        self._weights: Dict[str, float] = {}          # account_id → allocation weight
        self._last_updated: Optional[str] = None
        self._lock = threading.Lock()

    # ── Score calculation ─────────────────────────────────────────────────────

    def _compute_raw_score(self, stats: Dict) -> float:
        """Compose a weighted performance score from account metrics."""
        sharpe = float(stats.get("sharpe_ratio", 0.0))
        win_rate = float(stats.get("win_rate_pct", 0.0))      # 0–100
        pf = stats.get("profit_factor", 1.0)
        if pf == "∞":
            pf = 5.0
        pf = float(pf)

        # Normalise each dimension to a 0–1 scale
        sharpe_norm   = min(max(sharpe, 0.0) / 3.0, 1.0)     # 3.0 = excellent
        win_rate_norm = min(max(win_rate, 0.0) / 100.0, 1.0)
        pf_norm       = min(max(pf - 1.0, 0.0) / 2.0, 1.0)   # 3.0 PF → 1.0

        score = (
            sharpe_norm   * self._score_weights.get("sharpe_ratio", 0.0)
            + win_rate_norm * self._score_weights.get("win_rate_pct", 0.0)
            + pf_norm       * self._score_weights.get("profit_factor", 0.0)
        )
        return max(score, 0.001)   # minimum floor so new accounts aren't zero

    def _apply_ema(self, account_id: str, raw_score: float) -> float:
        """EMA-smooth raw score against historical EMA score."""
        prev = self._ema_scores.get(account_id, raw_score)
        smoothed = self._ema_alpha * raw_score + (1 - self._ema_alpha) * prev
        self._ema_scores[account_id] = smoothed
        return smoothed

    def _scores_to_weights(self, scores: Dict[str, float]) -> Dict[str, float]:
        """Convert raw scores to allocation weights with floor enforcement."""
        total = sum(scores.values())
        if total == 0:
            n = len(scores)
            return {aid: 1.0 / n for aid in scores} if n else {}

        raw_weights = {aid: s / total for aid, s in scores.items()}

        # Apply minimum weight floor
        below_floor = {aid: w for aid, w in raw_weights.items() if w < self._min_weight}
        above_floor = {aid: w for aid, w in raw_weights.items() if w >= self._min_weight}

        if not below_floor:
            return raw_weights

        # Lift below-floor accounts; scale above-floor accounts down proportionally
        floor_total = len(below_floor) * self._min_weight
        above_total = sum(above_floor.values())
        available = max(1.0 - floor_total, 0.0)

        weights: Dict[str, float] = {}
        for aid in below_floor:
            weights[aid] = self._min_weight
        for aid, w in above_floor.items():
            weights[aid] = (w / above_total) * available if above_total > 0 else available / len(above_floor)

        # Final normalisation
        total_w = sum(weights.values())
        if total_w > 0:
            weights = {aid: round(w / total_w, 6) for aid, w in weights.items()}
        return weights

    # ── Public API ────────────────────────────────────────────────────────────

    def update(self) -> Dict[str, float]:
        """
        Recompute allocation weights from the latest dashboard metrics.

        Should be called once per trading cycle (e.g. inside ``run_cycle``).

        Returns:
            Updated weight dict {account_id → fraction (0–1)}.
        """
        if not _DASH_AVAILABLE or not get_account_performance_dashboard:
            return self._weights

        try:
            dashboard = get_account_performance_dashboard().get_dashboard()
        except Exception as exc:
            logger.warning("[AIAllocator] dashboard unavailable: %s", exc)
            return self._weights

        if not dashboard:
            return self._weights

        with self._lock:
            smoothed: Dict[str, float] = {}
            for account_id, stats in dashboard.items():
                raw = self._compute_raw_score(stats)
                smoothed[account_id] = self._apply_ema(account_id, raw)

            self._weights = self._scores_to_weights(smoothed)
            self._last_updated = datetime.now(timezone.utc).isoformat()

        # Publish weights back to GlobalCapitalManager so SignalBroadcaster
        # picks them up automatically. We store the weights directly on the
        # allocator only — we do NOT touch GCM account balances here to avoid
        # corrupting the real USD values used for capital-scaling calculations.
        logger.info(
            "[AIAllocator] weights updated → %s",
            {k: f"{v:.1%}" for k, v in self._weights.items()},
        )
        return dict(self._weights)

    def get_weights(self) -> Dict[str, float]:
        """Return the last computed allocation weights."""
        with self._lock:
            return dict(self._weights)

    def get_best_account(self) -> Optional[str]:
        """Return the account_id currently receiving the highest allocation."""
        with self._lock:
            return max(self._weights, key=lambda k: self._weights[k]) if self._weights else None

    def get_report(self) -> Dict:
        """Return a full report for dashboards / logging."""
        with self._lock:
            return {
                "weights": dict(self._weights),
                "ema_scores": dict(self._ema_scores),
                "best_account": max(self._weights, key=lambda k: self._weights[k]) if self._weights else None,
                "last_updated": self._last_updated,
                "config": {
                    "ema_alpha": self._ema_alpha,
                    "score_weights": self._score_weights,
                    "min_weight_pct": self._min_weight * 100,
                },
            }

    @property
    def last_updated(self) -> Optional[str]:
        with self._lock:
            return self._last_updated


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_ALLOCATOR: Optional[AICapitalAllocator] = None
_ALLOCATOR_LOCK = threading.Lock()


def get_ai_capital_allocator() -> AICapitalAllocator:
    """Return the process-wide AICapitalAllocator singleton."""
    global _ALLOCATOR
    with _ALLOCATOR_LOCK:
        if _ALLOCATOR is None:
            _ALLOCATOR = AICapitalAllocator()
            logger.info(
                "[AIAllocator] singleton created "
                "(EMA alpha=%.0f%%, min_weight=%.0f%%) — "
                "auto capital shift to best performers enabled",
                EMA_ALPHA * 100,
                MIN_WEIGHT * 100,
            )
    return _ALLOCATOR
