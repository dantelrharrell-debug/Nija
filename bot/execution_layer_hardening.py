"""
NIJA Execution Layer Hardening - Unified Enforcement
====================================================

CRITICAL: This module provides a single integration point for ALL
execution-layer hardening controls, ensuring no system can bypass them.

Requirements Enforced:
1. User position cap (match platform cap)
2. Minimum per-position allocation (5-10% of account)
3. Block new entries below $X minimum position size
4. Consolidate dust positions
5. Disable trading if average position size < fee threshold

Integration Point: Called by broker_manager.py before EVERY order placement

Author: NIJA Trading Systems
Version: 1.0 - Unified Execution Layer Enforcement
Date: February 16, 2026
"""

import logging
from typing import Dict, Tuple, List, Optional
from datetime import datetime

logger = logging.getLogger("nija.execution.hardening")

# Import all enforcement modules
try:
    from bot.execution_position_cap_enforcer import get_execution_position_cap_enforcer
    from bot.execution_minimum_position_gate import get_execution_minimum_position_gate
    from bot.execution_average_position_monitor import get_execution_average_position_monitor
    from bot.dust_prevention_engine import DustPreventionEngine
    HARDENING_MODULES_AVAILABLE = True
except ImportError:
    try:
        from execution_position_cap_enforcer import get_execution_position_cap_enforcer
        from execution_minimum_position_gate import get_execution_minimum_position_gate
        from execution_average_position_monitor import get_execution_average_position_monitor
        from dust_prevention_engine import DustPreventionEngine
        HARDENING_MODULES_AVAILABLE = True
    except ImportError:
        HARDENING_MODULES_AVAILABLE = False
        logger.error("❌ CRITICAL: Hardening modules not available - execution layer unprotected!")
        get_execution_position_cap_enforcer = None
        get_execution_minimum_position_gate = None
        get_execution_average_position_monitor = None
        DustPreventionEngine = None


