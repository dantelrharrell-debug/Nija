"""
NIJA Capital Scaling & Compounding Engine

Main orchestrator that integrates profit compounding, drawdown protection,
and milestone management into a unified capital growth system.

This is the primary interface for the Capital Scaling & Compounding Engine.
It coordinates all three subsystems to provide:
- Automatic profit reinvestment and compound growth
- Drawdown protection and capital preservation
- Milestone tracking and progressive scaling
- Comprehensive capital management reporting

Author: NIJA Trading Systems
Version: 1.0
Date: January 28, 2026
"""

import logging
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

try:
    from profit_compounding_engine import (
        ProfitCompoundingEngine,
        CompoundingStrategy,
        CompoundingConfig
    )
    from drawdown_protection_system import (
        DrawdownProtectionSystem,
        DrawdownConfig,
        ProtectionLevel
    )
    from capital_milestone_manager import (
        CapitalMilestoneManager,
        MilestoneConfig
    )
except ImportError:
    from bot.profit_compounding_engine import (
        ProfitCompoundingEngine,
        CompoundingStrategy,
        CompoundingConfig
    )
    from bot.drawdown_protection_system import (
        DrawdownProtectionSystem,
        DrawdownConfig,
        ProtectionLevel
    )
    from bot.capital_milestone_manager import (
        CapitalMilestoneManager,
        MilestoneConfig
    )

logger = logging.getLogger("nija.capital_engine")


@dataclass
class CapitalEngineConfig:
    """Unified configuration for capital scaling engine"""
    # Compounding settings
    compounding_strategy: str = "moderate"  # conservative/moderate/aggressive/full_compound
    reinvest_percentage: float = 0.75
    preserve_percentage: float = 0.25

    # Drawdown protection settings
    enable_drawdown_protection: bool = True
    halt_threshold_pct: float = 20.0
    warning_threshold_pct: float = 10.0

    # Milestone settings
    enable_milestones: bool = True
    lock_profit_at_milestones: bool = True
    celebrate_achievements: bool = True

    # Position sizing
    enable_dynamic_position_sizing: bool = True
    base_position_pct: float = 0.05  # 5% base position size


