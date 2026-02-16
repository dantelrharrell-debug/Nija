"""
NIJA Execution-Layer Average Position Monitor
==============================================

CRITICAL: This module monitors average position size at the EXECUTION LAYER
and disables trading if positions are too small to be profitable.

Requirement: Disable trading if average position size < fee threshold

Logic:
- Calculate average position size across all open positions
- Compare against fee profitability threshold ($5-10 depending on broker/tier)
- Block new entries if average position size is below threshold
- This prevents "death by a thousand paper cuts" from small positions

Location: Integrated into broker_manager.py before ALL order placements

Author: NIJA Trading Systems
Version: 1.0 - Execution Layer Enforcement
Date: February 16, 2026
"""

import logging
from typing import Dict, Tuple, List, Optional

logger = logging.getLogger("nija.execution.avg_position")

# Import fee-aware configuration for profitability thresholds
try:
    from bot.fee_aware_config import (
        MIN_BALANCE_TO_TRADE,
        MARKET_ORDER_ROUND_TRIP,
        LIMIT_ORDER_ROUND_TRIP
    )
    FEE_AWARE_CONFIG_AVAILABLE = True
except ImportError:
    try:
        from fee_aware_config import (
            MIN_BALANCE_TO_TRADE,
            MARKET_ORDER_ROUND_TRIP,
            LIMIT_ORDER_ROUND_TRIP
        )
        FEE_AWARE_CONFIG_AVAILABLE = True
    except ImportError:
        FEE_AWARE_CONFIG_AVAILABLE = False
        MIN_BALANCE_TO_TRADE = 5.0
        MARKET_ORDER_ROUND_TRIP = 0.014  # 1.4%
        LIMIT_ORDER_ROUND_TRIP = 0.010   # 1.0%
        logger.warning("⚠️ Fee-aware config not available - using default fee thresholds")

# Import tier configuration
try:
    from bot.tier_config import get_tier_from_balance, get_tier_config
    TIER_CONFIG_AVAILABLE = True
except ImportError:
    try:
        from tier_config import get_tier_from_balance, get_tier_config
        TIER_CONFIG_AVAILABLE = True
    except ImportError:
        TIER_CONFIG_AVAILABLE = False
        logger.warning("⚠️ Tier configuration not available")
        get_tier_from_balance = None
        get_tier_config = None


