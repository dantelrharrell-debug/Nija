"""
NIJA Trade Regime Risk Controller
===================================

This module answers one critical question:

    "Should the bot be trading right now at all?"

Even the best strategies lose money when the entire market environment is bad.
Institutional systems add a meta-layer above the individual strategy to evaluate
macro market conditions before allowing any new entries.

Decision Flow
-------------
::

    Market Scan
        ↓
    Market Regime Controller   ← (this module)
        ↓
    Market Structure Filter    (per-symbol: HH/HL + volume + RSI)
        ↓
    Strategy (APEX)            (per-symbol signal generation)
        ↓
    Risk Budget Engine         (per-trade position sizing)
        ↓
    Trade

Regime Decisions
----------------
* **FAVORABLE**   – Healthy trending conditions; full strategy, normal sizing.
* **NEUTRAL**     – Mixed signals; reduced position sizing, stricter entry filters.
* **UNFAVORABLE** – Choppy or deteriorating environment; new entries paused.
* **CRISIS**      – Extreme volatility / breakdown; all new entries hard-blocked.

Scoring Model
-------------
Four factors are combined into a single regime score (0–100):

1. **Breadth score** – Fraction of recently analysed assets that passed the
   structural filter (Higher High / Higher Low + volume + RSI).
2. **Trend score** – Fraction of assets whose ADX indicates a meaningful trend
   (ADX ≥ ``ADX_TREND_THRESHOLD``).
3. **Momentum score** – Fraction of assets with RSI above the neutral midpoint
   (``RSI_BULLISH_THRESHOLD``).
4. **Volatility penalty** – Fraction of assets whose ATR/price ratio exceeds a
   crisis threshold; subtracted from the overall score.

The score maps to a regime via ``REGIME_THRESHOLDS``.

Author : NIJA Trading Systems
Version: 1.0
Date   : March 2026
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Deque, Dict, Optional, Tuple

logger = logging.getLogger("nija.regime_controller")

# ---------------------------------------------------------------------------
# Tuneable thresholds
# ---------------------------------------------------------------------------

# ADX threshold above which a market is considered "trending"
ADX_TREND_THRESHOLD: float = 22.0

# RSI threshold above which a market is considered "bullish momentum"
RSI_BULLISH_THRESHOLD: float = 52.0

# ATR/price ratio above which a market is in a volatility crisis
ATR_CRISIS_THRESHOLD: float = 0.06   # 6 % ATR/price

# Minimum fraction of scanned markets that must pass structure filter for FAVORABLE regime
MIN_BREADTH_FAVORABLE: float = 0.35  # ≥ 35 % of assets structurally valid

# Weights for each scoring component (must sum to 1.0)
BREADTH_WEIGHT: float = 0.35
TREND_WEIGHT: float = 0.30
MOMENTUM_WEIGHT: float = 0.25
VOLATILITY_PENALTY_WEIGHT: float = 0.10

# Score → Regime mapping (lower bound inclusive)
REGIME_THRESHOLDS: Dict[str, float] = {
    "FAVORABLE":   60.0,
    "NEUTRAL":     35.0,
    "UNFAVORABLE": 15.0,
    # anything below 15 → CRISIS
}

# Rolling window of market snapshots used to smooth regime transitions
REGIME_WINDOW_SIZE: int = 3   # Number of scan cycles to average


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class RegimeDecision(Enum):
    """Global trading regime — determines whether new entries are permitted."""

    FAVORABLE = "FAVORABLE"       # Healthy market; normal trading permitted
    NEUTRAL = "NEUTRAL"           # Mixed signals; reduced sizing, stricter gates
    UNFAVORABLE = "UNFAVORABLE"   # Poor conditions; new entries paused
    CRISIS = "CRISIS"             # Extreme conditions; hard block on all new entries


@dataclass
class MarketSnapshot:
    """Summary of market conditions collected during a single scan cycle."""

    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    total_assets_scanned: int = 0
    assets_passed_structure: int = 0    # Passed HH/HL + volume + RSI filter
    assets_trending: int = 0            # ADX ≥ ADX_TREND_THRESHOLD
    assets_bullish_momentum: int = 0    # RSI ≥ RSI_BULLISH_THRESHOLD
    assets_in_volatility_crisis: int = 0  # ATR/price ≥ ATR_CRISIS_THRESHOLD

    # Derived fractions (computed when snapshot is finalised)
    breadth_ratio: float = 0.0
    trend_ratio: float = 0.0
    momentum_ratio: float = 0.0
    crisis_ratio: float = 0.0
    regime_score: float = 0.0
    regime: str = RegimeDecision.NEUTRAL.value

    def finalise(self) -> None:
        """Compute derived ratios and regime score after all assets are recorded."""
        n = max(self.total_assets_scanned, 1)

        self.breadth_ratio = self.assets_passed_structure / n
        self.trend_ratio = self.assets_trending / n
        self.momentum_ratio = self.assets_bullish_momentum / n
        self.crisis_ratio = self.assets_in_volatility_crisis / n

        raw_score = (
            BREADTH_WEIGHT * self.breadth_ratio * 100
            + TREND_WEIGHT * self.trend_ratio * 100
            + MOMENTUM_WEIGHT * self.momentum_ratio * 100
            - VOLATILITY_PENALTY_WEIGHT * self.crisis_ratio * 100
        )
        self.regime_score = max(0.0, min(100.0, raw_score))
        self.regime = _score_to_regime(self.regime_score).value

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp,
            "total_assets_scanned": self.total_assets_scanned,
            "assets_passed_structure": self.assets_passed_structure,
            "assets_trending": self.assets_trending,
            "assets_bullish_momentum": self.assets_bullish_momentum,
            "assets_in_volatility_crisis": self.assets_in_volatility_crisis,
            "breadth_ratio": round(self.breadth_ratio, 4),
            "trend_ratio": round(self.trend_ratio, 4),
            "momentum_ratio": round(self.momentum_ratio, 4),
            "crisis_ratio": round(self.crisis_ratio, 4),
            "regime_score": round(self.regime_score, 2),
            "regime": self.regime,
        }


@dataclass
class RegimeResult:
    """Output of a regime evaluation."""

    decision: RegimeDecision
    score: float                            # 0–100
    reason: str
    allow_new_entries: bool
    position_size_multiplier: float         # Applied to every new position
    snapshot: MarketSnapshot
    smoothed_score: float = 0.0            # Average over the rolling window
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict:
        return {
            "decision": self.decision.value,
            "score": round(self.score, 2),
            "smoothed_score": round(self.smoothed_score, 2),
            "reason": self.reason,
            "allow_new_entries": self.allow_new_entries,
            "position_size_multiplier": self.position_size_multiplier,
            "snapshot": self.snapshot.to_dict(),
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _score_to_regime(score: float) -> RegimeDecision:
    """Map a numeric score (0–100) to a :class:`RegimeDecision`."""
    if score >= REGIME_THRESHOLDS["FAVORABLE"]:
        return RegimeDecision.FAVORABLE
    if score >= REGIME_THRESHOLDS["NEUTRAL"]:
        return RegimeDecision.NEUTRAL
    if score >= REGIME_THRESHOLDS["UNFAVORABLE"]:
        return RegimeDecision.UNFAVORABLE
    return RegimeDecision.CRISIS


def _regime_config(decision: RegimeDecision) -> Tuple[bool, float, str]:
    """
    Return ``(allow_new_entries, position_size_multiplier, reason)`` for a
    given :class:`RegimeDecision`.
    """
    configs = {
        RegimeDecision.FAVORABLE: (
            True,
            1.0,
            "Healthy trending market — full strategy active",
        ),
        RegimeDecision.NEUTRAL: (
            True,
            0.75,
            "Mixed market conditions — position sizes reduced to 75%",
        ),
        RegimeDecision.UNFAVORABLE: (
            False,
            0.0,
            "Unfavorable market regime — new entries paused",
        ),
        RegimeDecision.CRISIS: (
            False,
            0.0,
            "CRISIS regime detected — all new entries hard-blocked",
        ),
    }
    return configs[decision]


# ---------------------------------------------------------------------------
# Main controller
# ---------------------------------------------------------------------------

class MarketRegimeController:
    """
    Evaluates the global market environment once per scan cycle and decides
    whether new trade entries should be permitted.

    Typical integration
    -------------------
    ::

        controller = MarketRegimeController()

        # --- inside the scan cycle, before the symbol loop ---
        snapshot = controller.begin_snapshot()

        for symbol in markets_to_scan:
            df = fetch_candles(symbol)

            # Update the snapshot with per-symbol indicators
            controller.record_asset(
                snapshot,
                adx=indicators['adx'],
                rsi=indicators['rsi'],
                structure_passed=structure_valid(df),
                atr_pct=atr / price,
            )

        # Finalise and evaluate
        result = controller.evaluate(snapshot)

        if not result.allow_new_entries:
            logger.warning(f"🚫 Regime Controller: {result.reason}")
            return   # Skip new entries this cycle
    """

    def __init__(self, window_size: int = REGIME_WINDOW_SIZE) -> None:
        self._window_size = window_size
        self._history: Deque[MarketSnapshot] = deque(maxlen=window_size)
        self._last_result: Optional[RegimeResult] = None
        logger.info("=" * 65)
        logger.info("🌐 Market Regime Controller Initialized")
        logger.info("=" * 65)
        logger.info(f"  Window size         : {window_size} cycles")
        logger.info(f"  ADX trend threshold : {ADX_TREND_THRESHOLD}")
        logger.info(f"  RSI bullish thresh  : {RSI_BULLISH_THRESHOLD}")
        logger.info(f"  ATR crisis thresh   : {ATR_CRISIS_THRESHOLD:.0%}")
        logger.info(f"  Min breadth (FAVO.) : {MIN_BREADTH_FAVORABLE:.0%}")
        logger.info("=" * 65)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def begin_snapshot(self) -> MarketSnapshot:
        """
        Create a fresh :class:`MarketSnapshot` for the current scan cycle.

        Call this **once** at the start of each scan cycle, before iterating
        over individual symbols.  Pass the returned snapshot to
        :meth:`record_asset` for every symbol scanned, then to
        :meth:`evaluate` to obtain the regime decision.
        """
        return MarketSnapshot()

    def record_asset(
        self,
        snapshot: MarketSnapshot,
        *,
        adx: float,
        rsi: float,
        structure_passed: bool,
        atr_pct: float,
    ) -> None:
        """
        Record per-asset indicators into the current cycle's snapshot.

        Parameters
        ----------
        snapshot:
            The :class:`MarketSnapshot` returned by :meth:`begin_snapshot`.
        adx:
            Average Directional Index value for this asset.
        rsi:
            RSI value (any period — e.g. RSI_14) for this asset.
        structure_passed:
            ``True`` if the asset passed the :mod:`market_structure_filter`
            (Higher High/Low + volume expansion + momentum).
        atr_pct:
            ATR expressed as a fraction of the current price
            (e.g. ``0.03`` for 3 % ATR).
        """
        snapshot.total_assets_scanned += 1

        if structure_passed:
            snapshot.assets_passed_structure += 1

        if adx >= ADX_TREND_THRESHOLD:
            snapshot.assets_trending += 1

        if rsi >= RSI_BULLISH_THRESHOLD:
            snapshot.assets_bullish_momentum += 1

        if atr_pct >= ATR_CRISIS_THRESHOLD:
            snapshot.assets_in_volatility_crisis += 1

    def evaluate(self, snapshot: MarketSnapshot) -> RegimeResult:
        """
        Finalise the snapshot and produce a :class:`RegimeResult`.

        This method:
        1. Computes per-snapshot scores and regime.
        2. Stores the snapshot in the rolling window.
        3. Smooths the score over the last ``window_size`` cycles to avoid
           whipsaw regime changes.
        4. Maps the smoothed score to a final :class:`RegimeDecision`.
        5. Logs a clear summary banner.

        Parameters
        ----------
        snapshot:
            Snapshot populated by calls to :meth:`record_asset`.

        Returns
        -------
        RegimeResult
        """
        if snapshot.total_assets_scanned == 0:
            logger.warning(
                "⚠️  Regime Controller: no assets scanned — defaulting to NEUTRAL"
            )
            snapshot.regime_score = 50.0
            snapshot.regime = RegimeDecision.NEUTRAL.value
            self._history.append(snapshot)
            result = self._build_result(snapshot, smoothed_score=50.0)
            self._last_result = result
            return result

        # Finalise the raw snapshot
        snapshot.finalise()

        # Store in rolling window
        self._history.append(snapshot)

        # Smooth over window to reduce whipsaw
        smoothed_score = sum(s.regime_score for s in self._history) / len(
            self._history
        )

        # Override: if breadth is critically low, clamp smoothed score
        if snapshot.breadth_ratio < MIN_BREADTH_FAVORABLE * 0.5:
            smoothed_score = min(smoothed_score, REGIME_THRESHOLDS["UNFAVORABLE"])
            logger.debug(
                "Breadth critically low (%.1f%%) — clamping smoothed score to %.1f",
                snapshot.breadth_ratio * 100,
                smoothed_score,
            )

        result = self._build_result(snapshot, smoothed_score=smoothed_score)
        self._last_result = result
        self._log_summary(result)
        return result

    @property
    def last_result(self) -> Optional[RegimeResult]:
        """Return the result of the most recent :meth:`evaluate` call, or ``None``."""
        return self._last_result

    def get_history(self) -> list:
        """Return the rolling window of recent :class:`MarketSnapshot` dicts."""
        return [s.to_dict() for s in self._history]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_result(
        self, snapshot: MarketSnapshot, smoothed_score: float
    ) -> RegimeResult:
        decision = _score_to_regime(smoothed_score)
        allow, multiplier, reason = _regime_config(decision)
        return RegimeResult(
            decision=decision,
            score=snapshot.regime_score,
            smoothed_score=smoothed_score,
            reason=reason,
            allow_new_entries=allow,
            position_size_multiplier=multiplier,
            snapshot=snapshot,
        )

    def _log_summary(self, result: RegimeResult) -> None:
        snap = result.snapshot
        icons = {
            RegimeDecision.FAVORABLE: "✅",
            RegimeDecision.NEUTRAL: "⚠️",
            RegimeDecision.UNFAVORABLE: "🚫",
            RegimeDecision.CRISIS: "🔴",
        }
        icon = icons.get(result.decision, "❓")
        logger.info("=" * 65)
        logger.info(f"  {icon}  REGIME CONTROLLER — {result.decision.value}")
        logger.info("=" * 65)
        logger.info(
            f"  Score (raw / smoothed) : {result.score:.1f} / {result.smoothed_score:.1f}"
        )
        logger.info(
            f"  Breadth    : {snap.breadth_ratio:.1%}  "
            f"({snap.assets_passed_structure}/{snap.total_assets_scanned} assets)"
        )
        logger.info(
            f"  Trending   : {snap.trend_ratio:.1%}  "
            f"({snap.assets_trending}/{snap.total_assets_scanned} assets)"
        )
        logger.info(
            f"  Momentum   : {snap.momentum_ratio:.1%}  "
            f"({snap.assets_bullish_momentum}/{snap.total_assets_scanned} assets)"
        )
        logger.info(
            f"  Crisis ATR : {snap.crisis_ratio:.1%}  "
            f"({snap.assets_in_volatility_crisis}/{snap.total_assets_scanned} assets)"
        )
        logger.info(f"  Decision   : {result.reason}")
        logger.info(
            f"  New entries: {'ALLOWED' if result.allow_new_entries else 'BLOCKED'}  |  "
            f"Size multiplier: {result.position_size_multiplier:.2f}x"
        )
        logger.info("=" * 65)


# ---------------------------------------------------------------------------
# Module-level singleton helper
# ---------------------------------------------------------------------------

_controller_instance: Optional[MarketRegimeController] = None


def get_regime_controller(window_size: int = REGIME_WINDOW_SIZE) -> MarketRegimeController:
    """
    Return (and lazily create) the process-wide singleton
    :class:`MarketRegimeController`.

    Using a singleton ensures that the rolling-window history persists
    across scan cycles without needing to pass the controller through
    every function signature.
    """
    global _controller_instance
    if _controller_instance is None:
        _controller_instance = MarketRegimeController(window_size=window_size)
    return _controller_instance
