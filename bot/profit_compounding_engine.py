"""
NIJA Profit Compounding Engine

Automatically reinvests profits to achieve exponential capital growth.
Tracks profit vs. base capital, calculates compound growth rates, and
optimizes position sizing as the account grows.

Key Features:
- Separation of base capital vs. profit reserves
- Automatic profit reinvestment strategies
- Compound Annual Growth Rate (CAGR) tracking
- Profit allocation between risk/preservation
- Integration with tier-based capital management

Author: NIJA Trading Systems
Version: 1.0
Date: January 28, 2026
"""

import logging
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import json
from pathlib import Path

logger = logging.getLogger("nija.compounding")


class CompoundingStrategy(Enum):
    """Profit compounding strategies"""
    CONSERVATIVE = "conservative"  # 50% reinvest, 50% preserve
    MODERATE = "moderate"  # 75% reinvest, 25% preserve
    AGGRESSIVE = "aggressive"  # 90% reinvest, 10% preserve
    FULL_COMPOUND = "full_compound"  # 100% reinvest


@dataclass
class CompoundingConfig:
    """Configuration for profit compounding"""
    strategy: CompoundingStrategy = CompoundingStrategy.MODERATE
    reinvest_percentage: float = 0.75  # % of profits to reinvest
    preserve_percentage: float = 0.25  # % of profits to preserve
    min_profit_to_compound: float = 10.0  # Minimum profit to trigger compounding
    max_position_size_multiplier: float = 2.0  # Max position size vs base capital
    enable_milestone_locking: bool = True  # Lock in gains at milestones
    

@dataclass
class CapitalSnapshot:
    """Snapshot of capital state at a point in time"""
    timestamp: datetime
    base_capital: float  # Original starting capital
    total_capital: float  # Current total (base + profits)
    profit_reserve: float  # Preserved profits (not at risk)
    reinvested_profits: float  # Profits reinvested in trading
    total_profit: float  # All-time profit
    compound_multiplier: float  # Current capital / base capital
    
    @property
    def roi_percentage(self) -> float:
        """Return on Investment percentage"""
        if self.base_capital == 0:
            return 0.0
        return (self.total_profit / self.base_capital) * 100


@dataclass
class CompoundingMetrics:
    """Performance metrics for compounding"""
    days_active: int = 0
    total_trades: int = 0
    winning_trades: int = 0
    total_profit: float = 0.0
    total_fees: float = 0.0
    net_profit: float = 0.0
    cagr: float = 0.0  # Compound Annual Growth Rate
    daily_growth_rate: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    
    def calculate_cagr(self, base_capital: float, current_capital: float, 
                      days_active: int) -> float:
        """
        Calculate Compound Annual Growth Rate
        
        Formula: CAGR = ((Ending Value / Beginning Value) ^ (365/Days)) - 1
        """
        if base_capital == 0 or days_active == 0:
            return 0.0
        
        if current_capital <= 0:
            return -100.0  # Total loss
        
        growth_multiplier = current_capital / base_capital
        years = days_active / 365.0
        
        if years <= 0:
            return 0.0
        
        cagr = (growth_multiplier ** (1 / years)) - 1
        return cagr * 100  # Return as percentage