class ExecutionAveragePositionMonitor:
    """
    Monitors average position size and blocks trading if below profitability threshold.
    
    This monitor runs BEFORE any order is placed at the broker,
    ensuring positions remain profitable after fees.
    
    Features:
    - Real-time average position size calculation
    - Fee profitability threshold enforcement
    - Tier-aware minimum thresholds
    - Trading pause when average too low
    """
    
    # Fee profitability thresholds by broker
    # Positions smaller than this are likely to lose money to fees
    FEE_THRESHOLD_USD = {
        'coinbase': 5.0,   # Coinbase: $5 minimum for profitability
        'kraken': 10.0,    # Kraken: $10 minimum (exchange minimum)
        'binance': 5.0,    # Binance: $5 minimum
        'default': 5.0,    # Default: $5 minimum
    }
    
    # Minimum average threshold multiplier
    # Average position must be at least this multiple of fee threshold
    MIN_AVG_MULTIPLIER = 1.5  # 1.5x fee threshold
    
    # LOW_CAPITAL mode threshold
    # For accounts < $100, enforce strict $7.50 minimum average to prevent fee bleed
    LOW_CAPITAL_THRESHOLD = 100.0  # Balance threshold for LOW_CAPITAL mode
    LOW_CAPITAL_MIN_AVG = 7.50     # Minimum average position in LOW_CAPITAL mode
    
    def __init__(self, 
                 broker_type: str = 'coinbase',
                 enforce_average_check: bool = True,
                 enforce_low_capital_mode: bool = True):
        """
        Initialize the average position monitor.
        
        Args:
            broker_type: Broker type for fee threshold ('coinbase', 'kraken', etc.)
            enforce_average_check: Enable/disable average position checking
            enforce_low_capital_mode: Enable LOW_CAPITAL mode enforcement (< $100 accounts)
        """
        self.broker_type = broker_type.lower()
        self.enforce_average_check = enforce_average_check
        self.enforce_low_capital_mode = enforce_low_capital_mode
        self.fee_threshold = self.FEE_THRESHOLD_USD.get(
            self.broker_type,
            self.FEE_THRESHOLD_USD['default']
        )
        self.min_avg_threshold = self.fee_threshold * self.MIN_AVG_MULTIPLIER
        
        logger.info(f"✅ Execution Average Position Monitor initialized")
        logger.info(f"   Broker: {broker_type}")
        logger.info(f"   Fee threshold: ${self.fee_threshold:.2f}")
        logger.info(f"   Minimum average threshold: ${self.min_avg_threshold:.2f}")
        logger.info(f"   LOW_CAPITAL mode ($7.50 avg): {enforce_low_capital_mode}")
        logger.info(f"   Enforcement: {enforce_average_check}")
    
    def calculate_average_position_size(self, positions: List[Dict]) -> float:
        """
        Calculate average position size across all open positions.
        
        Args:
            positions: List of position dicts with 'size_usd' or 'position_size_usd'
            
        Returns:
            float: Average position size in USD (0 if no positions)
        """
        if not positions:
            return 0.0
        
        total_size = 0.0
        valid_positions = 0
        
        for pos in positions:
            # Try multiple keys for position size
            size_usd = pos.get('size_usd') or pos.get('position_size_usd') or 0
            if size_usd > 0:
                total_size += size_usd
                valid_positions += 1
        
        if valid_positions == 0:
            return 0.0
        
        return total_size / valid_positions
    
    def is_average_profitable(
        self,
        positions: List[Dict],
        include_dust_positions: bool = False
    ) -> Tuple[bool, float, str]:
        """
        Check if average position size is above profitability threshold.
        
        Args:
            positions: List of current positions
            include_dust_positions: Include positions < $1 in calculation
            
        Returns:
            Tuple[bool, float, str]: (is_profitable, avg_size, reason)
        """
        # Filter out dust positions if requested
        if not include_dust_positions:
            positions = [p for p in positions if p.get('size_usd', 0) >= 1.0]
        
        if not positions:
            # No positions = can't calculate average, allow trading
            return True, 0.0, "No positions to evaluate"
        
        avg_size = self.calculate_average_position_size(positions)
        
        if avg_size < self.min_avg_threshold:
            reason = (
                f"Average position size ${avg_size:.2f} below profitability threshold "
                f"${self.min_avg_threshold:.2f} ({self.broker_type})"
            )
            return False, avg_size, reason
        
        reason = f"Average position size ${avg_size:.2f} is profitable"
        return True, avg_size, reason
    
    def can_open_new_position(
        self,
        positions: List[Dict],
        new_position_size: float,
        balance: float = 0.0,
        symbol: str = "UNKNOWN",
        user_id: Optional[str] = None
    ) -> Tuple[bool, str, Dict]:
        """
        Check if a new position can be opened without dragging average below threshold.
        
        This is the PRIMARY enforcement point called by broker_manager.py
        before every order placement.
        
        Args:
            positions: Current open positions
            new_position_size: Proposed new position size in USD
            balance: Current account balance (for LOW_CAPITAL mode detection)
            symbol: Trading symbol (for logging)
            user_id: Optional user identifier
            
        Returns:
            Tuple[bool, str, Dict]: (can_open, reason, details)
        """
        # Skip check if enforcement disabled
        if not self.enforce_average_check:
            return True, "Average position check disabled", {}
        
        # Calculate current average
        current_avg = self.calculate_average_position_size(positions)
        
        # Calculate new average if this position is added
        position_count = len(positions)
        if position_count > 0:
            total_size = current_avg * position_count + new_position_size
            new_avg = total_size / (position_count + 1)
        else:
            # First position
            new_avg = new_position_size
        
        # Determine effective threshold based on balance (LOW_CAPITAL mode)
        is_low_capital = balance > 0 and balance < self.LOW_CAPITAL_THRESHOLD
        effective_threshold = self.min_avg_threshold
        
        if is_low_capital and self.enforce_low_capital_mode:
            # LOW_CAPITAL mode: Use stricter $7.50 minimum
            effective_threshold = max(self.LOW_CAPITAL_MIN_AVG, self.min_avg_threshold)
            mode_label = "LOW_CAPITAL"
        else:
            mode_label = "STANDARD"
        
        details = {
            'current_avg_size': current_avg,
            'new_avg_size': new_avg,
            'new_position_size': new_position_size,
            'position_count': position_count,
            'balance': balance,
            'is_low_capital_mode': is_low_capital,
            'mode': mode_label,
            'min_avg_threshold': effective_threshold,
            'fee_threshold': self.fee_threshold,
            'broker': self.broker_type,
            'symbol': symbol,
            'user_id': user_id or 'unknown'
        }
        
        # Check if new average would be below threshold
        if new_avg < effective_threshold:
            reason = (
                f"[{mode_label}] New position ${new_position_size:.2f} would reduce average to ${new_avg:.2f}, "
                f"below minimum ${effective_threshold:.2f} "
                f"(current avg: ${current_avg:.2f}, {position_count} positions, balance: ${balance:.2f})"
            )
            logger.warning(f"❌ EXECUTION LAYER: Average position check failed - {reason}")
            logger.warning(f"   Symbol: {symbol}, User: {user_id or 'unknown'}")
            if is_low_capital:
                logger.warning(f"   💡 LOW_CAPITAL mode active - strict $7.50 average enforced to prevent fee bleed")
            return False, reason, details
        
        reason = (
            f"[{mode_label}] Average position check passed: new avg ${new_avg:.2f} "
            f"above threshold ${effective_threshold:.2f}"
        )
        logger.debug(f"✅ EXECUTION LAYER: {reason}")
        return True, reason, details
    
    def should_pause_trading(
        self,
        positions: List[Dict],
        balance: float
    ) -> Tuple[bool, str, Dict]:
        """
        Determine if trading should be paused due to low average position size.
        
        Args:
            positions: Current open positions
            balance: Current account balance
            
        Returns:
            Tuple[bool, str, Dict]: (should_pause, reason, details)
        """
        if not self.enforce_average_check:
            return False, "Average position check disabled", {}
        
        is_profitable, avg_size, reason = self.is_average_profitable(positions)
        
        details = {
            'average_position_size': avg_size,
            'position_count': len(positions),
            'min_avg_threshold': self.min_avg_threshold,
            'balance': balance,
            'is_profitable': is_profitable
        }
        
        if not is_profitable and len(positions) > 0:
            pause_reason = (
                f"Trading paused: {reason}. "
                f"Close small positions or increase position sizes."
            )
            logger.error(f"⛔ EXECUTION LAYER: {pause_reason}")
            return True, pause_reason, details
        
        return False, "Average position size is healthy", details
    
    def get_position_health_report(self, positions: List[Dict]) -> Dict:
        """
        Generate health report on position sizing for monitoring/reporting.
        
        Args:
            positions: Current positions
            
        Returns:
            Dict with health metrics
        """
        if not positions:
            return {
                'position_count': 0,
                'average_size': 0,
                'total_size': 0,
                'smallest_position': 0,
                'largest_position': 0,
                'below_threshold_count': 0,
                'is_healthy': True,
                'min_threshold': self.min_avg_threshold
            }
        
        sizes = [p.get('size_usd', 0) for p in positions if p.get('size_usd', 0) > 0]
        
        if not sizes:
            return {
                'position_count': 0,
                'average_size': 0,
                'total_size': 0,
                'smallest_position': 0,
                'largest_position': 0,
                'below_threshold_count': 0,
                'is_healthy': True,
                'min_threshold': self.min_avg_threshold
            }
        
        avg_size = sum(sizes) / len(sizes)
        below_threshold = sum(1 for s in sizes if s < self.fee_threshold)
        
        return {
            'position_count': len(sizes),
            'average_size': avg_size,
            'total_size': sum(sizes),
            'smallest_position': min(sizes),
            'largest_position': max(sizes),
            'below_threshold_count': below_threshold,
            'is_healthy': avg_size >= self.min_avg_threshold,
            'min_threshold': self.min_avg_threshold,
            'fee_threshold': self.fee_threshold
        }


