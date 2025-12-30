"""
NIJA Multi-Exchange Capital Allocator
Split capital across exchanges to smooth drawdowns and optimize returns

Key Features:
- Intelligent capital distribution across exchanges
- Dynamic rebalancing based on performance
- Drawdown smoothing through diversification
- Exchange-specific position management
- Performance tracking and optimization

Author: NIJA Trading Systems
Version: 1.0
Date: December 30, 2025
"""

import logging
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta

logger = logging.getLogger("nija.capital_allocator")

# Import exchange profiles
try:
    from exchange_risk_profiles import (
        get_exchange_risk_profile,
        get_all_exchange_profiles,
        get_best_exchange_for_balance
    )
except ImportError:
    logger.warning("⚠️ exchange_risk_profiles not found, using fallback")
    def get_exchange_risk_profile(exchange: str) -> Dict:
        return {'capital_allocation_pct': 0.33}
    def get_all_exchange_profiles() -> Dict:
        return {}
    def get_best_exchange_for_balance(balance: float, exchanges: List[str]) -> str:
        return exchanges[0] if exchanges else 'coinbase'


# ============================================================================
# CAPITAL ALLOCATION STRATEGIES
# ============================================================================

class AllocationStrategy:
    """Capital allocation strategies"""
    
    EQUAL_WEIGHT = "equal_weight"  # Split evenly across exchanges
    FEE_OPTIMIZED = "fee_optimized"  # Allocate more to lower-fee exchanges
    PERFORMANCE_BASED = "performance_based"  # Allocate based on historical performance
    RISK_BALANCED = "risk_balanced"  # Balance risk across exchanges
    HYBRID = "hybrid"  # Combination of fee optimization and performance


# ============================================================================
# DEFAULT ALLOCATION PERCENTAGES
# ============================================================================

DEFAULT_ALLOCATIONS = {
    'coinbase': 0.40,  # 40% - Most reliable, US-based
    'okx': 0.30,       # 30% - Lowest fees, good for smaller trades
    'kraken': 0.30,    # 30% - Balanced fees and reliability
    'binance': 0.0,    # 0% - Not currently integrated
}


# ============================================================================
# MULTI-EXCHANGE CAPITAL ALLOCATOR
# ============================================================================

