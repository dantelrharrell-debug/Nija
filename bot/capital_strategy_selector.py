"""
NIJA Capital Strategy Selector
================================

Automatically selects the appropriate trading strategy profile based on
account capital:

  • < $1,000                 → MICRO   strategy  (ultra-conservative)
  • $1,000 ≤ balance < $10,000 → NORMAL  strategy  (standard)
  • ≥ $10,000                → ADVANCED strategy  (full feature set)

Each strategy profile defines:
  - Risk per trade (%)
  - Maximum concurrent positions
  - Allowed market regimes
  - Compounding aggressiveness
  - Indicator settings (RSI windows, ATR period, etc.)
  - Profit-target / stop-loss ranges
  - Trailing-stop mode

Usage::

    from bot.capital_strategy_selector import get_strategy_for_balance

    profile = get_strategy_for_balance(balance=250.0)
    print(profile.name)               # "MICRO"
    print(profile.risk_per_trade_pct) # 0.01

    # Or use the singleton selector directly:
    from bot.capital_strategy_selector import get_capital_strategy_selector

    selector = get_capital_strategy_selector()
    profile  = selector.select(balance=1500.0)
    print(profile.name)  # "NORMAL"

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger("nija.capital_strategy_selector")


# ---------------------------------------------------------------------------
# Strategy tier enum
# ---------------------------------------------------------------------------

class StrategyTier(str, Enum):
    """Capital-based strategy tiers."""

    MICRO = "MICRO"       # < $1 000
    NORMAL = "NORMAL"     # $1 000 – $9 999
    ADVANCED = "ADVANCED" # ≥ $10 000


# ---------------------------------------------------------------------------
# Strategy profile dataclass
# ---------------------------------------------------------------------------

@dataclass
class StrategyProfile:
    """
    Full configuration profile for a capital tier.

    Attributes:
        tier:                    Which tier this profile belongs to.
        name:                    Human-readable label.
        min_balance:             Minimum balance (USD) to activate this tier.
        max_balance:             Exclusive upper bound (None = no upper limit).
        description:             Plain-English summary.

        risk_per_trade_pct:      Fraction of account at risk per trade (0–1).
        max_positions:           Hard cap on concurrent open positions.
        max_daily_trades:        Maximum trades opened in one calendar day.
        daily_loss_limit_pct:    Stop trading today when daily loss exceeds this
                                 fraction of account (0–1).

        rsi_short_period:        Short RSI window (e.g. RSI-9).
        rsi_long_period:         Long RSI window (e.g. RSI-14).
        rsi_oversold:            RSI level considered oversold.
        rsi_overbought:          RSI level considered overbought.
        atr_period:              ATR period for volatility estimation.

        min_profit_target_pct:   Minimum profit target as % of entry price.
        max_profit_target_pct:   Maximum profit target as % of entry price.
        stop_loss_pct:           Fixed stop-loss as % of entry price.
        use_trailing_stop:       Enable trailing stop instead of fixed stop.
        trailing_stop_pct:       Trailing distance as % of peak price.

        allowed_regimes:         Market regimes this tier may trade in.
        compounding_strategy:    One of "conservative" / "moderate" / "aggressive".
        enable_leverage:         Whether leverage is permitted.
        enable_copy_trading:     Whether copy-trading features are enabled.
        require_high_confidence: Minimum signal quality gate.
    """

    tier: StrategyTier
    name: str
    min_balance: float
    max_balance: Optional[float]
    description: str

    # Risk parameters
    risk_per_trade_pct: float
    max_positions: int
    max_daily_trades: int
    daily_loss_limit_pct: float

    # Indicator settings
    rsi_short_period: int
    rsi_long_period: int
    rsi_oversold: float
    rsi_overbought: float
    atr_period: int

    # Profit / stop targets
    min_profit_target_pct: float
    max_profit_target_pct: float
    stop_loss_pct: float
    use_trailing_stop: bool
    trailing_stop_pct: float

    # Feature flags
    allowed_regimes: List[str]
    compounding_strategy: str
    enable_leverage: bool
    enable_copy_trading: bool
    require_high_confidence: bool

    # ---------------------------------------------------------------------------
    # Derived helpers
    # ---------------------------------------------------------------------------

    def max_position_usd(self, balance: float) -> float:
        """Return the maximum USD value of a single position."""
        return balance * self.risk_per_trade_pct

    def is_active_for_balance(self, balance: float) -> bool:
        """Return True when *balance* falls inside this tier's range."""
        if balance < self.min_balance:
            return False
        if self.max_balance is not None and balance >= self.max_balance:
            return False
        return True

    def to_dict(self) -> Dict:
        """Serialise the profile to a plain dictionary."""
        return {
            "tier": self.tier.value,
            "name": self.name,
            "min_balance": self.min_balance,
            "max_balance": self.max_balance,
            "description": self.description,
            "risk_per_trade_pct": self.risk_per_trade_pct,
            "max_positions": self.max_positions,
            "max_daily_trades": self.max_daily_trades,
            "daily_loss_limit_pct": self.daily_loss_limit_pct,
            "rsi_short_period": self.rsi_short_period,
            "rsi_long_period": self.rsi_long_period,
            "rsi_oversold": self.rsi_oversold,
            "rsi_overbought": self.rsi_overbought,
            "atr_period": self.atr_period,
            "min_profit_target_pct": self.min_profit_target_pct,
            "max_profit_target_pct": self.max_profit_target_pct,
            "stop_loss_pct": self.stop_loss_pct,
            "use_trailing_stop": self.use_trailing_stop,
            "trailing_stop_pct": self.trailing_stop_pct,
            "allowed_regimes": self.allowed_regimes,
            "compounding_strategy": self.compounding_strategy,
            "enable_leverage": self.enable_leverage,
            "enable_copy_trading": self.enable_copy_trading,
            "require_high_confidence": self.require_high_confidence,
        }


