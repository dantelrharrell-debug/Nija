"""
NIJA Smart Scaling Engine
==========================

Centrally implements all growth-focused scaling rules described in the NIJA
Scaling Road-map (March 2026):

  Step 1 — Dynamic Position Sizing
      position_size = max(min_position_size,
                          deployable_capital × position_size_pct)

      Tier table (keeps growth aggressive early, safer later):
        Balance $50  – $100 : 30 %
        Balance $100 – $250 : 25 %
        Balance $250 – $500 : 22 %
        Balance $500 – $1000: 20 %
        Balance $1000+      : 18 %  (leverage unlocked at this tier)

  Step 2 — Profit Recycling (aggressive but controlled)
      if trade_profit_pct > 2 %:
          reinvest 80 % back into trading
          lock    20 % in reserve
      Prevents giving back gains and emotional drawdowns.

  Step 3 — Loss Control (anti-blowup)
      max_loss_per_trade   = 2 % of balance
      max_daily_drawdown   = 6 %
      If daily_drawdown >= 6 % → trading is HALTED for the rest of the day.

  Step 4 — Auto Position Unlock (scaling trades)
      balance >= $150 → max_positions = 4
      balance >= $300 → max_positions = 5
      balance >= $600 → max_positions = 6
      (below $150 defaults to the base-level 3 positions)

  Step 5 — Smart Profit Mode
      if daily_profit_pct >= 5 %:
          reduce position size by 50 %
      Locks in green days; prevents giving it all back.

  AI Aggression Mode
      When the rolling win-rate exceeds WIN_RATE_HIGH_THRESHOLD (60 %),
      the engine enables "aggression mode" which applies a multiplier > 1.0
      to the position size (bounded by AGGRESSION_MAX_MULTIPLIER = 1.25).
      In trending markets the multiplier is further boosted by
      TREND_AGGRESSION_BOOST (0.10 additional).
      When win-rate is below WIN_RATE_LOW_THRESHOLD (45 %) the engine
      applies a conservative de-risk multiplier (0.75) to protect capital.

Usage
-----
    from bot.smart_scaling_engine import get_smart_scaling_engine

    engine = get_smart_scaling_engine()

    # After each trade close:
    engine.record_trade(pnl_usd=2.50, is_win=True, balance=75.0)
    engine.update_daily_pnl(daily_pnl_usd=3.80, balance=75.0)

    # Before sizing a new position:
    result = engine.calculate_position_size(balance=75.0)
    if not result.can_trade:
        return {'action': 'hold', 'reason': result.reason}
    size_usd = result.position_size_usd

    # Profit recycling decision after a winning trade:
    recycling = engine.apply_profit_recycling(profit_usd=2.50, balance=75.0)
    # recycling.reinvest_usd  → amount to put back into trading
    # recycling.lock_usd      → amount to lock in reserve

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("nija.smart_scaling")

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

# Position-size percentage tiers (fraction of deployable capital)
POSITION_SIZE_TIER_MICRO    = 0.30   # $50  – <$100
POSITION_SIZE_TIER_SMALL    = 0.25   # $100 – <$250
POSITION_SIZE_TIER_MID      = 0.22   # $250 – <$500
POSITION_SIZE_TIER_GROWTH   = 0.20   # $500 – <$1000
POSITION_SIZE_TIER_ELITE    = 0.18   # $1000+

# Minimum absolute position size in USD (safety floor)
MIN_POSITION_SIZE_USD       = 5.00

# Auto position-unlock thresholds
POS_UNLOCK_TIER_4           = 150.0   # balance >= $150 → 4 concurrent positions
POS_UNLOCK_TIER_5           = 300.0   # balance >= $300 → 5 concurrent positions
POS_UNLOCK_TIER_6           = 600.0   # balance >= $600 → 6 concurrent positions
BASE_MAX_POSITIONS          = 3       # default below $150

# Drawdown / loss control
MAX_LOSS_PER_TRADE_PCT      = 0.02    # 2 % of balance per trade
MAX_DAILY_DRAWDOWN_PCT      = 0.06    # 6 % → halt trading for the day

# Profit recycling
PROFIT_RECYCLING_THRESHOLD  = 0.02    # only applies when profit > 2 % of balance
REINVEST_FRACTION           = 0.80    # 80 % back into trading
LOCK_FRACTION               = 0.20    # 20 % locked in reserve

# Smart profit mode
SMART_PROFIT_MODE_THRESHOLD = 0.05    # 5 % daily profit → halve position size
SMART_PROFIT_SIZE_MULTIPLIER= 0.50    # reduce by 50 %

# AI aggression thresholds (based on rolling win-rate)
WIN_RATE_HIGH_THRESHOLD     = 0.60    # >= 60 % win-rate → aggression mode
WIN_RATE_LOW_THRESHOLD      = 0.45    # <= 45 % win-rate → de-risk mode
AGGRESSION_MULTIPLIER       = 1.20    # baseline aggression boost
AGGRESSION_MAX_MULTIPLIER   = 1.25    # hard cap on aggression multiplier
TREND_AGGRESSION_BOOST      = 0.10    # extra boost in trending markets
DE_RISK_MULTIPLIER          = 0.75    # multiplier when win-rate is low

# Minimum trades before aggression mode can activate
MIN_TRADES_FOR_AGGRESSION   = 10


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PositionSizeResult:
    """Result of a position-sizing calculation."""
    can_trade: bool
    position_size_usd: float
    position_size_pct: float      # fraction of balance used
    balance: float
    tier_label: str               # human-readable tier name
    aggression_multiplier: float  # 1.0 = neutral; >1 aggressive; <1 de-risk
    smart_profit_active: bool     # True when daily profit >= 5 %
    daily_drawdown_halt: bool     # True when halted due to drawdown
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ProfitRecyclingResult:
    """Result of a profit-recycling decision."""
    applied: bool               # True when the 2 % rule was triggered
    profit_usd: float
    reinvest_usd: float         # 80 % — goes back into trading
    lock_usd: float             # 20 % — locked in reserve
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class SmartScalingEngine:
    """
    Orchestrates dynamic position sizing, AI aggression mode, profit
    recycling, drawdown halts, and smart profit mode.

    Thread-safe singleton — obtain via ``get_smart_scaling_engine()``.
    """

    DATA_DIR   = Path(__file__).parent.parent / "data"
    STATE_FILE = DATA_DIR / "smart_scaling_state.json"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)

        # Rolling win-rate tracking
        self._total_trades: int = 0
        self._wins: int = 0

        # Daily state
        self._today: str = str(date.today())
        self._daily_pnl_usd: float = 0.0
        self._daily_start_balance: float = 0.0
        self._daily_halted: bool = False  # True when drawdown >= 6 %

        self._load_state()

        logger.info("=" * 60)
        logger.info("🚀 SmartScalingEngine initialised")
        logger.info("   Position tiers  : 30%% <$100 | 25%% <$250 | 22%% <$500 | 20%% <$1000 | 18%% $1000+")
        logger.info("   Max positions   : 3 base | 4 @$150 | 5 @$300 | 6 @$600")
        logger.info("   Daily drawdown  : halt at %.0f%%", MAX_DAILY_DRAWDOWN_PCT * 100)
        logger.info("   Profit recycling: reinvest %.0f%% / lock %.0f%% when profit >%.0f%%",
                    REINVEST_FRACTION * 100, LOCK_FRACTION * 100, PROFIT_RECYCLING_THRESHOLD * 100)
        logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_daily_pnl(self, daily_pnl_usd: float, balance: float) -> None:
        """
        Update today's cumulative P&L and check if the daily drawdown limit
        has been breached.

        Call this after every trade close or balance update.

        Args:
            daily_pnl_usd: Net profit/loss since the start of today (negative = loss).
            balance:        Current account balance in USD.
        """
        with self._lock:
            self._maybe_reset_day(balance)
            self._daily_pnl_usd = daily_pnl_usd

            if not self._daily_halted and self._daily_start_balance > 0:
                drawdown_pct = -daily_pnl_usd / self._daily_start_balance
                if drawdown_pct >= MAX_DAILY_DRAWDOWN_PCT:
                    self._daily_halted = True
                    logger.warning(
                        "🛑 DAILY DRAWDOWN HALT: drawdown=%.1f%% (>= %.0f%%). "
                        "Trading suspended for the rest of the day.",
                        drawdown_pct * 100, MAX_DAILY_DRAWDOWN_PCT * 100,
                    )

            self._save_state()

    def record_trade(self, pnl_usd: float, is_win: bool, balance: float) -> None:
        """
        Record a completed trade for win-rate tracking.

        Args:
            pnl_usd:  Realised P&L in USD.
            is_win:   True when the trade was profitable.
            balance:  Account balance after the trade.
        """
        with self._lock:
            self._maybe_reset_day(balance)
            self._total_trades += 1
            if is_win:
                self._wins += 1
            self._save_state()

    def calculate_position_size(
        self,
        balance: float,
        is_trending_market: bool = False,
    ) -> PositionSizeResult:
        """
        Calculate the recommended position size for a new trade.

        Applies (in order):
          1. Balance-tier position percentage
          2. AI aggression / de-risk multiplier
          3. Smart profit mode 50 % reduction
          4. Daily drawdown halt gate

        Args:
            balance:           Current account balance in USD.
            is_trending_market: When True, trending-market boost is applied
                               if aggression mode is active.

        Returns:
            PositionSizeResult with size recommendation and metadata.
        """
        with self._lock:
            self._maybe_reset_day(balance)

            # ── Gate: daily drawdown halt ───────────────────────────────
            if self._daily_halted:
                return PositionSizeResult(
                    can_trade=False,
                    position_size_usd=0.0,
                    position_size_pct=0.0,
                    balance=balance,
                    tier_label="HALTED",
                    aggression_multiplier=0.0,
                    smart_profit_active=False,
                    daily_drawdown_halt=True,
                    reason=(
                        f"🛑 Daily drawdown halt active — drawdown exceeded "
                        f"{MAX_DAILY_DRAWDOWN_PCT * 100:.0f}%. "
                        "Trading resumes tomorrow."
                    ),
                )

            # ── Step 1: Balance-tier position percentage ────────────────
            base_pct, tier_label = self._get_position_pct(balance)

            # ── Step 2: AI aggression / de-risk multiplier ──────────────
            aggression_mult = self._get_aggression_multiplier(is_trending_market)

            # ── Step 3: Compute raw size ────────────────────────────────
            raw_size = max(
                MIN_POSITION_SIZE_USD,
                balance * base_pct * aggression_mult,
            )

            # ── Step 4: Smart profit mode ───────────────────────────────
            smart_profit_active = False
            if self._daily_start_balance > 0:
                daily_profit_pct = self._daily_pnl_usd / self._daily_start_balance
                if daily_profit_pct >= SMART_PROFIT_MODE_THRESHOLD:
                    raw_size *= SMART_PROFIT_SIZE_MULTIPLIER
                    smart_profit_active = True
                    logger.info(
                        "🟡 Smart Profit Mode: daily profit=%.1f%% (>=%.0f%%) → position halved",
                        daily_profit_pct * 100, SMART_PROFIT_MODE_THRESHOLD * 100,
                    )

            # Cap to balance (never risk more than available)
            final_size = min(raw_size, balance)
            final_pct  = final_size / balance if balance > 0 else 0.0

            logger.debug(
                "SmartScaling: balance=$%.2f tier=%s base_pct=%.0f%% "
                "aggr=%.2f smart_profit=%s → size=$%.2f",
                balance, tier_label, base_pct * 100,
                aggression_mult, smart_profit_active, final_size,
            )

            return PositionSizeResult(
                can_trade=True,
                position_size_usd=round(final_size, 2),
                position_size_pct=round(final_pct, 4),
                balance=balance,
                tier_label=tier_label,
                aggression_multiplier=round(aggression_mult, 3),
                smart_profit_active=smart_profit_active,
                daily_drawdown_halt=False,
                reason="OK",
            )

    def get_max_positions(self, balance: float) -> int:
        """
        Return the maximum number of concurrent positions for this balance.

        Scaling rule:
          balance >= $600 → 6
          balance >= $300 → 5
          balance >= $150 → 4
          below $150     → 3 (base)

        Args:
            balance: Current account balance in USD.

        Returns:
            Maximum concurrent positions (int).
        """
        if balance >= POS_UNLOCK_TIER_6:
            return 6
        if balance >= POS_UNLOCK_TIER_5:
            return 5
        if balance >= POS_UNLOCK_TIER_4:
            return 4
        return BASE_MAX_POSITIONS

    def apply_profit_recycling(
        self,
        profit_usd: float,
        balance: float,
    ) -> ProfitRecyclingResult:
        """
        Apply the 80/20 profit-recycling rule.

        Rule:
          if trade_profit_pct > 2 %:
              reinvest_usd = profit_usd × 80 %
              lock_usd     = profit_usd × 20 %

        Args:
            profit_usd: Realised profit from a single trade (USD, must be > 0).
            balance:    Account balance *before* the profit was added.

        Returns:
            ProfitRecyclingResult with reinvest / lock breakdown.
        """
        if profit_usd <= 0 or balance <= 0:
            return ProfitRecyclingResult(
                applied=False,
                profit_usd=profit_usd,
                reinvest_usd=profit_usd,
                lock_usd=0.0,
                reason="No positive profit to recycle.",
            )

        profit_pct = profit_usd / balance
        if profit_pct <= PROFIT_RECYCLING_THRESHOLD:
            return ProfitRecyclingResult(
                applied=False,
                profit_usd=profit_usd,
                reinvest_usd=profit_usd,
                lock_usd=0.0,
                reason=(
                    f"Profit {profit_pct * 100:.2f}% <= "
                    f"{PROFIT_RECYCLING_THRESHOLD * 100:.0f}% threshold — "
                    "full profit recycled (no lock)."
                ),
            )

        reinvest = round(profit_usd * REINVEST_FRACTION, 2)
        lock     = round(profit_usd * LOCK_FRACTION,     2)

        logger.info(
            "♻️  Profit Recycling: profit=$%.2f (%.1f%%) → "
            "reinvest=$%.2f | lock=$%.2f",
            profit_usd, profit_pct * 100, reinvest, lock,
        )

        return ProfitRecyclingResult(
            applied=True,
            profit_usd=profit_usd,
            reinvest_usd=reinvest,
            lock_usd=lock,
            reason=(
                f"Profit {profit_pct * 100:.2f}% > "
                f"{PROFIT_RECYCLING_THRESHOLD * 100:.0f}% threshold — "
                f"reinvest ${reinvest:.2f} (80%) | lock ${lock:.2f} (20%)."
            ),
        )

    def get_max_loss_per_trade(self, balance: float) -> float:
        """Return the maximum allowable loss per trade in USD (2% of balance)."""
        return round(balance * MAX_LOSS_PER_TRADE_PCT, 2)

    def is_daily_halt_active(self) -> bool:
        """Return True when trading is halted due to the daily drawdown limit."""
        with self._lock:
            self._maybe_reset_day()
            return self._daily_halted

    def get_win_rate(self) -> float:
        """Return the rolling win-rate (0.0 – 1.0)."""
        with self._lock:
            if self._total_trades == 0:
                return 0.0
            return self._wins / self._total_trades

    def is_aggression_mode_active(self) -> bool:
        """Return True when the win-rate qualifies for aggression mode."""
        return (
            self._total_trades >= MIN_TRADES_FOR_AGGRESSION
            and self.get_win_rate() >= WIN_RATE_HIGH_THRESHOLD
        )

    def get_report(self) -> str:
        """Return a human-readable status report."""
        with self._lock:
            wr    = self.get_win_rate()
            agg   = self.is_aggression_mode_active()
            lines = [
                "",
                "=" * 60,
                "  NIJA SMART SCALING ENGINE STATUS",
                "=" * 60,
                f"  Date              : {self._today}",
                f"  Daily P&L         : ${self._daily_pnl_usd:>+10.2f}",
                f"  Daily Halt        : {'YES 🛑' if self._daily_halted else 'no ✅'}",
                f"  Trades (total)    : {self._total_trades}",
                f"  Win-rate          : {wr * 100:.1f}%",
                f"  Aggression Mode   : {'ACTIVE ⚡' if agg else 'standby'}",
                "=" * 60,
                "",
            ]
            return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_position_pct(balance: float) -> tuple[float, str]:
        """Return (position_pct, tier_label) for the given balance."""
        if balance < 100.0:
            return POSITION_SIZE_TIER_MICRO,  "MICRO (<$100)"
        if balance < 250.0:
            return POSITION_SIZE_TIER_SMALL,  "SMALL ($100-$250)"
        if balance < 500.0:
            return POSITION_SIZE_TIER_MID,    "MID ($250-$500)"
        if balance < 1000.0:
            return POSITION_SIZE_TIER_GROWTH, "GROWTH ($500-$1000)"
        return    POSITION_SIZE_TIER_ELITE,   "ELITE ($1000+)"

    def _get_aggression_multiplier(self, is_trending: bool) -> float:
        """Return the AI aggression / de-risk multiplier based on win-rate."""
        if self._total_trades < MIN_TRADES_FOR_AGGRESSION:
            return 1.0  # not enough data yet

        wr = self._wins / self._total_trades

        if wr >= WIN_RATE_HIGH_THRESHOLD:
            mult = AGGRESSION_MULTIPLIER
            if is_trending:
                mult = min(AGGRESSION_MAX_MULTIPLIER, mult + TREND_AGGRESSION_BOOST)
            logger.debug(
                "⚡ Aggression mode ACTIVE (win-rate=%.1f%%) → multiplier=%.2f",
                wr * 100, mult,
            )
            return mult

        if wr <= WIN_RATE_LOW_THRESHOLD:
            logger.debug(
                "🛡️  De-risk mode ACTIVE (win-rate=%.1f%%) → multiplier=%.2f",
                wr * 100, DE_RISK_MULTIPLIER,
            )
            return DE_RISK_MULTIPLIER

        return 1.0  # neutral zone

    def _maybe_reset_day(self, balance: float = 0.0) -> None:
        """Reset daily counters if a new calendar day has started."""
        today = str(date.today())
        if today != self._today:
            logger.info(
                "📅 SmartScalingEngine: new day (%s) — resetting daily state.", today
            )
            self._today = today
            self._daily_pnl_usd = 0.0
            self._daily_halted  = False
            if balance > 0:
                self._daily_start_balance = balance
            self._save_state()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        try:
            data = {
                "today":               self._today,
                "daily_pnl_usd":       self._daily_pnl_usd,
                "daily_start_balance": self._daily_start_balance,
                "daily_halted":        self._daily_halted,
                "total_trades":        self._total_trades,
                "wins":                self._wins,
            }
            with open(self.STATE_FILE, "w") as fh:
                json.dump(data, fh, indent=2)
        except Exception as exc:
            logger.error("Failed to save SmartScalingEngine state: %s", exc)

    def _load_state(self) -> None:
        if not self.STATE_FILE.exists():
            return
        try:
            with open(self.STATE_FILE, "r") as fh:
                data = json.load(fh)

            self._total_trades        = data.get("total_trades", 0)
            self._wins                = data.get("wins", 0)

            saved_date = data.get("today", "")
            today      = str(date.today())
            if saved_date == today:
                self._today               = today
                self._daily_pnl_usd       = data.get("daily_pnl_usd", 0.0)
                self._daily_start_balance = data.get("daily_start_balance", 0.0)
                self._daily_halted        = data.get("daily_halted", False)
            else:
                # Stale — keep all-time trade counts, reset daily state
                self._today               = today
                self._daily_pnl_usd       = 0.0
                self._daily_halted        = False

            logger.info(
                "✅ SmartScalingEngine state loaded "
                "(trades=%d wins=%d halt=%s)",
                self._total_trades, self._wins, self._daily_halted,
            )
        except Exception as exc:
            logger.warning("Failed to load SmartScalingEngine state: %s", exc)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_engine_instance: Optional[SmartScalingEngine] = None
_engine_lock = threading.Lock()


def get_smart_scaling_engine() -> SmartScalingEngine:
    """
    Return the process-wide SmartScalingEngine singleton.

    Thread-safe; the instance is created on the first call.
    """
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = SmartScalingEngine()
    return _engine_instance