class CapitalScalingEngine:
    """
    Unified Capital Scaling & Compounding Engine

    Orchestrates three subsystems:
    1. Profit Compounding Engine - Reinvests profits for exponential growth
    2. Drawdown Protection System - Reduces risk during losses
    3. Capital Milestone Manager - Tracks progress and locks in gains

    Responsibilities:
    - Provide unified interface for capital management
    - Coordinate between subsystems
    - Calculate optimal position sizes
    - Generate comprehensive reporting
    - Track overall capital performance
    """

    def __init__(self, base_capital: float,
                 current_capital: Optional[float] = None,
                 config: Optional[CapitalEngineConfig] = None):
        """
        Initialize Capital Scaling Engine

        Args:
            base_capital: Starting capital amount
            current_capital: Current capital (defaults to base_capital)
            config: Engine configuration (optional)
        """
        self.config = config or CapitalEngineConfig()
        self.base_capital = base_capital
        self.current_capital = current_capital or base_capital

        # Initialize subsystems
        logger.info("🚀 Initializing Capital Scaling & Compounding Engine")

        # 1. Profit Compounding Engine
        compounding_config = CompoundingConfig(
            strategy=CompoundingStrategy(self.config.compounding_strategy),
            reinvest_percentage=self.config.reinvest_percentage,
            preserve_percentage=self.config.preserve_percentage
        )
        self.compounding = ProfitCompoundingEngine(base_capital, compounding_config)

        # 2. Drawdown Protection System
        if self.config.enable_drawdown_protection:
            drawdown_config = DrawdownConfig(
                halt_threshold_pct=self.config.halt_threshold_pct,
                warning_threshold_pct=self.config.warning_threshold_pct
            )
            self.protection = DrawdownProtectionSystem(base_capital, drawdown_config)
        else:
            self.protection = None

        # 3. Capital Milestone Manager
        if self.config.enable_milestones:
            milestone_config = MilestoneConfig(
                enable_profit_locking=self.config.lock_profit_at_milestones,
                celebrate_milestones=self.config.celebrate_achievements
            )
            self.milestones = CapitalMilestoneManager(
                base_capital,
                self.current_capital,
                milestone_config
            )
        else:
            self.milestones = None

        # Update current capital in all subsystems
        if current_capital and current_capital != base_capital:
            self.update_capital(current_capital)

        logger.info("=" * 70)
        logger.info("✅ Capital Scaling Engine Ready")
        logger.info("=" * 70)
        logger.info(f"Base Capital: ${self.base_capital:.2f}")
        logger.info(f"Current Capital: ${self.current_capital:.2f}")
        logger.info(f"Compounding: {self.config.compounding_strategy}")
        logger.info(f"Protection: {'ENABLED' if self.protection else 'DISABLED'}")
        logger.info(f"Milestones: {'ENABLED' if self.milestones else 'DISABLED'}")
        logger.info("=" * 70)

    def record_trade(self, profit: float, fees: float, is_win: bool,
                    new_capital: float):
        """
        Record a completed trade and update all subsystems

        Args:
            profit: Gross profit from trade (before fees)
            fees: Fees paid
            is_win: True if profitable trade
            new_capital: Capital after trade
        """
        # Update compounding engine
        self.compounding.record_trade(profit, fees, is_win)

        # Update drawdown protection
        if self.protection:
            self.protection.record_trade(new_capital, is_win)

        # Update milestones
        if self.milestones:
            self.milestones.update_capital(new_capital)

        # Update current capital
        self.current_capital = new_capital

        logger.info(f"📊 Trade recorded: {'WIN ✅' if is_win else 'LOSS ❌'} | "
                   f"P/L: ${profit - fees:.2f} | Capital: ${new_capital:.2f}")

    def update_capital(self, new_capital: float):
        """
        Update current capital across all subsystems

        Args:
            new_capital: New capital amount
        """
        self.current_capital = new_capital

        # Update all subsystems
        self.compounding.update_balance(new_capital)

        if self.protection:
            self.protection.update_capital(new_capital)

        if self.milestones:
            self.milestones.update_capital(new_capital)

    def get_optimal_position_size(self, available_balance: float) -> float:
        """
        Calculate optimal position size considering all factors

        Factors considered:
        1. Base position percentage from config
        2. Compounding multiplier (grows with profits)
        3. Drawdown protection adjustment (reduces during losses)
        4. Milestone achievement bonus (increases after milestones)

        Args:
            available_balance: Current available balance

        Returns:
            Optimal position size in USD
        """
        # Start with base position
        base_size = available_balance * self.config.base_position_pct

        # Apply compounding multiplier if enabled
        if self.config.enable_dynamic_position_sizing:
            size = self.compounding.get_optimal_position_size(
                self.config.base_position_pct,
                available_balance
            )
        else:
            size = base_size

        # Apply drawdown protection adjustment
        if self.protection:
            size = self.protection.get_adjusted_position_size(size)

        # Apply milestone bonus
        if self.milestones and self.config.enable_dynamic_position_sizing:
            milestone_multiplier = self.milestones.get_position_size_multiplier()
            size *= milestone_multiplier

        # Never exceed available balance
        return min(size, available_balance)

    def can_trade(self) -> Tuple[bool, str]:
        """
        Check if trading is allowed

        Returns:
            Tuple of (can_trade, reason)
        """
        # Check drawdown protection
        if self.protection:
            can_trade, reason = self.protection.can_trade()
            if not can_trade:
                return (False, reason)

        return (True, "Trading allowed")

    def get_capital_status(self) -> Dict:
        """
        Get comprehensive capital status

        Returns:
            Dictionary with all capital metrics
        """
        status = {
            'base_capital': self.base_capital,
            'current_capital': self.current_capital,
            'total_profit': self.current_capital - self.base_capital,
            'roi_pct': self.compounding.get_roi_percentage(),
            'compound_multiplier': self.compounding.get_compound_multiplier(),
            'tradeable_capital': self.compounding.get_tradeable_capital(),
            'preserved_profit': self.compounding.profit_reserve,
        }

        # Add drawdown info if enabled
        if self.protection:
            status['drawdown_pct'] = self.protection.state.drawdown_pct
            status['protection_level'] = self.protection.state.protection_level.value
            status['losing_streak'] = self.protection.state.losing_streak
            status['winning_streak'] = self.protection.state.winning_streak

        # Add milestone info if enabled
        if self.milestones:
            next_milestone = self.milestones.get_next_milestone()
            if next_milestone:
                progress = self.milestones.get_progress_to_next()
                if progress:
                    _, progress_pct, remaining = progress
                    status['next_milestone'] = next_milestone.name
                    status['milestone_target'] = next_milestone.target_amount
                    status['milestone_progress_pct'] = progress_pct
                    status['milestone_remaining'] = remaining

            status['locked_profit'] = self.milestones.get_locked_profit()
            status['milestones_achieved_pct'] = self.milestones.get_achievement_percentage()

        # Add CAGR if available
        if self.compounding.metrics.days_active > 0:
            status['cagr'] = self.compounding.metrics.cagr
            status['daily_growth_rate'] = self.compounding.metrics.daily_growth_rate

        return status

    def get_comprehensive_report(self) -> str:
        """Generate comprehensive capital management report"""
        report = [
            "\n" + "=" * 90,
            "CAPITAL SCALING & COMPOUNDING ENGINE - COMPREHENSIVE REPORT",
            "=" * 90,
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            ""
        ]

        # Overall status
        status = self.get_capital_status()
        can_trade, trade_reason = self.can_trade()

        report.extend([
            "📊 OVERALL STATUS",
            "-" * 90,
            f"  Base Capital:         ${status['base_capital']:>12,.2f}",
            f"  Current Capital:      ${status['current_capital']:>12,.2f}",
            f"  Total Profit:         ${status['total_profit']:>12,.2f}",
            f"  ROI:                  {status['roi_pct']:>12.2f}%",
            f"  Trading Status:       {'ALLOWED ✅' if can_trade else 'BLOCKED ❌'}",
            ""
        ])

        # Add individual subsystem reports
        report.append(self.compounding.get_compounding_report())

        if self.protection:
            report.append(self.protection.get_protection_report())

        if self.milestones:
            report.append(self.milestones.get_milestone_report())

        # Position sizing example
        example_balance = self.current_capital
        optimal_size = self.get_optimal_position_size(example_balance)

        report.extend([
            "💡 POSITION SIZING EXAMPLE",
            "-" * 90,
            f"  Available Balance:    ${example_balance:>12,.2f}",
            f"  Base Position %:      {self.config.base_position_pct*100:>12.1f}%",
            f"  Base Size:            ${example_balance * self.config.base_position_pct:>12,.2f}",
            f"  Optimal Size:         ${optimal_size:>12,.2f}",
            f"  Adjustment Factor:    {optimal_size / (example_balance * self.config.base_position_pct):>12.2f}x",
            ""
        ])

        report.append("=" * 90 + "\n")

        return "\n".join(report)

    def get_quick_summary(self) -> str:
        """Get a quick one-line summary"""
        status = self.get_capital_status()
        can_trade, _ = self.can_trade()

        summary = (
            f"💰 ${status['current_capital']:.2f} "
            f"({status['roi_pct']:+.1f}% ROI) | "
            f"{'✅ TRADING' if can_trade else '❌ HALTED'}"
        )

        if self.protection:
            summary += f" | 🛡️  {status['protection_level'].upper()}"

        if self.milestones and 'next_milestone' in status:
            summary += f" | 🎯 Next: {status['next_milestone']} ({status['milestone_progress_pct']:.0f}%)"

        return summary