# ---------------------------------------------------------------------------
# Built-in strategy profiles
# ---------------------------------------------------------------------------

#: MICRO strategy — accounts below $1,000
MICRO_STRATEGY = StrategyProfile(
    tier=StrategyTier.MICRO,
    name="MICRO",
    min_balance=0.0,
    max_balance=1_000.0,
    description=(
        "Ultra-conservative capital preservation mode for accounts under $1,000. "
        "Single high-confidence positions, tight stops, no leverage."
    ),

    # Risk: 1 % of capital per trade, never more than 2 simultaneous positions
    risk_per_trade_pct=0.01,
    max_positions=2,
    max_daily_trades=5,
    daily_loss_limit_pct=0.03,  # Halt after 3 % daily loss

    # Indicators — standard dual-RSI (9/14)
    rsi_short_period=9,
    rsi_long_period=14,
    rsi_oversold=30.0,
    rsi_overbought=70.0,
    atr_period=14,

    # Tight profit targets / stops
    min_profit_target_pct=0.010,  # 1.0 %
    max_profit_target_pct=0.030,  # 3.0 %
    stop_loss_pct=0.008,          # 0.8 %
    use_trailing_stop=False,
    trailing_stop_pct=0.005,

    # Feature flags
    allowed_regimes=["TRENDING", "RANGING"],
    compounding_strategy="conservative",
    enable_leverage=False,
    enable_copy_trading=False,
    require_high_confidence=True,
)

#: NORMAL strategy — accounts $1,000–$9,999
NORMAL_STRATEGY = StrategyProfile(
    tier=StrategyTier.NORMAL,
    name="NORMAL",
    min_balance=1_000.0,
    max_balance=10_000.0,
    description=(
        "Balanced growth mode for accounts between $1,000 and $10,000. "
        "Moderate risk, trailing stops, moderate compounding."
    ),

    # Risk: 2 % of capital per trade, up to 5 simultaneous positions
    risk_per_trade_pct=0.02,
    max_positions=5,
    max_daily_trades=15,
    daily_loss_limit_pct=0.05,  # Halt after 5 % daily loss

    # Indicators — standard dual-RSI (9/14)
    rsi_short_period=9,
    rsi_long_period=14,
    rsi_oversold=32.0,
    rsi_overbought=68.0,
    atr_period=14,

    # Wider targets with trailing stop
    min_profit_target_pct=0.015,  # 1.5 %
    max_profit_target_pct=0.060,  # 6.0 %
    stop_loss_pct=0.012,          # 1.2 %
    use_trailing_stop=True,
    trailing_stop_pct=0.008,

    # Feature flags
    allowed_regimes=["TRENDING", "RANGING", "VOLATILE", "BREAKOUT"],
    compounding_strategy="moderate",
    enable_leverage=False,
    enable_copy_trading=False,
    require_high_confidence=False,
)

