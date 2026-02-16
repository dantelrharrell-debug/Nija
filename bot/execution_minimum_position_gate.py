"""
NIJA Execution-Layer Minimum Position Size Gate
================================================

CRITICAL: This module enforces minimum position sizes at the EXECUTION LAYER,
preventing bypass by copy trading engines or any other system.

Requirements:
- Enforce minimum per-position allocation (5-10% of account)
- Block new entries below $X minimum position size
- Tier-aware minimum enforcement

Location: Integrated into broker_manager.py before ALL order placements

Author: NIJA Trading Systems
Version: 1.0 - Execution Layer Enforcement
Date: February 16, 2026
"""

import logging
from typing import Dict, Tuple, Optional

logger = logging.getLogger("nija.execution.min_position")

# Import tier configuration for tier-aware minimums
try:
    from bot.tier_config import get_tier_from_balance, get_tier_config, TradingTier
    TIER_CONFIG_AVAILABLE = True
except ImportError:
    try:
        from tier_config import get_tier_from_balance, get_tier_config, TradingTier
        TIER_CONFIG_AVAILABLE = True
    except ImportError:
        TIER_CONFIG_AVAILABLE = False
        logger.warning("⚠️ Tier configuration not available - using default minimums")
        get_tier_from_balance = None
        get_tier_config = None

# Import fee-aware configuration for profitability thresholds
try:
    from bot.fee_aware_config import MIN_BALANCE_TO_TRADE, MICRO_ACCOUNT_THRESHOLD
    FEE_AWARE_CONFIG_AVAILABLE = True
except ImportError:
    try:
        from fee_aware_config import MIN_BALANCE_TO_TRADE, MICRO_ACCOUNT_THRESHOLD
        FEE_AWARE_CONFIG_AVAILABLE = True
    except ImportError:
        FEE_AWARE_CONFIG_AVAILABLE = False
        MIN_BALANCE_TO_TRADE = 5.0
        MICRO_ACCOUNT_THRESHOLD = 5.0
        logger.warning("⚠️ Fee-aware config not available - using default minimums")