def get_capital_engine(base_capital: float,
                      current_capital: Optional[float] = None,
                      strategy: str = "moderate",
                      enable_protection: bool = True,
                      enable_milestones: bool = True) -> CapitalScalingEngine:
    """
    Get or create capital scaling engine instance

    Args:
        base_capital: Starting capital
        current_capital: Current capital (optional)
        strategy: Compounding strategy (conservative/moderate/aggressive/full_compound)
        enable_protection: Enable drawdown protection
        enable_milestones: Enable milestone tracking

    Returns:
        CapitalScalingEngine instance
    """
    config = CapitalEngineConfig(
        compounding_strategy=strategy,
        enable_drawdown_protection=enable_protection,
        enable_milestones=enable_milestones
    )

    return CapitalScalingEngine(base_capital, current_capital, config)


if __name__ == "__main__":
    # Test/demonstration
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s - %(message)s'
    )

    # Create engine with $1000 starting capital
    engine = get_capital_engine(
        base_capital=1000.0,
        strategy="moderate",
        enable_protection=True,
        enable_milestones=True
    )

    print("\n" + "=" * 90)
    print("SIMULATING TRADING ACTIVITY")
    print("=" * 90 + "\n")

    # Simulate some trades
    capital = 1000.0

    # Series of wins
    print("📈 Simulating 5 winning trades...")
    for i in range(5):
        profit = 50.0
        fees = 2.0
        capital += (profit - fees)
        engine.record_trade(profit, fees, is_win=True, new_capital=capital)

    print("\n" + engine.get_quick_summary() + "\n")

    # Series of losses
    print("📉 Simulating 3 losing trades...")
    for i in range(3):
        profit = -30.0
        fees = 1.5
        capital += (profit - fees)
        engine.record_trade(profit, fees, is_win=False, new_capital=capital)

    print("\n" + engine.get_quick_summary() + "\n")

    # Big winner
    print("🚀 Simulating big winning trade...")
    profit = 150.0
    fees = 4.0
    capital += (profit - fees)
    engine.record_trade(profit, fees, is_win=True, new_capital=capital)

    print("\n" + engine.get_quick_summary() + "\n")

    # Generate comprehensive report
    print(engine.get_comprehensive_report())

    # Test position sizing
    print("\n" + "=" * 90)
    print("POSITION SIZING EXAMPLES")
    print("=" * 90)

    available = engine.current_capital
    optimal = engine.get_optimal_position_size(available)

    print(f"\nAvailable Balance: ${available:.2f}")
    print(f"Optimal Position Size: ${optimal:.2f}")
    print(f"Position % of Capital: {(optimal/available)*100:.2f}%")

    can_trade, reason = engine.can_trade()
    print(f"\nCan Trade: {can_trade}")
    print(f"Reason: {reason}")
