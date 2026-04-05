"""
NIJA Profit Optimizer
=====================

Three-layer profit maximization system:

1. **ConfidencePositionSizer**
   Scales every position 0.5×–2.0× based on the signal confidence score so
   high-conviction setups automatically receive more capital while weak setups
   are reduced.

2. **TradeRankingEngine**
   Maintains a rolling window of recent setup scores and gates entry on whether
   the current setup is in the top percentile.  Only the best setups get
   submitted — the rest are skipped without touching capital.

3. **ProfitAccelerationModel**
   Tier-based reinvestment model.  As the account grows it automatically
   reinvests a larger slice of each win back into position sizing, compounding
   small balances toward a user-defined target (default $1 000).

Usage
-----
::

    from bot.profit_optimizer import get_profit_optimizer

    opt = get_profit_optimizer(target_balance=1000.0)

    # ── 1. Scale position size by confidence ─────────────────────────────────
    position_size = opt.sizer.scale(base_size=50.0, confidence=0.78)

    # ── 2. Gate on ranking (returns True → submit, False → skip) ─────────────
    if opt.ranker.should_enter(score=analysis['score'], symbol="BTC-USD"):
        # ── 3. Apply acceleration multiplier ─────────────────────────────────
        position_size *= opt.accelerator.get_multiplier(current_balance=74.0)
        # ... place trade ...
        opt.accelerator.record_trade(pnl_usd=3.50, current_balance=77.50)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional, Tuple

logger = logging.getLogger("nija.profit_optimizer")

# ---------------------------------------------------------------------------
# Profit Mode Controller — optional dependency
# ---------------------------------------------------------------------------
_PMC_AVAILABLE = False
_get_pmc = None  # type: ignore
try:
    from profit_mode_controller import get_profit_mode_controller as _get_pmc  # type: ignore
    _PMC_AVAILABLE = True
except ImportError:
    try:
        from bot.profit_mode_controller import get_profit_mode_controller as _get_pmc  # type: ignore
        _PMC_AVAILABLE = True
    except ImportError:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# 1. Confidence-based position sizer
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SizerConfig:
    """Tunable parameters for :class:`ConfidencePositionSizer`."""
    min_multiplier: float = 0.5     # Applied when confidence <= low_threshold
    max_multiplier: float = 2.0     # Applied when confidence >= high_threshold
    low_threshold: float  = 0.40    # Below this confidence → minimum size
    high_threshold: float = 0.80    # Above this confidence → maximum size


class ConfidencePositionSizer:
    """
    Linear interpolation between ``min_multiplier`` and ``max_multiplier``
    over the confidence range [``low_threshold``, ``high_threshold``].

    Outside that range the multiplier is clamped to the nearest bound.
    """

    def __init__(self, config: Optional[SizerConfig] = None) -> None:
        self.config = config or SizerConfig()

    def get_multiplier(self, confidence: float) -> float:
        """Return a size multiplier in [min_multiplier, max_multiplier]."""
        cfg = self.config
        if confidence <= cfg.low_threshold:
            return cfg.min_multiplier
        if confidence >= cfg.high_threshold:
            return cfg.max_multiplier
        # Linear interpolation
        ratio = (confidence - cfg.low_threshold) / (cfg.high_threshold - cfg.low_threshold)
        return cfg.min_multiplier + ratio * (cfg.max_multiplier - cfg.min_multiplier)

    def scale(self, base_size: float, confidence: float) -> float:
        """Return *base_size* scaled by the confidence-derived multiplier."""
        mult = self.get_multiplier(confidence)
        scaled = base_size * mult
        logger.debug(
            f"[ConfidencePositionSizer] conf={confidence:.3f} → "
            f"×{mult:.2f}  ${base_size:.2f}→${scaled:.2f}"
        )
        return scaled


# ─────────────────────────────────────────────────────────────────────────────
# 2. Trade ranking engine
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RankerConfig:
    """Tunable parameters for :class:`TradeRankingEngine`."""
    window_size: int      = 50    # Rolling window of recent setup scores
    pass_percentile: float = 0.45  # Top 55% of setups pass (loosened 0.65→0.55→0.45 for max frequency)
    min_window_fill: int  = 5     # Entries required before ranking is enforced


class TradeRankingEngine:
    """
    Maintains a rolling window of recent opportunity scores and blocks entry
    on any setup that does not rank in the configured top percentile.

    ``pass_percentile=0.55`` means a setup's score must be at or above the
    55th percentile of the rolling window to pass — i.e. the top 45%
    of setups are accepted (loosened from 0.65 / top 35% to increase trade frequency).

    Before the window contains enough samples (``min_window_fill``) every
    setup is allowed through so the bot can start trading immediately.
    """

    def __init__(self, config: Optional[RankerConfig] = None) -> None:
        self.config = config or RankerConfig()
        self._scores: Deque[float] = deque(maxlen=self.config.window_size)
        self._lock = threading.Lock()

    def should_enter(self, score: float, symbol: str = "") -> bool:
        """
        Push *score* into the rolling window and decide whether this setup
        passes the ranking gate.

        Returns ``True`` (enter) or ``False`` (skip).
        """
        with self._lock:
            self._scores.append(score)
            n = len(self._scores)

            if n < self.config.min_window_fill:
                logger.debug(
                    f"[TradeRanker] {symbol} window not full ({n}/{self.config.min_window_fill})"
                    f" — allowing through"
                )
                return True

            # Resolve pass_percentile from profit mode if available, falling
            # back to the configured default.  This allows runtime level changes
            # (e.g. switching from Level 1 → Level 2) to widen the gate without
            # restarting the process.
            if _PMC_AVAILABLE and _get_pmc is not None:
                try:
                    effective_percentile = _get_pmc().params.pass_percentile
                except Exception as _exc:
                    logger.debug("TradeRanker: profit mode pass_percentile read failed — using config default: %s", _exc)
                    effective_percentile = self.config.pass_percentile
            else:
                effective_percentile = self.config.pass_percentile

            # Threshold: the score value at pass_percentile of the window.
            # Only setups scoring >= this value are accepted.
            sorted_scores = sorted(self._scores)
            idx = int(len(sorted_scores) * effective_percentile)
            threshold = sorted_scores[min(idx, len(sorted_scores) - 1)]

            passed = score >= threshold
            logger.debug(
                f"[TradeRanker] {symbol} score={score:.3f} threshold={threshold:.3f} "
                f"pct={effective_percentile:.2f} "
                f"({'✅ PASS' if passed else '❌ SKIP'})"
            )
            return passed

    def get_percentile(self, score: float) -> float:
        """Return the percentile rank (0–1) of *score* in the current window."""
        with self._lock:
            if not self._scores:
                return 1.0
            below = sum(1 for s in self._scores if s < score)
            return below / len(self._scores)

    @property
    def window_size(self) -> int:
        """Current number of scores in the rolling window."""
        with self._lock:
            return len(self._scores)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Profit acceleration model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AccelerationTier:
    """One reinvestment tier of :class:`ProfitAccelerationModel`."""
    min_balance: float          # Lower bound for this tier (USD)
    reinvest_rate: float        # Fraction of each win reinvested (0–1)
    size_multiplier: float      # Position-size boost multiplier
    label: str                  # Human-readable name


# Tier ladder — from smallest to largest balance.
#
# Auto-scaling path: multipliers grow as balance increases so profits compound
# faster at every tier boundary.  Compared to the original design these
# multipliers are more aggressive to match "balanced aggression" mode:
#
#   micro      $0–$100   — 1.05× (slight edge even at the start)
#   seed       $100–$250 — 1.20×
#   sprout     $250–$500 — 1.40×
#   grow       $500–$750 — 1.60×
#   build      $750–$1K  — 1.80×
#   scale      $1K–$2.5K — 2.10×
#   compound   $2.5K+    — 2.50× (full compounding mode)
_DEFAULT_TIERS: Tuple[AccelerationTier, ...] = (
    AccelerationTier(min_balance=0,      reinvest_rate=0.65, size_multiplier=1.05, label="micro"),
    AccelerationTier(min_balance=100,    reinvest_rate=0.70, size_multiplier=1.20, label="seed"),
    AccelerationTier(min_balance=250,    reinvest_rate=0.75, size_multiplier=1.40, label="sprout"),
    AccelerationTier(min_balance=500,    reinvest_rate=0.78, size_multiplier=1.60, label="grow"),
    AccelerationTier(min_balance=750,    reinvest_rate=0.80, size_multiplier=1.80, label="build"),
    AccelerationTier(min_balance=1_000,  reinvest_rate=0.85, size_multiplier=2.10, label="scale"),
    AccelerationTier(min_balance=2_500,  reinvest_rate=0.88, size_multiplier=2.50, label="compound"),
)


@dataclass
class AccelerationState:
    """Live state tracked by :class:`ProfitAccelerationModel`."""
    total_trades: int = 0
    total_wins: int   = 0
    total_pnl: float  = 0.0
    peak_balance: float = 0.0
    current_tier: str = "micro"


class ProfitAccelerationModel:
    """
    Tier-based compounding model that automatically reinvests a growing slice
    of profits as the account balance rises toward ``target_balance``.

    At each tier:
    - A larger fraction of winning P&L is rolled back into position sizing.
    - The position-size multiplier increases so the bot captures more per trade.

    Once ``target_balance`` is reached the model holds at the highest tier and
    simply tracks performance.

    Example path: $74 → micro tier → $100 → seed → $250 → sprout → $500 → grow → $750 → build → $1 000 → scale.
    At ~$300 balance the $25/day net profit target becomes achievable with 15+ trades at 65%+ win rate.
    """

    def __init__(
        self,
        target_balance: float = 1_000.0,
        tiers: Optional[Tuple[AccelerationTier, ...]] = None,
    ) -> None:
        self.target_balance = target_balance
        self.tiers = tiers or _DEFAULT_TIERS
        self._state = AccelerationState()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get_tier(self, current_balance: float) -> AccelerationTier:
        """Return the :class:`AccelerationTier` for *current_balance*."""
        active = self.tiers[0]
        for tier in self.tiers:
            if current_balance >= tier.min_balance:
                active = tier
        return active

    def get_multiplier(self, current_balance: float) -> float:
        """
        Return the position-size multiplier for *current_balance*.

        Scales linearly toward the *next* tier's multiplier so there is no
        sudden step-change at tier boundaries.
        """
        tier = self.get_tier(current_balance)
        # Find the next tier (if any) for smooth interpolation
        next_tier: Optional[AccelerationTier] = None
        for t in self.tiers:
            if t.min_balance > tier.min_balance:
                next_tier = t
                break

        if next_tier is None or next_tier.min_balance <= tier.min_balance:
            return tier.size_multiplier

        # Fraction of the way through the current tier range
        span = next_tier.min_balance - tier.min_balance
        progress = max(0.0, min(1.0, (current_balance - tier.min_balance) / span))
        mult = tier.size_multiplier + progress * (next_tier.size_multiplier - tier.size_multiplier)
        return mult

    def record_trade(self, pnl_usd: float, current_balance: float) -> None:
        """
        Record a closed trade result and update internal state.

        Args:
            pnl_usd:         Realised P&L in USD (positive = win, negative = loss).
            current_balance: Account balance **after** the trade settled.
        """
        with self._lock:
            self._state.total_trades += 1
            self._state.total_pnl += pnl_usd
            if pnl_usd > 0:
                self._state.total_wins += 1
            if current_balance > self._state.peak_balance:
                self._state.peak_balance = current_balance
            tier = self.get_tier(current_balance)
            self._state.current_tier = tier.label

        progress_pct = min(100.0, current_balance / self.target_balance * 100)
        logger.info(
            f"[ProfitAccel] tier={tier.label} "
            f"balance=${current_balance:.2f} "
            f"target=${self.target_balance:.2f} "
            f"progress={progress_pct:.1f}% "
            f"pnl={pnl_usd:+.2f} "
            f"mult={self.get_multiplier(current_balance):.2f}×"
        )

    def get_report(self) -> dict:
        """Return a snapshot of current acceleration state."""
        with self._lock:
            s = self._state
            return {
                "total_trades":  s.total_trades,
                "total_wins":    s.total_wins,
                "win_rate":      s.total_wins / s.total_trades if s.total_trades else 0.0,
                "total_pnl":     round(s.total_pnl, 4),
                "peak_balance":  round(s.peak_balance, 4),
                "current_tier":  s.current_tier,
                "target_balance": self.target_balance,
            }


# ─────────────────────────────────────────────────────────────────────────────
# 4. Win-streak accelerator
# ─────────────────────────────────────────────────────────────────────────────

class WinStreakAccelerator:
    """
    Boosts position size when the bot is on a consecutive-win streak.

    Streak tiers (consecutive wins → size multiplier):
        0–2   → 1.00×  (neutral — no adjustment)
        3–4   → 1.20×  (+20% — first momentum confirmation)
        5–7   → 1.40×  (+40% — sustained momentum)
        8+    → 1.60×  (+60% — hot streak; hard-capped for safety)

    Any losing trade immediately resets the streak to 0 so the multiplier
    drops back to 1.00× instantly, preventing runaway sizing after market
    reversal.
    """

    # (min_consecutive_wins, size_multiplier)
    _TIERS: Tuple[Tuple[int, float], ...] = (
        (0, 1.00),
        (3, 1.20),
        (5, 1.40),
        (8, 1.60),
    )
    _MAX_MULTIPLIER: float = 2.00  # Absolute safety cap

    def __init__(self) -> None:
        self._streak: int = 0
        self._lock = threading.Lock()

    @property
    def streak(self) -> int:
        """Current consecutive win count (read-only)."""
        with self._lock:
            return self._streak

    def record_win(self) -> None:
        """Increment the win streak by one."""
        with self._lock:
            self._streak += 1
            logger.info(
                "[WinStreakAccel] win streak=%d → size boost ×%.2f",
                self._streak,
                self._get_multiplier_locked(),
            )

    def record_loss(self) -> None:
        """Reset the win streak to zero on any loss."""
        with self._lock:
            if self._streak > 0:
                logger.info("[WinStreakAccel] streak reset %d → 0 (loss)", self._streak)
            self._streak = 0

    def get_multiplier(self) -> float:
        """Return the current size multiplier (1.00× baseline)."""
        with self._lock:
            return self._get_multiplier_locked()

    def _get_multiplier_locked(self) -> float:
        """Compute multiplier — must be called with self._lock held."""
        mult = 1.00
        for min_wins, m in self._TIERS:
            if self._streak >= min_wins:
                mult = m
        return min(mult, self._MAX_MULTIPLIER)

    def get_report(self) -> dict:
        """Return a snapshot of current streak state."""
        with self._lock:
            return {
                "win_streak": self._streak,
                "size_multiplier": round(self._get_multiplier_locked(), 2),
            }


# ─────────────────────────────────────────────────────────────────────────────
# Composite facade
# ─────────────────────────────────────────────────────────────────────────────

class ProfitOptimizer:
    """
    Thin facade that groups all four profit optimization components so callers
    need only one import.

    Attributes:
        sizer:              :class:`ConfidencePositionSizer`
        ranker:             :class:`TradeRankingEngine`
        accelerator:        :class:`ProfitAccelerationModel`
        streak_accelerator: :class:`WinStreakAccelerator`
    """

    def __init__(
        self,
        target_balance: float = 1_000.0,
        sizer_config: Optional[SizerConfig] = None,
        ranker_config: Optional[RankerConfig] = None,
    ) -> None:
        self.sizer              = ConfidencePositionSizer(config=sizer_config)
        self.ranker             = TradeRankingEngine(config=ranker_config)
        self.accelerator        = ProfitAccelerationModel(target_balance=target_balance)
        self.streak_accelerator = WinStreakAccelerator()
        logger.info(
            f"[ProfitOptimizer] initialised — "
            f"target=${target_balance:.0f} "
            f"sizer=[{self.sizer.config.min_multiplier}×–{self.sizer.config.max_multiplier}×] "
            f"ranker=[top {int((1 - self.ranker.config.pass_percentile)*100)}%] "
            f"win-streak-accel=enabled"
        )

    def apply(
        self,
        base_size: float,
        confidence: float,
        score: float,
        current_balance: float,
        symbol: str = "",
    ) -> Tuple[float, bool]:
        """
        Single convenience call that runs all four layers.

        Returns:
            (adjusted_size, should_enter) — if ``should_enter`` is ``False``
            the caller should skip the trade entirely.
        """
        # Gate 1: ranking
        if not self.ranker.should_enter(score=score, symbol=symbol):
            return base_size, False

        # Layer 2: confidence scaling
        sized = self.sizer.scale(base_size=base_size, confidence=confidence)

        # Layer 3: balance-based acceleration multiplier
        accel_mult = self.accelerator.get_multiplier(current_balance)
        sized = sized * accel_mult

        # Layer 4: win-streak boost
        streak_mult = self.streak_accelerator.get_multiplier()
        final_size = sized * streak_mult

        # Safety cap: combined multiplier (conf × accel × streak) must not
        # exceed 3.0× base_size to prevent extreme position concentration.
        _MAX_COMBINED = 3.0
        if base_size > 0:
            combined_mult = final_size / base_size
            if combined_mult > _MAX_COMBINED:
                final_size = base_size * _MAX_COMBINED
                logger.debug(
                    f"[ProfitOptimizer] {symbol} combined mult {combined_mult:.2f}× "
                    f"capped at {_MAX_COMBINED}×"
                )

        logger.debug(
            f"[ProfitOptimizer] {symbol} "
            f"base=${base_size:.2f} "
            f"→ conf×{self.sizer.get_multiplier(confidence):.2f} "
            f"→ accel×{accel_mult:.2f} "
            f"→ streak×{streak_mult:.2f} "
            f"→ final=${final_size:.2f}"
        )
        return final_size, True

    def record_win_loss(self, is_win: bool) -> None:
        """
        Record a trade outcome in the win-streak accelerator.

        Call this once per closed trade so the streak multiplier stays current.
        """
        if is_win:
            self.streak_accelerator.record_win()
        else:
            self.streak_accelerator.record_loss()


# ─────────────────────────────────────────────────────────────────────────────
# Singleton factory
# ─────────────────────────────────────────────────────────────────────────────

_optimizer_instance: Optional[ProfitOptimizer] = None
_optimizer_lock = threading.Lock()


def get_profit_optimizer(
    target_balance: float = 1_000.0,
    sizer_config: Optional[SizerConfig] = None,
    ranker_config: Optional[RankerConfig] = None,
) -> ProfitOptimizer:
    """
    Return the process-wide singleton :class:`ProfitOptimizer`.

    On the first call the instance is created with the supplied parameters.
    Subsequent calls return the same object regardless of parameters.
    """
    global _optimizer_instance
    if _optimizer_instance is None:
        with _optimizer_lock:
            if _optimizer_instance is None:
                _optimizer_instance = ProfitOptimizer(
                    target_balance=target_balance,
                    sizer_config=sizer_config,
                    ranker_config=ranker_config,
                )
    return _optimizer_instance
