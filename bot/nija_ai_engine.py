"""
NIJA AI Engine
==============

Fully-tuned, plug-and-play entry-signal coordinator.

Solves three root causes of the bot stalling:

1. **Ranking instead of hard gates** — all candidate symbols are scored and the
   top-N are selected, so the bot ALWAYS has something to trade even when the
   market is mediocre.

2. **Adaptive threshold** — the minimum acceptable score drops automatically
   when the candidate pool is thin, preventing zero-entry cycles.

3. **Cycle speed control** — scan interval shortens when the market is hot
   (many signals) and lengthens when it is cold, giving fast execution when
   opportunities exist and avoiding pointless API calls when they don't.

Architecture
------------
::

    NijaAIEngine
    ├── evaluate_symbol(df, indicators, side, regime, broker) → AIEngineSignal | None
    ├── rank_and_select(candidates, available_slots) → List[AIEngineSignal]
    └── CycleSpeedController  (attribute: self.speed_ctrl)

Integration
-----------
Called from ``NIJAApexStrategyV71.check_entry_with_enhanced_scoring``.
The ``NijaCoreLoop`` uses ``rank_and_select`` to pick top-N across all scanned
symbols in a single cycle pass.

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("nija.ai_engine")

# ---------------------------------------------------------------------------
# Score tier constants
# ---------------------------------------------------------------------------
TIER_ELITE = 75.0    # 1.5× position size
TIER_GOOD = 60.0     # 1.0× position size
TIER_FAIR = 45.0     # 0.75× position size
TIER_FLOOR = 30.0    # 0.5× position size (taken only as top-N, no better option)

# Composite score blend weights (must sum to 1.0)
_W_ENHANCED  = 0.55   # EnhancedEntryScorer contributes most weight
_W_OPTIMIZER = 0.25   # EntryOptimizer RSI-div / BB-zone bonus
_W_GATE      = 0.20   # 5-Gate AI gate penalty deduction

# Hard absolute floor — never execute below this regardless of ranking
MIN_SCORE_ABSOLUTE = 22.0

# Default number of top signals to select per cycle
TOP_N_DEFAULT = 3

# Adaptive threshold relaxation: when < this many candidates are above the
# regime threshold, relax down to TIER_FLOOR so we still get some trades.
RELAX_CANDIDATE_COUNT = 2


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AIEngineSignal:
    """A scored, approved entry signal for one symbol / side."""
    symbol: str
    side: str                    # 'long' | 'short'
    composite_score: float       # 0-100
    position_multiplier: float   # 0.5-2.0 (size scaling driven by score)
    entry_type: str              # 'scalp' | 'swing' | 'breakout' | 'mean_reversion'
    threshold_used: float        # Adaptive threshold that approved this signal
    reason: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_elite(self) -> bool:
        return self.composite_score >= TIER_ELITE

    @property
    def is_good(self) -> bool:
        return self.composite_score >= TIER_GOOD


@dataclass
class _Candidate:
    """Internal scored candidate before final selection."""
    symbol: str
    side: str
    composite_score: float
    entry_type: str
    reason: str
    metadata: Dict[str, Any]


# ---------------------------------------------------------------------------
# Cycle speed controller
# ---------------------------------------------------------------------------

class CycleSpeedController:
    """
    Adapts the scan cycle interval based on recent signal density.

    - Hot market  (>= 2 signals last cycle) → FAST interval (90 s)
    - Normal market                          → NORMAL interval (150 s)
    - Cold market (0 signals, 2+ cold cycles in a row) → SLOW interval (300 s)
    """

    INTERVAL_FAST: int = 90     # 1.5 min
    INTERVAL_NORMAL: int = 150  # 2.5 min
    INTERVAL_SLOW: int = 300    # 5.0 min

    def __init__(self) -> None:
        self._last_interval: int = self.INTERVAL_NORMAL
        self._cold_streak: int = 0
        self._lock = threading.Lock()

    def record_cycle(self, signals_found: int) -> int:
        """Record cycle result and return recommended next interval (seconds)."""
        with self._lock:
            if signals_found >= 2:
                self._cold_streak = 0
                self._last_interval = self.INTERVAL_FAST
            elif signals_found == 1:
                self._cold_streak = 0
                self._last_interval = self.INTERVAL_NORMAL
            else:
                self._cold_streak += 1
                if self._cold_streak >= 2:
                    self._last_interval = self.INTERVAL_SLOW
                else:
                    self._last_interval = self.INTERVAL_NORMAL
            return self._last_interval

    @property
    def interval(self) -> int:
        with self._lock:
            return self._last_interval

    def reset(self) -> None:
        with self._lock:
            self._last_interval = self.INTERVAL_NORMAL
            self._cold_streak = 0


# ---------------------------------------------------------------------------
# Main AI Engine
# ---------------------------------------------------------------------------

class NijaAIEngine:
    """
    Unified entry-signal coordinator.

    Plug-and-play: each component is loaded lazily and degrades gracefully
    when unavailable.  The engine always returns a ranked result — it never
    returns an empty list due to threshold over-filtering.
    """

    def __init__(self) -> None:
        self.speed_ctrl = CycleSpeedController()
        self._lock = threading.Lock()

        # Lazy-loaded component references (set on first use)
        self._enhanced_scorer = None
        self._entry_optimizer = None
        self._ai_entry_gate = None
        self._regime_bridge = None

        logger.info("✅ NijaAIEngine initialized (rank-first, adaptive-threshold)")

    # ------------------------------------------------------------------
    # Component lazy-loaders
    # ------------------------------------------------------------------

    def _get_scorer(self):
        if self._enhanced_scorer is None:
            try:
                from enhanced_entry_scoring import EnhancedEntryScorer
                self._enhanced_scorer = EnhancedEntryScorer()
            except ImportError:
                try:
                    from bot.enhanced_entry_scoring import EnhancedEntryScorer
                    self._enhanced_scorer = EnhancedEntryScorer()
                except ImportError:
                    pass
        return self._enhanced_scorer

    def _get_optimizer(self):
        if self._entry_optimizer is None:
            try:
                from entry_optimizer import get_entry_optimizer
                self._entry_optimizer = get_entry_optimizer()
            except ImportError:
                try:
                    from bot.entry_optimizer import get_entry_optimizer
                    self._entry_optimizer = get_entry_optimizer()
                except ImportError:
                    pass
        return self._entry_optimizer

    def _get_gate(self):
        if self._ai_entry_gate is None:
            try:
                from ai_entry_gate import get_ai_entry_gate
                self._ai_entry_gate = get_ai_entry_gate()
            except ImportError:
                try:
                    from bot.ai_entry_gate import get_ai_entry_gate
                    self._ai_entry_gate = get_ai_entry_gate()
                except ImportError:
                    pass
        return self._ai_entry_gate

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate_symbol(
        self,
        df: pd.DataFrame,
        indicators: Dict[str, Any],
        side: str,
        regime: Any = None,
        broker: str = "coinbase",
        entry_type: str = "swing",
        symbol: str = "UNKNOWN",
    ) -> Optional[AIEngineSignal]:
        """
        Score one symbol/side and return an AIEngineSignal if it passes the
        absolute floor.  Returns ``None`` when data is insufficient or the
        score is below ``MIN_SCORE_ABSOLUTE``.

        The caller should collect all ``AIEngineSignal`` results across
        candidates and pass them to ``rank_and_select`` for final selection.
        """
        try:
            composite, breakdown = self._compute_composite(df, indicators, side, regime, broker, entry_type)

            if composite < MIN_SCORE_ABSOLUTE:
                logger.debug(
                    "   🤖 AI Engine %s %s: score=%.1f < floor=%.1f — skipped",
                    symbol, side.upper(), composite, MIN_SCORE_ABSOLUTE,
                )
                return None

            reason = self._build_reason(side, composite, breakdown, regime)
            mult = self._position_multiplier(composite)

            return AIEngineSignal(
                symbol=symbol,
                side=side,
                composite_score=composite,
                position_multiplier=mult,
                entry_type=entry_type,
                threshold_used=MIN_SCORE_ABSOLUTE,
                reason=reason,
                metadata=breakdown,
            )

        except Exception as exc:
            logger.warning("NijaAIEngine.evaluate_symbol error for %s: %s", symbol, exc)
            return None

    def rank_and_select(
        self,
        candidates: List[AIEngineSignal],
        available_slots: int,
        regime: Any = None,
    ) -> List[AIEngineSignal]:
        """
        Rank candidates by composite score and return the best ones that fit
        the available position slots.

        Adaptive threshold:
        - Normally uses ``TIER_FLOOR`` as minimum for selection
        - When fewer than ``RELAX_CANDIDATE_COUNT`` candidates exceed the
          normal threshold, drops the bar to ``MIN_SCORE_ABSOLUTE`` so the
          bot always finds *something* to execute

        Args:
            candidates:      All ``AIEngineSignal`` objects from the scan cycle.
            available_slots: How many new positions can still be opened.
            regime:          Current market regime (for threshold logic).

        Returns:
            Sorted list of approved signals (highest score first), length <=
            ``min(available_slots, TOP_N_DEFAULT)``.
        """
        if not candidates or available_slots <= 0:
            return []

        # Sort descending by composite score
        ranked = sorted(candidates, key=lambda s: s.composite_score, reverse=True)

        # Choose adaptive threshold
        threshold = self._adaptive_threshold(ranked)

        # Assign the resolved threshold and multiplier back to each selected signal
        selected: List[AIEngineSignal] = []
        slots_used = 0
        max_take = min(available_slots, TOP_N_DEFAULT)

        for sig in ranked:
            if slots_used >= max_take:
                break
            if sig.composite_score >= threshold:
                sig.threshold_used = threshold
                sig.position_multiplier = self._position_multiplier(sig.composite_score)
                selected.append(sig)
                slots_used += 1

        logger.info(
            "🤖 AI Engine ranked %d candidates | threshold=%.1f | selected=%d (slots=%d)",
            len(ranked),
            threshold,
            len(selected),
            available_slots,
        )
        for sig in selected:
            logger.info(
                "   ✅ %s %s score=%.1f mult=×%.2f [%s]",
                sig.symbol, sig.side.upper(), sig.composite_score,
                sig.position_multiplier, sig.entry_type,
            )

        # Record for cycle speed adaptation
        self.speed_ctrl.record_cycle(len(selected))

        return selected

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_composite(
        self,
        df: pd.DataFrame,
        indicators: Dict[str, Any],
        side: str,
        regime: Any,
        broker: str,
        entry_type: str,
    ) -> Tuple[float, Dict]:
        """
        Composite score = weighted blend of:
        1. EnhancedEntryScorer  (0-100)           weight _W_ENHANCED  (0.55)
        2. EntryOptimizer delta (0-2)  scaled 0-20 weight _W_OPTIMIZER (0.25)
        3. 5-Gate AI gate penalty      -8 per gate failure (max 3)
                                                   weight _W_GATE      (0.20)

        Always returns a value in [0, 100].
        """
        breakdown: Dict[str, Any] = {}

        # ── Component 1: Enhanced scorer ─────────────────────────────────
        scorer = self._get_scorer()
        if scorer is not None:
            try:
                raw_score, score_breakdown = scorer.calculate_entry_score(df, indicators, side)
                breakdown["enhanced_score"] = raw_score
                breakdown["score_breakdown"] = score_breakdown
            except Exception as exc:
                logger.debug("EnhancedEntryScorer error: %s", exc)
                raw_score = 50.0
                breakdown["enhanced_score"] = raw_score
        else:
            raw_score = 50.0
            breakdown["enhanced_score"] = raw_score

        # ── Component 2: Entry optimizer bonus ───────────────────────────
        optimizer = self._get_optimizer()
        opt_delta = 0.0
        if optimizer is not None:
            try:
                opt_result = optimizer.analyze_entry(df, indicators, side)
                # Scale: max delta ~2.0 → normalize to 0-20 extra points
                opt_delta = min(opt_result.score_delta / 2.0, 1.0) * 20.0
                breakdown["optimizer_delta"] = opt_result.score_delta
                breakdown["optimizer_reason"] = opt_result.reason
            except Exception as exc:
                logger.debug("EntryOptimizer error: %s", exc)

        # ── Component 3: 5-gate AI confirmation ──────────────────────────
        gate_penalty = 0.0
        gate = self._get_gate()
        if gate is not None:
            try:
                gate_result = gate.check(
                    df=df,
                    indicators=indicators,
                    side=side,
                    enhanced_score=float(raw_score),
                    regime=regime,
                    broker=broker,
                    entry_type=entry_type,
                )
                breakdown["gate_passed"] = gate_result.passed
                breakdown["gate_reason"] = gate_result.reason
                if not gate_result.passed:
                    # Count how many gates failed and apply proportional penalty
                    n_failed = sum(
                        1 for g in (gate_result.gates or {}).values()
                        if hasattr(g, "passed") and not g.passed
                    )
                    gate_penalty = min(n_failed, 3) * 8.0
            except Exception as exc:
                logger.debug("AIEntryGate error: %s", exc)

        # ── Weighted composite ────────────────────────────────────────────
        # Penalty: 8 pts per failed gate, capped at 3 gates (max -24 pts before weighting)
        composite = (raw_score * _W_ENHANCED) + (opt_delta * _W_OPTIMIZER) - (gate_penalty * _W_GATE)
        composite = float(np.clip(composite, 0.0, 100.0))
        breakdown["composite_score"] = composite
        breakdown["gate_penalty"] = gate_penalty

        return composite, breakdown

    @staticmethod
    def _adaptive_threshold(ranked: List[AIEngineSignal]) -> float:
        """
        Return the selection threshold for this cycle.

        If fewer than RELAX_CANDIDATE_COUNT candidates score >= TIER_FLOOR,
        relax to MIN_SCORE_ABSOLUTE so we always execute *something*.
        """
        above_floor = sum(1 for s in ranked if s.composite_score >= TIER_FLOOR)
        if above_floor >= RELAX_CANDIDATE_COUNT:
            return TIER_FLOOR
        # Relax — take whatever is above the hard minimum
        return MIN_SCORE_ABSOLUTE

    @staticmethod
    def _position_multiplier(score: float) -> float:
        """Map composite score to position-size multiplier."""
        if score >= TIER_ELITE:
            return 1.5
        if score >= TIER_GOOD:
            return 1.0
        if score >= TIER_FAIR:
            return 0.75
        if score >= TIER_FLOOR:
            return 0.5
        return 0.4

    @staticmethod
    def _build_reason(
        side: str,
        composite: float,
        breakdown: Dict,
        regime: Any,
    ) -> str:
        regime_str = str(regime.value) if hasattr(regime, "value") else str(regime or "")
        gate_ok = breakdown.get("gate_passed", True)
        opt = breakdown.get("optimizer_delta", 0.0)
        return (
            f"{side.upper()} | composite={composite:.1f}/100 | "
            f"enhanced={breakdown.get('enhanced_score', 0):.1f} | "
            f"opt+{opt:.1f} | gate={'✅' if gate_ok else '⚠️'} | "
            f"regime={regime_str}"
        )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_engine: Optional[NijaAIEngine] = None


def get_nija_ai_engine() -> NijaAIEngine:
    """Return (or lazily create) the module-level singleton NijaAIEngine."""
    global _engine
    if _engine is None:
        _engine = NijaAIEngine()
    return _engine
