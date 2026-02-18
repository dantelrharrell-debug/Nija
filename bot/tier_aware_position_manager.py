"""
NIJA Tier-Aware Position Manager

Integrates the capital tier hierarchy, exposure compression, and deterministic
entry validation into the existing trading system.

This module acts as a facade/orchestrator that:
1. Coordinates between new tier-based components
2. Provides clean integration points for existing code
3. Maintains backward compatibility where needed
4. Adds comprehensive logging of tier-based decisions

Author: NIJA Trading Systems
Version: 1.0
Date: February 18, 2026
"""

import logging
from typing import Dict, Tuple, Optional, List
from datetime import datetime

logger = logging.getLogger("nija.tier_position_manager")

# Import new tier-based components
try:
    from capital_tier_hierarchy import (
        get_capital_tier_hierarchy,
        get_max_positions_for_balance,
        get_optimal_positions_for_balance,
        validate_position_entry,
        CapitalTierHierarchy
    )
    TIER_HIERARCHY_AVAILABLE = True
except ImportError:
    try:
        from bot.capital_tier_hierarchy import (
            get_capital_tier_hierarchy,
            get_max_positions_for_balance,
            get_optimal_positions_for_balance,
            validate_position_entry,
            CapitalTierHierarchy
        )
        TIER_HIERARCHY_AVAILABLE = True
    except ImportError:
        TIER_HIERARCHY_AVAILABLE = False
        logger.warning("⚠️ Capital tier hierarchy not available")

try:
    from exposure_compression_engine import (
        get_exposure_compression_engine,
        allocate_capital_to_signals,
        get_next_position,
        ExposureCompressionEngine
    )
    EXPOSURE_COMPRESSION_AVAILABLE = True
except ImportError:
    try:
        from bot.exposure_compression_engine import (
            get_exposure_compression_engine,
            allocate_capital_to_signals,
            get_next_position,
            ExposureCompressionEngine
        )
        EXPOSURE_COMPRESSION_AVAILABLE = True
    except ImportError:
        EXPOSURE_COMPRESSION_AVAILABLE = False
        logger.warning("⚠️ Exposure compression engine not available")

try:
    from deterministic_entry_validator import (
        get_entry_validator,
        validate_entry,
        ValidationContext,
        ValidationResult,
        DeterministicEntryValidator
    )
    ENTRY_VALIDATOR_AVAILABLE = True
except ImportError:
    try:
        from bot.deterministic_entry_validator import (
            get_entry_validator,
            validate_entry,
            ValidationContext,
            ValidationResult,
            DeterministicEntryValidator
        )
        ENTRY_VALIDATOR_AVAILABLE = True
    except ImportError:
        ENTRY_VALIDATOR_AVAILABLE = False
        logger.warning("⚠️ Deterministic entry validator not available")

try:
    from risk_containment_layer import (
        get_risk_containment_layer,
        apply_risk_containment,
        RiskContainmentLayer
    )
    RISK_CONTAINMENT_AVAILABLE = True
except ImportError:
    try:
        from bot.risk_containment_layer import (
            get_risk_containment_layer,
            apply_risk_containment,
            RiskContainmentLayer
        )
        RISK_CONTAINMENT_AVAILABLE = True
    except ImportError:
        RISK_CONTAINMENT_AVAILABLE = False
        logger.warning("⚠️ Risk containment layer not available")