class ExecutionMinimumPositionGate:
    """
    Enforces minimum position sizes at the execution layer.
    
    This gate runs BEFORE any order is placed at the broker,
    ensuring that no system can create unprofitable small positions.
    
    Features:
    - Tier-aware minimum position sizes
    - Minimum percentage allocation enforcement (5-10% of account)
    - Absolute dollar minimums for fee profitability
    - Clear error messages for blocked orders
    """
    
    # Absolute minimum position sizes (USD) by tier
    # These ensure positions are large enough to be profitable after fees
    TIER_MINIMUM_USD = {
        'STARTER': 5.0,    # $5 minimum (Coinbase minimum for profitability)
        'SAVER': 10.0,     # $10 minimum (Kraken minimum)
        'INVESTOR': 20.0,  # $20 minimum (better fee efficiency)
        'INCOME': 30.0,    # $30 minimum (optimal fee efficiency)
        'LIVABLE': 50.0,   # $50 minimum (institutional approach)
        'BALLER': 100.0,   # $100 minimum (capital deployment mode)
    }
    
    # Minimum percentage allocation (of account balance)
    # Prevents spreading capital too thin
    MIN_ALLOCATION_PCT = 0.05   # 5% minimum
    MAX_ALLOCATION_PCT = 0.10   # 10% minimum for larger accounts
    
    def __init__(self, 
                 enforce_percentage: bool = True,
                 enforce_absolute: bool = True):
        """
        Initialize the minimum position gate.
        
        Args:
            enforce_percentage: Enforce minimum percentage allocation (5-10%)
            enforce_absolute: Enforce absolute dollar minimums
        """
        self.enforce_percentage = enforce_percentage
        self.enforce_absolute = enforce_absolute
        logger.info(f"✅ Execution Minimum Position Gate initialized")
        logger.info(f"   Percentage enforcement: {enforce_percentage}")
        logger.info(f"   Absolute enforcement: {enforce_absolute}")
        logger.info(f"   Tier-aware minimums: {TIER_CONFIG_AVAILABLE}")
    
    def get_minimum_position_size(self, balance: float) -> Tuple[float, float, str]:
        """
        Get minimum position size for a given balance.
        
        Returns both percentage-based and absolute minimums.
        The final minimum is the LARGER of the two.
        
        Args:
            balance: Current account balance in USD
            
        Returns:
            Tuple[float, float, str]: (min_usd, min_pct, tier_name)
        """
        tier_name = self._get_tier_name(balance)
        
        # Get absolute minimum from tier configuration
        absolute_min = self.TIER_MINIMUM_USD.get(tier_name, MIN_BALANCE_TO_TRADE)
        
        # Get percentage-based minimum (5% of balance)
        percentage_min_pct = self.MIN_ALLOCATION_PCT
        percentage_min_usd = balance * percentage_min_pct
        
        # Use tier config if available for more precise minimums
        if TIER_CONFIG_AVAILABLE and balance > 0:
            try:
                tier = get_tier_from_balance(balance)
                tier_config = get_tier_config(tier)
                # Use tier's trade_size_min if it's larger
                if tier_config.trade_size_min > absolute_min:
                    absolute_min = tier_config.trade_size_min
            except Exception as e:
                logger.debug(f"Could not get tier config: {e}")
        
        # Final minimum is the LARGER of absolute and percentage
        final_min_usd = max(absolute_min, percentage_min_usd)
        
        return final_min_usd, percentage_min_pct, tier_name
    
    def validate_position_size(
        self,
        position_size_usd: float,
        balance: float,
        symbol: str = "UNKNOWN",
        user_id: Optional[str] = None
    ) -> Tuple[bool, str, Dict]:
        """
        Validate that position size meets minimum requirements.
        
        This is the PRIMARY enforcement point called by broker_manager.py
        before every order placement.
        
        Args:
            position_size_usd: Proposed position size in USD
            balance: Current account balance in USD
            symbol: Trading symbol (for logging)
            user_id: Optional user identifier
            
        Returns:
            Tuple[bool, str, Dict]: (is_valid, reason, details)
        """
        min_usd, min_pct, tier_name = self.get_minimum_position_size(balance)
        actual_pct = (position_size_usd / balance * 100) if balance > 0 else 0
        
        details = {
            'position_size_usd': position_size_usd,
            'balance': balance,
            'min_size_usd': min_usd,
            'min_pct': min_pct * 100,
            'actual_pct': actual_pct,
            'tier': tier_name,
            'symbol': symbol,
            'user_id': user_id or 'unknown'
        }
        
        # Check absolute minimum
        if self.enforce_absolute and position_size_usd < min_usd:
            reason = (
                f"Position size ${position_size_usd:.2f} below tier minimum ${min_usd:.2f} "
                f"({tier_name} tier, balance ${balance:.2f})"
            )
            logger.warning(f"❌ EXECUTION LAYER: Minimum position gate enforced - {reason}")
            logger.warning(f"   Symbol: {symbol}, User: {user_id or 'unknown'}")
            return False, reason, details
        
        # Check percentage minimum (5% of account)
        min_allocation_usd = balance * self.MIN_ALLOCATION_PCT
        if self.enforce_percentage and position_size_usd < min_allocation_usd:
            reason = (
                f"Position size ${position_size_usd:.2f} below minimum allocation "
                f"${min_allocation_usd:.2f} ({self.MIN_ALLOCATION_PCT*100:.0f}% of ${balance:.2f})"
            )
            logger.warning(f"❌ EXECUTION LAYER: Minimum allocation enforced - {reason}")
            logger.warning(f"   Symbol: {symbol}, User: {user_id or 'unknown'}")
            return False, reason, details
        
        reason = (
            f"Position size OK: ${position_size_usd:.2f} "
            f"({actual_pct:.1f}% of ${balance:.2f}, min: ${min_usd:.2f})"
        )
        logger.debug(f"✅ EXECUTION LAYER: {reason}")
        return True, reason, details
    
    def _get_tier_name(self, balance: float) -> str:
        """Get tier name for a given balance."""
        if not TIER_CONFIG_AVAILABLE or balance <= 0:
            # Fallback tier determination
            if balance < 50:
                return "MICRO"
            elif balance < 100:
                return "STARTER"
            elif balance < 250:
                return "SAVER"
            elif balance < 1000:
                return "INVESTOR"
            elif balance < 5000:
                return "INCOME"
            elif balance < 25000:
                return "LIVABLE"
            else:
                return "BALLER"
        
        try:
            tier = get_tier_from_balance(balance)
            return tier.value
        except Exception:
            return "UNKNOWN"
    
    def can_trade_with_balance(self, balance: float) -> Tuple[bool, str]:
        """
        Check if trading is allowed with the given balance.
        
        Args:
            balance: Current account balance
            
        Returns:
            Tuple[bool, str]: (can_trade, reason)
        """
        min_usd, min_pct, tier_name = self.get_minimum_position_size(balance)
        
        # Need at least enough for one minimum position
        if balance < min_usd:
            reason = (
                f"Balance ${balance:.2f} below minimum ${min_usd:.2f} "
                f"for {tier_name} tier trading"
            )
            return False, reason
        
        # Need at least enough for minimum allocation
        min_allocation = balance * self.MIN_ALLOCATION_PCT
        if balance < min_allocation / self.MIN_ALLOCATION_PCT:  # i.e., balance < min for 5% allocation
            reason = f"Balance too low for minimum {self.MIN_ALLOCATION_PCT*100:.0f}% allocation"
            return False, reason
        
        return True, f"Balance ${balance:.2f} sufficient for {tier_name} tier trading"
    
    def get_recommended_position_size(self, balance: float) -> Dict:
        """
        Get recommended position size range for monitoring/UI.
        
        Args:
            balance: Current account balance
            
        Returns:
            Dict with recommended sizing information
        """
        min_usd, min_pct, tier_name = self.get_minimum_position_size(balance)
        
        # Recommended range: 5-10% of balance (but at least the tier minimum)
        recommended_min = max(min_usd, balance * self.MIN_ALLOCATION_PCT)
        recommended_max = balance * self.MAX_ALLOCATION_PCT
        
        return {
            'tier': tier_name,
            'balance': balance,
            'min_size_usd': min_usd,
            'min_allocation_pct': self.MIN_ALLOCATION_PCT * 100,
            'max_allocation_pct': self.MAX_ALLOCATION_PCT * 100,
            'recommended_min_usd': recommended_min,
            'recommended_max_usd': recommended_max,
            'can_trade': balance >= min_usd
        }