class ExecutionLayerHardening:
    """
    Unified enforcement of all execution-layer hardening controls.
    
    This class coordinates all hardening checks and provides a single
    validation method that broker_manager.py calls before every order.
    
    All checks are logged for audit trail and monitoring.
    """
    
    def __init__(self, 
                 broker_type: str = 'coinbase',
                 enable_position_cap: bool = True,
                 enable_minimum_size: bool = True,
                 enable_average_monitor: bool = True,
                 enable_dust_prevention: bool = True):
        """
        Initialize execution layer hardening.
        
        Args:
            broker_type: Broker type ('coinbase', 'kraken', etc.)
            enable_position_cap: Enable position cap enforcement
            enable_minimum_size: Enable minimum position size enforcement
            enable_average_monitor: Enable average position size monitoring
            enable_dust_prevention: Enable dust position prevention
        """
        self.broker_type = broker_type
        self.enable_position_cap = enable_position_cap
        self.enable_minimum_size = enable_minimum_size
        self.enable_average_monitor = enable_average_monitor
        self.enable_dust_prevention = enable_dust_prevention
        
        # Initialize enforcement modules
        if not HARDENING_MODULES_AVAILABLE:
            logger.error("❌ CRITICAL: Cannot initialize hardening - modules not available")
            self.position_cap_enforcer = None
            self.minimum_position_gate = None
            self.average_position_monitor = None
            self.dust_prevention_engine = None
            return
        
        try:
            self.position_cap_enforcer = get_execution_position_cap_enforcer() if enable_position_cap else None
            self.minimum_position_gate = get_execution_minimum_position_gate() if enable_minimum_size else None
            self.average_position_monitor = get_execution_average_position_monitor(
                broker_type=broker_type
            ) if enable_average_monitor else None
            self.dust_prevention_engine = DustPreventionEngine(
                max_positions=8,  # Will be overridden by tier-aware cap
                auto_dust_cleanup_enabled=True,
                dust_threshold_usd=1.0
            ) if enable_dust_prevention else None
            
            logger.info("✅ Execution Layer Hardening initialized")
            logger.info(f"   Broker: {broker_type}")
            logger.info(f"   Position cap enforcement: {enable_position_cap}")
            logger.info(f"   Minimum size enforcement: {enable_minimum_size}")
            logger.info(f"   Average monitor: {enable_average_monitor}")
            logger.info(f"   Dust prevention: {enable_dust_prevention}")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize hardening modules: {e}")
            self.position_cap_enforcer = None
            self.minimum_position_gate = None
            self.average_position_monitor = None
            self.dust_prevention_engine = None
    
    def validate_order_hardening(
        self,
        symbol: str,
        side: str,
        position_size_usd: float,
        balance: float,
        current_positions: List[Dict],
        user_id: Optional[str] = None,
        force_liquidate: bool = False
    ) -> Tuple[bool, str, Dict]:
        """
        PRIMARY ENFORCEMENT METHOD - Called by broker_manager.py before EVERY order.
        
        Validates ALL hardening requirements:
        1. Position cap check
        2. Minimum position size check  
        3. Average position size check
        4. Dust prevention check
        
        Args:
            symbol: Trading symbol
            side: 'BUY' or 'SELL'
            position_size_usd: Proposed position size in USD
            balance: Current account balance
            current_positions: List of current positions
            user_id: Optional user identifier
            force_liquidate: Skip checks for emergency exits
            
        Returns:
            Tuple[bool, str, Dict]: (is_valid, error_message, validation_details)
        """
        # CRITICAL: Emergency exits (force_liquidate) bypass ALL checks
        if force_liquidate:
            return True, "Emergency liquidation - bypassing all checks", {}
        
        # CRITICAL: SELL orders bypass hardening checks (only block new entries)
        if side.upper() in ['SELL', 'EXIT', 'CLOSE']:
            logger.debug(f"✅ EXECUTION LAYER: SELL order for {symbol} - bypassing hardening checks")
            return True, "Exit orders bypass hardening", {}
        
        # Only BUY orders are subject to hardening checks
        if side.upper() not in ['BUY', 'ENTER', 'OPEN']:
            # Unknown order type - allow but log warning
            logger.warning(f"⚠️ Unknown order side '{side}' - allowing by default")
            return True, f"Unknown order side '{side}' allowed", {}
        
        validation_details = {
            'symbol': symbol,
            'side': side,
            'position_size_usd': position_size_usd,
            'balance': balance,
            'position_count': len(current_positions),
            'user_id': user_id or 'unknown',
            'timestamp': datetime.now().isoformat(),
            'checks_performed': []
        }
        
        # ============================================================
        # CHECK 1: Position Cap Enforcement
        # ============================================================
        if self.enable_position_cap and self.position_cap_enforcer:
            is_valid, reason = self.position_cap_enforcer.validate_position_cap(
                current_positions=len(current_positions),
                balance=balance,
                order_side=side,
                user_id=user_id
            )
            validation_details['checks_performed'].append({
                'check': 'position_cap',
                'passed': is_valid,
                'reason': reason
            })
            if not is_valid:
                logger.error(f"❌ EXECUTION LAYER HARDENING: Position cap check failed")
                logger.error(f"   Symbol: {symbol}, Side: {side}, Size: ${position_size_usd:.2f}")
                logger.error(f"   {reason}")
                return False, reason, validation_details
        
        # ============================================================
        # CHECK 2: Minimum Position Size Enforcement
        # ============================================================
        if self.enable_minimum_size and self.minimum_position_gate:
            is_valid, reason, size_details = self.minimum_position_gate.validate_position_size(
                position_size_usd=position_size_usd,
                balance=balance,
                symbol=symbol,
                user_id=user_id
            )
            validation_details['checks_performed'].append({
                'check': 'minimum_position_size',
                'passed': is_valid,
                'reason': reason,
                'details': size_details
            })
            if not is_valid:
                logger.error(f"❌ EXECUTION LAYER HARDENING: Minimum position size check failed")
                logger.error(f"   Symbol: {symbol}, Side: {side}, Size: ${position_size_usd:.2f}")
                logger.error(f"   {reason}")
                return False, reason, validation_details
        
        # ============================================================
        # CHECK 3: Average Position Size Monitoring
        # ============================================================
        if self.enable_average_monitor and self.average_position_monitor:
            can_open, reason, avg_details = self.average_position_monitor.can_open_new_position(
                positions=current_positions,
                new_position_size=position_size_usd,
                balance=balance,
                symbol=symbol,
                user_id=user_id
            )
            validation_details['checks_performed'].append({
                'check': 'average_position_monitor',
                'passed': can_open,
                'reason': reason,
                'details': avg_details
            })
            if not can_open:
                logger.error(f"❌ EXECUTION LAYER HARDENING: Average position check failed")
                logger.error(f"   Symbol: {symbol}, Side: {side}, Size: ${position_size_usd:.2f}")
                logger.error(f"   {reason}")
                return False, reason, validation_details
        
        # ============================================================
        # CHECK 4: Dust Prevention
        # ============================================================
        if self.enable_dust_prevention and self.dust_prevention_engine:
            # Check if this would create a dust position
            if position_size_usd < self.dust_prevention_engine.DUST_THRESHOLD_USD:
                reason = (
                    f"Position size ${position_size_usd:.2f} would create dust position "
                    f"(< ${self.dust_prevention_engine.DUST_THRESHOLD_USD:.2f})"
                )
                validation_details['checks_performed'].append({
                    'check': 'dust_prevention',
                    'passed': False,
                    'reason': reason
                })
                logger.error(f"❌ EXECUTION LAYER HARDENING: Dust prevention check failed")
                logger.error(f"   Symbol: {symbol}, Size: ${position_size_usd:.2f}")
                logger.error(f"   {reason}")
                return False, reason, validation_details
            
            validation_details['checks_performed'].append({
                'check': 'dust_prevention',
                'passed': True,
                'reason': f"Position size ${position_size_usd:.2f} above dust threshold"
            })
        
        # ALL CHECKS PASSED
        success_msg = (
            f"All hardening checks passed for {symbol}: "
            f"${position_size_usd:.2f} position with {len(current_positions)} existing positions"
        )
        logger.info(f"✅ EXECUTION LAYER HARDENING: {success_msg}")
        return True, success_msg, validation_details
    
    def get_hardening_status(self) -> Dict:
        """
        Get current status of all hardening modules.
        
        Returns:
            Dict with status of each module
        """
        return {
            'broker_type': self.broker_type,
            'modules_available': HARDENING_MODULES_AVAILABLE,
            'position_cap_enabled': self.enable_position_cap and self.position_cap_enforcer is not None,
            'minimum_size_enabled': self.enable_minimum_size and self.minimum_position_gate is not None,
            'average_monitor_enabled': self.enable_average_monitor and self.average_position_monitor is not None,
            'dust_prevention_enabled': self.enable_dust_prevention and self.dust_prevention_engine is not None,
            'fully_operational': all([
                HARDENING_MODULES_AVAILABLE,
                self.position_cap_enforcer is not None if self.enable_position_cap else True,
                self.minimum_position_gate is not None if self.enable_minimum_size else True,
                self.average_position_monitor is not None if self.enable_average_monitor else True,
                self.dust_prevention_engine is not None if self.enable_dust_prevention else True,
            ])
        }
    
    def consolidate_dust_positions(self, positions: List[Dict]) -> Tuple[List[Dict], Dict]:
        """
        Consolidate dust positions by identifying them for closure.
        
        This method should be called periodically by the trading system to clean up
        dust positions (< $1 USD) that are bleeding value through fees.
        
        Args:
            positions: List of current positions with 'symbol', 'size_usd', 'pnl_pct'
            
        Returns:
            Tuple[List[Dict], Dict]: (positions_to_close, consolidation_summary)
        """
        if not self.enable_dust_prevention or not self.dust_prevention_engine:
            return [], {
                'enabled': False,
                'dust_positions_found': 0,
                'positions_to_close': 0,
                'total_dust_value': 0.0,
                'reason': 'Dust prevention disabled'
            }
        
        return self.dust_prevention_engine.consolidate_dust_positions(positions)


