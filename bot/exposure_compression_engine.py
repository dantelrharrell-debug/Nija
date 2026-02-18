"""
NIJA Exposure Compression Engine

Implements intelligent capital allocation that compresses exposure for small accounts
and expands diversification as capital grows.

Problem Solved:
- $50 account with 50 positions = $1 each = IMPOSSIBLE & UNPROFITABLE
- Small accounts need CONCENTRATION (fewer, larger positions)
- Large accounts can afford DIVERSIFICATION (many smaller positions)

Exposure Compression Strategy:
- Ranks signals by quality score
- Allocates capital to BEST signals first
- Small accounts: 80-100% in top 1-2 signals
- Medium accounts: 60-80% in top 3-5 signals
- Large accounts: Even distribution across 8-15 signals

Author: NIJA Trading Systems
Version: 1.0
Date: February 18, 2026
"""

import logging
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger("nija.exposure_compression")


@dataclass
class SignalAllocation:
    """
    Represents a trading signal with its allocated capital.
    
    Attributes:
        symbol: Trading pair symbol
        signal_type: LONG or SHORT
        quality_score: Signal quality score (0-100)
        rank: Ranking among all signals (1 = best)
        allocated_pct: Allocated % of total capital
        allocated_usd: Allocated capital in USD
        position_priority: Priority for position opening (1 = highest)
    """
    symbol: str
    signal_type: str
    quality_score: float
    rank: int
    allocated_pct: float
    allocated_usd: float
    position_priority: int
    
    def __repr__(self):
        return (f"SignalAllocation({self.symbol} {self.signal_type}, "
                f"score={self.quality_score:.1f}, rank={self.rank}, "
                f"allocated=${self.allocated_usd:.2f} ({self.allocated_pct*100:.1f}%))")