# Singleton instance
_monitor_instance = None
_monitor_lock = __import__('threading').Lock()


def get_execution_average_position_monitor(
    broker_type: str = 'coinbase',
    enforce_average_check: bool = True,
    enforce_low_capital_mode: bool = True
) -> ExecutionAveragePositionMonitor:
    """
    Get singleton instance of ExecutionAveragePositionMonitor.
    
    Args:
        broker_type: Broker type for fee threshold
        enforce_average_check: Enable/disable average position checking
        enforce_low_capital_mode: Enable LOW_CAPITAL mode enforcement
        
    Returns:
        ExecutionAveragePositionMonitor instance
    """
    global _monitor_instance
    
    if _monitor_instance is None:
        with _monitor_lock:
            if _monitor_instance is None:
                _monitor_instance = ExecutionAveragePositionMonitor(
                    broker_type=broker_type,
                    enforce_average_check=enforce_average_check,
                    enforce_low_capital_mode=enforce_low_capital_mode
                )
    
    return _monitor_instance


# Example usage and testing
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    monitor = get_execution_average_position_monitor(broker_type='coinbase')
    
    # Test scenarios
    test_positions = [
        {'symbol': 'BTC-USD', 'size_usd': 10.0},
        {'symbol': 'ETH-USD', 'size_usd': 8.0},
        {'symbol': 'SOL-USD', 'size_usd': 12.0},
    ]
    
    print("\n🧪 Testing Average Position Size Monitoring:\n")
    
    # Test 1: Check current average
    avg = monitor.calculate_average_position_size(test_positions)
    print(f"Current average position size: ${avg:.2f}")
    print(f"Minimum threshold: ${monitor.min_avg_threshold:.2f}\n")
    
    # Test 2: Try to add a small position
    can_open, reason, details = monitor.can_open_new_position(
        test_positions,
        new_position_size=3.0,
        symbol='ADA-USD'
    )
    print(f"Can open $3 position: {can_open}")
    print(f"Reason: {reason}\n")
    
    # Test 3: Try to add a normal position
    can_open, reason, details = monitor.can_open_new_position(
        test_positions,
        new_position_size=10.0,
        symbol='MATIC-USD'
    )
    print(f"Can open $10 position: {can_open}")
    print(f"Reason: {reason}\n")
    
    # Test 4: Health report
    report = monitor.get_position_health_report(test_positions)
    print(f"Position Health Report:")
    print(f"  Count: {report['position_count']}")
    print(f"  Average: ${report['average_size']:.2f}")
    print(f"  Smallest: ${report['smallest_position']:.2f}")
    print(f"  Largest: ${report['largest_position']:.2f}")
    print(f"  Healthy: {report['is_healthy']}")
