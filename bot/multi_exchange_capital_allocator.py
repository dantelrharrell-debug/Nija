"""
NIJA Multi-Exchange Capital Allocation Manager
Splits capital across exchanges to smooth drawdowns and optimize performance

Features:
- Dynamic capital allocation across exchanges
- Drawdown smoothing through diversification
- Performance-based rebalancing
- Risk-adjusted position sizing per exchange
- Automatic rebalancing triggers

Version: 1.0
Author: NIJA Trading Systems
"""

import logging
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
import json

from exchange_risk_profiles import ExchangeType, get_exchange_risk_manager

logger = logging.getLogger("nija.capital_allocator")


@dataclass
class ExchangeAllocation:
    """Capital allocation for a single exchange"""
    exchange: ExchangeType
    target_allocation_pct: float  # Target % of total capital
    current_allocation_pct: float  # Current actual %
    allocated_capital_usd: float  # USD allocated
    available_balance_usd: float  # USD available for trading
    in_positions_usd: float  # USD currently in positions
    total_pnl_usd: float  # Cumulative P&L
    total_trades: int  # Total trades on exchange
    win_rate: float = 0.0  # Win rate (0-1)
    avg_profit_per_trade: float = 0.0
    sharpe_ratio: Optional[float] = None
    max_drawdown_pct: float = 0.0
    last_rebalance: Optional[datetime] = None

    @property
    def utilization_pct(self) -> float:
        """Calculate capital utilization percentage"""
        if self.allocated_capital_usd == 0:
            return 0.0
        return (self.in_positions_usd / self.allocated_capital_usd) * 100.0

    @property
    def roi_pct(self) -> float:
        """Calculate ROI percentage"""
        if self.allocated_capital_usd == 0:
            return 0.0
        return (self.total_pnl_usd / self.allocated_capital_usd) * 100.0


@dataclass
class AllocationStrategy:
    """Capital allocation strategy configuration"""
    # Target allocations per exchange (must sum to 1.0)
    target_allocations: Dict[ExchangeType, float]

    # Rebalancing thresholds
    rebalance_threshold_pct: float = 10.0  # Rebalance if drift > 10%
    min_days_between_rebalance: int = 7  # Minimum 7 days between rebalances

    # Performance-based adjustments
    enable_performance_weighting: bool = True
    performance_adjustment_pct: float = 5.0  # Max 5% shift based on performance

    # Risk management
    max_single_exchange_pct: float = 0.50  # Max 50% on any exchange
    min_single_exchange_pct: float = 0.10  # Min 10% on any exchange

    # Drawdown protection
    reduce_allocation_on_drawdown_pct: float = 15.0  # Reduce if drawdown > 15%
    drawdown_reduction_amount_pct: float = 25.0  # Reduce by 25%