class ProfitCompoundingEngine:
    """
    Manages profit compounding and capital growth
    
    Responsibilities:
    1. Track base capital vs. profit separately
    2. Apply compounding strategy to profits
    3. Calculate compound growth metrics
    4. Optimize position sizing based on growth
    5. Protect capital during drawdowns
    """
    
    # Data persistence
    DATA_DIR = Path(__file__).parent.parent / "data"
    COMPOUNDING_FILE = DATA_DIR / "compounding_state.json"
    
    def __init__(self, base_capital: float, 
                 config: Optional[CompoundingConfig] = None):
        """
        Initialize Profit Compounding Engine
        
        Args:
            base_capital: Starting capital amount
            config: Compounding configuration (optional)
        """
        self.config = config or CompoundingConfig()
        
        # Capital tracking
        self.base_capital = base_capital
        self.total_capital = base_capital
        self.profit_reserve = 0.0  # Preserved profits
        self.reinvested_profits = 0.0  # Profits reinvested
        
        # Performance tracking
        self.metrics = CompoundingMetrics()
        self.start_date = datetime.now()
        
        # History tracking
        self.snapshots: List[CapitalSnapshot] = []
        
        # Ensure data directory exists
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        
        # Load existing state or initialize
        if not self._load_state():
            self._save_snapshot("initialization")
        
        logger.info("=" * 70)
        logger.info("💰 Profit Compounding Engine Initialized")
        logger.info("=" * 70)
        logger.info(f"Base Capital: ${self.base_capital:.2f}")
        logger.info(f"Strategy: {self.config.strategy.value}")
        logger.info(f"Reinvest: {self.config.reinvest_percentage*100:.0f}%")
        logger.info(f"Preserve: {self.config.preserve_percentage*100:.0f}%")
        logger.info("=" * 70)
    
    def _load_state(self) -> bool:
        """Load state from persistent storage"""
        if not self.COMPOUNDING_FILE.exists():
            return False
        
        try:
            with open(self.COMPOUNDING_FILE, 'r') as f:
                data = json.load(f)
            
            self.base_capital = data['base_capital']
            self.total_capital = data['total_capital']
            self.profit_reserve = data['profit_reserve']
            self.reinvested_profits = data['reinvested_profits']
            self.start_date = datetime.fromisoformat(data['start_date'])
            
            # Load metrics
            metrics_data = data.get('metrics', {})
            self.metrics = CompoundingMetrics(**metrics_data)
            
            logger.info(f"✅ Loaded compounding state from {self.COMPOUNDING_FILE}")
            return True
        except Exception as e:
            logger.warning(f"Failed to load compounding state: {e}")
            return False
    
    def _save_state(self):
        """Save state to persistent storage"""
        try:
            data = {
                'base_capital': self.base_capital,
                'total_capital': self.total_capital,
                'profit_reserve': self.profit_reserve,
                'reinvested_profits': self.reinvested_profits,
                'start_date': self.start_date.isoformat(),
                'last_updated': datetime.now().isoformat(),
                'metrics': {
                    'days_active': self.metrics.days_active,
                    'total_trades': self.metrics.total_trades,
                    'winning_trades': self.metrics.winning_trades,
                    'total_profit': self.metrics.total_profit,
                    'total_fees': self.metrics.total_fees,
                    'net_profit': self.metrics.net_profit,
                    'cagr': self.metrics.cagr,
                    'daily_growth_rate': self.metrics.daily_growth_rate,
                    'win_rate': self.metrics.win_rate,
                    'profit_factor': self.metrics.profit_factor,
                }
            }
            
            with open(self.COMPOUNDING_FILE, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.debug("💾 Compounding state saved")
        except Exception as e:
            logger.error(f"Failed to save compounding state: {e}")
    
    def _save_snapshot(self, event: str):
        """Save a capital snapshot"""
        snapshot = CapitalSnapshot(
            timestamp=datetime.now(),
            base_capital=self.base_capital,
            total_capital=self.total_capital,
            profit_reserve=self.profit_reserve,
            reinvested_profits=self.reinvested_profits,
            total_profit=self.total_capital - self.base_capital,
            compound_multiplier=self.total_capital / self.base_capital if self.base_capital > 0 else 1.0
        )
        
        self.snapshots.append(snapshot)
        
        # Keep only last 1000 snapshots to prevent unbounded growth
        if len(self.snapshots) > 1000:
            self.snapshots = self.snapshots[-1000:]
        
        logger.debug(f"📸 Capital snapshot saved: {event}")
    
    def record_trade(self, profit: float, fees: float, is_win: bool):
        """
        Record a completed trade and update metrics
        
        Args:
            profit: Gross profit from trade (before fees)
            fees: Fees paid for trade
            is_win: True if trade was profitable
        """
        net_profit = profit - fees
        
        # Update metrics
        self.metrics.total_trades += 1
        if is_win:
            self.metrics.winning_trades += 1
        
        self.metrics.total_profit += profit
        self.metrics.total_fees += fees
        self.metrics.net_profit += net_profit
        
        # Calculate win rate
        if self.metrics.total_trades > 0:
            self.metrics.win_rate = (self.metrics.winning_trades / self.metrics.total_trades) * 100
        
        # Update total capital
        self.total_capital += net_profit
        
        # Apply compounding strategy if profit threshold met
        if net_profit >= self.config.min_profit_to_compound:
            self._compound_profit(net_profit)
        
        # Update CAGR
        days_active = (datetime.now() - self.start_date).days
        self.metrics.days_active = max(1, days_active)  # Minimum 1 day
        self.metrics.cagr = self.metrics.calculate_cagr(
            self.base_capital,
            self.total_capital,
            self.metrics.days_active
        )
        
        # Calculate daily growth rate
        if self.metrics.days_active > 0:
            total_growth = (self.total_capital / self.base_capital) - 1
            self.metrics.daily_growth_rate = (total_growth / self.metrics.days_active) * 100
        
        self._save_state()
        
        logger.info(f"📊 Trade Recorded: P/L=${net_profit:.2f}, Win={is_win}")
        logger.info(f"   Total Capital: ${self.total_capital:.2f} ({self.get_roi_percentage():.2f}% ROI)")
    
    def _compound_profit(self, net_profit: float):
        """
        Apply compounding strategy to profit
        
        Args:
            net_profit: Net profit to compound
        """
        # Calculate amounts based on strategy
        reinvest_amount = net_profit * self.config.reinvest_percentage
        preserve_amount = net_profit * self.config.preserve_percentage
        
        # Update tracking
        self.reinvested_profits += reinvest_amount
        self.profit_reserve += preserve_amount
        
        logger.info(f"💰 Compounding Profit: ${net_profit:.2f}")
        logger.info(f"   Reinvested: ${reinvest_amount:.2f} ({self.config.reinvest_percentage*100:.0f}%)")
        logger.info(f"   Preserved: ${preserve_amount:.2f} ({self.config.preserve_percentage*100:.0f}%)")
        logger.info(f"   Total Reinvested: ${self.reinvested_profits:.2f}")
        logger.info(f"   Total Preserved: ${self.profit_reserve:.2f}")
        
        self._save_snapshot("profit_compounded")
    
    def get_tradeable_capital(self) -> float:
        """
        Get capital available for trading (base + reinvested profits)
        
        Returns:
            Tradeable capital in USD
        """
        return self.base_capital + self.reinvested_profits
    
    def get_roi_percentage(self) -> float:
        """Get return on investment percentage"""
        if self.base_capital == 0:
            return 0.0
        total_profit = self.total_capital - self.base_capital
        return (total_profit / self.base_capital) * 100
    
    def get_compound_multiplier(self) -> float:
        """Get capital growth multiplier (current / base)"""
        if self.base_capital == 0:
            return 1.0
        return self.total_capital / self.base_capital
    
    def get_optimal_position_size(self, base_position_pct: float, 
                                  available_balance: float) -> float:
        """
        Calculate optimal position size with compounding adjustment
        
        Args:
            base_position_pct: Base position size as % (e.g., 0.05 for 5%)
            available_balance: Current available balance
            
        Returns:
            Optimal position size in USD
        """
        # Calculate base position
        base_position = available_balance * base_position_pct
        
        # Apply compound multiplier (but cap at max)
        multiplier = min(self.get_compound_multiplier(), self.config.max_position_size_multiplier)
        
        # Adjusted position size
        adjusted_position = base_position * multiplier
        
        # Never exceed available balance
        return min(adjusted_position, available_balance)
    
    def get_compounding_report(self) -> str:
        """Generate detailed compounding report"""
        report = [
            "\n" + "=" * 90,
            "PROFIT COMPOUNDING & CAPITAL GROWTH REPORT",
            "=" * 90,
            f"Strategy: {self.config.strategy.value.upper()}",
            f"Days Active: {self.metrics.days_active}",
            ""
        ]
        
        # Capital breakdown
        total_profit = self.total_capital - self.base_capital
        report.extend([
            "💰 CAPITAL BREAKDOWN",
            "-" * 90,
            f"  Base Capital:         ${self.base_capital:>12,.2f}",
            f"  Reinvested Profits:   ${self.reinvested_profits:>12,.2f}",
            f"  Preserved Profits:    ${self.profit_reserve:>12,.2f}",
            f"  ────────────────────────────────────",
            f"  Total Capital:        ${self.total_capital:>12,.2f}",
            f"  Total Profit:         ${total_profit:>12,.2f}",
            f"  ROI:                  {self.get_roi_percentage():>12.2f}%",
            f"  Compound Multiplier:  {self.get_compound_multiplier():>12.2f}x",
            ""
        ])
        
        # Trading metrics
        report.extend([
            "📊 TRADING PERFORMANCE",
            "-" * 90,
            f"  Total Trades:         {self.metrics.total_trades:>12,}",
            f"  Winning Trades:       {self.metrics.winning_trades:>12,}",
            f"  Win Rate:             {self.metrics.win_rate:>12.2f}%",
            f"  Gross Profit:         ${self.metrics.total_profit:>12,.2f}",
            f"  Total Fees:           ${self.metrics.total_fees:>12,.2f}",
            f"  Net Profit:           ${self.metrics.net_profit:>12,.2f}",
            ""
        ])
        
        # Growth metrics
        report.extend([
            "📈 COMPOUND GROWTH METRICS",
            "-" * 90,
            f"  CAGR:                 {self.metrics.cagr:>12.2f}%",
            f"  Daily Growth Rate:    {self.metrics.daily_growth_rate:>12.4f}%",
            f"  Capital Velocity:     ${self.metrics.net_profit / max(1, self.metrics.days_active):>12.2f}/day",
            ""
        ])
        
        # Compounding strategy
        report.extend([
            "⚙️  COMPOUNDING STRATEGY",
            "-" * 90,
            f"  Reinvest %:           {self.config.reinvest_percentage*100:>12.0f}%",
            f"  Preserve %:           {self.config.preserve_percentage*100:>12.0f}%",
            f"  Min Profit Threshold: ${self.config.min_profit_to_compound:>12,.2f}",
            f"  Max Position Multiplier: {self.config.max_position_size_multiplier:>12.1f}x",
            ""
        ])
        
        # Projections (if positive growth)
        if self.metrics.cagr > 0 and self.metrics.days_active >= 7:
            # Project 30, 90, 365 days forward
            for days in [30, 90, 365]:
                future_capital = self.total_capital * ((1 + self.metrics.cagr/100) ** (days/365))
                future_profit = future_capital - self.base_capital
                report.append(f"  Projected {days:3d} days:  ${future_capital:>12,.2f} (+${future_profit:>10,.2f})")
        
        report.append("=" * 90 + "\n")
        
        return "\n".join(report)
    
    def update_balance(self, new_balance: float):
        """
        Update total capital with new balance
        
        Args:
            new_balance: New total balance
        """
        old_balance = self.total_capital
        self.total_capital = new_balance
        
        # Recalculate profit components
        total_profit = new_balance - self.base_capital
        
        logger.debug(f"💰 Balance updated: ${old_balance:.2f} → ${new_balance:.2f}")
        self._save_state()


def get_compounding_engine(base_capital: float,
                          strategy: str = "moderate") -> ProfitCompoundingEngine:
    """
    Get or create profit compounding engine instance
    
    Args:
        base_capital: Starting capital
        strategy: Compounding strategy (conservative/moderate/aggressive/full_compound)
        
    Returns:
        ProfitCompoundingEngine instance
    """
    strategy_enum = CompoundingStrategy(strategy.lower())
    
    # Create config based on strategy
    if strategy_enum == CompoundingStrategy.CONSERVATIVE:
        config = CompoundingConfig(
            strategy=strategy_enum,
            reinvest_percentage=0.50,
            preserve_percentage=0.50
        )
    elif strategy_enum == CompoundingStrategy.MODERATE:
        config = CompoundingConfig(
            strategy=strategy_enum,
            reinvest_percentage=0.75,
            preserve_percentage=0.25
        )
    elif strategy_enum == CompoundingStrategy.AGGRESSIVE:
        config = CompoundingConfig(
            strategy=strategy_enum,
            reinvest_percentage=0.90,
            preserve_percentage=0.10
        )
    else:  # FULL_COMPOUND
        config = CompoundingConfig(
            strategy=strategy_enum,
            reinvest_percentage=1.00,
            preserve_percentage=0.00
        )
    
    return ProfitCompoundingEngine(base_capital, config)


if __name__ == "__main__":
    # Test/demonstration
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s - %(message)s'
    )
    
    # Create engine with $1000 base capital
    engine = get_compounding_engine(1000.0, "moderate")
    
    # Simulate some trades
    print("\nSimulating trades...\n")
    
    # Winning trade: $50 profit, $2 fees
    engine.record_trade(profit=50.0, fees=2.0, is_win=True)
    
    # Winning trade: $30 profit, $1.5 fees
    engine.record_trade(profit=30.0, fees=1.5, is_win=True)
    
    # Losing trade: -$20 loss, $1 fees
    engine.record_trade(profit=-20.0, fees=1.0, is_win=False)
    
    # Big winner: $100 profit, $3 fees
    engine.record_trade(profit=100.0, fees=3.0, is_win=True)
    
    # Print report
    print(engine.get_compounding_report())
    
    # Test position sizing
    print("\nPosition Sizing Examples:")
    print(f"5% of ${engine.get_tradeable_capital():.2f} = ${engine.get_optimal_position_size(0.05, engine.get_tradeable_capital()):.2f}")
    print(f"10% of ${engine.get_tradeable_capital():.2f} = ${engine.get_optimal_position_size(0.10, engine.get_tradeable_capital()):.2f}")