class MultiExchangeCapitalAllocator:
    """
    Manages capital allocation across multiple exchanges.
    
    Features:
    - Automatic capital distribution
    - Drawdown smoothing
    - Performance tracking
    - Dynamic rebalancing
    """
    
    def __init__(self, 
                 strategy: str = AllocationStrategy.HYBRID,
                 min_exchange_allocation: float = 0.15,
                 max_exchange_allocation: float = 0.50,
                 rebalance_threshold: float = 0.10):
        """
        Initialize capital allocator.
        
        Args:
            strategy: Allocation strategy to use
            min_exchange_allocation: Minimum % per exchange (0.15 = 15%)
            max_exchange_allocation: Maximum % per exchange (0.50 = 50%)
            rebalance_threshold: Trigger rebalance when drift > this (0.10 = 10%)
        """
        self.strategy = strategy
        self.min_allocation = min_exchange_allocation
        self.max_allocation = max_exchange_allocation
        self.rebalance_threshold = rebalance_threshold
        
        # Track allocations and performance
        self.current_allocations: Dict[str, float] = {}
        self.target_allocations: Dict[str, float] = {}
        self.exchange_balances: Dict[str, float] = {}
        self.exchange_performance: Dict[str, Dict] = {}
        
        logger.info(f"✅ Multi-Exchange Capital Allocator initialized")
        logger.info(f"   Strategy: {strategy}")
        logger.info(f"   Allocation range: {min_exchange_allocation*100:.0f}% - {max_exchange_allocation*100:.0f}%")
    
    def calculate_allocation(self, 
                            total_capital: float,
                            available_exchanges: List[str],
                            exchange_balances: Optional[Dict[str, float]] = None) -> Dict[str, float]:
        """
        Calculate optimal capital allocation across exchanges.
        
        Args:
            total_capital: Total capital to allocate
            available_exchanges: List of available exchange names
            exchange_balances: Current balances on each exchange (optional)
            
        Returns:
            Dict mapping exchange name to USD allocation amount
        """
        if not available_exchanges:
            logger.warning("⚠️ No exchanges available for allocation")
            return {}
        
        # Calculate allocation percentages based on strategy
        if self.strategy == AllocationStrategy.EQUAL_WEIGHT:
            allocations_pct = self._equal_weight_allocation(available_exchanges)
        elif self.strategy == AllocationStrategy.FEE_OPTIMIZED:
            allocations_pct = self._fee_optimized_allocation(available_exchanges)
        elif self.strategy == AllocationStrategy.PERFORMANCE_BASED:
            allocations_pct = self._performance_based_allocation(available_exchanges)
        elif self.strategy == AllocationStrategy.RISK_BALANCED:
            allocations_pct = self._risk_balanced_allocation(available_exchanges)
        else:  # HYBRID
            allocations_pct = self._hybrid_allocation(available_exchanges)
        
        # Convert percentages to dollar amounts
        allocations_usd = {
            exchange: total_capital * pct
            for exchange, pct in allocations_pct.items()
        }
        
        # Store target allocations
        self.target_allocations = allocations_pct
        
        # Update current balances if provided
        if exchange_balances:
            self.exchange_balances = exchange_balances
        
        return allocations_usd
    
    def _equal_weight_allocation(self, exchanges: List[str]) -> Dict[str, float]:
        """Equal allocation across all exchanges"""
        pct_per_exchange = 1.0 / len(exchanges)
        return {exchange: pct_per_exchange for exchange in exchanges}
    
    def _fee_optimized_allocation(self, exchanges: List[str]) -> Dict[str, float]:
        """
        Allocate more capital to lower-fee exchanges.
        
        Inverse weighting: Lower fees = higher allocation
        """
        profiles = {ex: get_exchange_risk_profile(ex) for ex in exchanges}
        
        # Calculate inverse fee weights
        fee_weights = {}
        total_inverse_fee = 0
        
        for exchange in exchanges:
            fee = profiles[exchange]['fees']['total_round_trip']
            # Inverse: lower fee = higher weight
            inverse_fee = 1.0 / fee if fee > 0 else 100.0
            fee_weights[exchange] = inverse_fee
            total_inverse_fee += inverse_fee
        
        # Normalize to percentages
        allocations = {
            exchange: fee_weights[exchange] / total_inverse_fee
            for exchange in exchanges
        }
        
        # Apply min/max constraints
        return self._apply_constraints(allocations)
    
    def _performance_based_allocation(self, exchanges: List[str]) -> Dict[str, float]:
        """
        Allocate based on historical performance.
        
        Better performing exchanges get more capital.
        Falls back to fee-optimized if no performance data.
        """
        if not self.exchange_performance:
            logger.info("No performance data, using fee-optimized allocation")
            return self._fee_optimized_allocation(exchanges)
        
        # Calculate performance scores
        perf_weights = {}
        total_score = 0
        
        for exchange in exchanges:
            if exchange in self.exchange_performance:
                perf = self.exchange_performance[exchange]
                # Score based on win rate and profit factor
                win_rate = perf.get('win_rate', 0.5)
                profit_factor = perf.get('profit_factor', 1.0)
                score = (win_rate * 2) + profit_factor  # Weighted score
            else:
                score = 1.0  # Neutral score for new exchanges
            
            perf_weights[exchange] = score
            total_score += score
        
        # Normalize to percentages
        allocations = {
            exchange: perf_weights[exchange] / total_score
            for exchange in exchanges
        }
        
        return self._apply_constraints(allocations)
    
    def _risk_balanced_allocation(self, exchanges: List[str]) -> Dict[str, float]:
        """
        Allocate to balance risk across exchanges.
        
        Considers reliability and volatility.
        """
        profiles = {ex: get_exchange_risk_profile(ex) for ex in exchanges}
        
        # Calculate risk scores (higher = safer)
        risk_scores = {}
        total_score = 0
        
        for exchange in exchanges:
            profile = profiles[exchange]
            reliability = profile.get('reliability_score', 0.85)
            # Lower fees reduce risk
            fee_factor = 1.0 - profile['fees']['total_round_trip']
            
            risk_score = reliability * fee_factor
            risk_scores[exchange] = risk_score
            total_score += risk_score
        
        # Normalize to percentages
        allocations = {
            exchange: risk_scores[exchange] / total_score
            for exchange in exchanges
        }
        
        return self._apply_constraints(allocations)
    
    def _hybrid_allocation(self, exchanges: List[str]) -> Dict[str, float]:
        """
        Hybrid approach: Fee optimization + reliability + performance.
        
        Weights:
        - 50% fee optimization
        - 30% reliability
        - 20% performance (if available)
        """
        # Get base allocations from different strategies
        fee_alloc = self._fee_optimized_allocation(exchanges)
        risk_alloc = self._risk_balanced_allocation(exchanges)
        
        # Combine with weights
        hybrid_alloc = {}
        for exchange in exchanges:
            # 60% fee-optimized, 40% risk-balanced
            hybrid_alloc[exchange] = (
                fee_alloc[exchange] * 0.60 +
                risk_alloc[exchange] * 0.40
            )
        
        # If we have performance data, incorporate it
        if self.exchange_performance:
            perf_alloc = self._performance_based_allocation(exchanges)
            # Adjust: 50% hybrid, 50% performance
            for exchange in exchanges:
                hybrid_alloc[exchange] = (
                    hybrid_alloc[exchange] * 0.70 +
                    perf_alloc[exchange] * 0.30
                )
        
        return self._apply_constraints(hybrid_alloc)
    
    def _apply_constraints(self, allocations: Dict[str, float]) -> Dict[str, float]:
        """Apply min/max constraints to allocations"""
        constrained = {}
        
        for exchange, pct in allocations.items():
            # Clamp to min/max
            constrained[exchange] = max(self.min_allocation, 
                                       min(self.max_allocation, pct))
        
        # Renormalize to ensure sum = 1.0
        total = sum(constrained.values())
        if total > 0:
            constrained = {ex: pct/total for ex, pct in constrained.items()}
        
        return constrained
    
    def needs_rebalancing(self, current_balances: Dict[str, float]) -> Tuple[bool, str]:
        """
        Check if portfolio needs rebalancing.
        
        Args:
            current_balances: Current balance on each exchange
            
        Returns:
            Tuple of (needs_rebalance: bool, reason: str)
        """
        if not self.target_allocations:
            return False, "No target allocations set"
        
        total_balance = sum(current_balances.values())
        if total_balance == 0:
            return False, "No capital deployed"
        
        # Calculate current allocation percentages
        current_pct = {
            ex: bal / total_balance 
            for ex, bal in current_balances.items()
        }
        
        # Check drift from targets
        max_drift = 0
        drift_exchange = None
        
        for exchange in self.target_allocations:
            target = self.target_allocations[exchange]
            actual = current_pct.get(exchange, 0)
            drift = abs(target - actual)
            
            if drift > max_drift:
                max_drift = drift
                drift_exchange = exchange
        
        if max_drift > self.rebalance_threshold:
            return True, f"{drift_exchange} drifted {max_drift*100:.1f}% from target"
        
        return False, "Allocation within tolerance"
    
    def update_performance(self, exchange: str, trade_result: Dict) -> None:
        """
        Update performance tracking for an exchange.
        
        Args:
            exchange: Exchange name
            trade_result: Dict with 'outcome' ('win'/'loss'), 'pnl', etc.
        """
        if exchange not in self.exchange_performance:
            self.exchange_performance[exchange] = {
                'trades': 0,
                'wins': 0,
                'losses': 0,
                'total_pnl': 0,
                'total_win_pnl': 0,
                'total_loss_pnl': 0,
                'win_rate': 0,
                'profit_factor': 0,
                'last_updated': datetime.now()
            }
        
        perf = self.exchange_performance[exchange]
        perf['trades'] += 1
        perf['total_pnl'] += trade_result.get('pnl', 0)
        
        if trade_result['outcome'] == 'win':
            perf['wins'] += 1
            perf['total_win_pnl'] += trade_result.get('pnl', 0)
        else:
            perf['losses'] += 1
            perf['total_loss_pnl'] += abs(trade_result.get('pnl', 0))
        
        # Update metrics
        perf['win_rate'] = perf['wins'] / perf['trades'] if perf['trades'] > 0 else 0
        
        if perf['total_loss_pnl'] > 0:
            perf['profit_factor'] = perf['total_win_pnl'] / perf['total_loss_pnl']
        else:
            perf['profit_factor'] = perf['total_win_pnl'] if perf['total_win_pnl'] > 0 else 1.0
        
        perf['last_updated'] = datetime.now()
        
        logger.info(f"📊 {exchange} performance updated: "
                   f"{perf['wins']}W/{perf['losses']}L, "
                   f"WR: {perf['win_rate']*100:.1f}%, "
                   f"PF: {perf['profit_factor']:.2f}")
    
    def get_allocation_summary(self, total_capital: float) -> str:
        """Get formatted summary of current allocation"""
        if not self.target_allocations:
            return "No allocations calculated yet"
        
        summary = "\n" + "="*70 + "\n"
        summary += "MULTI-EXCHANGE CAPITAL ALLOCATION\n"
        summary += "="*70 + "\n"
        summary += f"\nTotal Capital: ${total_capital:.2f}\n"
        summary += f"Strategy: {self.strategy}\n\n"
        
        summary += f"{'Exchange':<15} {'Allocation %':<15} {'Amount':<15} {'Status':<15}\n"
        summary += "-"*70 + "\n"
        
        for exchange, pct in sorted(self.target_allocations.items(), 
                                   key=lambda x: x[1], reverse=True):
            amount = total_capital * pct
            status = "✅ Active" if amount > 0 else "⚠️ Inactive"
            summary += f"{exchange:<15} {pct*100:>10.1f}%    ${amount:>10.2f}    {status}\n"
        
        summary += "="*70 + "\n"
        return summary


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def get_recommended_allocation(total_capital: float,
                              available_exchanges: List[str],
                              strategy: str = AllocationStrategy.HYBRID) -> Dict[str, float]:
    """
    Get recommended capital allocation.
    
    Args:
        total_capital: Total capital to allocate
        available_exchanges: List of available exchange names
        strategy: Allocation strategy
        
    Returns:
        Dict mapping exchange name to USD allocation
    """
    allocator = MultiExchangeCapitalAllocator(strategy=strategy)
    return allocator.calculate_allocation(total_capital, available_exchanges)


