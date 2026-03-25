"""
NIJA Kraken Parameters Optimizer
==================================

Kraken-specific parameter optimization that leverages Kraken's significantly
lower fee structure (~3x cheaper than Coinbase) to enable:

1. **Lower profit targets** — 0.8% / 1.4% / 2.0% vs Coinbase's 2% / 3.5% / 5%
2. **Tighter stop losses** — -0.7% to -1.0% vs -1.5% (better R:R ratio)
3. **Higher trade frequency** — fees don't eat into small gains
4. **Smaller positions still profitable** — $10+ viable vs higher Coinbase minimums
5. **Regime-aware adjustments** — BULL loosens targets, CRASH tightens them

Fee structure comparison (standard tier):
  ╔══════════════╦═════════════╦═════════════╦══════════════════╗
  ║ Exchange     ║ Taker fee   ║ Maker fee   ║ Round-trip (mkt) ║
  ╠══════════════╬═════════════╬═════════════╬══════════════════╣
  ║ Kraken       ║ 0.26%       ║ 0.16%       ║ ~0.62%           ║
  ║ Coinbase     ║ 0.60%       ║ 0.40%       ║ ~1.40%           ║
  ╚══════════════╩═════════════╩═════════════╩══════════════════╝

With 0.62% round-trip costs, break-even is ~0.62%.  Adding a 0.20% buffer
sets the minimum profitable target at **~0.82%** — allowing profit targets
that are impossible to achieve profitably on Coinbase.

Adaptive learning
-----------------
After each Kraken trade the optimizer:
  - Records win/loss and P&L
  - Adjusts the target multiplier (widens when winning, tightens when losing)
  - Adjusts the stop-loss multiplier (tighter when losing frequently)

This ensures the optimizer reacts to live market conditions rather than
relying solely on static fee arithmetic.

Singleton usage::

    from bot.kraken_params_optimizer import get_kraken_params_optimizer

    optimizer = get_kraken_params_optimizer()
    optimizer.update_regime("bull", confidence=0.8)
    params = optimizer.get_params()
    # → params.profit_targets, params.stop_loss, params.min_profit_threshold, …

    # After a trade completes:
    optimizer.record_trade(pnl_usd=1.50, is_win=True)

Author: NIJA Trading Systems
Version: 1.0 — Kraken Fee-Optimised Edition
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.kraken_params_optimizer")

# ---------------------------------------------------------------------------
# Kraken fee constants (current standard/starter tier, March 2026)
# ---------------------------------------------------------------------------

#: Taker fee (market orders) — 0.26 %
KRAKEN_TAKER_FEE: float = 0.0026
#: Maker fee (limit orders that rest in the book) — 0.16 %
KRAKEN_MAKER_FEE: float = 0.0016
#: Typical bid-ask spread on major pairs — ~0.10 %
KRAKEN_TYPICAL_SPREAD: float = 0.0010

#: Total round-trip cost using market (taker) orders — 0.62 %
KRAKEN_ROUND_TRIP_TAKER: float = (KRAKEN_TAKER_FEE * 2) + KRAKEN_TYPICAL_SPREAD
#: Total round-trip cost using limit (maker) orders — 0.42 %
KRAKEN_ROUND_TRIP_MAKER: float = (KRAKEN_MAKER_FEE * 2) + KRAKEN_TYPICAL_SPREAD

#: Safety buffer added above break-even — 0.20 %
KRAKEN_PROFIT_BUFFER: float = 0.0020

#: Minimum gross profit for a taker-order trade to be net-positive — 0.82 %
KRAKEN_MIN_PROFIT_THRESHOLD_TAKER: float = KRAKEN_ROUND_TRIP_TAKER + KRAKEN_PROFIT_BUFFER
#: Minimum gross profit for a maker-order trade to be net-positive — 0.62 %
KRAKEN_MIN_PROFIT_THRESHOLD_MAKER: float = KRAKEN_ROUND_TRIP_MAKER + KRAKEN_PROFIT_BUFFER

# ---------------------------------------------------------------------------
# Default profit targets (gross %, with descriptive labels)
# These are calibrated for Kraken's 0.62 % taker round-trip cost.
# Compare to PROFIT_TARGETS_KRAKEN in trading_strategy.py (2 / 3 / 4 %)
# which were conservatively set for Coinbase-like fee assumptions.
# ---------------------------------------------------------------------------

#: Three-tier profit target ladder for Kraken (lowest-to-exit-first ordering)
KRAKEN_DEFAULT_PROFIT_TARGETS: List[Tuple[float, str]] = [
    (0.020, "Kraken TP3 +2.0% (Net +1.38% after 0.62% fees) — MAJOR PROFIT"),
    (0.014, "Kraken TP2 +1.4% (Net +0.78% after fees) — GOOD"),
    (0.008, "Kraken TP1 +0.8% (Net +0.18% after fees) — MINIMAL"),
]

# ---------------------------------------------------------------------------
# Regime multipliers
# factor > 1.0 → widen targets (let winners run);  factor < 1.0 → tighten them
# ---------------------------------------------------------------------------

_REGIME_TARGET_MULTIPLIERS: Dict[str, float] = {
    "bull":   1.20,   # trending up  → chase larger moves
    "normal": 1.00,   # baseline
    "chop":   0.90,   # sideways     → lock profits sooner
    "crash":  0.70,   # sharp drop   → survival mode, take small gains fast
}

_REGIME_POSITION_MULTIPLIERS: Dict[str, float] = {
    "bull":   1.10,   # deploy slightly more in trending market
    "normal": 1.00,
    "chop":   0.85,   # reduce exposure in directionless market
    "crash":  0.60,   # minimal exposure during drawdowns
}

# ---------------------------------------------------------------------------
# Stop-loss defaults
# ---------------------------------------------------------------------------

#: Primary stop loss for normal conditions — -1.0 %
KRAKEN_STOP_LOSS_DEFAULT: float = -0.010
#: Tightest stop loss allowed — -0.7 % (calm, low-volatility sessions)
KRAKEN_STOP_LOSS_MIN: float = -0.007
#: Widest stop loss allowed — -2.0 % (volatile / crash regime)
KRAKEN_STOP_LOSS_MAX: float = -0.020

# ---------------------------------------------------------------------------
# Adaptive-learning guard rails
# ---------------------------------------------------------------------------

_MIN_HISTORY_TRADES: int = 10     # need ≥10 trades before auto-tuning kicks in
_WIN_RATE_HIGH: float = 0.65       # ≥65% win rate → loosen targets a little
_WIN_RATE_LOW: float = 0.40        # <40% win rate → tighten targets, cut losses faster
_MAX_TARGET_MULTIPLIER: float = 1.50   # never expand targets beyond +50%
_MIN_TARGET_MULTIPLIER: float = 0.70   # never compress targets below -30%


# ---------------------------------------------------------------------------
# Public dataclass returned to callers
# ---------------------------------------------------------------------------

@dataclass
class KrakenOptParams:
    """Resolved, regime-adjusted Kraken trading parameters for a single cycle."""

    #: Three-tier profit target list [(gross_pct, label), …] — already scaled
    profit_targets: List[Tuple[float, str]]
    #: Primary stop loss as a negative fraction (e.g. -0.010 = -1.0 %)
    stop_loss: float
    #: Minimum gross profit required for a trade to be net-positive
    min_profit_threshold: float
    #: Multiplier to apply to the baseline position size (1.0 = no change)
    position_size_multiplier: float
    #: RSI lower bound for BUY entries
    rsi_buy_min: float
    #: RSI upper bound for BUY entries
    rsi_buy_max: float
    #: RSI level above which SELL / exit signals are valid
    rsi_sell_min: float
    #: Current market regime name ("bull", "chop", "crash", "normal")
    regime: str
    #: Historical Kraken win rate (0.0–1.0); 0.0 until sufficient data
    win_rate: float
    #: Total Kraken trades recorded so far
    total_trades: int


# ---------------------------------------------------------------------------
# Optimizer class
# ---------------------------------------------------------------------------

class KrakenParamsOptimizer:
    """
    Adaptive Kraken-specific parameter optimizer.

    Combines static fee-arithmetic with rolling win-rate feedback to
    continuously tune profit targets and stop losses for Kraken trades.

    Thread-safe — all state mutations are protected by a single lock.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

        # Market regime state
        self._regime: str = "normal"
        self._regime_confidence: float = 0.5

        # Trade history
        self._wins: int = 0
        self._losses: int = 0
        self._total_pnl_usd: float = 0.0

        # Adaptive multipliers (start neutral, drift with performance)
        self._target_multiplier: float = 1.0
        self._sl_multiplier: float = 1.0

        logger.info(
            "✅ Kraken Params Optimizer initialized — "
            "min target=%.2f%% (taker), round-trip=%.2f%%",
            KRAKEN_MIN_PROFIT_THRESHOLD_TAKER * 100,
            KRAKEN_ROUND_TRIP_TAKER * 100,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_regime(self, regime: str, confidence: float = 0.5) -> None:
        """
        Update the current market regime classification.

        Args:
            regime: One of ``"bull"``, ``"chop"``, ``"crash"``, ``"normal"``.
                    Unknown values fall back to ``"normal"``.
            confidence: Regime detector confidence in [0.0, 1.0].
                        Low confidence blends the regime effect toward
                        the neutral baseline.
        """
        key = (regime or "normal").lower()
        if key not in _REGIME_TARGET_MULTIPLIERS:
            key = "normal"
        with self._lock:
            self._regime = key
            self._regime_confidence = max(0.0, min(1.0, confidence))
        logger.debug(
            "Kraken optimizer regime updated → %s (confidence=%.2f)",
            key,
            confidence,
        )

    def record_trade(self, pnl_usd: float, is_win: bool) -> KrakenOptParams:
        """
        Record a completed Kraken trade and update adaptive parameters.

        Args:
            pnl_usd: Realised profit/loss in USD (positive = profit).
            is_win: ``True`` if the trade closed above break-even.

        Returns:
            Updated :class:`KrakenOptParams` reflecting the new state.
        """
        with self._lock:
            if is_win:
                self._wins += 1
            else:
                self._losses += 1
            self._total_pnl_usd += pnl_usd
            self._update_multipliers()
        return self.get_params()

    def get_params(self) -> KrakenOptParams:
        """Return the current Kraken-optimized trading parameters."""
        with self._lock:
            return self._build_params()

    def get_report(self) -> Dict:
        """
        Return a status dictionary suitable for logging or monitoring.

        Keys: ``wins``, ``losses``, ``total_trades``, ``win_rate``,
        ``total_pnl_usd``, ``regime``, ``regime_confidence``,
        ``target_multiplier``, ``sl_multiplier``.
        """
        with self._lock:
            total = self._wins + self._losses
            win_rate = self._wins / total if total > 0 else 0.0
            return {
                "wins": self._wins,
                "losses": self._losses,
                "total_trades": total,
                "win_rate": win_rate,
                "total_pnl_usd": self._total_pnl_usd,
                "regime": self._regime,
                "regime_confidence": self._regime_confidence,
                "target_multiplier": self._target_multiplier,
                "sl_multiplier": self._sl_multiplier,
                "min_profit_threshold_pct": KRAKEN_MIN_PROFIT_THRESHOLD_TAKER * 100,
                "round_trip_cost_pct": KRAKEN_ROUND_TRIP_TAKER * 100,
            }

    # ------------------------------------------------------------------
    # Private helpers (all called with lock held unless noted)
    # ------------------------------------------------------------------

    def _update_multipliers(self) -> None:
        """Adjust target and SL multipliers based on rolling win rate."""
        total = self._wins + self._losses
        if total < _MIN_HISTORY_TRADES:
            return  # Not enough data — keep defaults

        win_rate = self._wins / total

        # ── Profit target multiplier ──────────────────────────────────
        if win_rate >= _WIN_RATE_HIGH:
            # Excellent win rate → widen targets to capture bigger moves
            self._target_multiplier = min(
                self._target_multiplier + 0.05,
                _MAX_TARGET_MULTIPLIER,
            )
        elif win_rate < _WIN_RATE_LOW:
            # Poor win rate → tighten targets to lock gains faster
            self._target_multiplier = max(
                self._target_multiplier - 0.05,
                _MIN_TARGET_MULTIPLIER,
            )
        else:
            # Healthy range → gentle mean-reversion toward 1.0
            self._target_multiplier += 0.01 * (1.0 - self._target_multiplier)

        # ── Stop-loss multiplier ──────────────────────────────────────
        if win_rate < _WIN_RATE_LOW:
            # Losing frequently → tighten SL (cut losses faster)
            self._sl_multiplier = max(self._sl_multiplier - 0.03, 0.80)
        elif win_rate >= _WIN_RATE_HIGH:
            # Winning well → give trades a little more room to breathe
            self._sl_multiplier = min(self._sl_multiplier + 0.02, 1.20)
        else:
            # Mean-revert toward neutral
            self._sl_multiplier += 0.005 * (1.0 - self._sl_multiplier)

    def _build_params(self) -> KrakenOptParams:
        """Construct KrakenOptParams from current state (lock must be held)."""
        # ── Regime blending ───────────────────────────────────────────
        target_regime_mult = _REGIME_TARGET_MULTIPLIERS.get(self._regime, 1.0)
        pos_regime_mult = _REGIME_POSITION_MULTIPLIERS.get(self._regime, 1.0)
        conf = self._regime_confidence

        # Low confidence → blend regime effect toward neutral (1.0)
        blended_target_regime = 1.0 + (target_regime_mult - 1.0) * conf
        blended_pos_regime = 1.0 + (pos_regime_mult - 1.0) * conf

        # ── Profit targets ────────────────────────────────────────────
        combined_mult = self._target_multiplier * blended_target_regime
        combined_mult = max(_MIN_TARGET_MULTIPLIER, min(_MAX_TARGET_MULTIPLIER, combined_mult))

        scaled_targets: List[Tuple[float, str]] = []
        for base_pct, label in KRAKEN_DEFAULT_PROFIT_TARGETS:
            scaled_pct = base_pct * combined_mult
            scaled_label = f"{label} [mult={combined_mult:.2f}]"
            scaled_targets.append((scaled_pct, scaled_label))

        # ── Stop loss ─────────────────────────────────────────────────
        raw_sl = KRAKEN_STOP_LOSS_DEFAULT * self._sl_multiplier
        # Clamp: never tighter than -0.7 % or wider than -2.0 %
        stop_loss = max(KRAKEN_STOP_LOSS_MAX, min(KRAKEN_STOP_LOSS_MIN, raw_sl))

        # ── RSI entry thresholds (regime-sensitive) ───────────────────
        if self._regime == "bull":
            rsi_buy_min, rsi_buy_max = 30.0, 60.0
            rsi_sell_min = 70.0
        elif self._regime == "chop":
            rsi_buy_min, rsi_buy_max = 25.0, 45.0
            rsi_sell_min = 60.0
        elif self._regime == "crash":
            rsi_buy_min, rsi_buy_max = 20.0, 35.0
            rsi_sell_min = 55.0
        else:  # normal
            rsi_buy_min, rsi_buy_max = 25.0, 55.0
            rsi_sell_min = 65.0

        # ── Win rate snapshot ─────────────────────────────────────────
        total = self._wins + self._losses
        win_rate = self._wins / total if total > 0 else 0.0

        return KrakenOptParams(
            profit_targets=scaled_targets,
            stop_loss=stop_loss,
            min_profit_threshold=KRAKEN_MIN_PROFIT_THRESHOLD_TAKER,
            position_size_multiplier=blended_pos_regime,
            rsi_buy_min=rsi_buy_min,
            rsi_buy_max=rsi_buy_max,
            rsi_sell_min=rsi_sell_min,
            regime=self._regime,
            win_rate=win_rate,
            total_trades=total,
        )


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_instance: Optional[KrakenParamsOptimizer] = None
_instance_lock = threading.Lock()


def get_kraken_params_optimizer() -> KrakenParamsOptimizer:
    """
    Return the global :class:`KrakenParamsOptimizer` singleton.

    Thread-safe — safe to call from multiple threads simultaneously.
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = KrakenParamsOptimizer()
    return _instance


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    "KrakenOptParams",
    "KrakenParamsOptimizer",
    "get_kraken_params_optimizer",
    # Fee constants (useful for external callers)
    "KRAKEN_TAKER_FEE",
    "KRAKEN_MAKER_FEE",
    "KRAKEN_ROUND_TRIP_TAKER",
    "KRAKEN_ROUND_TRIP_MAKER",
    "KRAKEN_MIN_PROFIT_THRESHOLD_TAKER",
    "KRAKEN_MIN_PROFIT_THRESHOLD_MAKER",
    "KRAKEN_DEFAULT_PROFIT_TARGETS",
    "KRAKEN_STOP_LOSS_DEFAULT",
    "KRAKEN_STOP_LOSS_MIN",
    "KRAKEN_STOP_LOSS_MAX",
]