class TierAwarePositionManager:
    """
    Tier-aware position manager that orchestrates capital allocation,
    position sizing, and entry validation based on capital tier.
    
    This is the main integration point for tier-based position management.
    """
    
    def __init__(self):
        """Initialize the tier-aware position manager"""
        self.tier_hierarchy = None
        self.compression_engine = None
        self.entry_validator = None
        self.risk_containment = None
        
        # Initialize components
        if TIER_HIERARCHY_AVAILABLE:
            self.tier_hierarchy = get_capital_tier_hierarchy()
            logger.info("✅ Capital tier hierarchy integrated")
        
        if EXPOSURE_COMPRESSION_AVAILABLE:
            self.compression_engine = get_exposure_compression_engine()
            logger.info("✅ Exposure compression engine integrated")
        
        if ENTRY_VALIDATOR_AVAILABLE:
            self.entry_validator = get_entry_validator()
            logger.info("✅ Deterministic entry validator integrated")
        
        if RISK_CONTAINMENT_AVAILABLE:
            self.risk_containment = get_risk_containment_layer()
            logger.info("✅ Risk containment layer integrated")
        
        # Track current state
        self.last_balance = 0.0
        self.current_tier = None
        
        logger.info("🎯 Tier-Aware Position Manager initialized")
    
    def update_balance(self, balance: float) -> None:
        """
        Update current balance and tier.
        
        Args:
            balance: Current account balance in USD
        """
        if self.tier_hierarchy:
            self.tier_hierarchy.update_balance(balance)
            self.last_balance = balance
            self.current_tier = self.tier_hierarchy.current_tier
    
    def get_max_positions(self, balance: float) -> int:
        """
        Get maximum allowed positions for balance.
        
        Args:
            balance: Account balance in USD
            
        Returns:
            Maximum number of concurrent positions
        """
        if self.tier_hierarchy:
            return self.tier_hierarchy.get_max_positions(balance)
        else:
            # Fallback to legacy logic
            return 10
    
    def get_optimal_positions(self, balance: float) -> int:
        """
        Get optimal number of positions for balance.
        
        Args:
            balance: Account balance in USD
            
        Returns:
            Optimal number of concurrent positions
        """
        if self.tier_hierarchy:
            return self.tier_hierarchy.get_optimal_position_count(balance)
        else:
            # Fallback
            return 5
    
    def calculate_tier_aware_position_size(self, balance: float, 
                                          current_position_count: int,
                                          signal_quality: float = 75.0,
                                          stop_loss_pct: Optional[float] = None,
                                          apply_risk_control: bool = True) -> Tuple[float, Dict]:
        """
        Calculate position size using tier-aware logic WITH risk containment.
        
        Args:
            balance: Current account balance
            current_position_count: Number of open positions
            signal_quality: Quality score of signal (0-100)
            stop_loss_pct: Stop loss as decimal (0.05 = 5%), if None uses tier default
            apply_risk_control: Whether to apply risk containment (default True)
            
        Returns:
            Tuple of (position_size, calculation_details)
        """
        if not self.tier_hierarchy:
            # Fallback: simple percentage
            return (balance * 0.10, {'fallback': True})
        
        # Get tier name
        tier_name = self.tier_hierarchy.get_tier_from_balance(balance).value
        
        # Get target size from tier hierarchy (concentration-based)
        target_size = self.tier_hierarchy.calculate_target_position_size(
            balance, current_position_count
        )
        
        details = {
            'tier': tier_name,
            'tier_target_size': target_size,
            'tier_target_pct': (target_size / balance * 100) if balance > 0 else 0
        }
        
        # Apply risk containment if enabled
        if apply_risk_control and self.risk_containment:
            risk_calc = self.risk_containment.calculate_risk_adjusted_position_size(
                balance=balance,
                tier_name=tier_name,
                requested_size=target_size,
                stop_loss_pct=stop_loss_pct
            )
            
            final_size = risk_calc.risk_adjusted_size
            
            details['risk_containment_applied'] = True
            details['risk_adjusted_size'] = final_size
            details['actual_risk_pct'] = risk_calc.actual_risk_pct * 100
            details['max_risk_pct'] = risk_calc.max_risk_pct * 100
            details['stop_loss_pct'] = risk_calc.stop_loss_pct * 100
            details['size_reduced'] = risk_calc.size_reduced
            
            if risk_calc.size_reduced:
                details['reduction_reason'] = risk_calc.reduction_reason
                logger.warning(f"⚠️ RISK CONTAINMENT: Position size reduced from "
                             f"${target_size:.2f} to ${final_size:.2f}")
        else:
            final_size = target_size
            details['risk_containment_applied'] = False
        
        return (final_size, details)
    
    def validate_new_position(self, balance: float, 
                             current_position_count: int,
                             proposed_size: float,
                             symbol: str,
                             signal_type: str = "LONG",
                             signal_quality: float = 75.0,
                             signal_confidence: float = 0.70,
                             open_positions: Optional[List[str]] = None,
                             exchange_name: str = "coinbase") -> ValidationResult:
        """
        Validate if a new position can be opened.
        
        Args:
            balance: Current account balance
            current_position_count: Number of open positions
            proposed_size: Proposed position size in USD
            symbol: Trading symbol
            signal_type: LONG or SHORT
            signal_quality: Signal quality score (0-100)
            signal_confidence: Signal confidence (0-1)
            open_positions: List of open position symbols
            exchange_name: Exchange name for minimum validation
            
        Returns:
            ValidationResult with pass/fail and explicit rejection code
        """
        if not self.entry_validator:
            # Fallback: basic validation
            if current_position_count >= 10:
                from deterministic_entry_validator import ValidationResult, RejectionCode
                return ValidationResult(
                    passed=False,
                    rejection_code=RejectionCode.TIER_MAX_POSITIONS,
                    rejection_message="Max positions reached (fallback validation)",
                    validation_timestamp=datetime.now(),
                    validation_details={}
                )
            return ValidationResult(
                passed=True,
                rejection_code=RejectionCode.VALIDATION_PASSED,
                rejection_message="Validation passed (fallback)",
                validation_timestamp=datetime.now(),
                validation_details={}
            )
        
        # Get tier name
        if self.tier_hierarchy:
            tier_name = self.tier_hierarchy.get_tier_from_balance(balance).value
        else:
            tier_name = "INCOME"  # Fallback
        
        # Calculate available capital (80% of balance)
        available_capital = balance * 0.80
        
        # Create validation context
        context = ValidationContext(
            balance=balance,
            tier_name=tier_name,
            current_position_count=current_position_count,
            open_positions=open_positions or [],
            available_capital=available_capital,
            symbol=symbol,
            signal_type=signal_type,
            signal_quality=signal_quality,
            signal_confidence=signal_confidence,
            proposed_size_usd=proposed_size,
            exchange_name=exchange_name
        )
        
        # Validate
        result = self.entry_validator.validate_entry(context)
        
        return result
    
    def allocate_capital_to_signals(self, balance: float, signals: List[Dict],
                                   current_position_count: int) -> List:
        """
        Allocate capital across signals using exposure compression.
        
        Args:
            balance: Current account balance
            signals: List of signal dicts with 'symbol', 'signal_type', 'quality_score'
            current_position_count: Number of currently open positions
            
        Returns:
            List of SignalAllocation objects
        """
        if not self.compression_engine or not self.tier_hierarchy:
            # Fallback: equal allocation
            max_pos = min(10, len(signals))
            size_per_position = balance / max_pos
            return [
                {
                    'symbol': s['symbol'],
                    'signal_type': s.get('signal_type', 'LONG'),
                    'allocated_usd': size_per_position,
                    'rank': i+1
                }
                for i, s in enumerate(signals[:max_pos])
            ]
        
        # Get tier name
        tier_name = self.tier_hierarchy.get_tier_from_balance(balance).value
        
        # Get max positions for tier
        max_positions = self.tier_hierarchy.get_max_positions(balance)
        
        # Allocate using compression engine
        allocations = self.compression_engine.allocate_capital(
            balance, tier_name, signals, max_positions
        )
        
        return allocations
    
    def get_tier_info(self, balance: float) -> Dict:
        """
        Get comprehensive tier information.
        
        Args:
            balance: Current account balance
            
        Returns:
            Dictionary with tier information
        """
        if self.tier_hierarchy:
            return self.tier_hierarchy.get_tier_info(balance)
        else:
            # Fallback
            return {
                'tier': 'UNKNOWN',
                'balance': balance,
                'max_positions': 10,
                'optimal_positions': 5,
                'min_position_size': 10.0
            }
    
    def log_tier_summary(self, balance: float, current_positions: int) -> None:
        """
        Log comprehensive tier summary.
        
        Args:
            balance: Current account balance
            current_positions: Number of open positions
        """
        if self.tier_hierarchy:
            self.tier_hierarchy.log_tier_summary(balance, current_positions)
        else:
            logger.info(f"Balance: ${balance:.2f}, Positions: {current_positions}")
    
    def get_entry_rejection_stats(self) -> Dict:
        """Get validation statistics"""
        if self.entry_validator:
            return self.entry_validator.get_validation_stats()
        return {}
    
    def log_validation_summary(self) -> None:
        """Log validation statistics summary"""
        if self.entry_validator:
            self.entry_validator.log_validation_summary()