def print_allocation_comparison(total_capital: float, 
                               available_exchanges: List[str]) -> None:
    """Print comparison of different allocation strategies"""
    print("\n" + "="*80)
    print("CAPITAL ALLOCATION STRATEGY COMPARISON")
    print(f"Total Capital: ${total_capital:.2f}")
    print(f"Exchanges: {', '.join(available_exchanges)}")
    print("="*80 + "\n")
    
    strategies = [
        AllocationStrategy.EQUAL_WEIGHT,
        AllocationStrategy.FEE_OPTIMIZED,
        AllocationStrategy.RISK_BALANCED,
        AllocationStrategy.HYBRID
    ]
    
    for strategy in strategies:
        allocator = MultiExchangeCapitalAllocator(strategy=strategy)
        allocations = allocator.calculate_allocation(total_capital, available_exchanges)
        
        print(f"\n{strategy.upper().replace('_', ' ')}:")
        print("-"*80)
        for exchange, amount in sorted(allocations.items(), key=lambda x: x[1], reverse=True):
            pct = (amount / total_capital) * 100
            print(f"  {exchange:<12} ${amount:>8.2f}  ({pct:>5.1f}%)")
    
    print("\n" + "="*80 + "\n")


if __name__ == "__main__":
    # Test allocation with different strategies
    test_capital = 500.00
    test_exchanges = ['coinbase', 'okx', 'kraken']
    
    print_allocation_comparison(test_capital, test_exchanges)
    
    # Test with allocator instance
    allocator = MultiExchangeCapitalAllocator(strategy=AllocationStrategy.HYBRID)
    allocations = allocator.calculate_allocation(test_capital, test_exchanges)
    print(allocator.get_allocation_summary(test_capital))
