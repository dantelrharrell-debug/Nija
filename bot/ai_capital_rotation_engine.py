"""
NIJA AI Capital Rotation Engine
=================================

Implements intelligent capital concentration through a disciplined 4-step
rotation process and a market-regime-driven meta allocation layer.

Capital Rotation Steps
----------------------
Step 1 – Let losers naturally exit via stop rules
    Identify losing positions that are already covered by the bot's stop-loss
    rules.  The engine marks them for natural exit rather than forcing an
    immediate sell, respecting the existing stop-loss workflow.

Step 2 – Close very small (dust) positions
    Positions below the dust threshold (default $5 USD) tie up capital that
    could be deployed in higher-conviction trades.  These are queued for
    immediate closure.

Step 3 – Reallocate capital into highest-conviction signals
    After freeing capital the engine ranks pending opportunities by conviction
    score and returns an ordered list for execution, from best to worst.

Step 4 – Cap total positions at MAX_ACTIVE_POSITIONS = 12
    The engine will never recommend opening a new position when 12 are
    already active, and it selects which existing positions to prune whenever
    the cap is exceeded.

Meta Allocation (AI Capital Rotation)
--------------------------------------
NIJA shifts capital proportionally across the four built-in strategies
based on the current market regime:

    Regime        | ApexTrend | MeanReversion | MomentumBreakout | Liquidity
    --------------|-----------|---------------|------------------|----------
    TRENDING      |    60 %   |     10 %      |       20 %       |   10 %
    RANGING       |    10 %   |     40 %      |       20 %       |   30 %
    VOLATILE      |    15 %   |     10 %      |       60 %       |   15 %
    UNKNOWN/OTHER |    25 %   |     25 %      |       25 %       |   25 %

When the MetaLearningOptimizer has performance data for the current regime,
its Sharpe-weighted scores blend with the hard-coded defaults so the
allocations adapt over time.

Integration Example
-------------------
    from bot.ai_capital_rotation_engine import get_ai_capital_rotation_engine

    engine = get_ai_capital_rotation_engine()

    # Run a full rotation cycle
    result = engine.run_rotation_cycle(
        current_positions=positions,   # list[dict] from broker.get_positions()
        pending_signals=signals,       # list[dict] with "symbol", "score", etc.
        account_balance=balance,       # float – current USD balance
        market_regime="TRENDING",      # str – from regime classifier
    )

    # Act on recommendations
    for pos in result.positions_to_close:
        broker.close_position(pos["symbol"])

    for sig in result.top_signals:
        broker.enter_position(sig["symbol"], sig["recommended_size_usd"])

    # Inspect meta allocation
    print(result.meta_allocation)
    # → {"ApexTrendStrategy": 0.60, "MeanReversionStrategy": 0.10, ...}

Author: NIJA Trading Systems
Version: 1.0 – AI Capital Concentration
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.ai_capital_rotation")

# ---------------------------------------------------------------------------
# Optional diversity filter (from advanced_trading_optimizer)
# ---------------------------------------------------------------------------
try:
    from advanced_trading_optimizer import _apply_diversity_filter as _diversity_filter
    _DIVERSITY_FILTER_AVAILABLE = True
except ImportError:
    try:
        from bot.advanced_trading_optimizer import _apply_diversity_filter as _diversity_filter
        _DIVERSITY_FILTER_AVAILABLE = True
    except ImportError:
        _diversity_filter = None
        _DIVERSITY_FILTER_AVAILABLE = False
        logger.debug("Diversity filter not available in ai_capital_rotation_engine")


class _SignalWrap:
    """
    Lightweight wrapper that gives a plain signal dict the attribute interface
    expected by :func:`_apply_diversity_filter` (i.e. ``symbol``, ``score``,
    ``metadata``, ``priority``, ``confidence``, ``volatility_regime``,
    ``position_size``).

    The original dict is stored in ``_orig`` and is accessible after filtering.
    """
    __slots__ = ('symbol', 'score', 'confidence', 'volatility_regime',
                 'position_size', 'priority', 'metadata', '_orig')

    def __init__(self, d: dict) -> None:
        self.symbol = d.get('symbol', '')
        self.score = float(d.get('score', 0) or 0)
        self.confidence = float(d.get('confidence', 0.5) or 0.5)
        self.volatility_regime = d.get('volatility_regime', 'normal')
        self.position_size = d.get('position_size', 0)
        self.priority = 0
        self.metadata = dict(d.get('metadata') or {})
        self._orig = d

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

MAX_ACTIVE_POSITIONS: int = 12          # Hard cap on concurrent positions
DUST_THRESHOLD_USD: float = 5.0         # Positions below this are dust
MIN_SIGNAL_SCORE: float = 60.0          # Minimum score for a signal to be eligible
META_BLEND_WEIGHT: float = 0.40         # How much learned weights blend into hard-coded defaults

# Hard-coded meta-allocation defaults per regime
# (ApexTrendStrategy, MeanReversionStrategy, MomentumBreakoutStrategy, LiquidityReversalStrategy)
_BASE_META_ALLOCATION: Dict[str, Dict[str, float]] = {
    "TRENDING": {
        "ApexTrendStrategy":        0.60,
        "MeanReversionStrategy":    0.10,
        "MomentumBreakoutStrategy": 0.20,
        "LiquidityReversalStrategy": 0.10,
    },
    "RANGING": {
        "ApexTrendStrategy":        0.10,
        "MeanReversionStrategy":    0.40,
        "MomentumBreakoutStrategy": 0.20,
        "LiquidityReversalStrategy": 0.30,
    },
    "VOLATILE": {
        "ApexTrendStrategy":        0.15,
        "MeanReversionStrategy":    0.10,
        "MomentumBreakoutStrategy": 0.60,
        "LiquidityReversalStrategy": 0.15,
    },
    "UNKNOWN": {
        "ApexTrendStrategy":        0.25,
        "MeanReversionStrategy":    0.25,
        "MomentumBreakoutStrategy": 0.25,
        "LiquidityReversalStrategy": 0.25,
    },
}

# Map common regime strings → canonical names
_REGIME_ALIASES: Dict[str, str] = {
    "trending":           "TRENDING",
    "trending_up":        "TRENDING",
    "trending_down":      "TRENDING",
    "bull_trending":      "TRENDING",
    "bullish":            "TRENDING",
    "strong_trend":       "TRENDING",
    "weak_trend":         "TRENDING",
    "ranging":            "RANGING",
    "sideways":           "RANGING",
    "consolidation":      "RANGING",
    "range":              "RANGING",
    "neutral":            "RANGING",
    "low_volatility":     "RANGING",
    "volatile":           "VOLATILE",
    "volatility_expansion": "VOLATILE",
    "high_volatility":    "VOLATILE",
    "breakout":           "VOLATILE",
    "momentum":           "VOLATILE",
    "volatile_choppy":    "VOLATILE",
}


# ─────────────────────────────────────────────────────────────────────────────
# Data containers
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RotationResult:
    """Outcome of one rotation cycle."""

    # Positions the engine recommends closing (ordered by urgency)
    positions_to_close: List[Dict] = field(default_factory=list)

    # Signals ordered by conviction – ready for execution
    top_signals: List[Dict] = field(default_factory=list)

    # Meta allocation weights (strategy_name → fraction of deployable capital)
    meta_allocation: Dict[str, float] = field(default_factory=dict)

    # Human-readable summary of the cycle
    summary: str = ""

    # Timestamp of the rotation
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Diagnostics
    active_position_count: int = 0
    dust_count: int = 0
    loser_stop_count: int = 0
    signals_evaluated: int = 0
    regime: str = "UNKNOWN"


# ─────────────────────────────────────────────────────────────────────────────
# Main Engine
# ─────────────────────────────────────────────────────────────────────────────

class AICapitalRotationEngine:
    """
    Orchestrates the 4-step capital rotation and meta allocation.

    Parameters
    ----------
    max_active_positions : int
        Hard cap on concurrent open positions.  Default: 12.
    dust_threshold_usd : float
        Positions with USD value below this are considered dust.  Default: $5.
    min_signal_score : float
        Signals below this score are excluded from reallocation candidates.
        Default: 60.0.
    meta_blend_weight : float
        Weight given to learned strategy scores when blending with the
        hard-coded regime defaults.  0.0 = fully hard-coded, 1.0 = fully
        learned.  Default: 0.40.
    """

    def __init__(
        self,
        max_active_positions: int = MAX_ACTIVE_POSITIONS,
        dust_threshold_usd: float = DUST_THRESHOLD_USD,
        min_signal_score: float = MIN_SIGNAL_SCORE,
        meta_blend_weight: float = META_BLEND_WEIGHT,
    ) -> None:
        self.max_active_positions = max_active_positions
        self.dust_threshold_usd = dust_threshold_usd
        self.min_signal_score = min_signal_score
        self.meta_blend_weight = meta_blend_weight

        self._lock = threading.RLock()

        # Lazy-load optional dependencies
        self._meta_optimizer = None
        self._meta_optimizer_loaded = False

        logger.info("=" * 70)
        logger.info("🔄 AI Capital Rotation Engine initialised")
        logger.info(f"   MAX_ACTIVE_POSITIONS : {self.max_active_positions}")
        logger.info(f"   Dust threshold       : ${self.dust_threshold_usd:.2f}")
        logger.info(f"   Min signal score     : {self.min_signal_score:.0f}/100")
        logger.info(f"   Meta-blend weight    : {self.meta_blend_weight:.0%}")
        logger.info("=" * 70)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_rotation_cycle(
        self,
        current_positions: List[Dict],
        pending_signals: List[Dict],
        account_balance: float,
        market_regime: str = "UNKNOWN",
    ) -> RotationResult:
        """
        Execute a full capital rotation cycle.

        Parameters
        ----------
        current_positions : list[dict]
            Live positions from the broker.  Each dict must have at least:
            ``symbol``, ``size_usd`` (or ``usd_value``), ``pnl_pct``,
            ``stop_loss_active`` (optional bool).
        pending_signals : list[dict]
            Candidate trade signals.  Each dict must have at least:
            ``symbol``, ``score`` (0–100).
        account_balance : float
            Current unrestricted USD balance.
        market_regime : str
            Current market regime string (see _REGIME_ALIASES for accepted values).

        Returns
        -------
        RotationResult
        """
        with self._lock:
            regime = self._normalise_regime(market_regime)
            result = RotationResult(regime=regime)
            result.active_position_count = len(current_positions)

            logger.info("=" * 70)
            logger.info(f"🔄 AI Capital Rotation Cycle — Regime: {regime}")
            logger.info(f"   Active positions : {len(current_positions)}/{self.max_active_positions}")
            logger.info(f"   Account balance  : ${account_balance:,.2f}")
            logger.info(f"   Pending signals  : {len(pending_signals)}")
            logger.info("=" * 70)

            # Step 1 – identify losers covered by stop rules
            loser_positions = self._step1_identify_stop_covered_losers(current_positions)
            result.loser_stop_count = len(loser_positions)
            logger.info(f"📌 Step 1 – Stop-covered losers identified: {len(loser_positions)}")

            # Step 2 – identify dust positions
            dust_positions = self._step2_identify_dust_positions(current_positions)
            result.dust_count = len(dust_positions)
            logger.info(f"🧹 Step 2 – Dust positions identified: {len(dust_positions)}")

            # Aggregate positions to close (dust first, then stop-covered losers)
            # Deduplicate by symbol
            seen_symbols: set = set()
            positions_to_close: List[Dict] = []
            for pos in dust_positions + loser_positions:
                sym = pos.get("symbol", "")
                if sym not in seen_symbols:
                    seen_symbols.add(sym)
                    positions_to_close.append(pos)

            # Step 4 – enforce position cap (prune excess beyond those already queued)
            cap_prune = self._step4_enforce_position_cap(
                current_positions, positions_to_close
            )
            for pos in cap_prune:
                sym = pos.get("symbol", "")
                if sym not in seen_symbols:
                    seen_symbols.add(sym)
                    positions_to_close.append(pos)

            result.positions_to_close = positions_to_close

            # Step 3 – rank and select top signals for reallocation
            top_signals = self._step3_rank_signals(
                pending_signals, current_positions, positions_to_close, account_balance
            )
            result.top_signals = top_signals
            result.signals_evaluated = len(pending_signals)
            logger.info(f"🎯 Step 3 – Top signals selected: {len(top_signals)}")

            # Meta allocation
            result.meta_allocation = self.get_meta_allocation(regime)

            # Build summary
            result.summary = self._build_summary(result)
            logger.info(result.summary)

            return result

    def get_meta_allocation(self, market_regime: str = "UNKNOWN") -> Dict[str, float]:
        """
        Return capital allocation weights across the four built-in strategies
        for the given market regime.

        The weights are a blend of:
        - Hard-coded regime defaults (e.g. trending → 60% trend strategy)
        - Learned Sharpe-weighted scores from ``MetaLearningOptimizer``
          (when available and when ``meta_blend_weight > 0``)

        Parameters
        ----------
        market_regime : str
            Accepted values: TRENDING, RANGING, VOLATILE, UNKNOWN (or aliases).

        Returns
        -------
        dict[str, float]
            Strategy name → fraction of deployable capital (sums to ~1.0).
        """
        regime = self._normalise_regime(market_regime)
        base = dict(_BASE_META_ALLOCATION.get(regime, _BASE_META_ALLOCATION["UNKNOWN"]))

        # Attempt to blend with learned weights
        if self.meta_blend_weight > 0:
            learned = self._get_learned_weights(regime)
            if learned:
                for strategy in base:
                    base_w = base[strategy]
                    learned_w = learned.get(strategy, base_w)
                    base[strategy] = (
                        (1.0 - self.meta_blend_weight) * base_w
                        + self.meta_blend_weight * learned_w
                    )
                # Re-normalise after blending
                total = sum(base.values()) or 1.0
                base = {k: v / total for k, v in base.items()}

        logger.debug(
            f"📊 Meta allocation for {regime}: "
            + ", ".join(f"{k.replace('Strategy','')}: {v:.0%}" for k, v in base.items())
        )
        return base

    # ------------------------------------------------------------------
    # Step implementations
    # ------------------------------------------------------------------

    def _step1_identify_stop_covered_losers(
        self, positions: List[Dict]
    ) -> List[Dict]:
        """
        Step 1: Flag losing positions that are covered by active stop-loss
        rules and should be allowed to exit naturally rather than being
        force-closed immediately.

        A position qualifies when:
        - It has a negative P&L (``pnl_pct < 0``)
        - It has ``stop_loss_active = True`` OR a defined ``stop_loss_price``

        Returns a list of positions annotated with ``rotation_reason``.
        """
        losers: List[Dict] = []
        for pos in positions:
            pnl_pct = float(pos.get("pnl_pct", 0) or 0)
            stop_active = bool(pos.get("stop_loss_active", False))
            stop_price = pos.get("stop_loss_price") or pos.get("stop_price")

            if pnl_pct < 0 and (stop_active or stop_price is not None):
                annotated = dict(pos)
                annotated["rotation_reason"] = (
                    f"STOP_COVERED_LOSER (pnl={pnl_pct:.2%}, "
                    f"stop={'active' if stop_active else f'@ {stop_price}'})"
                )
                annotated["rotation_action"] = "natural_exit"
                losers.append(annotated)
                logger.debug(
                    f"   Step 1 – {pos.get('symbol')}: natural exit via stop "
                    f"(pnl={pnl_pct:.2%})"
                )
        return losers

    def _step2_identify_dust_positions(
        self, positions: List[Dict]
    ) -> List[Dict]:
        """
        Step 2: Identify positions whose USD value falls below the dust
        threshold.  These are queued for immediate closure to reclaim
        capital that would otherwise bleed away in fees.
        """
        dust: List[Dict] = []
        for pos in positions:
            size_usd = float(
                pos.get("size_usd", 0)
                or pos.get("usd_value", 0)
                or 0
            )
            if size_usd < self.dust_threshold_usd:
                annotated = dict(pos)
                annotated["rotation_reason"] = (
                    f"DUST (${size_usd:.2f} < ${self.dust_threshold_usd:.2f} threshold)"
                )
                annotated["rotation_action"] = "close_immediately"
                dust.append(annotated)
                logger.debug(
                    f"   Step 2 – {pos.get('symbol')}: dust ${size_usd:.2f}"
                )
        return dust

    def _step3_rank_signals(
        self,
        signals: List[Dict],
        current_positions: List[Dict],
        positions_to_close: List[Dict],
        account_balance: float,
    ) -> List[Dict]:
        """
        Step 3: Rank pending signals by conviction score and return those
        eligible for capital reallocation.

        Eligibility criteria:
        - Score ≥ ``min_signal_score``
        - Not already in an open position
        - Slots remain below ``max_active_positions`` after accounting for
          planned closures

        Each returned signal is annotated with ``recommended_size_usd``.
        """
        open_symbols = {p.get("symbol", "") for p in current_positions}
        close_symbols = {p.get("symbol", "") for p in positions_to_close}

        # Remaining slots after planned closures
        remaining_positions = [
            p for p in current_positions
            if p.get("symbol") not in close_symbols
        ]
        available_slots = max(0, self.max_active_positions - len(remaining_positions))

        if available_slots == 0:
            logger.info("   Step 3 – No available slots for new entries after rotation")
            return []

        # Filter and score
        eligible = [
            s for s in signals
            if float(s.get("score", 0) or 0) >= self.min_signal_score
            and s.get("symbol", "") not in open_symbols
        ]

        # Sort descending by score
        eligible.sort(key=lambda s: float(s.get("score", 0) or 0), reverse=True)

        # Apply sector-diversity filter so top slots aren't filled with
        # correlated assets (e.g. BTC + ETH + SOL → BTC + LINK + AVAX).
        if _DIVERSITY_FILTER_AVAILABLE and _diversity_filter is not None:
            # _apply_diversity_filter operates on objects with .symbol and
            # .metadata attributes; use the module-level _SignalWrap adapter.
            wrapped = [_SignalWrap(s) for s in eligible]
            filtered = _diversity_filter(wrapped)
            eligible = [w._orig for w in filtered]

        # Take only as many as available slots
        top = eligible[:available_slots]

        # Annotate with a suggested position size (equal-weight across slots)
        deployable = account_balance * 0.95  # keep 5% reserve
        if top:
            size_per_trade = deployable / max(len(top), 1)
            for i, sig in enumerate(top):
                annotated = dict(sig)
                annotated["recommended_size_usd"] = round(size_per_trade, 2)
                annotated["rotation_action"] = "enter_new_position"
                top[i] = annotated

        return top

    def _step4_enforce_position_cap(
        self,
        current_positions: List[Dict],
        already_queued: List[Dict],
    ) -> List[Dict]:
        """
        Step 4: Enforce the MAX_ACTIVE_POSITIONS cap.

        If, after removing already-queued closures, the bot would still exceed
        the cap, select additional positions for closure.  The selection
        criterion prioritises:
        1. Smallest USD value (dust-like)
        2. Worst P&L percentage
        """
        queued_symbols = {p.get("symbol", "") for p in already_queued}
        remaining = [
            p for p in current_positions
            if p.get("symbol", "") not in queued_symbols
        ]

        excess = len(remaining) - self.max_active_positions
        if excess <= 0:
            return []

        # Sort: smallest value first, then worst P&L
        remaining_sorted = sorted(
            remaining,
            key=lambda p: (
                float(p.get("size_usd", 0) or p.get("usd_value", 0) or 0),
                float(p.get("pnl_pct", 0) or 0),
            ),
        )

        to_prune: List[Dict] = []
        for pos in remaining_sorted[:excess]:
            annotated = dict(pos)
            annotated["rotation_reason"] = (
                f"CAP_EXCEEDED (max={self.max_active_positions})"
            )
            annotated["rotation_action"] = "close_immediately"
            to_prune.append(annotated)
            logger.warning(
                f"   Step 4 – {pos.get('symbol')}: pruned to enforce "
                f"cap ({self.max_active_positions})"
            )

        if to_prune:
            logger.warning(
                f"🚨 Step 4 – Position cap enforcement: closing {len(to_prune)} "
                f"excess position(s)"
            )
        return to_prune

    # ------------------------------------------------------------------
    # Meta allocation helpers
    # ------------------------------------------------------------------

    def _normalise_regime(self, regime: str) -> str:
        """Map any regime string to a canonical name."""
        if not regime:
            return "UNKNOWN"
        key = regime.strip().lower()
        canonical = _REGIME_ALIASES.get(key)
        if canonical:
            return canonical
        # Try uppercase lookup
        upper = regime.strip().upper()
        if upper in _BASE_META_ALLOCATION:
            return upper
        return "UNKNOWN"

    def _get_learned_weights(self, regime: str) -> Optional[Dict[str, float]]:
        """
        Fetch strategy weights from MetaLearningOptimizer if available.
        Returns None on failure.
        """
        if not self._meta_optimizer_loaded:
            self._meta_optimizer_loaded = True
            try:
                from bot.meta_learning_optimizer import get_meta_learning_optimizer
                self._meta_optimizer = get_meta_learning_optimizer()
            except ImportError:
                try:
                    from meta_learning_optimizer import get_meta_learning_optimizer
                    self._meta_optimizer = get_meta_learning_optimizer()
                except ImportError:
                    self._meta_optimizer = None

        if self._meta_optimizer is None:
            return None

        try:
            return self._meta_optimizer.get_regime_weights(regime)
        except Exception as exc:
            logger.debug(f"MetaLearningOptimizer lookup failed: {exc}")
            return None

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def _build_summary(self, result: RotationResult) -> str:
        alloc_str = " | ".join(
            f"{k.replace('Strategy', '')}: {v:.0%}"
            for k, v in result.meta_allocation.items()
        )
        lines = [
            "",
            "=" * 70,
            "🔄 AI CAPITAL ROTATION SUMMARY",
            "=" * 70,
            f"  Regime              : {result.regime}",
            f"  Active positions    : {result.active_position_count}/{self.max_active_positions}",
            f"  Stop-covered losers : {result.loser_stop_count} (natural exit)",
            f"  Dust positions      : {result.dust_count} (immediate close)",
            f"  Positions to close  : {len(result.positions_to_close)}",
            f"  Signals evaluated   : {result.signals_evaluated}",
            f"  Top signals         : {len(result.top_signals)}",
            f"  Meta allocation     : {alloc_str}",
            "=" * 70,
        ]
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Singleton accessor
# ─────────────────────────────────────────────────────────────────────────────

_ENGINE_INSTANCE: Optional[AICapitalRotationEngine] = None
_ENGINE_LOCK = threading.Lock()


def get_ai_capital_rotation_engine(
    max_active_positions: int = MAX_ACTIVE_POSITIONS,
    dust_threshold_usd: float = DUST_THRESHOLD_USD,
    min_signal_score: float = MIN_SIGNAL_SCORE,
    meta_blend_weight: float = META_BLEND_WEIGHT,
) -> AICapitalRotationEngine:
    """
    Return the process-wide singleton ``AICapitalRotationEngine``.

    Parameters are only applied on the first call; subsequent calls return the
    same instance regardless of arguments.
    """
    global _ENGINE_INSTANCE
    if _ENGINE_INSTANCE is None:
        with _ENGINE_LOCK:
            if _ENGINE_INSTANCE is None:
                _ENGINE_INSTANCE = AICapitalRotationEngine(
                    max_active_positions=max_active_positions,
                    dust_threshold_usd=dust_threshold_usd,
                    min_signal_score=min_signal_score,
                    meta_blend_weight=meta_blend_weight,
                )
    return _ENGINE_INSTANCE