class MultiExchangeCapitalAllocator:
    """
    Manages capital allocation across multiple exchanges

    Strategies:
    1. Equal Weight: Distribute capital equally
    2. Risk-Adjusted: Weight by inverse volatility
    3. Performance-Weighted: Increase allocation to better performers
    4. Custom: User-defined weights
    """

    # Default allocation strategies
    EQUAL_WEIGHT_STRATEGY = "equal_weight"
    RISK_ADJUSTED_STRATEGY = "risk_adjusted"
    PERFORMANCE_WEIGHTED_STRATEGY = "performance_weighted"
    CONSERVATIVE_STRATEGY = "conservative"

    # Data persistence
    DATA_DIR = Path(__file__).parent.parent / "data"
    ALLOCATION_FILE = DATA_DIR / "capital_allocation.json"

    def __init__(self, total_capital_usd: float,
                 strategy_name: str = EQUAL_WEIGHT_STRATEGY):
        """
        Initialize Multi-Exchange Capital Allocator

        Args:
            total_capital_usd: Total capital available across all exchanges
            strategy_name: Allocation strategy to use
        """
        self.total_capital_usd = total_capital_usd
        self.strategy_name = strategy_name
        self.allocations: Dict[ExchangeType, ExchangeAllocation] = {}
        self.risk_manager = get_exchange_risk_manager()

        # Ensure data directory exists
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)

        # Load existing state or initialize
        if not self._load_state():
            self._initialize_allocations()

        logger.info("=" * 70)
        logger.info("💰 Multi-Exchange Capital Allocator Initialized")
        logger.info("=" * 70)
        logger.info(f"Total Capital: ${self.total_capital_usd:.2f}")
        logger.info(f"Strategy: {strategy_name}")
        logger.info(f"Active Exchanges: {len(self.allocations)}")
        logger.info("=" * 70)

    def _load_state(self) -> bool:
        """Load state from persistent storage"""
        if not self.ALLOCATION_FILE.exists():
            return False

        try:
            with open(self.ALLOCATION_FILE, 'r') as f:
                data = json.load(f)

            self.total_capital_usd = data['total_capital_usd']
            self.strategy_name = data['strategy_name']

            self.allocations = {}
            for exchange_str, alloc_data in data['allocations'].items():
                exchange = ExchangeType(exchange_str)
                alloc_data['exchange'] = exchange
                # Convert datetime strings back
                if alloc_data.get('last_rebalance'):
                    alloc_data['last_rebalance'] = datetime.fromisoformat(
                        alloc_data['last_rebalance']
                    )
                self.allocations[exchange] = ExchangeAllocation(**alloc_data)

            logger.info(f"✅ Loaded allocation state from {self.ALLOCATION_FILE}")
            return True
        except Exception as e:
            logger.warning(f"Failed to load allocation state: {e}")
            return False

    def _save_state(self):
        """Save state to persistent storage"""
        try:
            data = {
                'total_capital_usd': self.total_capital_usd,
                'strategy_name': self.strategy_name,
                'last_updated': datetime.now().isoformat(),
                'allocations': {}
            }

            for exchange, alloc in self.allocations.items():
                alloc_dict = {
                    'exchange': exchange.value,
                    'target_allocation_pct': alloc.target_allocation_pct,
                    'current_allocation_pct': alloc.current_allocation_pct,
                    'allocated_capital_usd': alloc.allocated_capital_usd,
                    'available_balance_usd': alloc.available_balance_usd,
                    'in_positions_usd': alloc.in_positions_usd,
                    'total_pnl_usd': alloc.total_pnl_usd,
                    'total_trades': alloc.total_trades,
                    'win_rate': alloc.win_rate,
                    'avg_profit_per_trade': alloc.avg_profit_per_trade,
                    'sharpe_ratio': alloc.sharpe_ratio,
                    'max_drawdown_pct': alloc.max_drawdown_pct,
                    'last_rebalance': alloc.last_rebalance.isoformat() if alloc.last_rebalance else None
                }
                data['allocations'][exchange.value] = alloc_dict

            with open(self.ALLOCATION_FILE, 'w') as f:
                json.dump(data, f, indent=2)

            logger.debug("💾 Allocation state saved")
        except Exception as e:
            logger.error(f"Failed to save allocation state: {e}")

    def _initialize_allocations(self):
        """Initialize allocations based on strategy"""
        logger.info(f"🆕 Initializing {self.strategy_name} allocation strategy")

        if self.strategy_name == self.EQUAL_WEIGHT_STRATEGY:
            self._initialize_equal_weight()
        elif self.strategy_name == self.RISK_ADJUSTED_STRATEGY:
            self._initialize_risk_adjusted()
        elif self.strategy_name == self.CONSERVATIVE_STRATEGY:
            self._initialize_conservative()
        else:
            # Default to equal weight
            self._initialize_equal_weight()

        self._save_state()

    def _initialize_equal_weight(self):
        """Initialize with equal weight across exchanges"""
        # Only use exchanges that are actually available/configured
        active_exchanges = [
            ExchangeType.COINBASE,  # Primary
            ExchangeType.OKX,       # Secondary
        ]

        weight_per_exchange = 1.0 / len(active_exchanges)

        for exchange in active_exchanges:
            allocated = self.total_capital_usd * weight_per_exchange
            self.allocations[exchange] = ExchangeAllocation(
                exchange=exchange,
                target_allocation_pct=weight_per_exchange * 100,
                current_allocation_pct=weight_per_exchange * 100,
                allocated_capital_usd=allocated,
                available_balance_usd=allocated,
                in_positions_usd=0.0,
                total_pnl_usd=0.0,
                total_trades=0,
                last_rebalance=datetime.now()
            )

    def _initialize_risk_adjusted(self):
        """Initialize with risk-adjusted weights (inverse volatility)"""
        active_exchanges = [ExchangeType.COINBASE, ExchangeType.OKX]

        # Get risk scores (lower is better)
        risk_scores = {}
        for exchange in active_exchanges:
            profile = self.risk_manager.get_profile(exchange)
            risk_scores[exchange] = profile.risk_score

        # Inverse weighting (lower risk = higher weight)
        max_risk = max(risk_scores.values())
        inverse_weights = {ex: (max_risk - score + 1) for ex, score in risk_scores.items()}
        total_weight = sum(inverse_weights.values())

        for exchange in active_exchanges:
            weight = inverse_weights[exchange] / total_weight
            allocated = self.total_capital_usd * weight
            self.allocations[exchange] = ExchangeAllocation(
                exchange=exchange,
                target_allocation_pct=weight * 100,
                current_allocation_pct=weight * 100,
                allocated_capital_usd=allocated,
                available_balance_usd=allocated,
                in_positions_usd=0.0,
                total_pnl_usd=0.0,
                total_trades=0,
                last_rebalance=datetime.now()
            )

    def _initialize_conservative(self):
        """Initialize with conservative allocation (favor safest exchanges)"""
        # Conservative: 70% Coinbase, 30% OKX
        allocations = {
            ExchangeType.COINBASE: 0.70,
            ExchangeType.OKX: 0.30,
        }

        for exchange, weight in allocations.items():
            allocated = self.total_capital_usd * weight
            self.allocations[exchange] = ExchangeAllocation(
                exchange=exchange,
                target_allocation_pct=weight * 100,
                current_allocation_pct=weight * 100,
                allocated_capital_usd=allocated,
                available_balance_usd=allocated,
                in_positions_usd=0.0,
                total_pnl_usd=0.0,
                total_trades=0,
                last_rebalance=datetime.now()
            )

    def get_allocation(self, exchange: ExchangeType) -> Optional[ExchangeAllocation]:
        """Get allocation for an exchange"""
        return self.allocations.get(exchange)

    def update_balance(self, exchange: ExchangeType,
                      available_balance: float,
                      in_positions: float):
        """
        Update actual balances for an exchange

        Args:
            exchange: Exchange type
            available_balance: Available USD balance
            in_positions: USD value in open positions
        """
        if exchange not in self.allocations:
            logger.warning(f"Exchange {exchange} not in allocations")
            return

        alloc = self.allocations[exchange]
        alloc.available_balance_usd = available_balance
        alloc.in_positions_usd = in_positions
        alloc.allocated_capital_usd = available_balance + in_positions
        alloc.current_allocation_pct = (alloc.allocated_capital_usd / self.total_capital_usd) * 100

        self._save_state()

    def update_total_capital(self, new_total_capital: float):
        """
        Update total capital and rebalance allocations proportionally

        Args:
            new_total_capital: New total capital amount in USD
        """
        if new_total_capital <= 0:
            logger.warning(f"Invalid total capital: ${new_total_capital:.2f}")
            return

        old_total = self.total_capital_usd
        self.total_capital_usd = new_total_capital

        # Recalculate current allocation percentages based on new total
        for alloc in self.allocations.values():
            if old_total > 0:
                alloc.current_allocation_pct = (alloc.allocated_capital_usd / new_total_capital) * 100

        logger.info(f"💰 Updated total capital: ${old_total:.2f} → ${new_total_capital:.2f}")
        self._save_state()

    def record_trade(self, exchange: ExchangeType, pnl: float, is_win: bool):
        """
        Record a completed trade for performance tracking

        Args:
            exchange: Exchange where trade occurred
            pnl: Profit/loss in USD
            is_win: True if profitable trade
        """
        if exchange not in self.allocations:
            return

        alloc = self.allocations[exchange]
        alloc.total_trades += 1
        alloc.total_pnl_usd += pnl

        # Update win rate (running average)
        old_wins = alloc.win_rate * (alloc.total_trades - 1)
        new_wins = old_wins + (1.0 if is_win else 0.0)
        alloc.win_rate = new_wins / alloc.total_trades

        # Update average profit
        alloc.avg_profit_per_trade = alloc.total_pnl_usd / alloc.total_trades

        self._save_state()

    def check_rebalancing_needed(self) -> Tuple[bool, str]:
        """
        Check if rebalancing is needed

        Returns:
            Tuple of (needs_rebalance, reason)
        """
        max_drift = 0.0
        drift_exchange = None

        for exchange, alloc in self.allocations.items():
            drift = abs(alloc.current_allocation_pct - alloc.target_allocation_pct)
            if drift > max_drift:
                max_drift = drift
                drift_exchange = exchange

        # Check drift threshold
        if max_drift > 10.0:  # 10% drift threshold
            return True, f"{drift_exchange.value} drifted {max_drift:.1f}% from target"

        # Check time since last rebalance
        for alloc in self.allocations.values():
            if alloc.last_rebalance:
                days_since = (datetime.now() - alloc.last_rebalance).days
                if days_since > 30:  # Monthly rebalance
                    return True, f"{days_since} days since last rebalance"

        return False, "No rebalancing needed"

    def get_optimal_position_size(self, exchange: ExchangeType,
                                  base_position_pct: float) -> float:
        """
        Get optimal position size for exchange considering allocation

        Args:
            exchange: Exchange type
            base_position_pct: Base position size as % of account

        Returns:
            Position size in USD
        """
        alloc = self.get_allocation(exchange)
        if not alloc:
            return 0.0

        # Get exchange-specific adjustment
        profile = self.risk_manager.get_profile(exchange)
        adjusted_size = profile.get_adjusted_position_size(
            base_position_pct,
            alloc.available_balance_usd
        )

        # Ensure we don't exceed exchange max exposure
        max_exposure_usd = alloc.allocated_capital_usd * (profile.max_total_exposure_pct)
        remaining_exposure = max_exposure_usd - alloc.in_positions_usd

        return min(adjusted_size, remaining_exposure)

    def get_allocation_report(self) -> str:
        """Generate detailed allocation report"""
        report = [
            "\n" + "=" * 90,
            "MULTI-EXCHANGE CAPITAL ALLOCATION REPORT",
            "=" * 90,
            f"Total Capital: ${self.total_capital_usd:.2f}",
            f"Strategy: {self.strategy_name}",
            ""
        ]

        for exchange, alloc in self.allocations.items():
            report.extend([
                f"\n{exchange.value.upper()}",
                "-" * 90,
                f"  Target Allocation: {alloc.target_allocation_pct:.1f}%",
                f"  Current Allocation: {alloc.current_allocation_pct:.1f}%",
                f"  Drift: {abs(alloc.current_allocation_pct - alloc.target_allocation_pct):.1f}%",
                f"  Allocated Capital: ${alloc.allocated_capital_usd:.2f}",
                f"  Available Balance: ${alloc.available_balance_usd:.2f}",
                f"  In Positions: ${alloc.in_positions_usd:.2f} ({alloc.utilization_pct:.1f}%)",
                f"  Total P&L: ${alloc.total_pnl_usd:.2f} ({alloc.roi_pct:.2f}%)",
                f"  Total Trades: {alloc.total_trades}",
                f"  Win Rate: {alloc.win_rate*100:.1f}%",
                f"  Avg Profit/Trade: ${alloc.avg_profit_per_trade:.2f}",
            ])

        # Overall statistics
        total_pnl = sum(a.total_pnl_usd for a in self.allocations.values())
        total_trades = sum(a.total_trades for a in self.allocations.values())
        avg_win_rate = sum(a.win_rate for a in self.allocations.values()) / len(self.allocations)

        report.extend([
            "\n" + "=" * 90,
            "OVERALL PERFORMANCE",
            "=" * 90,
            f"  Total P&L: ${total_pnl:.2f} ({(total_pnl/self.total_capital_usd)*100:.2f}%)",
            f"  Total Trades: {total_trades}",
            f"  Average Win Rate: {avg_win_rate*100:.1f}%",
            "=" * 90 + "\n"
        ])

        return "\n".join(report)


def get_capital_allocator(total_capital: float,
                         strategy: str = "equal_weight") -> MultiExchangeCapitalAllocator:
    """
    Get capital allocator instance

    Args:
        total_capital: Total capital in USD
        strategy: Allocation strategy name

    Returns:
        MultiExchangeCapitalAllocator instance
    """
    return MultiExchangeCapitalAllocator(total_capital, strategy)


if __name__ == "__main__":
    # Test/demonstration
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s - %(message)s'
    )

    allocator = MultiExchangeCapitalAllocator(1000.0, "conservative")
    print(allocator.get_allocation_report())

    # Simulate some trading
    allocator.update_balance(ExchangeType.COINBASE, 680.0, 20.0)
    allocator.record_trade(ExchangeType.COINBASE, 5.0, True)

    print("\nAfter simulated trading:")
    print(allocator.get_allocation_report())
