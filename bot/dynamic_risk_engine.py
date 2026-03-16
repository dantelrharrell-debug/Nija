"""
NIJA Dynamic Risk Engine — Position Sizing Intelligence
=========================================================

Unified position-sizing layer that combines four complementary
methodologies into a single, capital-tier-aware risk decision:

1. **Fractional-Kelly Criterion** — mathematically optimal bet size
   derived from historical win-rate and average risk/reward.

2. **ATR Volatility Sizing** — normalises risk exposure so every trade
   carries roughly the same dollar risk regardless of asset volatility.

3. **Signal-Strength Weighting** — scales the position up/down based on
   how strongly the entry signal fires (0 → 1).

4. **Capital-Tier Constraints** — enforces hard limits from
   :mod:`bot.capital_strategy_selector` so MICRO / NORMAL / ADVANCED
   accounts never exceed their per-tier risk envelope.

Usage::

    from bot.dynamic_risk_engine import get_dynamic_risk_engine

    engine = get_dynamic_risk_engine()

    result = engine.calculate(
        balance=1_500.0,
        current_price=50_000.0,
        atr=800.0,           # 14-period ATR in price units
        signal_strength=0.8, # 0-1 (e.g. from RSI confluence score)
        win_rate=0.55,       # historical win-rate (0-1)
        avg_win_pct=0.025,   # average winning trade return
        avg_loss_pct=0.012,  # average losing trade return (positive value)
    )

    if result.can_trade:
        place_order(size_usd=result.position_size_usd)

    # Record every completed trade to keep Kelly estimates fresh:
    engine.record_trade(win=True, return_pct=0.022, loss_pct=0.0)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional

logger = logging.getLogger("nija.dynamic_risk_engine")

# ---------------------------------------------------------------------------
# Optional integration with CapitalStrategySelector
# ---------------------------------------------------------------------------
try:
    from capital_strategy_selector import (
        StrategyProfile,
        get_strategy_for_balance,
    )
    _SELECTOR_AVAILABLE = True
except ImportError:
    try:
        from bot.capital_strategy_selector import (
            StrategyProfile,
            get_strategy_for_balance,
        )
        _SELECTOR_AVAILABLE = True
    except ImportError:
        _SELECTOR_AVAILABLE = False
        StrategyProfile = None  # type: ignore
        logger.warning(
            "⚠️  CapitalStrategySelector unavailable — "
            "DynamicRiskEngine will use built-in defaults."
        )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Fractional Kelly multiplier — we use 25 % of full Kelly to avoid
#: overconfidence in noisy win-rate estimates.
DEFAULT_KELLY_FRACTION: float = 0.25

#: Default ATR-based risk target expressed as % of account balance.
DEFAULT_ATR_RISK_PCT: float = 0.01  # 1 % per trade

#: Hard floor — never risk more than this fraction of balance on one trade.
ABSOLUTE_MAX_RISK_PCT: float = 0.10  # 10 %

#: Hard floor — never open a position smaller than this USD amount.
MIN_POSITION_USD: float = 1.0


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class RiskCalculationResult:
    """
    Output of :meth:`DynamicRiskEngine.calculate`.

    Attributes
    ----------
    can_trade:
        False when conditions prevent any position (e.g. balance too low,
        daily loss limit hit).
    position_size_usd:
        Recommended position size in USD.
    position_size_base:
        Equivalent base-currency units at *current_price*.
    risk_amount_usd:
        Dollar amount at risk (position_size_usd × stop_distance %).
    risk_pct_of_balance:
        Fraction of balance at risk (0–1).
    strategy_tier:
        Name of the capital tier used (MICRO / NORMAL / ADVANCED).
    sizing_breakdown:
        Per-component size estimates before final capping.
    reason:
        Human-readable explanation, especially when can_trade is False.
    """

    can_trade: bool
    position_size_usd: float
    position_size_base: float
    risk_amount_usd: float
    risk_pct_of_balance: float
    strategy_tier: str
    sizing_breakdown: Dict[str, float] = field(default_factory=dict)
    reason: str = ""


# ---------------------------------------------------------------------------
# Trade history tracker (for Kelly estimation)
# ---------------------------------------------------------------------------

@dataclass
class _TradeRecord:
    win: bool
    return_pct: float  # absolute positive value


class _TradeHistory:
    """Rolling trade history for adaptive Kelly estimation."""

    MAX_RECORDS = 200

    def __init__(self) -> None:
        self._records: list[_TradeRecord] = []
        self._lock = threading.Lock()

    def push(self, win: bool, return_pct: float) -> None:
        with self._lock:
            self._records.append(_TradeRecord(win=win, return_pct=abs(return_pct)))
            if len(self._records) > self.MAX_RECORDS:
                self._records.pop(0)

    def stats(self) -> tuple[float, float, float]:
        """Return (win_rate, avg_win_pct, avg_loss_pct)."""
        with self._lock:
            if not self._records:
                return 0.5, 0.02, 0.01
            wins = [r for r in self._records if r.win]
            losses = [r for r in self._records if not r.win]
            win_rate = len(wins) / len(self._records)
            avg_win = sum(r.return_pct for r in wins) / len(wins) if wins else 0.02
            avg_loss = sum(r.return_pct for r in losses) / len(losses) if losses else 0.01
            return win_rate, avg_win, avg_loss


# ---------------------------------------------------------------------------
# Main engine class
# ---------------------------------------------------------------------------

class DynamicRiskEngine:
    """
    Position Sizing Intelligence engine.

    Thread-safe — a single instance may be shared across strategy threads.
    Use :func:`get_dynamic_risk_engine` to obtain the module singleton.
    """

    def __init__(
        self,
        kelly_fraction: float = DEFAULT_KELLY_FRACTION,
        atr_risk_pct: float = DEFAULT_ATR_RISK_PCT,
    ) -> None:
        self._kelly_fraction = kelly_fraction
        self._atr_risk_pct = atr_risk_pct
        self._history = _TradeHistory()
        self._lock = threading.Lock()
        self._daily_loss_usd: float = 0.0
        self._daily_loss_date: str = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def calculate(
        self,
        balance: float,
        current_price: float,
        atr: float,
        signal_strength: float = 1.0,
        win_rate: Optional[float] = None,
        avg_win_pct: Optional[float] = None,
        avg_loss_pct: Optional[float] = None,
        stop_loss_pct: Optional[float] = None,
    ) -> RiskCalculationResult:
        """
        Calculate the optimal position size for the given market conditions.

        Parameters
        ----------
        balance:
            Available account balance in USD.
        current_price:
            Current asset price in USD.
        atr:
            14-period ATR value in price units.
        signal_strength:
            Confidence of the entry signal, range 0–1.
            Higher values → larger position.
        win_rate:
            Historical win-rate (0–1).  If *None* the engine uses its
            internal rolling estimate from :meth:`record_trade`.
        avg_win_pct:
            Average winning trade return as a positive fraction (e.g. 0.025).
            Defaults to internal estimate.
        avg_loss_pct:
            Average losing trade return as a positive fraction (e.g. 0.012).
            Defaults to internal estimate.
        stop_loss_pct:
            Stop-loss distance as a fraction of entry price.  When *None*
            the tier's default is used.

        Returns
        -------
        RiskCalculationResult
        """
        # ── 0. Basic sanity checks ────────────────────────────────────
        if balance <= 0:
            return RiskCalculationResult(
                can_trade=False,
                position_size_usd=0.0,
                position_size_base=0.0,
                risk_amount_usd=0.0,
                risk_pct_of_balance=0.0,
                strategy_tier="UNKNOWN",
                reason="Balance is zero or negative.",
            )
        if current_price <= 0:
            return RiskCalculationResult(
                can_trade=False,
                position_size_usd=0.0,
                position_size_base=0.0,
                risk_amount_usd=0.0,
                risk_pct_of_balance=0.0,
                strategy_tier="UNKNOWN",
                reason="Price is zero or negative.",
            )

        signal_strength = max(0.0, min(1.0, signal_strength))

        # ── 1. Resolve capital tier and per-tier limits ───────────────
        tier_name, max_risk_pct, tier_stop_pct = self._get_tier_params(balance)

        effective_stop_pct = stop_loss_pct if stop_loss_pct is not None else tier_stop_pct

        # ── 2. Daily loss guard ───────────────────────────────────────
        if not self._check_daily_loss(balance, max_risk_pct):
            return RiskCalculationResult(
                can_trade=False,
                position_size_usd=0.0,
                position_size_base=0.0,
                risk_amount_usd=0.0,
                risk_pct_of_balance=0.0,
                strategy_tier=tier_name,
                reason=f"Daily loss limit hit for {tier_name} tier.",
            )

        # ── 3. Resolve Kelly inputs (override or rolling history) ─────
        hist_wr, hist_aw, hist_al = self._history.stats()
        wr = win_rate if win_rate is not None else hist_wr
        aw = avg_win_pct if avg_win_pct is not None else hist_aw
        al = avg_loss_pct if avg_loss_pct is not None else hist_al

        # ── 4. Component sizing ───────────────────────────────────────
        kelly_size = self._kelly_size(balance, wr, aw, al)
        atr_size = self._atr_size(balance, current_price, atr, effective_stop_pct)
        signal_size = balance * max_risk_pct * signal_strength

        # ── 5. Blend: average of three components ─────────────────────
        blended = (kelly_size + atr_size + signal_size) / 3.0

        # ── 6. Cap to tier maximum ────────────────────────────────────
        tier_cap = balance * max_risk_pct
        position_usd = min(blended, tier_cap, balance)

        # ── 7. Enforce absolute minimum ───────────────────────────────
        if position_usd < MIN_POSITION_USD:
            return RiskCalculationResult(
                can_trade=False,
                position_size_usd=0.0,
                position_size_base=0.0,
                risk_amount_usd=0.0,
                risk_pct_of_balance=0.0,
                strategy_tier=tier_name,
                sizing_breakdown={
                    "kelly": kelly_size,
                    "atr": atr_size,
                    "signal": signal_size,
                    "blended": blended,
                    "tier_cap": tier_cap,
                },
                reason=f"Position size ${position_usd:.2f} below minimum ${MIN_POSITION_USD:.2f}.",
            )

        risk_usd = position_usd * effective_stop_pct
        position_base = position_usd / current_price

        logger.debug(
            "DynamicRiskEngine [%s] kelly=$%.2f atr=$%.2f signal=$%.2f "
            "→ blended=$%.2f cap=$%.2f final=$%.2f",
            tier_name, kelly_size, atr_size, signal_size, blended, tier_cap, position_usd,
        )

        return RiskCalculationResult(
            can_trade=True,
            position_size_usd=round(position_usd, 2),
            position_size_base=position_base,
            risk_amount_usd=round(risk_usd, 2),
            risk_pct_of_balance=position_usd / balance,
            strategy_tier=tier_name,
            sizing_breakdown={
                "kelly": round(kelly_size, 2),
                "atr": round(atr_size, 2),
                "signal": round(signal_size, 2),
                "blended": round(blended, 2),
                "tier_cap": round(tier_cap, 2),
            },
            reason="OK",
        )

    def record_trade(
        self,
        win: bool,
        return_pct: float,
        loss_pct: float = 0.0,
        pnl_usd: float = 0.0,
    ) -> None:
        """
        Record a completed trade to update the internal rolling Kelly estimate.

        Parameters
        ----------
        win:
            True if the trade was profitable.
        return_pct:
            Absolute return as a fraction (e.g. 0.025 for +2.5 %).
        loss_pct:
            Absolute loss as a fraction (e.g. 0.012 for −1.2 %).
        pnl_usd:
            Realised PnL in USD (used for daily loss tracking).
        """
        self._history.push(win=win, return_pct=return_pct if win else loss_pct)
        if pnl_usd < 0:
            with self._lock:
                self._daily_loss_usd += abs(pnl_usd)

    def reset_daily_loss(self) -> None:
        """Reset the daily-loss accumulator (call at the start of each trading day)."""
        with self._lock:
            self._daily_loss_usd = 0.0

    def get_status(self) -> Dict:
        """Return a snapshot of the engine's current state."""
        wr, aw, al = self._history.stats()
        with self._lock:
            daily = self._daily_loss_usd
        return {
            "kelly_fraction": self._kelly_fraction,
            "atr_risk_pct": self._atr_risk_pct,
            "rolling_win_rate": round(wr, 4),
            "rolling_avg_win_pct": round(aw, 4),
            "rolling_avg_loss_pct": round(al, 4),
            "daily_loss_usd_accumulated": round(daily, 2),
            "trade_history_length": len(self._history._records),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_tier_params(self, balance: float) -> tuple[str, float, float]:
        """
        Return (tier_name, max_risk_pct, stop_loss_pct) for the given balance.

        Uses CapitalStrategySelector when available, else built-in defaults.
        """
        if _SELECTOR_AVAILABLE:
            try:
                profile: StrategyProfile = get_strategy_for_balance(balance)
                return profile.name, profile.risk_per_trade_pct, profile.stop_loss_pct
            except Exception as exc:
                logger.warning("CapitalStrategySelector error: %s — using defaults.", exc)

        # ── Built-in fallback tier logic (mirrors capital_strategy_selector) ──
        if balance < 1_000.0:
            return "MICRO", 0.01, 0.008
        elif balance < 10_000.0:
            return "NORMAL", 0.02, 0.012
        else:
            return "ADVANCED", 0.03, 0.015

    def _kelly_size(
        self,
        balance: float,
        win_rate: float,
        avg_win_pct: float,
        avg_loss_pct: float,
    ) -> float:
        """
        Compute fractional-Kelly position size in USD.

        Kelly formula: f* = (W/L − (1−p)) / (W/L)
        where p = win_rate, W = avg_win, L = avg_loss.

        We apply self._kelly_fraction (default 0.25) as a safety margin.
        """
        if avg_loss_pct <= 0:
            return balance * self._atr_risk_pct  # fallback

        win_loss_ratio = avg_win_pct / avg_loss_pct
        kelly_f = (win_loss_ratio * win_rate - (1.0 - win_rate)) / win_loss_ratio
        kelly_f = max(0.0, min(kelly_f, ABSOLUTE_MAX_RISK_PCT))
        fractional_kelly = kelly_f * self._kelly_fraction
        return balance * fractional_kelly

    def _atr_size(
        self,
        balance: float,
        price: float,
        atr: float,
        stop_pct: float,
    ) -> float:
        """
        Compute ATR-based position size.

        Dollar risk  = balance × atr_risk_pct
        Stop distance = price × stop_pct  (or ATR itself when larger)
        Position USD  = dollar_risk / (stop_distance / price)
        """
        if price <= 0 or atr <= 0:
            return balance * self._atr_risk_pct

        dollar_risk = balance * self._atr_risk_pct
        atr_stop_pct = atr / price
        effective_stop = max(stop_pct, atr_stop_pct)
        if effective_stop <= 0:
            return balance * self._atr_risk_pct

        position_usd = dollar_risk / effective_stop
        return min(position_usd, balance)

    def _check_daily_loss(self, balance: float, max_risk_pct: float) -> bool:
        """Return True when daily loss is still within the tier's limit."""
        with self._lock:
            daily_limit = balance * max_risk_pct * 3  # Allow ~3 losing trades/day
            return self._daily_loss_usd < daily_limit


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_engine_instance: Optional[DynamicRiskEngine] = None
_engine_lock = threading.Lock()


def get_dynamic_risk_engine(
    kelly_fraction: float = DEFAULT_KELLY_FRACTION,
    atr_risk_pct: float = DEFAULT_ATR_RISK_PCT,
) -> DynamicRiskEngine:
    """Return (or create) the module-level :class:`DynamicRiskEngine` singleton."""
    global _engine_instance
    with _engine_lock:
        if _engine_instance is None:
            _engine_instance = DynamicRiskEngine(
                kelly_fraction=kelly_fraction,
                atr_risk_pct=atr_risk_pct,
            )
    return _engine_instance


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import logging as _logging

    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s - %(message)s")

    engine = get_dynamic_risk_engine()

    # Simulate trades to populate history
    for i in range(20):
        engine.record_trade(win=(i % 2 == 0), return_pct=0.025, loss_pct=0.012, pnl_usd=-50.0 if i % 2 != 0 else 80.0)

    print("\n=== Dynamic Risk Engine — Position Sizing Demo ===\n")
    scenarios = [
        (200.0, 50_000.0, 800.0, 0.70),    # MICRO   tier
        (1_500.0, 3_000.0, 90.0, 0.85),    # NORMAL  tier
        (15_000.0, 180.0, 5.0, 0.60),      # ADVANCED tier
    ]

    header = f"{'Balance':>10}  {'Tier':<10}  {'Signal':>7}  {'Size USD':>10}  {'Risk USD':>9}  {'Risk%':>7}"
    print(header)
    print("-" * len(header))
    for bal, price, atr, sig in scenarios:
        engine.reset_daily_loss()  # fresh slate per scenario
        r = engine.calculate(balance=bal, current_price=price, atr=atr, signal_strength=sig)
        print(
            f"  ${bal:>8,.0f}  {r.strategy_tier:<10}  {sig:>6.0%}  "
            f"${r.position_size_usd:>9,.2f}  ${r.risk_amount_usd:>8,.2f}  "
            f"{r.risk_pct_of_balance:>6.1%}"
        )

    print("\nEngine status:", engine.get_status())