# ============================================================================
# GLOBAL INSTANCE
# ============================================================================
_position_manager_instance: Optional[TierAwarePositionManager] = None


def get_tier_aware_position_manager() -> TierAwarePositionManager:
    """Get or create the global TierAwarePositionManager instance"""
    global _position_manager_instance
    if _position_manager_instance is None:
        _position_manager_instance = TierAwarePositionManager()
    return _position_manager_instance


# ============================================================================
# CONVENIENCE FUNCTIONS FOR INTEGRATION
# ============================================================================

def should_allow_new_position(balance: float, current_positions: int,
                             proposed_size: float, symbol: str,
                             signal_quality: float = 75.0,
                             **kwargs) -> Tuple[bool, str, str]:
    """
    Check if a new position should be allowed.
    
    Returns:
        Tuple of (allowed, rejection_code, rejection_message)
    """
    manager = get_tier_aware_position_manager()
    
    result = manager.validate_new_position(
        balance=balance,
        current_position_count=current_positions,
        proposed_size=proposed_size,
        symbol=symbol,
        signal_quality=signal_quality,
        **kwargs
    )
    
    return (result.passed, result.rejection_code.value, result.rejection_message)


def get_tier_position_limits(balance: float) -> Tuple[int, int]:
    """
    Get position limits for balance.
    
    Returns:
        Tuple of (optimal_positions, max_positions)
    """
    manager = get_tier_aware_position_manager()
    optimal = manager.get_optimal_positions(balance)
    maximum = manager.get_max_positions(balance)
    return (optimal, maximum)


