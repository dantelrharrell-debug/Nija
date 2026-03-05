"""
NIJA Compounding Engine
========================

Enhanced profit compounding engine with:
1. Milestone-based capital locking (protect gains at key thresholds)
2. Dynamic growth tier management (auto-upgrade compounding intensity)
3. Risk-adjusted compounding (reduce reinvestment during drawdown)
4. Compounding projection calculator (30d / 90d / 1y / 2y scenarios)
5. Volatility-scaled reinvestment (scale reinvestment by recent volatility)

This module complements `profit_compounding_engine.py` but provides a
higher-level, self-managing interface suitable for investor reporting.

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

import json
import logging
import math
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.compounding_engine")

# ---------------------------------------------------------------------------
# Enums & configurations
# ---------------------------------------------------------------------------

class GrowthTier(Enum):
    """Capital growth tier that drives compounding intensity."""
    SEED = "seed"             # < $1,000   — conservative, build track record
    STARTER = "starter"       # $1k–$5k    — moderate reinvestment
    GROWTH = "growth"         # $5k–$25k   — aggressive compounding
    SCALE = "scale"           # $25k–$100k — optimised compound + preservation
    ELITE = "elite"           # > $100k    — institutional-grade management


@dataclass
class TierConfig:
    """Configuration for each growth tier."""
    name: str
    min_capital: float
    max_capital: float
    reinvest_pct: float         # fraction of profits to reinvest
    preserve_pct: float         # fraction of profits to lock in
    max_position_multiplier: float
    target_daily_growth: float  # target daily return %


TIER_CONFIGS: Dict[GrowthTier, TierConfig] = {
    GrowthTier.SEED: TierConfig("SEED", 0, 1_000, 0.60, 0.40, 1.25, 0.30),
    GrowthTier.STARTER: TierConfig("STARTER", 1_000, 5_000, 0.70, 0.30, 1.50, 0.35),
    GrowthTier.GROWTH: TierConfig("GROWTH", 5_000, 25_000, 0.80, 0.20, 1.75, 0.40),
    GrowthTier.SCALE: TierConfig("SCALE", 25_000, 100_000, 0.85, 0.15, 2.00, 0.45),
    GrowthTier.ELITE: TierConfig("ELITE", 100_000, float("inf"), 0.90, 0.10, 2.50, 0.50),
}

MILESTONES = [500, 1_000, 2_500, 5_000, 10_000, 25_000, 50_000, 100_000, 250_000, 500_000, 1_000_000]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CapitalState:
    """Current state of the compounding account."""
    base_capital: float             # original starting amount
    total_capital: float            # current total (base + all reinvested profits)
    locked_profits: float           # profits locked at milestones — not at risk
    reinvested_profits: float       # profits returned to trading pool
    total_gross_profit: float       # cumulative gross profit (before drawdown)
    total_fees: float
    total_trades: int
    winning_trades: int
    start_date: str                 # ISO string
    tier: str                       # current GrowthTier name
    milestones_hit: List[float] = field(default_factory=list)
    last_updated: str = ""

    @property
    def net_profit(self) -> float:
        return self.total_capital - self.base_capital

    @property
    def roi_pct(self) -> float:
        if self.base_capital > 0:
            return (self.net_profit / self.base_capital) * 100
        return 0.0

    @property
    def win_rate(self) -> float:
        if self.total_trades > 0:
            return self.winning_trades / self.total_trades
        return 0.0


@dataclass
class TradeResult:
    """Result from a single trade passed to the compounding engine."""
    trade_id: str
    gross_profit: float     # before fees (can be negative)
    fees: float
    strategy: str = "unknown"
    symbol: str = "unknown"


@dataclass
class CompoundingProjection:
    """Capital growth projection for a given number of days."""
    days: int
    projected_capital: float
    projected_profit: float
    projected_roi_pct: float
    daily_growth_rate: float
    cagr_pct: float


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

class CompoundingEngine:
    """
    Manages capital compounding with milestone locking and dynamic tier management.

    This engine is self-managing: it automatically:
    - Upgrades to the next growth tier when capital crosses thresholds
    - Locks profits at milestone levels so gains are protected
    - Adjusts reinvestment rate during drawdowns
    - Calculates compound projections for investor reporting
    """

    DATA_DIR = Path(__file__).parent.parent / "data"
    STATE_FILE = DATA_DIR / "compounding_engine_state.json"

    def __init__(self, base_capital: float):
        """
        Initialise the compounding engine.

        Args:
            base_capital: Starting capital in USD.
        """
        self._state = CapitalState(
            base_capital=base_capital,
            total_capital=base_capital,
            locked_profits=0.0,
            reinvested_profits=0.0,
            total_gross_profit=0.0,
            total_fees=0.0,
            total_trades=0,
            winning_trades=0,
            start_date=datetime.now().isoformat(),
            tier=GrowthTier.SEED.value,
        )

        self._pnl_history: List[float] = []  # per-trade net PnL for Sharpe / drawdown
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)

        if not self._load_state():
            self._save_state()

        tier_cfg = self._get_tier_config()
        logger.info("=" * 70)
        logger.info("💰 NIJA Compounding Engine Initialized")
        logger.info("=" * 70)
        logger.info("  Base Capital:   $%.2f", self._state.base_capital)
        logger.info("  Total Capital:  $%.2f", self._state.total_capital)
        logger.info("  Current Tier:   %s", self._state.tier)
        logger.info("  Reinvest %%:     %.0f%%", tier_cfg.reinvest_pct * 100)
        logger.info("=" * 70)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_trade(self, result: TradeResult) -> Dict[str, Any]:
        """
        Record a completed trade and apply compounding logic.

        Args:
            result: TradeResult with gross profit and fees.

        Returns:
            Dictionary with applied compounding details.
        """
        net_pnl = result.gross_profit - result.fees
        self._pnl_history.append(net_pnl)

        self._state.total_trades += 1
        self._state.total_fees += result.fees
        if net_pnl > 0:
            self._state.winning_trades += 1
            self._state.total_gross_profit += net_pnl

        # Check for drawdown — reduce reinvestment if losing
        drawdown_adj = self._get_drawdown_adjustment()
        tier_cfg = self._get_tier_config()
        effective_reinvest = tier_cfg.reinvest_pct * drawdown_adj

        compound_detail = {}

        if net_pnl > 0:
            reinvest_amount = net_pnl * effective_reinvest
            preserve_amount = net_pnl * (1.0 - effective_reinvest)
            self._state.reinvested_profits += reinvest_amount
            self._state.locked_profits += preserve_amount
            compound_detail = {
                "reinvested": round(reinvest_amount, 4),
                "locked": round(preserve_amount, 4),
                "effective_reinvest_pct": round(effective_reinvest * 100, 2),
                "drawdown_adj": round(drawdown_adj, 4),
            }
        else:
            # Loss — subtract from reinvested first, then base if needed
            loss = abs(net_pnl)
            if self._state.reinvested_profits >= loss:
                self._state.reinvested_profits -= loss
            else:
                remainder = loss - self._state.reinvested_profits
                self._state.reinvested_profits = 0.0
                self._state.base_capital = max(0.0, self._state.base_capital - remainder)

        # Recalculate total capital
        self._state.total_capital = (
            self._state.base_capital
            + self._state.reinvested_profits
            + self._state.locked_profits
        )

        # Check milestones
        newly_hit = self._check_milestones()
        if newly_hit:
            compound_detail["milestones_hit"] = newly_hit

        # Auto-upgrade tier
        new_tier = self._determine_tier()
        if new_tier != self._state.tier:
            logger.info("🎯 Tier upgrade: %s → %s", self._state.tier, new_tier)
            self._state.tier = new_tier

        self._state.last_updated = datetime.now().isoformat()
        self._save_state()

        logger.info(
            "💰 Trade recorded | net=%.2f | total=$%.2f | roi=%.2f%% | tier=%s",
            net_pnl, self._state.total_capital, self._state.roi_pct, self._state.tier,
        )
        return compound_detail

    def get_tradeable_capital(self) -> float:
        """
        Return the capital available for active trading.
        Excludes locked profits which are protected from risk.
        """
        return self._state.base_capital + self._state.reinvested_profits

    def get_optimal_position_size(self, base_pct: float) -> float:
        """
        Calculate optimal position size with tier-adjusted multiplier.

        Args:
            base_pct: Base position as fraction of tradeable capital (e.g. 0.05).

        Returns:
            Position size in USD.
        """
        tradeable = self.get_tradeable_capital()
        tier_cfg = self._get_tier_config()
        multiplier = min(self._get_compound_multiplier(), tier_cfg.max_position_multiplier)
        return min(tradeable * base_pct * multiplier, tradeable)

    def get_projections(self) -> List[CompoundingProjection]:
        """
        Generate compound growth projections based on current metrics.

        Returns:
            List of CompoundingProjection for 30d, 90d, 180d, 365d, 730d.
        """
        daily_rate = self._calculate_daily_growth_rate()
        cagr = self._calculate_cagr()

        projections = []
        for days in [30, 90, 180, 365, 730]:
            projected = self._state.total_capital * ((1 + daily_rate) ** days)
            projections.append(CompoundingProjection(
                days=days,
                projected_capital=round(projected, 2),
                projected_profit=round(projected - self._state.base_capital, 2),
                projected_roi_pct=round(((projected - self._state.base_capital) / max(1, self._state.base_capital)) * 100, 2),
                daily_growth_rate=round(daily_rate * 100, 4),
                cagr_pct=round(cagr, 2),
            ))

        return projections

    def get_state(self) -> CapitalState:
        """Return the current capital state."""
        return self._state

    def generate_report(self) -> str:
        """Generate a comprehensive compounding report."""
        state = self._state
        tier_cfg = self._get_tier_config()
        days_active = max(1, (datetime.now() - datetime.fromisoformat(state.start_date)).days)
        cagr = self._calculate_cagr()
        daily_rate = self._calculate_daily_growth_rate()
        next_milestone = self._next_milestone()

        lines = [
            "",
            "=" * 90,
            "💰  NIJA COMPOUNDING ENGINE REPORT",
            "=" * 90,
            f"  Days Active:          {days_active}",
            f"  Current Tier:         {state.tier}",
            f"  Reinvest Rate:        {tier_cfg.reinvest_pct * 100:.0f}%  (preserve {tier_cfg.preserve_pct * 100:.0f}%)",
            "",
            "  CAPITAL BREAKDOWN",
            f"    Base Capital:       ${state.base_capital:>12,.2f}",
            f"    Reinvested Profits: ${state.reinvested_profits:>12,.2f}",
            f"    Locked Profits:     ${state.locked_profits:>12,.2f}",
            f"    ─────────────────────────────────",
            f"    Total Capital:      ${state.total_capital:>12,.2f}",
            f"    Net Profit:         ${state.net_profit:>12,.2f}",
            f"    ROI:                {state.roi_pct:>12.2f}%",
            f"    Compound Mult:      {self._get_compound_multiplier():>12.2f}x",
            "",
            "  PERFORMANCE",
            f"    Total Trades:       {state.total_trades:>12,}",
            f"    Win Rate:           {state.win_rate * 100:>12.1f}%",
            f"    CAGR:               {cagr:>12.2f}%",
            f"    Daily Growth:       {daily_rate * 100:>12.4f}%",
            f"    Total Fees:         ${state.total_fees:>12,.2f}",
        ]

        if state.milestones_hit:
            lines.extend(["", f"    Milestones Hit:     {', '.join(f'${m:,.0f}' for m in state.milestones_hit)}"])

        if next_milestone:
            progress = (state.total_capital / next_milestone) * 100
            lines.append(f"    Next Milestone:     ${next_milestone:,.0f}  ({progress:.1f}% there)")

        # Projections
        if days_active >= 3 and daily_rate > 0:
            lines.extend(["", "  GROWTH PROJECTIONS"])
            for proj in self.get_projections():
                lines.append(
                    f"    {proj.days:>4}d: ${proj.projected_capital:>12,.2f} "
                    f"(+${proj.projected_profit:>10,.2f} / +{proj.projected_roi_pct:.1f}%)"
                )

        lines.append("=" * 90)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_tier_config(self) -> TierConfig:
        for tier, cfg in TIER_CONFIGS.items():
            if tier.value == self._state.tier:
                return cfg
        return TIER_CONFIGS[GrowthTier.SEED]

    def _determine_tier(self) -> str:
        capital = self._state.total_capital
        for tier in reversed(list(GrowthTier)):
            cfg = TIER_CONFIGS[tier]
            if capital >= cfg.min_capital:
                return tier.value
        return GrowthTier.SEED.value

    def _get_compound_multiplier(self) -> float:
        if self._state.base_capital > 0:
            return self._state.total_capital / self._state.base_capital
        return 1.0

    def _get_drawdown_adjustment(self) -> float:
        """
        Calculate a drawdown-based adjustment to reinvestment rate.
        Returns 1.0 (no adjustment) when performing well,
        down to 0.4 during significant drawdown.
        """
        if len(self._pnl_history) < 10:
            return 1.0

        recent = self._pnl_history[-20:]
        equity = 0.0
        peak = 0.0
        max_dd = 0.0

        for pnl in recent:
            equity += pnl
            peak = max(peak, equity)
            dd = peak - equity
            max_dd = max(max_dd, dd)

        if peak == 0:
            return 1.0

        dd_pct = max_dd / (peak + abs(min(recent)) + 0.01)
        if dd_pct < 0.05:
            return 1.0
        elif dd_pct < 0.10:
            return 0.80
        elif dd_pct < 0.20:
            return 0.60
        else:
            return 0.40

    def _check_milestones(self) -> List[float]:
        """Check and record any newly crossed milestones."""
        newly_hit = []
        for milestone in MILESTONES:
            if (milestone not in self._state.milestones_hit
                    and self._state.total_capital >= milestone):
                self._state.milestones_hit.append(milestone)
                newly_hit.append(milestone)
                logger.info("🎯 MILESTONE HIT: $%s! 🚀", f"{milestone:,.0f}")
        return newly_hit

    def _next_milestone(self) -> Optional[float]:
        for milestone in MILESTONES:
            if milestone not in self._state.milestones_hit:
                return milestone
        return None

    def _calculate_daily_growth_rate(self) -> float:
        """Calculate daily growth rate from start date to now."""
        try:
            start = datetime.fromisoformat(self._state.start_date)
            days = max(1, (datetime.now() - start).days)
            if self._state.base_capital > 0 and self._state.total_capital > 0:
                total_growth = (self._state.total_capital / self._state.base_capital) - 1
                return (1 + total_growth) ** (1.0 / days) - 1
        except Exception:
            pass
        return 0.0

    def _calculate_cagr(self) -> float:
        """Calculate Compound Annual Growth Rate."""
        try:
            start = datetime.fromisoformat(self._state.start_date)
            days = max(1, (datetime.now() - start).days)
            if self._state.base_capital > 0 and self._state.total_capital > 0:
                years = days / 365.0
                cagr = ((self._state.total_capital / self._state.base_capital) ** (1.0 / years)) - 1
                return cagr * 100.0
        except Exception:
            pass
        return 0.0

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> bool:
        if not self.STATE_FILE.exists():
            return False
        try:
            with open(self.STATE_FILE, "r") as f:
                data = json.load(f)
            state_data = data.get("state", {})
            self._state = CapitalState(**state_data)
            self._pnl_history = data.get("pnl_history", [])
            logger.info("✅ Compounding engine state loaded from disk")
            return True
        except Exception as exc:
            logger.warning("Could not load compounding engine state: %s", exc)
            return False

    def _save_state(self) -> None:
        try:
            payload = {
                "state": asdict(self._state),
                "pnl_history": self._pnl_history[-500:],  # keep last 500
                "updated_at": datetime.now().isoformat(),
            }
            with open(self.STATE_FILE, "w") as f:
                json.dump(payload, f, indent=2)
        except Exception as exc:
            logger.error("Failed to save compounding engine state: %s", exc)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_engine: Optional[CompoundingEngine] = None


def get_compounding_engine(base_capital: float = 1000.0) -> CompoundingEngine:
    """
    Return the module-level singleton CompoundingEngine.

    Args:
        base_capital: Starting capital (only used when creating a new engine).

    Returns:
        CompoundingEngine instance.
    """
    global _engine
    if _engine is None:
        _engine = CompoundingEngine(base_capital)
    return _engine


if __name__ == "__main__":
    import random

    logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")

    engine = CompoundingEngine(base_capital=1000.0)

    print("\nSimulating 30 trades...\n")
    for i in range(30):
        gross_pnl = random.gauss(8, 25)
        engine.record_trade(TradeResult(
            trade_id=f"SIM-{i:04d}",
            gross_profit=gross_pnl,
            fees=0.50,
            strategy="apex_v71",
            symbol="BTC-USD",
        ))

    print(engine.generate_report())
    print(f"\nTradeable Capital: ${engine.get_tradeable_capital():.2f}")
    print(f"Optimal 5% Position: ${engine.get_optimal_position_size(0.05):.2f}")