class ExposureCompressionEngine:
    """
    Manages capital allocation with tier-aware exposure compression.
    
    Key Concepts:
    1. Signal Quality Ranking: Orders signals by quality score
    2. Capital Concentration: Allocates MORE capital to FEWER top signals (small accounts)
    3. Progressive Diversification: Expands allocation as capital grows
    4. Position Priority: Determines which signals get positions first
    
    Allocation Curves:
    - STARTER/SAVER: 80% top signal, 20% second signal
    - INVESTOR: 40% top, 30% second, 30% third
    - INCOME: 25% each (4 signals)
    - LIVABLE: 15-20% each (5-6 signals)
    - BALLER: 10-12% each (8-10 signals)
    """
    
    def __init__(self):
        """Initialize the exposure compression engine"""
        self.compression_curves = self._build_compression_curves()
        logger.info("🎯 Exposure Compression Engine initialized")
    
    def _build_compression_curves(self) -> Dict[str, List[float]]:
        """
        Build capital allocation curves for each tier.
        
        Returns dictionary mapping tier name to list of allocation percentages.
        Each list represents the % allocation to ranked signals (1st, 2nd, 3rd, etc.)
        
        Example: STARTER: [0.80, 0.20] means 80% to best signal, 20% to second
        """
        return {
            # STARTER ($50-99): Ultra-concentrated (1-2 positions)
            # Allocate 80% to best signal, 20% to second best
            "STARTER": [0.80, 0.20],
            
            # SAVER ($100-249): High concentration (2-3 positions)
            # Allocate 50% to best, 30% to second, 20% to third
            "SAVER": [0.50, 0.30, 0.20],
            
            # INVESTOR ($250-999): Moderate concentration (3-5 positions)
            # Allocate 30% to top 2, then 25%, 20%, 15% to next 3
            "INVESTOR": [0.30, 0.30, 0.20, 0.15, 0.05],
            
            # INCOME ($1k-5k): Balanced allocation (5-7 positions)
            # More even distribution but still favor top signals
            "INCOME": [0.20, 0.18, 0.16, 0.15, 0.13, 0.11, 0.07],
            
            # LIVABLE ($5k-25k): Mild concentration (6-10 positions)
            # Nearly even with slight preference for top signals
            "LIVABLE": [0.13, 0.12, 0.12, 0.11, 0.11, 0.10, 0.10, 0.09, 0.07, 0.05],
            
            # BALLER ($25k+): Full diversification (8-15 positions)
            # Even distribution across all positions
            "BALLER": [0.10, 0.10, 0.09, 0.09, 0.08, 0.08, 0.08, 0.07, 0.07, 0.07, 
                      0.06, 0.05, 0.04, 0.02, 0.01],
        }
    
    def rank_signals_by_quality(self, signals: List[Dict]) -> List[Dict]:
        """
        Rank signals by quality score (highest first).
        
        Args:
            signals: List of signal dictionaries with 'quality_score' field
            
        Returns:
            Sorted list of signals (best to worst)
        """
        # Sort by quality_score in descending order
        ranked = sorted(signals, key=lambda s: s.get('quality_score', 0), reverse=True)
        
        # Add rank field
        for i, signal in enumerate(ranked, 1):
            signal['rank'] = i
        
        return ranked
    
    def allocate_capital(self, balance: float, tier_name: str, signals: List[Dict],
                        max_positions: int) -> List[SignalAllocation]:
        """
        Allocate capital across signals using tier-specific compression curve.
        
        Args:
            balance: Available capital in USD
            tier_name: Capital tier name (STARTER, SAVER, etc.)
            signals: List of signal dicts with 'symbol', 'signal_type', 'quality_score'
            max_positions: Maximum number of positions allowed for this tier
            
        Returns:
            List of SignalAllocation objects with capital allocations
        """
        if not signals:
            logger.warning("No signals provided for capital allocation")
            return []
        
        # Get compression curve for this tier
        compression_curve = self.compression_curves.get(tier_name, self.compression_curves["INCOME"])
        
        # Rank signals by quality
        ranked_signals = self.rank_signals_by_quality(signals)
        
        # Limit to max_positions
        signals_to_allocate = ranked_signals[:max_positions]
        
        # Get allocation percentages for these signals
        allocations = []
        for i, signal in enumerate(signals_to_allocate):
            # Get allocation % from curve (or use equal weight if beyond curve)
            if i < len(compression_curve):
                alloc_pct = compression_curve[i]
            else:
                # Equal weight for signals beyond curve definition
                remaining_pct = 1.0 - sum(compression_curve[:i])
                remaining_signals = len(signals_to_allocate) - i
                alloc_pct = remaining_pct / remaining_signals if remaining_signals > 0 else 0
            
            # Calculate USD allocation
            alloc_usd = balance * alloc_pct
            
            # Create allocation object
            allocation = SignalAllocation(
                symbol=signal['symbol'],
                signal_type=signal.get('signal_type', 'LONG'),
                quality_score=signal.get('quality_score', 0),
                rank=signal['rank'],
                allocated_pct=alloc_pct,
                allocated_usd=alloc_usd,
                position_priority=signal['rank']
            )
            allocations.append(allocation)
        
        # Log allocation summary
        self._log_allocation_summary(tier_name, balance, allocations)
        
        return allocations
    
    def get_next_position_size(self, balance: float, tier_name: str, 
                              current_positions: int, signals: List[Dict],
                              max_positions: int) -> Tuple[Optional[str], float, str]:
        """
        Get the next position to open and its size.
        
        Args:
            balance: Available capital in USD
            tier_name: Capital tier name
            current_positions: Number of currently open positions
            signals: List of available signals
            max_positions: Maximum positions allowed
            
        Returns:
            Tuple of (symbol, size_usd, signal_type) or (None, 0, "") if no more positions
        """
        # Check if we can open more positions
        if current_positions >= max_positions:
            logger.info(f"At maximum positions ({current_positions}/{max_positions})")
            return (None, 0.0, "")
        
        # Allocate capital across signals
        allocations = self.allocate_capital(balance, tier_name, signals, max_positions)
        
        if not allocations:
            logger.warning("No allocations generated")
            return (None, 0.0, "")
        
        # Get the next position to open (by priority)
        # Priority = rank, so find the highest rank signal we haven't opened yet
        # For now, return the first allocation (highest priority)
        next_allocation = allocations[current_positions] if current_positions < len(allocations) else None
        
        if next_allocation:
            logger.info(f"Next position: {next_allocation.symbol} {next_allocation.signal_type} "
                       f"size=${next_allocation.allocated_usd:.2f} (priority: {next_allocation.position_priority})")
            return (next_allocation.symbol, next_allocation.allocated_usd, next_allocation.signal_type)
        
        return (None, 0.0, "")
    
    def calculate_concentration_score(self, allocations: List[SignalAllocation]) -> float:
        """
        Calculate concentration score for a set of allocations.
        Higher score = more concentrated (small accounts)
        Lower score = more diversified (large accounts)
        
        Uses Herfindahl-Hirschman Index (HHI) calculation.
        
        Returns:
            Concentration score (0-1, where 1 = fully concentrated in single position)
        """
        if not allocations:
            return 0.0
        
        # HHI = sum of squared allocation percentages
        hhi = sum(alloc.allocated_pct ** 2 for alloc in allocations)
        
        return hhi
    
    def _log_allocation_summary(self, tier_name: str, balance: float, 
                               allocations: List[SignalAllocation]) -> None:
        """Log capital allocation summary"""
        if not allocations:
            return
        
        concentration = self.calculate_concentration_score(allocations)
        total_allocated_pct = sum(a.allocated_pct for a in allocations)
        
        logger.info("="*70)
        logger.info(f"EXPOSURE ALLOCATION - Tier: {tier_name}, Balance: ${balance:.2f}")
        logger.info(f"Concentration Score: {concentration:.3f} (1.0 = fully concentrated)")
        logger.info(f"Positions: {len(allocations)}, Total Allocated: {total_allocated_pct*100:.1f}%")
        logger.info("-"*70)
        
        for i, alloc in enumerate(allocations, 1):
            logger.info(f"  {i}. {alloc.symbol:>12} {alloc.signal_type:>5} | "
                       f"Score: {alloc.quality_score:>5.1f} | "
                       f"Allocation: ${alloc.allocated_usd:>8.2f} ({alloc.allocated_pct*100:>5.1f}%)")
        
        logger.info("="*70)
    
    def validate_allocation(self, allocations: List[SignalAllocation], 
                           min_position_size: float) -> Tuple[bool, List[str]]:
        """
        Validate that all allocations meet minimum position size requirements.
        
        Args:
            allocations: List of signal allocations
            min_position_size: Minimum viable position size in USD
            
        Returns:
            Tuple of (is_valid, list of validation messages)
        """
        issues = []
        
        for alloc in allocations:
            if alloc.allocated_usd < min_position_size:
                issues.append(
                    f"{alloc.symbol}: Allocated ${alloc.allocated_usd:.2f} "
                    f"below minimum ${min_position_size:.2f}"
                )
        
        is_valid = len(issues) == 0
        return (is_valid, issues)
    
    def rebalance_allocations(self, allocations: List[SignalAllocation], 
                            min_position_size: float) -> List[SignalAllocation]:
        """
        Rebalance allocations to ensure all meet minimum size requirements.
        Removes allocations that are too small and redistributes capital.
        
        Args:
            allocations: Original allocations
            min_position_size: Minimum position size
            
        Returns:
            Rebalanced allocations
        """
        if not allocations:
            return []
        
        # Filter out allocations below minimum
        valid_allocations = [a for a in allocations if a.allocated_usd >= min_position_size]
        
        if len(valid_allocations) == len(allocations):
            # No rebalancing needed
            return allocations
        
        # Calculate total capital from original allocations
        total_capital = sum(a.allocated_usd for a in allocations)
        
        # Redistribute capital across valid allocations
        if valid_allocations:
            for alloc in valid_allocations:
                # Proportionally increase allocation
                alloc.allocated_usd = (alloc.allocated_usd / sum(a.allocated_usd for a in valid_allocations)) * total_capital
                alloc.allocated_pct = alloc.allocated_usd / total_capital
            
            logger.info(f"Rebalanced: {len(allocations)} → {len(valid_allocations)} positions "
                       f"(removed {len(allocations) - len(valid_allocations)} below ${min_position_size:.2f})")
        
        return valid_allocations