def calculate_tier_position_size(balance: float, current_positions: int,
                                stop_loss_pct: Optional[float] = None) -> Tuple[float, Dict]:
    """
    Calculate position size using tier-aware logic WITH risk containment.
    
    Args:
        balance: Account balance
        current_positions: Number of open positions
        stop_loss_pct: Stop loss as decimal (0.05 = 5%), optional
    
    Returns:
        Tuple of (position_size, calculation_details)
    """
    manager = get_tier_aware_position_manager()
    return manager.calculate_tier_aware_position_size(
        balance, current_positions, stop_loss_pct=stop_loss_pct
    )


if __name__ == "__main__":
    # Demo: Test tier-aware position manager
    import logging
    logging.basicConfig(level=logging.INFO)
    
    manager = TierAwarePositionManager()
    
    print("\n" + "="*100)
    print("TIER-AWARE POSITION MANAGER - Integration Demo")
    print("="*100 + "\n")
    
    # Test balances
    test_balances = [60, 120, 300, 1500, 8000, 30000]
    
    for balance in test_balances:
        print(f"\n{'='*100}")
        print(f"Balance: ${balance:,.0f}")
        print(f"{'='*100}")
        
        # Update balance
        manager.update_balance(balance)
        
        # Get tier info
        info = manager.get_tier_info(balance)
        print(f"Tier: {info['tier']}")
        print(f"Max Positions: {info['max_positions']}")
        print(f"Optimal Positions: {info['optimal_positions']}")
        print(f"Min Position Size: ${info['min_position_size']:.2f}")
        
        # Calculate position size for first position
        size = manager.calculate_tier_aware_position_size(balance, 0)
        print(f"First Position Size: ${size:.2f} ({size/balance*100:.1f}% of balance)")
        
        # Validate a position
        result = manager.validate_new_position(
            balance=balance,
            current_position_count=0,
            proposed_size=size,
            symbol="BTC-USD",
            signal_quality=75.0
        )
        print(f"Validation: {'✅ PASSED' if result.passed else '❌ REJECTED'}")
        if not result.passed:
            print(f"  Reason: {result.rejection_code.value}")
    
    print("\n" + "="*100)
    print("Integration successful!")
    print("="*100 + "\n")