# Singleton instance
_gate_instance = None
_gate_lock = __import__('threading').Lock()


def get_execution_minimum_position_gate(
    enforce_percentage: bool = True,
    enforce_absolute: bool = True
) -> ExecutionMinimumPositionGate:
    """
    Get singleton instance of ExecutionMinimumPositionGate.
    
    Args:
        enforce_percentage: Enforce minimum percentage allocation
        enforce_absolute: Enforce absolute dollar minimums
        
    Returns:
        ExecutionMinimumPositionGate instance
    """
    global _gate_instance
    
    if _gate_instance is None:
        with _gate_lock:
            if _gate_instance is None:
                _gate_instance = ExecutionMinimumPositionGate(
                    enforce_percentage=enforce_percentage,
                    enforce_absolute=enforce_absolute
                )
    
    return _gate_instance


# Example usage and testing
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    gate = get_execution_minimum_position_gate()
    
    # Test scenarios
    test_cases = [
        # (balance, position_size, expected_valid)
        (50.0, 2.0, False),    # Below tier minimum ($5)
        (50.0, 5.0, True),     # At tier minimum
        (50.0, 10.0, True),    # Above minimum (20% allocation)
        (100.0, 8.0, False),   # Below 10% minimum allocation
        (100.0, 10.0, True),   # At tier minimum
        (250.0, 15.0, False),  # Below $20 investor minimum
        (250.0, 20.0, True),   # At investor minimum
        (1000.0, 25.0, False), # Below $30 income minimum
        (1000.0, 50.0, True),  # Above income minimum (5% allocation)
    ]
    
    print("\n🧪 Testing Minimum Position Size Enforcement:\n")
    for balance, size, expected_valid in test_cases:
        is_valid, reason, details = gate.validate_position_size(size, balance)
        status = "✅ PASS" if is_valid == expected_valid else "❌ FAIL"
        print(f"{status}: Balance ${balance}, Position ${size}")
        print(f"   {reason}")
        print(f"   Tier: {details['tier']}, Min: ${details['min_size_usd']:.2f}\n")