#: ADVANCED strategy — accounts $10,000+
ADVANCED_STRATEGY = StrategyProfile(
    tier=StrategyTier.ADVANCED,
    name="ADVANCED",
    min_balance=10_000.0,
    max_balance=None,   # No upper limit
    description=(
        "Full-feature mode for accounts of $10,000 or more. "
        "Aggressive compounding, wider diversification, full regime coverage."
    ),

    # Risk: 3 % of capital per trade, up to 10 simultaneous positions
    risk_per_trade_pct=0.03,
    max_positions=10,
    max_daily_trades=40,
    daily_loss_limit_pct=0.07,  # Halt after 7 % daily loss

    # Indicators — tighter dual-RSI for more signals
    rsi_short_period=7,
    rsi_long_period=14,
    rsi_oversold=35.0,
    rsi_overbought=65.0,
    atr_period=14,

    # Aggressive targets with trailing stop
    min_profit_target_pct=0.020,  # 2.0 %
    max_profit_target_pct=0.120,  # 12.0 %
    stop_loss_pct=0.015,          # 1.5 %
    use_trailing_stop=True,
    trailing_stop_pct=0.010,

    # Feature flags — all regimes, aggressive compounding
    allowed_regimes=["TRENDING", "RANGING", "VOLATILE", "BREAKOUT", "REVERSAL"],
    compounding_strategy="aggressive",
    enable_leverage=False,   # Leverage opt-in via separate flag
    enable_copy_trading=True,
    require_high_confidence=False,
)

#: Ordered list used for tier resolution (most restrictive first)
_ALL_PROFILES: List[StrategyProfile] = [
    MICRO_STRATEGY,
    NORMAL_STRATEGY,
    ADVANCED_STRATEGY,
]


# ---------------------------------------------------------------------------
# Selector class
# ---------------------------------------------------------------------------

class CapitalStrategySelector:
    """
    Selects and caches the strategy profile appropriate for the current
    account balance.

    Thread-safe singleton — use ``get_capital_strategy_selector()`` rather
    than constructing instances directly.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current_profile: Optional[StrategyProfile] = None
        self._last_balance: float = -1.0

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def select(self, balance: float) -> StrategyProfile:
        """
        Return the :class:`StrategyProfile` that matches *balance*.

        Parameters
        ----------
        balance:
            Current account balance in USD.

        Returns
        -------
        StrategyProfile
            The selected profile.  Falls back to ``MICRO_STRATEGY`` when no
            profile matches (should never happen in normal operation).
        """
        with self._lock:
            selected = self._resolve(balance)

            if self._current_profile is None or selected.tier != self._current_profile.tier:
                prev = self._current_profile.name if self._current_profile else "none"
                logger.info(
                    "🔄 Capital strategy changed: %s → %s  (balance=$%.2f)",
                    prev,
                    selected.name,
                    balance,
                )
                self._current_profile = selected

            self._last_balance = balance
            return selected

    def current_profile(self) -> Optional[StrategyProfile]:
        """Return the most recently selected profile (None if never called)."""
        with self._lock:
            return self._current_profile

    def get_all_profiles(self) -> List[StrategyProfile]:
        """Return a copy of all built-in strategy profiles."""
        return list(_ALL_PROFILES)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve(balance: float) -> StrategyProfile:
        """Pick the highest tier the balance qualifies for."""
        selected = MICRO_STRATEGY  # safe fallback
        for profile in _ALL_PROFILES:
            if profile.is_active_for_balance(balance):
                selected = profile
        return selected


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_selector_instance: Optional[CapitalStrategySelector] = None
_selector_lock = threading.Lock()


def get_capital_strategy_selector() -> CapitalStrategySelector:
    """Return (or create) the module-level :class:`CapitalStrategySelector` singleton."""
    global _selector_instance
    with _selector_lock:
        if _selector_instance is None:
            _selector_instance = CapitalStrategySelector()
    return _selector_instance


def get_strategy_for_balance(balance: float) -> StrategyProfile:
    """
    Convenience function — return the :class:`StrategyProfile` for *balance*.

    Equivalent to::

        get_capital_strategy_selector().select(balance)
    """
    return get_capital_strategy_selector().select(balance)


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import logging as _logging

    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s - %(message)s")

    test_balances = [50.0, 100.0, 500.0, 999.99, 1_000.0, 5_000.0, 9_999.99, 10_000.0, 50_000.0]

    print("\n{'Balance':>12}  {'Tier':<10}  {'Risk/Trade':>10}  {'Max Pos':>8}  Compounding")
    print("-" * 65)
    for bal in test_balances:
        p = get_strategy_for_balance(bal)
        print(
            f"  ${bal:>10,.2f}  {p.name:<10}  {p.risk_per_trade_pct*100:>9.1f}%"
            f"  {p.max_positions:>8}  {p.compounding_strategy}"
        )
