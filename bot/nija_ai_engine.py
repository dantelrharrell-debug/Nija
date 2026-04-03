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
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("nija.ai_engine")

# ---------------------------------------------------------------------------
# Score Distribution Debugger — optional dependency
# ---------------------------------------------------------------------------
_SDD_AVAILABLE = False
_get_sdd = None  # type: ignore
try:
    from score_distribution_debugger import get_score_debugger as _get_sdd  # type: ignore
    _SDD_AVAILABLE = True
except ImportError:
    try:
        from bot.score_distribution_debugger import get_score_debugger as _get_sdd  # type: ignore
        _SDD_AVAILABLE = True
    except ImportError:
        pass

# ---------------------------------------------------------------------------
# Win-Rate Score Shaper — optional dependency
# ---------------------------------------------------------------------------
_WRSS_AVAILABLE = False
_get_wrss = None  # type: ignore
try:
    from win_rate_score_shaper import get_win_rate_score_shaper as _get_wrss  # type: ignore
    _WRSS_AVAILABLE = True
except ImportError:
    try:
        from bot.win_rate_score_shaper import get_win_rate_score_shaper as _get_wrss  # type: ignore
        _WRSS_AVAILABLE = True
    except ImportError:
        pass

# ---------------------------------------------------------------------------
# Score tier constants
# ---------------------------------------------------------------------------
TIER_ELITE = 75.0    # 1.5× position size
TIER_GOOD = 34.0     # 1.0× position size (lowered 40→34 ~15% to increase qualifying entries)
TIER_FAIR = 25.0     # 0.75× position size (lowered 30→25 ~17% to allow B-grade setups)
TIER_FLOOR = 17.0    # 0.5× position size (taken only as top-N, no better option)

# Composite score blend weights (must sum to 1.0)
_W_ENHANCED  = 0.55   # EnhancedEntryScorer contributes most weight
_W_OPTIMIZER = 0.25   # EntryOptimizer RSI-div / BB-zone bonus
_W_GATE      = 0.20   # 5-Gate AI gate penalty deduction

# Hard absolute floor — never execute below this regardless of ranking.
# NOTE: the composite formula (raw_score * 0.55 + opt_delta * 0.25 - penalty * 0.20)
# produces values in the 0-60 range, so this floor must be calibrated accordingly.
# Lowered from 25.0 → 20.0 (~20%) to increase trade frequency (Apr 2026).
MIN_SCORE_ABSOLUTE = 20.0

# Default number of top signals to select per cycle
TOP_N_DEFAULT = 3

