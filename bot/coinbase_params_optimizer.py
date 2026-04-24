"""
NIJA Coinbase Parameters Optimizer
=====================================

Coinbase-specific parameter optimization that accounts for Coinbase's high
fee structure (~1.4% round-trip) to ensure every trade is net-profitable.

1. **Higher profit targets** — 2.0% / 3.5% / 5.0% minimum to clear 1.4% fees
2. **Tighter stop losses** — -1.0% to -1.5% to protect capital
3. **Lower trade frequency** — fees punish marginal setups heavily
4. **Larger minimum move requirement** — skip trades that won't clear fees
5. **Regime-aware adjustments** — BULL loosens targets, CRASH tightens them

Fee structure (Coinbase Advanced Trade, standard tier):
  ╔══════════════════╦═════════════╦═════════════╦══════════════════╗
  ║ Exchange         ║ Taker fee   ║ Maker fee   ║ Round-trip (mkt) ║
  ╠══════════════════╬═════════════╬═════════════╬══════════════════╣
  ║ Coinbase Adv.    ║ 0.60%       ║ 0.40%       ║ ~1.40%           ║
  ╚══════════════════╩═════════════╩═════════════╩══════════════════╝

With 1.40% round-trip costs, break-even is ~1.40%.  Adding a 0.20% buffer
sets the minimum profitable target at **~1.60%** — meaning only swing-style
moves of 2%+ deliver meaningful net profit.

Adaptive learning
-----------------
After each Coinbase trade the optimizer:
  - Records win/loss and P&L
  - Adjusts the target multiplier (widens when winning, tightens when losing)
  - Adjusts the stop-loss multiplier (tighter when losing frequently)

Singleton usage::

    from bot.coinbase_params_optimizer import get_coinbase_params_optimizer

    optimizer = get_coinbase_params_optimizer()
    optimizer.update_regime("bull", confidence=0.8)
    params = optimizer.get_params()
    # → params.profit_targets, params.stop_loss, params.min_profit_threshold, …

    # After a trade completes:
    optimizer.record_trade(pnl_usd=-0.50, is_win=False)

Author: NIJA Trading Systems
Version: 1.0 — Coinbase Fee-Optimised Edition
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.coinbase_params_optimizer")

# ---------------------------------------------------------------------------
# Coinbase fee constants (Advanced Trade, standard tier)
# ---------------------------------------------------------------------------

#: Taker fee (market orders) — 0.60 %
COINBASE_TAKER_FEE: float = 0.0060
#: Maker fee (limit orders) — 0.40 %
COINBASE_MAKER_FEE: float = 0.0040
#: Typical bid-ask spread on major pairs — ~0.20 %
COINBASE_TYPICAL_SPREAD: float = 0.0020

#: Total round-trip cost using market (taker) orders — 1.40 %
COINBASE_ROUND_TRIP_TAKER: float = (COINBASE_TAKER_FEE * 2) + COINBASE_TYPICAL_SPREAD
#: Total round-trip cost using limit (maker) orders — 1.00 %
COINBASE_ROUND_TRIP_MAKER: float = (COINBASE_MAKER_FEE * 2) + COINBASE_TYPICAL_SPREAD

#: Safety buffer added above break-even — 0.20 %
COINBASE_PROFIT_BUFFER: float = 0.0020

#: Minimum gross profit for a taker-order trade to be net-positive — 1.60 %
COINBASE_MIN_PROFIT_THRESHOLD_TAKER: float = COINBASE_ROUND_TRIP_TAKER + COINBASE_PROFIT_BUFFER
#: Minimum gross profit for a maker-order trade to be net-positive — 1.20 %
COINBASE_MIN_PROFIT_THRESHOLD_MAKER: float = COINBASE_ROUND_TRIP_MAKER + COINBASE_PROFIT_BUFFER

# ---------------------------------------------------------------------------
# Default profit targets (gross %, with descriptive labels)
# These are calibrated for Coinbase's 1.40 % taker round-trip cost.
# ---------------------------------------------------------------------------

#: Three-tier profit target ladder for Coinbase (lowest-to-exit-first ordering)
COINBASE_DEFAULT_PROFIT_TARGETS: List[Tuple[float, str]] = [
    (0.050, "Coinbase TP3 +5.0% (Net +3.6% after 1.4% fees) — MAJOR PROFIT"),
    (0.035, "Coinbase TP2 +3.5% (Net +2.1% after fees) — EXCELLENT"),
    (0.020, "Coinbase TP1 +2.0% (Net +0.6% after fees) — MINIMUM"),
]

# ---------------------------------------------------------------------------
# Stop-loss constants
# ---------------------------------------------------------------------------

#: Default primary stop loss — -1.0 %  (tight, fees are expensive)
COINBASE_STOP_LOSS_DEFAULT: float = -0.010
#: Tightest allowed stop — -0.8 %
COINBASE_STOP_LOSS_MIN: float = -0.008
#: Widest allowed stop — -1.5 %
COINBASE_STOP_LOSS_MAX: float = -0.015

# ---------------------------------------------------------------------------
# Regime multipliers
# ---------------------------------------------------------------------------

_REGIME_TARGET_MULTIPLIERS: Dict[str, float] = {
    "bull":   1.15,   # Looser targets — strong momentum, ride the wave
    "normal": 1.00,   # Neutral baseline
    "chop":   0.90,   # Tighter — chop kills swing trades
    "crash":  0.80,   # Very tight — protect capital
}

_REGIME_POSITION_MULTIPLIERS: Dict[str, float] = {
    "bull":   1.20,   # Scale up in trending bull
    "normal": 1.00,
    "chop":   0.70,   # Reduce size in chop
    "crash":  0.40,   # Minimal exposure in crash
}

# ---------------------------------------------------------------------------
# Adaptive learning thresholds
# ---------------------------------------------------------------------------

_MIN_HISTORY_TRADES: int = 10         # trades before adaptation kicks in
_WIN_RATE_HIGH: float = 0.60          # above this → widen targets
_WIN_RATE_LOW: float = 0.45           # below this → tighten
_MIN_TARGET_MULTIPLIER: float = 0.75
_MAX_TARGET_MULTIPLIER: float = 1.50

# ---------------------------------------------------------------------------
# Public dataclass returned to callers
# ---------------------------------------------------------------------------


@dataclass
class CoinbaseOptParams:
    """Resolved, regime-adjusted Coinbase trading parameters for a single cycle."""

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
    #: Historical Coinbase win rate (0.0–1.0); 0.0 until sufficient data
    win_rate: float
    #: Total Coinbase trades recorded so far
    total_trades: int


# ---------------------------------------------------------------------------
# Optimizer class
# ---------------------------------------------------------------------------


class CoinbaseParamsOptimizer:
    """
    Adaptive Coinbase-specific parameter optimizer.

    Combines static fee-arithmetic with rolling win-rate feedback to
    continuously tune profit targets and stop losses for Coinbase trades.

    High-fee exchange strategy: swing-style entries only, skip marginal setups,
    require larger expected moves before committing capital.

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
            "✅ Coinbase Params Optimizer initialized — "
            "min target=%.2f%% (taker), round-trip=%.2f%%",
            COINBASE_MIN_PROFIT_THRESHOLD_TAKER * 100,
            COINBASE_ROUND_TRIP_TAKER * 100,
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
        """
        key = (regime or "normal").lower()
        if key not in _REGIME_TARGET_MULTIPLIERS:
            key = "normal"
        with self._lock:
            self._regime = key
            self._regime_confidence = max(0.0, min(1.0, confidence))
        logger.debug(
            "Coinbase optimizer regime updated → %s (confidence=%.2f)",
            key,
            confidence,
        )

    def record_trade(self, pnl_usd: float, is_win: bool) -> CoinbaseOptParams:
        """
        Record a completed Coinbase trade and update adaptive parameters.

        Args:
            pnl_usd: Realised profit/loss in USD (positive = profit).
            is_win: ``True`` if the trade closed above break-even.

        Returns:
            Updated :class:`CoinbaseOptParams` reflecting the new state.
        """
        with self._lock:
            if is_win:
                self._wins += 1
            else:
                self._losses += 1
            self._total_pnl_usd += pnl_usd
            self._update_multipliers()
        return self.get_params()

    def get_params(self) -> CoinbaseOptParams:
        """Return the current Coinbase-optimized trading parameters."""
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
                "min_profit_threshold_pct": COINBASE_MIN_PROFIT_THRESHOLD_TAKER * 100,
                "round_trip_cost_pct": COINBASE_ROUND_TRIP_TAKER * 100,
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
            # Excellent win rate → widen targets to capture bigger swing moves
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
            # Losing frequently → tighten SL (Coinbase losses hurt more due to fees)
            self._sl_multiplier = max(self._sl_multiplier - 0.04, 0.75)
        elif win_rate >= _WIN_RATE_HIGH:
            # Winning well → allow a bit more room
            self._sl_multiplier = min(self._sl_multiplier + 0.02, 1.15)
        else:
            # Mean-revert toward neutral
            self._sl_multiplier += 0.005 * (1.0 - self._sl_multiplier)

    def _build_params(self) -> CoinbaseOptParams:
        """Construct CoinbaseOptParams from current state (lock must be held)."""
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
        for base_pct, label in COINBASE_DEFAULT_PROFIT_TARGETS:
            scaled_pct = base_pct * combined_mult
            scaled_label = f"{label} [mult={combined_mult:.2f}]"
            scaled_targets.append((scaled_pct, scaled_label))

        # ── Stop loss ─────────────────────────────────────────────────
        raw_sl = COINBASE_STOP_LOSS_DEFAULT * self._sl_multiplier
        # Clamp: never tighter than -0.8 % or wider than -1.5 %
        stop_loss = max(COINBASE_STOP_LOSS_MAX, min(COINBASE_STOP_LOSS_MIN, raw_sl))

        # ── RSI entry thresholds (swing-style, regime-sensitive) ──────
        if self._regime == "bull":
            rsi_buy_min, rsi_buy_max = 35.0, 55.0
            rsi_sell_min = 65.0
        elif self._regime == "chop":
            rsi_buy_min, rsi_buy_max = 30.0, 42.0
            rsi_sell_min = 58.0
        elif self._regime == "crash":
            rsi_buy_min, rsi_buy_max = 25.0, 35.0
            rsi_sell_min = 52.0
        else:  # normal
            rsi_buy_min, rsi_buy_max = 30.0, 50.0
            rsi_sell_min = 60.0

        # ── Win rate snapshot ─────────────────────────────────────────
        total = self._wins + self._losses
        win_rate = self._wins / total if total > 0 else 0.0

        return CoinbaseOptParams(
            profit_targets=scaled_targets,
            stop_loss=stop_loss,
            min_profit_threshold=COINBASE_MIN_PROFIT_THRESHOLD_TAKER,
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

_instance: Optional[CoinbaseParamsOptimizer] = None
_instance_lock = threading.Lock()


def get_coinbase_params_optimizer() -> CoinbaseParamsOptimizer:
    """
    Return the global :class:`CoinbaseParamsOptimizer` singleton.

    Thread-safe — safe to call from multiple threads simultaneously.
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = CoinbaseParamsOptimizer()
    return _instance


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    "CoinbaseOptParams",
    "CoinbaseParamsOptimizer",
    "get_coinbase_params_optimizer",
    # Fee constants (useful for external callers)
    "COINBASE_TAKER_FEE",
    "COINBASE_MAKER_FEE",
    "COINBASE_ROUND_TRIP_TAKER",
    "COINBASE_ROUND_TRIP_MAKER",
    "COINBASE_MIN_PROFIT_THRESHOLD_TAKER",
    "COINBASE_MIN_PROFIT_THRESHOLD_MAKER",
    "COINBASE_DEFAULT_PROFIT_TARGETS",
    "COINBASE_STOP_LOSS_DEFAULT",
    "COINBASE_STOP_LOSS_MIN",
    "COINBASE_STOP_LOSS_MAX",
]