# ============================================================================
# GLOBAL INSTANCE
# ============================================================================
_compression_engine_instance: Optional[ExposureCompressionEngine] = None


def get_exposure_compression_engine() -> ExposureCompressionEngine:
    """Get or create the global ExposureCompressionEngine instance"""
    global _compression_engine_instance
    if _compression_engine_instance is None:
        _compression_engine_instance = ExposureCompressionEngine()
    return _compression_engine_instance


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def allocate_capital_to_signals(balance: float, tier_name: str, signals: List[Dict],
                               max_positions: int) -> List[SignalAllocation]:
    """Convenience function to allocate capital"""
    engine = get_exposure_compression_engine()
    return engine.allocate_capital(balance, tier_name, signals, max_positions)


def get_next_position(balance: float, tier_name: str, current_positions: int,
                     signals: List[Dict], max_positions: int) -> Tuple[Optional[str], float, str]:
    """Convenience function to get next position to open"""
    engine = get_exposure_compression_engine()
    return engine.get_next_position_size(balance, tier_name, current_positions, signals, max_positions)


if __name__ == "__main__":
    # Demo: Show exposure compression across tiers
    import logging
    logging.basicConfig(level=logging.INFO)
    
    engine = ExposureCompressionEngine()
    
    # Create sample signals
    signals = [
        {'symbol': 'BTC-USD', 'signal_type': 'LONG', 'quality_score': 85.0},
        {'symbol': 'ETH-USD', 'signal_type': 'LONG', 'quality_score': 78.0},
        {'symbol': 'SOL-USD', 'signal_type': 'LONG', 'quality_score': 72.0},
        {'symbol': 'AVAX-USD', 'signal_type': 'LONG', 'quality_score': 68.0},
        {'symbol': 'MATIC-USD', 'signal_type': 'LONG', 'quality_score': 65.0},
        {'symbol': 'LINK-USD', 'signal_type': 'SHORT', 'quality_score': 62.0},
        {'symbol': 'UNI-USD', 'signal_type': 'LONG', 'quality_score': 60.0},
        {'symbol': 'AAVE-USD', 'signal_type': 'LONG', 'quality_score': 58.0},
    ]
    
    # Test different tiers
    test_cases = [
        (75.0, "STARTER", 2),
        (150.0, "SAVER", 3),
        (500.0, "INVESTOR", 5),
        (2500.0, "INCOME", 7),
        (10000.0, "LIVABLE", 10),
        (50000.0, "BALLER", 15),
    ]
    
    print("\n" + "="*100)
    print("EXPOSURE COMPRESSION ENGINE - Capital Allocation Demo")
    print("="*100 + "\n")
    
    for balance, tier, max_pos in test_cases:
        print(f"\n{'='*100}")
        print(f"Tier: {tier}, Balance: ${balance:,.0f}, Max Positions: {max_pos}")
        print(f"{'='*100}")
        
        allocations = engine.allocate_capital(balance, tier, signals, max_pos)
        
        # Show concentration
        concentration = engine.calculate_concentration_score(allocations)
        print(f"\nConcentration Score: {concentration:.3f}")
        print(f"Number of Positions: {len(allocations)}")
        print(f"\nCapital Allocation:")
        
        for i, alloc in enumerate(allocations, 1):
            print(f"  {i}. {alloc.symbol:>12} {alloc.signal_type:>5} | "
                  f"Score: {alloc.quality_score:>5.1f} | "
                  f"${alloc.allocated_usd:>8.2f} ({alloc.allocated_pct*100:>5.1f}%)")
        
        # Validate allocations
        min_size = 15.0 if tier in ["STARTER", "SAVER"] else 20.0
        is_valid, issues = engine.validate_allocation(allocations, min_size)
        if not is_valid:
            print(f"\n⚠️  Validation Issues:")
            for issue in issues:
                print(f"    - {issue}")
    
    print("\n" + "="*100)
    print("Key Insight: Small tiers = concentrated capital, Large tiers = diversified")
    print("="*100 + "\n")