# Adaptive threshold relaxation: when < this many candidates are above the
# regime threshold, relax down to TIER_FLOOR so we still get some trades.
RELAX_CANDIDATE_COUNT = 1


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
    Adapts the scan cycle interval based on recent signal density and market regime.

    - Hot market  (>= 2 signals last cycle) → FAST interval (90 s)
    - Normal market                          → NORMAL interval (150 s)
    - Cold market (0 signals, 2+ cold cycles in a row) → SLOW interval (300 s)

    A regime hint (set via ``set_regime_hint``) acts as a soft constraint:
    - In defensive/crisis regimes (hint ≥ 240 s): interval is floored at hint
      so the bot never scans faster than the regime recommends.
    - In trending/scalp regimes (hint ≤ 120 s): interval is capped at hint
      so the bot always scans at least as fast as the regime requires.
    - Otherwise the signal-density logic runs freely within [hint×0.8, hint×1.5].
    """

    INTERVAL_FAST: int = 90     # 1.5 min
    INTERVAL_NORMAL: int = 150  # 2.5 min
    INTERVAL_SLOW: int = 300    # 5.0 min

    def __init__(self) -> None:
        self._last_interval: int = self.INTERVAL_NORMAL
        self._cold_streak: int = 0
        self._regime_hint: int = self.INTERVAL_NORMAL
        self._lock = threading.Lock()

    def set_regime_hint(self, secs: int) -> None:
        """
        Provide the market-regime recommended scan interval.

        Called whenever the regime changes (e.g. after ``regime_bridge.get_params``).
        The hint biases the signal-density logic without fully overriding it.

        Args:
            secs: Recommended interval in seconds from ``RegimeTradingParams.scan_interval_secs``.
        """
        with self._lock:
            self._regime_hint = max(self.INTERVAL_FAST, int(secs))

    def record_cycle(self, signals_found: int) -> int:
        """Record cycle result and return recommended next interval (seconds)."""
        with self._lock:
            if signals_found >= 2:
                self._cold_streak = 0
                signal_interval = self.INTERVAL_FAST
            elif signals_found == 1:
                self._cold_streak = 0
                signal_interval = self.INTERVAL_NORMAL
            else:
                self._cold_streak += 1
                if self._cold_streak >= 2:
                    signal_interval = self.INTERVAL_SLOW
                else:
                    signal_interval = self.INTERVAL_NORMAL

            # Apply regime hint as a directional constraint:
            # - Crisis/defensive (hint ≥ 240s): never scan faster than the regime allows
            # - Trending/scalp   (hint ≤ 120s): always scan at least as fast as regime needs
            hint = self._regime_hint
            if hint >= 240:
                # Defensive regime — floor the interval at the regime hint
                self._last_interval = max(signal_interval, hint)
            elif hint <= 120:
                # Fast regime — cap the interval at the regime hint
                self._last_interval = min(signal_interval, hint)
            else:
                # Neutral — blend: signal logic governs but bias toward hint
                self._last_interval = signal_interval

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
# Adaptive threshold controller
# ---------------------------------------------------------------------------

class AdaptiveThresholdController:
    """
    Real-time self-adjusting AI score threshold.

    Tracks closed-trade outcomes in a rolling window and nudges
    MIN_SCORE_ABSOLUTE up or down to keep the win rate inside a
    55–65 % target band.

    * Win rate < 55 %  → raise bar (+0.5 pts/cycle, max +8 pts)
    * Win rate > 65 %  → lower bar (−0.5 pts/cycle, max −8 pts)
    * Win rate in band → hold current adjustment

    Usage
    -----
    After each trade closes call ``record_outcome(won=True/False)``.
    ``NijaAIEngine.evaluate_symbol`` automatically reads
    ``get_effective_floor(MIN_SCORE_ABSOLUTE)`` on every call.
    """

    _TARGET_FLOOR:  float = 0.55   # raise threshold below this win rate
    _TARGET_CEIL:   float = 0.65   # lower threshold above this win rate
    _WINDOW:        int   = 20     # rolling outcome window
    _STEP:          float = 0.5    # composite-score pts nudged per recompute
    _MAX_ADJ:       float = 8.0    # maximum |composite adjustment| in pts
    _MIN_SAMPLES:   int   = 5      # outcomes needed before any adjustment

    # Gate-domain adjustment — operates in the same units as
    # BASE_ENTRY_SCORE_THRESHOLD (0-9 scale) so ±3.0 stays meaningful.
    _GATE_STEP:     float = 0.25   # gate pts nudged per recompute
    _GATE_MAX_ADJ:  float = 3.0    # maximum |gate adjustment| in pts

    def __init__(self) -> None:
        self._outcomes: Deque[float] = deque(maxlen=self._WINDOW)
        self._adjustment: float = 0.0
        self._gate_adjustment: float = 0.0   # gate-domain tracker (±3.0 max)
        self._lock = threading.Lock()

    # ── Public interface ────────────────────────────────────────────────

    def record_outcome(self, won: bool) -> None:
        """Call after each trade closes (True = profitable, False = loss)."""
        with self._lock:
            self._outcomes.append(1.0 if won else 0.0)
            self._recompute()

    def get_effective_floor(self, base_floor: float) -> float:
        """Return base_floor adjusted by the current auto-tune delta."""
        with self._lock:
            return max(5.0, base_floor + self._adjustment)

    def get_threshold(self, base_threshold: float) -> float:
        """Return ``base_threshold`` nudged by the gate-domain win-rate adjustment.

        Operates in the same units as ``base_threshold`` (e.g. the 0-9 gate
        scoring scale) so step=0.25 and the ±3.0 clamp stay meaningful.
        The returned value is floored at 2.0 so at least two gate conditions
        must always be met regardless of adjustment direction.

        Example::

            adaptive = atc.get_threshold(BASE_ENTRY_SCORE_THRESHOLD)
            passed   = total_score >= adaptive
        """
        with self._lock:
            return max(2.0, base_threshold + self._gate_adjustment)

    @property
    def total_trades(self) -> int:
        """Number of closed-trade outcomes recorded in the rolling window."""
        with self._lock:
            return len(self._outcomes)

    @property
    def threshold_delta(self) -> float:
        """Current adjustment delta (positive = tighter, negative = looser)."""
        with self._lock:
            return self._adjustment

    def win_rate(self) -> float:
        """Current rolling win rate (0.0–1.0). Returns neutral 0.60 before data."""
        with self._lock:
            if len(self._outcomes) < self._MIN_SAMPLES:
                return 0.60
            return sum(self._outcomes) / len(self._outcomes)

    def status(self) -> str:
        wr = self.win_rate()
        with self._lock:
            n = len(self._outcomes)
        return (
            f"win_rate={wr:.1%}  adj={self._adjustment:+.1f}pts  "
            f"window={n}/{self._WINDOW}"
        )

    # ── Internal ────────────────────────────────────────────────────────

    def _recompute(self) -> None:
        """Nudge the adjustment based on the latest window. Must hold _lock."""
        if len(self._outcomes) < self._MIN_SAMPLES:
            return
        wr = sum(self._outcomes) / len(self._outcomes)
        if wr < self._TARGET_FLOOR:
            self._adjustment = min(self._MAX_ADJ, self._adjustment + self._STEP)
            self._gate_adjustment = min(self._GATE_MAX_ADJ, self._gate_adjustment + self._GATE_STEP)
        elif wr > self._TARGET_CEIL:
            self._adjustment = max(-self._MAX_ADJ, self._adjustment - self._STEP)
            self._gate_adjustment = max(-self._GATE_MAX_ADJ, self._gate_adjustment - self._GATE_STEP)
        # else: in-band → no change


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
        self.threshold_ctrl = AdaptiveThresholdController()
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

            # Feed every composite score (pass or fail) into the distribution debugger
            # so the per-cycle histogram includes the full picture.
            if _SDD_AVAILABLE and _get_sdd is not None:
                try:
                    _sdd = _get_sdd()
                    if _sdd is not None:
                        _sdd.record_score(symbol, composite)
                except Exception:
                    pass

            # Apply self-adjusting threshold: win-rate feedback nudges the floor
            # ±8 pts in real-time to keep win rate in the 55–65% target band.
            effective_floor = self.threshold_ctrl.get_effective_floor(MIN_SCORE_ABSOLUTE)

            if composite < effective_floor:
                logger.debug(
                    "   🤖 AI Engine %s %s: score=%.1f < floor=%.1f (adj%+.1f) — skipped",
                    symbol, side.upper(), composite, effective_floor,
                    self.threshold_ctrl.threshold_delta,
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
                threshold_used=effective_floor,
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
            "🤖 AI Engine ranked %d candidates | threshold=%.1f (adj%+.1f wr=%.0f%%) | selected=%d (slots=%d)",
            len(ranked),
            threshold,
            self.threshold_ctrl.threshold_delta,
            self.threshold_ctrl.win_rate() * 100,
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

        # ── Win-rate score shaping by regime ─────────────────────────────
        # Apply a multiplicative factor derived from the bot's historical
        # win-rate in this specific regime.  Regimes where the bot wins
        # consistently get a score boost; regimes where it struggles get a
        # dampen.  Factor stays at 1.0 when history is insufficient.
        wrss_factor = 1.0
        if _WRSS_AVAILABLE and _get_wrss is not None:
            try:
                _wrss = _get_wrss()
                if _wrss is not None:
                    wrss_factor = _wrss.get_score_multiplier(regime)
                    if wrss_factor != 1.0:
                        composite = float(np.clip(composite * wrss_factor, 0.0, 100.0))
            except Exception:
                pass
        breakdown["wrss_factor"] = wrss_factor
        breakdown["composite_score"] = composite
        breakdown["gate_penalty"] = gate_penalty

        return composite, breakdown

    def _adaptive_threshold(self, ranked: List[AIEngineSignal]) -> float:
        """
        Return the selection threshold for this cycle.

        Applies the AdaptiveThresholdController delta so the threshold
        automatically rises/falls to maintain 55–65% win rate.

        If fewer than RELAX_CANDIDATE_COUNT candidates score >= TIER_FLOOR
        (after delta), relax to MIN_SCORE_ABSOLUTE so we always execute
        *something*.
        """
        base_threshold = TIER_FLOOR
        delta = self.threshold_ctrl.threshold_delta
        adjusted_floor = max(5.0, base_threshold + delta)
        above_floor = sum(1 for s in ranked if s.composite_score >= adjusted_floor)
        if above_floor >= RELAX_CANDIDATE_COUNT:
            adaptive_threshold = adjusted_floor
        else:
            # Relax — take whatever is above the hard minimum (also delta-adjusted)
            adaptive_threshold = max(5.0, MIN_SCORE_ABSOLUTE + delta)

        logger.info(
            f"🎯 Adaptive Threshold → base={base_threshold:.2f} "
            f"adj={delta:+.2f} "
            f"final={adaptive_threshold:.2f} "
            f"wr={self.threshold_ctrl.win_rate():.1%} "
            f"trades={self.threshold_ctrl.total_trades}"
        )
        return adaptive_threshold

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


def record_trade_outcome(won: bool) -> None:
    """
    Convenience function: record a closed trade result into the singleton
    AI engine's AdaptiveThresholdController.

    Call this after every trade closes so the self-adjusting threshold
    can maintain the 55–65 % win-rate target band in real-time.

    Example usage in trading_strategy.py or broker_integration.py::

        from nija_ai_engine import record_trade_outcome
        record_trade_outcome(pnl_usd > 0)
    """
    get_nija_ai_engine().threshold_ctrl.record_outcome(won)