# Singleton instance
_hardening_instance = None
_hardening_lock = __import__('threading').Lock()


def get_execution_layer_hardening(
    broker_type: str = 'coinbase',
    enable_position_cap: bool = True,
    enable_minimum_size: bool = True,
    enable_average_monitor: bool = True,
    enable_dust_prevention: bool = True
) -> ExecutionLayerHardening:
    """
    Get singleton instance of ExecutionLayerHardening.
    
    Args:
        broker_type: Broker type
        enable_position_cap: Enable position cap enforcement
        enable_minimum_size: Enable minimum position size enforcement
        enable_average_monitor: Enable average position monitoring
        enable_dust_prevention: Enable dust prevention
        
    Returns:
        ExecutionLayerHardening instance
    """
    global _hardening_instance
    
    if _hardening_instance is None:
        with _hardening_lock:
            if _hardening_instance is None:
                _hardening_instance = ExecutionLayerHardening(
                    broker_type=broker_type,
                    enable_position_cap=enable_position_cap,
                    enable_minimum_size=enable_minimum_size,
                    enable_average_monitor=enable_average_monitor,
                    enable_dust_prevention=enable_dust_prevention
                )
    
    return _hardening_instance


# Example usage and testing
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    hardening = get_execution_layer_hardening(broker_type='coinbase')
    
    # Test scenario: User with $100 balance, 0 positions, wants to buy $8 of BTC
    test_positions = []
    
    print("\n🧪 Testing Execution Layer Hardening:\n")
    
    # Test 1: Small position (should fail minimum size check)
    is_valid, reason, details = hardening.validate_order_hardening(
        symbol='BTC-USD',
        side='BUY',
        position_size_usd=3.0,
        balance=100.0,
        current_positions=test_positions,
        user_id='test_user'
    )
    print(f"Test 1 - $3 position: {'✅ PASS' if not is_valid else '❌ FAIL'}")
    print(f"  Expected: Blocked (too small)")
    print(f"  Result: {reason}\n")
    
    # Test 2: Minimum viable position (should pass)
    is_valid, reason, details = hardening.validate_order_hardening(
        symbol='BTC-USD',
        side='BUY',
        position_size_usd=10.0,
        balance=100.0,
        current_positions=test_positions,
        user_id='test_user'
    )
    print(f"Test 2 - $10 position: {'✅ PASS' if is_valid else '❌ FAIL'}")
    print(f"  Expected: Allowed")
    print(f"  Result: {reason}\n")
    
    # Test 3: SELL order (should always pass)
    is_valid, reason, details = hardening.validate_order_hardening(
        symbol='BTC-USD',
        side='SELL',
        position_size_usd=1.0,  # Even tiny sells should pass
        balance=100.0,
        current_positions=test_positions,
        user_id='test_user'
    )
    print(f"Test 3 - $1 SELL: {'✅ PASS' if is_valid else '❌ FAIL'}")
    print(f"  Expected: Allowed (exits bypass checks)")
    print(f"  Result: {reason}\n")
    
    # Status check
    status = hardening.get_hardening_status()
    print(f"Hardening Status:")
    print(f"  Fully Operational: {status['fully_operational']}")
    print(f"  Position Cap: {status['position_cap_enabled']}")
    print(f"  Minimum Size: {status['minimum_size_enabled']}")
    print(f"  Average Monitor: {status['average_monitor_enabled']}")
    print(f"  Dust Prevention: {status['dust_prevention_enabled']}")
