"""
NIJA Binance Parameters Optimizer
=====================================

Binance-specific parameter optimization that leverages Binance's ultra-low
fee structure (~0.28% round-trip) to enable high-frequency scalp trading.

1. **Lower profit targets** — 0.5% / 0.9% / 1.5% viable after only 0.28% fees
2. **Tighter stop losses** — -0.4% to -0.8% for fast scalp exits
3. **Higher trade frequency** — near-zero fees support frequent entries
4. **Smaller minimum move** — 0.5% moves are profitable on Binance
5. **Regime-aware adjustments** — BULL loosens targets, CRASH tightens them

Fee structure (Binance standard tier, no BNB discount):
  ╔══════════════╦═════════════╦═════════════╦══════════════════╗
  ║ Exchange     ║ Taker fee   ║ Maker fee   ║ Round-trip (mkt) ║
  ╠══════════════╬═════════════╬═════════════╬══════════════════╣
  ║ Binance      ║ 0.10%       ║ 0.10%       ║ ~0.28%           ║
  ╚══════════════╩═════════════╩═════════════╩══════════════════╝

With 0.28% round-trip costs, break-even is ~0.28%.  Adding a 0.10% buffer
sets the minimum profitable target at **~0.38%** — enabling scalp-style
trading that is impossible to profit from on Coinbase.

Adaptive learning
-----------------
After each Binance trade the optimizer:
  - Records win/loss and P&L
  - Adjusts the target multiplier (widens when winning, tightens when losing)
  - Adjusts the stop-loss multiplier (tighter when losing frequently)

Singleton usage::

    from bot.binance_params_optimizer import get_binance_params_optimizer

    optimizer = get_binance_params_optimizer()
    optimizer.update_regime("bull", confidence=0.8)
    params = optimizer.get_params()
    # → params.profit_targets, params.stop_loss, params.min_profit_threshold, …

    # After a trade completes:
    optimizer.record_trade(pnl_usd=0.30, is_win=True)

Author: NIJA Trading Systems
Version: 1.0 — Binance Fee-Optimised Edition
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.binance_params_optimizer")

# ---------------------------------------------------------------------------
# Binance fee constants (standard tier, no BNB discount)
# ---------------------------------------------------------------------------

#: Taker fee (market orders) — 0.10 %
BINANCE_TAKER_FEE: float = 0.0010
#: Maker fee (limit orders) — 0.10 %
BINANCE_MAKER_FEE: float = 0.0010
#: Typical bid-ask spread on major pairs — ~0.08 %
BINANCE_TYPICAL_SPREAD: float = 0.0008

#: Total round-trip cost using market (taker) orders — 0.28 %
BINANCE_ROUND_TRIP_TAKER: float = (BINANCE_TAKER_FEE * 2) + BINANCE_TYPICAL_SPREAD
#: Total round-trip cost using limit (maker) orders — 0.28 %  (same, maker=taker on Binance)
BINANCE_ROUND_TRIP_MAKER: float = (BINANCE_MAKER_FEE * 2) + BINANCE_TYPICAL_SPREAD

#: Safety buffer added above break-even — 0.10 %
BINANCE_PROFIT_BUFFER: float = 0.0010

#: Minimum gross profit for a taker-order trade to be net-positive — 0.38 %
BINANCE_MIN_PROFIT_THRESHOLD_TAKER: float = BINANCE_ROUND_TRIP_TAKER + BINANCE_PROFIT_BUFFER
#: Minimum gross profit for a maker-order trade to be net-positive — 0.38 %
BINANCE_MIN_PROFIT_THRESHOLD_MAKER: float = BINANCE_ROUND_TRIP_MAKER + BINANCE_PROFIT_BUFFER

# ---------------------------------------------------------------------------
# Default profit targets (gross %, with descriptive labels)
# These are calibrated for Binance's 0.28 % taker round-trip cost.
# ---------------------------------------------------------------------------

#: Three-tier profit target ladder for Binance (lowest-to-exit-first ordering)
BINANCE_DEFAULT_PROFIT_TARGETS: List[Tuple[float, str]] = [
    (0.015, "Binance TP3 +1.5% (Net +1.22% after 0.28% fees) — MAJOR PROFIT"),
    (0.009, "Binance TP2 +0.9% (Net +0.62% after fees) — GOOD"),
    (0.005, "Binance TP1 +0.5% (Net +0.22% after fees) — MINIMAL"),
]

# ---------------------------------------------------------------------------
# Stop-loss constants
# ---------------------------------------------------------------------------

#: Default primary stop loss — -0.5 %  (tight scalp stop)
BINANCE_STOP_LOSS_DEFAULT: float = -0.005
#: Tightest allowed stop — -0.3 %
BINANCE_STOP_LOSS_MIN: float = -0.003
#: Widest allowed stop — -0.8 %
BINANCE_STOP_LOSS_MAX: float = -0.008

# ---------------------------------------------------------------------------
# Regime multipliers
# ---------------------------------------------------------------------------

_REGIME_TARGET_MULTIPLIERS: Dict[str, float] = {
    "bull":   1.20,   # Loosened — strong momentum supports larger scalp captures
    "normal": 1.00,   # Neutral baseline
    "chop":   0.85,   # Tighter — chop is noisy for scalps
    "crash":  0.70,   # Very tight — protect capital
}

_REGIME_POSITION_MULTIPLIERS: Dict[str, float] = {
    "bull":   1.30,   # Scale up aggressively in trending bull (low fees allow it)
    "normal": 1.00,
    "chop":   0.75,   # Reduce size in chop
    "crash":  0.35,   # Minimal exposure in crash
}

# ---------------------------------------------------------------------------
# Adaptive learning thresholds
# ---------------------------------------------------------------------------

_MIN_HISTORY_TRADES: int = 10          # trades before adaptation kicks in
_WIN_RATE_HIGH: float = 0.58           # above this → widen targets
_WIN_RATE_LOW: float = 0.42            # below this → tighten
_MIN_TARGET_MULTIPLIER: float = 0.70
_MAX_TARGET_MULTIPLIER: float = 1.60

# ---------------------------------------------------------------------------
# Public dataclass returned to callers
# ---------------------------------------------------------------------------


@dataclass
class BinanceOptParams:
    """Resolved, regime-adjusted Binance trading parameters for a single cycle."""

    #: Three-tier profit target list [(gross_pct, label), …] — already scaled
    profit_targets: List[Tuple[float, str]]
    #: Primary stop loss as a negative fraction (e.g. -0.005 = -0.5 %)
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
    #: Historical Binance win rate (0.0–1.0); 0.0 until sufficient data
    win_rate: float
    #: Total Binance trades recorded so far
    total_trades: int


# ---------------------------------------------------------------------------
# Optimizer class
# ---------------------------------------------------------------------------


class BinanceParamsOptimizer:
    """
    Adaptive Binance-specific parameter optimizer.

    Combines static fee-arithmetic with rolling win-rate feedback to
    continuously tune profit targets and stop losses for Binance trades.

    Low-fee exchange strategy: scalp-style entries, higher frequency,
    tight stops that still leave meaningful net profit after minimal fees.

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
            "✅ Binance Params Optimizer initialized — "
            "min target=%.2f%% (taker), round-trip=%.2f%%",
            BINANCE_MIN_PROFIT_THRESHOLD_TAKER * 100,
            BINANCE_ROUND_TRIP_TAKER * 100,
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
            "Binance optimizer regime updated → %s (confidence=%.2f)",
            key,
            confidence,
        )

    def record_trade(self, pnl_usd: float, is_win: bool) -> BinanceOptParams:
        """
        Record a completed Binance trade and update adaptive parameters.

        Args:
            pnl_usd: Realised profit/loss in USD (positive = profit).
            is_win: ``True`` if the trade closed above break-even.

        Returns:
            Updated :class:`BinanceOptParams` reflecting the new state.
        """
        with self._lock:
            if is_win:
                self._wins += 1
            else:
                self._losses += 1
            self._total_pnl_usd += pnl_usd
            self._update_multipliers()
        return self.get_params()

    def get_params(self) -> BinanceOptParams:
        """Return the current Binance-optimized trading parameters."""
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
                "min_profit_threshold_pct": BINANCE_MIN_PROFIT_THRESHOLD_TAKER * 100,
                "round_trip_cost_pct": BINANCE_ROUND_TRIP_TAKER * 100,
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
            # Excellent win rate → widen targets; low fees make this very viable
            self._target_multiplier = min(
                self._target_multiplier + 0.06,
                _MAX_TARGET_MULTIPLIER,
            )
        elif win_rate < _WIN_RATE_LOW:
            # Poor win rate → tighten targets to lock quick gains
            self._target_multiplier = max(
                self._target_multiplier - 0.06,
                _MIN_TARGET_MULTIPLIER,
            )
        else:
            # Healthy range → gentle mean-reversion toward 1.0
            self._target_multiplier += 0.01 * (1.0 - self._target_multiplier)

        # ── Stop-loss multiplier ──────────────────────────────────────
        if win_rate < _WIN_RATE_LOW:
            # Losing frequently → tighten SL fast (low fees = cut quick)
            self._sl_multiplier = max(self._sl_multiplier - 0.04, 0.75)
        elif win_rate >= _WIN_RATE_HIGH:
            # Winning well → allow a fraction more room on scalps
            self._sl_multiplier = min(self._sl_multiplier + 0.03, 1.25)
        else:
            # Mean-revert toward neutral
            self._sl_multiplier += 0.005 * (1.0 - self._sl_multiplier)

    def _build_params(self) -> BinanceOptParams:
        """Construct BinanceOptParams from current state (lock must be held)."""
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
        for base_pct, label in BINANCE_DEFAULT_PROFIT_TARGETS:
            scaled_pct = base_pct * combined_mult
            scaled_label = f"{label} [mult={combined_mult:.2f}]"
            scaled_targets.append((scaled_pct, scaled_label))

        # ── Stop loss ─────────────────────────────────────────────────
        raw_sl = BINANCE_STOP_LOSS_DEFAULT * self._sl_multiplier
        # Clamp: never tighter than -0.3 % or wider than -0.8 %
        stop_loss = max(BINANCE_STOP_LOSS_MAX, min(BINANCE_STOP_LOSS_MIN, raw_sl))

        # ── RSI entry thresholds (scalp-style, regime-sensitive) ──────
        if self._regime == "bull":
            rsi_buy_min, rsi_buy_max = 30.0, 60.0
            rsi_sell_min = 68.0
        elif self._regime == "chop":
            rsi_buy_min, rsi_buy_max = 28.0, 45.0
            rsi_sell_min = 58.0
        elif self._regime == "crash":
            rsi_buy_min, rsi_buy_max = 22.0, 35.0
            rsi_sell_min = 52.0
        else:  # normal
            rsi_buy_min, rsi_buy_max = 28.0, 55.0
            rsi_sell_min = 63.0

        # ── Win rate snapshot ─────────────────────────────────────────
        total = self._wins + self._losses
        win_rate = self._wins / total if total > 0 else 0.0

        return BinanceOptParams(
            profit_targets=scaled_targets,
            stop_loss=stop_loss,
            min_profit_threshold=BINANCE_MIN_PROFIT_THRESHOLD_TAKER,
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

_instance: Optional[BinanceParamsOptimizer] = None
_instance_lock = threading.Lock()


def get_binance_params_optimizer() -> BinanceParamsOptimizer:
    """
    Return the global :class:`BinanceParamsOptimizer` singleton.

    Thread-safe — safe to call from multiple threads simultaneously.
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = BinanceParamsOptimizer()
    return _instance


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    "BinanceOptParams",
    "BinanceParamsOptimizer",
    "get_binance_params_optimizer",
    # Fee constants (useful for external callers)
    "BINANCE_TAKER_FEE",
    "BINANCE_MAKER_FEE",
    "BINANCE_ROUND_TRIP_TAKER",
    "BINANCE_ROUND_TRIP_MAKER",
    "BINANCE_MIN_PROFIT_THRESHOLD_TAKER",
    "BINANCE_MIN_PROFIT_THRESHOLD_MAKER",
    "BINANCE_DEFAULT_PROFIT_TARGETS",
    "BINANCE_STOP_LOSS_DEFAULT",
    "BINANCE_STOP_LOSS_MIN",
    "BINANCE_STOP_LOSS_MAX",
]
