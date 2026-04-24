"""
NIJA Execution-Layer Position Cap Enforcer
==========================================

CRITICAL: This module enforces position caps at the EXECUTION LAYER,
preventing bypass by copy trading engines or any other system.

Requirement: Enforce user position cap (match platform cap)
Location: Integrated into broker_manager.py before ALL order placements

Author: NIJA Trading Systems
Version: 1.0 - Execution Layer Enforcement
Date: February 16, 2026
"""

import logging
from typing import Dict, Tuple, Optional
from datetime import datetime

logger = logging.getLogger("nija.execution.position_cap")

# Import tier configuration for tier-aware limits
try:
    from bot.tier_config import get_tier_from_balance, get_tier_config, TradingTier, TIER_CONFIGS
    TIER_CONFIG_AVAILABLE = True
except ImportError:
    try:
        from tier_config import get_tier_from_balance, get_tier_config, TradingTier, TIER_CONFIGS
        TIER_CONFIG_AVAILABLE = True
    except ImportError:
        TIER_CONFIG_AVAILABLE = False
        logger.warning("⚠️ Tier configuration not available - using default limits")
        get_tier_from_balance = None
        get_tier_config = None


class ExecutionPositionCapEnforcer:
    """
    Enforces position caps at the execution layer.
    
    This enforcer runs BEFORE any order is placed at the broker,
    ensuring that no system can bypass position limits.
    
    Features:
    - Tier-aware position limits (SAVER: 1, INVESTOR: 3, INCOME: 5, etc.)
    - Real-time position count validation
    - Clear error messages for blocked orders
    - Logging for audit trail
    """
    
    def __init__(self, default_max_positions: int = 5):
        """
        Initialize the position cap enforcer.
        
        Args:
            default_max_positions: Default max positions if tier config unavailable
        """
        self.default_max_positions = default_max_positions
        logger.info(f"✅ Execution Position Cap Enforcer initialized")
        logger.info(f"   Tier-aware limits: {TIER_CONFIG_AVAILABLE}")
        logger.info(f"   Default max positions: {default_max_positions}")
    
    def get_max_positions_for_balance(self, balance: float) -> int:
        """
        Get maximum allowed positions for a given balance.
        
        Args:
            balance: Current account balance in USD
            
        Returns:
            int: Maximum allowed positions
        """
        if not TIER_CONFIG_AVAILABLE or balance <= 0:
            return self.default_max_positions
        
        try:
            tier = get_tier_from_balance(balance)
            tier_config = get_tier_config(tier)
            return tier_config.max_positions
        except Exception as e:
            logger.warning(f"Failed to get tier-based max positions: {e}")
            return self.default_max_positions
    
    def can_open_new_position(
        self,
        current_position_count: int,
        balance: float,
        user_id: Optional[str] = None
    ) -> Tuple[bool, str, Dict]:
        """
        Check if a new position can be opened.
        
        This is the PRIMARY enforcement point called by broker_manager.py
        before every order placement.
        
        Args:
            current_position_count: Number of currently open positions
            balance: Current account balance in USD
            user_id: Optional user identifier for logging
            
        Returns:
            Tuple[bool, str, Dict]: (can_open, reason, details)
                - can_open: True if new position allowed
                - reason: Human-readable reason
                - details: Additional context for logging
        """
        max_positions = self.get_max_positions_for_balance(balance)
        
        details = {
            'current_positions': current_position_count,
            'max_positions': max_positions,
            'balance': balance,
            'user_id': user_id or 'unknown',
            'timestamp': datetime.now().isoformat(),
            'tier': self._get_tier_name(balance)
        }
        
        if current_position_count >= max_positions:
            reason = (
                f"Position cap reached: {current_position_count}/{max_positions} positions "
                f"(Tier: {details['tier']}, Balance: ${balance:.2f})"
            )
            logger.warning(f"❌ EXECUTION LAYER: Position cap enforced - {reason}")
            return False, reason, details
        
        reason = f"Position cap OK: {current_position_count}/{max_positions} positions"
        logger.debug(f"✅ EXECUTION LAYER: {reason}")
        return True, reason, details
    
    def _get_tier_name(self, balance: float) -> str:
        """Get tier name for a given balance."""
        if not TIER_CONFIG_AVAILABLE or balance <= 0:
            return "UNKNOWN"
        
        try:
            tier = get_tier_from_balance(balance)
            return tier.value
        except Exception:
            return "UNKNOWN"
    
    def validate_position_cap(
        self,
        current_positions: int,
        balance: float,
        order_side: str,
        user_id: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Validate position cap before order execution.
        
        This is a convenience method that wraps can_open_new_position()
        and is optimized for use in order validation pipelines.
        
        Args:
            current_positions: Current number of open positions
            balance: Account balance
            order_side: 'BUY' or 'SELL' (only BUY orders create new positions)
            user_id: Optional user identifier
            
        Returns:
            Tuple[bool, str]: (is_valid, error_message)
        """
        # Only check position cap for BUY orders (new positions)
        # SELL orders close existing positions
        if order_side.upper() in ['SELL', 'EXIT', 'CLOSE']:
            return True, "Exit orders bypass position cap"
        
        can_open, reason, details = self.can_open_new_position(
            current_position_count=current_positions,
            balance=balance,
            user_id=user_id
        )
        
        if not can_open:
            error_msg = f"POSITION_CAP_EXCEEDED: {reason}"
            return False, error_msg
        
        return True, reason
    
    def get_position_cap_status(self, balance: float, current_positions: int) -> Dict:
        """
        Get current position cap status for monitoring/reporting.
        
        Args:
            balance: Current account balance
            current_positions: Current number of positions
            
        Returns:
            Dict with status information
        """
        max_positions = self.get_max_positions_for_balance(balance)
        utilization_pct = (current_positions / max_positions * 100) if max_positions > 0 else 0
        
        return {
            'current_positions': current_positions,
            'max_positions': max_positions,
            'positions_available': max(0, max_positions - current_positions),
            'utilization_pct': utilization_pct,
            'at_capacity': current_positions >= max_positions,
            'tier': self._get_tier_name(balance),
            'balance': balance
        }


# Singleton instance
_enforcer_instance = None
_enforcer_lock = __import__('threading').Lock()


def get_execution_position_cap_enforcer(
    default_max_positions: int = 5
) -> ExecutionPositionCapEnforcer:
    """
    Get singleton instance of ExecutionPositionCapEnforcer.
    
    Args:
        default_max_positions: Default max positions if tier config unavailable
        
    Returns:
        ExecutionPositionCapEnforcer instance
    """
    global _enforcer_instance
    
    if _enforcer_instance is None:
        with _enforcer_lock:
            if _enforcer_instance is None:
                _enforcer_instance = ExecutionPositionCapEnforcer(
                    default_max_positions=default_max_positions
                )
    
    return _enforcer_instance


# Example usage and testing
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    enforcer = get_execution_position_cap_enforcer()
    
    # Test scenarios
    test_cases = [
        # (balance, current_positions, expected_result)
        (50.0, 0, True),    # STARTER tier - 1 max, 0 current = OK
        (50.0, 1, False),   # STARTER tier - 1 max, 1 current = BLOCKED
        (100.0, 0, True),   # SAVER tier - 1 max, 0 current = OK
        (250.0, 2, True),   # INVESTOR tier - 3 max, 2 current = OK
        (250.0, 3, False),  # INVESTOR tier - 3 max, 3 current = BLOCKED
        (1000.0, 4, True),  # INCOME tier - 5 max, 4 current = OK
        (5000.0, 6, False), # LIVABLE tier - 6 max, 6 current = BLOCKED
    ]
    
    print("\n🧪 Testing Position Cap Enforcement:\n")
    for balance, positions, expected_ok in test_cases:
        can_open, reason, details = enforcer.can_open_new_position(positions, balance)
        status = "✅ PASS" if can_open == expected_ok else "❌ FAIL"
        print(f"{status}: Balance ${balance}, Positions {positions}/{details['max_positions']}")
        print(f"   {reason}\n")
