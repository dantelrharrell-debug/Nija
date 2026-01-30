"""
Position Validator

Validates position state and reconciliation with broker.

Author: NIJA Trading Systems
Date: January 30, 2026
"""

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

from bot.validation_models import ValidationResult, ValidationLevel, ValidationCategory

logger = logging.getLogger("nija.validators.position")


class PositionValidator:
    """Validates position state and broker reconciliation"""
    
    def __init__(
        self,
        max_position_size_pct: float = 50.0,
        max_position_drift_pct: float = 5.0
    ):
        """
        Initialize position validator
        
        Args:
            max_position_size_pct: Maximum position size as % of account
            max_position_drift_pct: Maximum acceptable drift between local and broker positions
        """
        self.max_position_size_pct = max_position_size_pct
        self.max_position_drift_pct = max_position_drift_pct
        self.last_reconciliation: Dict[str, datetime] = {}
    
    def validate_position_size(
        self,
        symbol: str,
        size: float,
        account_balance: float,
        current_price: float,
        broker: str = "unknown",
        account_id: str = "default"
    ) -> ValidationResult:
        """
        Validate position size against account balance
        
        Args:
            symbol: Trading symbol
            size: Position size
            account_balance: Account balance
            current_price: Current price
            broker: Broker name
            account_id: Account identifier
            
        Returns:
            ValidationResult
        """
        if account_balance <= 0:
            return ValidationResult(
                level=ValidationLevel.ERROR,
                category=ValidationCategory.RISK,
                validator_name="PositionValidator.validate_position_size",
                message="Invalid account balance",
                symbol=symbol,
                broker=broker,
                account_id=account_id,
                can_proceed=False,
                recommended_action="Verify account balance"
            )
        
        position_value = size * current_price
        position_pct = (position_value / account_balance) * 100
        
        if position_pct > self.max_position_size_pct:
            return ValidationResult(
                level=ValidationLevel.ERROR,
                category=ValidationCategory.RISK,
                validator_name="PositionValidator.validate_position_size",
                message=f"Position too large: {position_pct:.1f}% of account (max: {self.max_position_size_pct}%)",
                symbol=symbol,
                broker=broker,
                account_id=account_id,
                can_proceed=False,
                metrics={
                    'position_value': position_value,
                    'account_balance': account_balance,
                    'position_pct': position_pct
                },
                recommended_action="Reduce position size to comply with risk limits"
            )
        
        return ValidationResult(
            level=ValidationLevel.PASS,
            category=ValidationCategory.RISK,
            validator_name="PositionValidator.validate_position_size",
            message=f"Position size acceptable: {position_pct:.1f}% of account",
            symbol=symbol,
            broker=broker,
            account_id=account_id,
            metrics={'position_pct': position_pct}
        )
    
    def validate_position_reconciliation(
        self,
        symbol: str,
        local_size: float,
        broker_size: float,
        broker: str = "unknown",
        account_id: str = "default"
    ) -> ValidationResult:
        """
        Validate local position matches broker position
        
        Args:
            symbol: Trading symbol
            local_size: Local position size
            broker_size: Broker-reported position size
            broker: Broker name
            account_id: Account identifier
            
        Returns:
            ValidationResult
        """
        key = f"{broker}:{account_id}:{symbol}"
        self.last_reconciliation[key] = datetime.utcnow()
        
        # Calculate drift
        if broker_size == 0:
            if local_size != 0:
                return ValidationResult(
                    level=ValidationLevel.ERROR,
                    category=ValidationCategory.POSITION_RECONCILIATION,
                    validator_name="PositionValidator.validate_position_reconciliation",
                    message=f"Position mismatch: local={local_size}, broker=0",
                    symbol=symbol,
                    broker=broker,
                    account_id=account_id,
                    can_proceed=False,
                    metrics={'local_size': local_size, 'broker_size': broker_size},
                    recommended_action="Reconcile position - broker shows no position but local state has position"
                )
        else:
            drift_pct = abs((local_size - broker_size) / broker_size) * 100
            
            if drift_pct > self.max_position_drift_pct:
                return ValidationResult(
                    level=ValidationLevel.ERROR,
                    category=ValidationCategory.POSITION_RECONCILIATION,
                    validator_name="PositionValidator.validate_position_reconciliation",
                    message=f"Position drift: {drift_pct:.2f}% (max: {self.max_position_drift_pct}%)",
                    symbol=symbol,
                    broker=broker,
                    account_id=account_id,
                    can_proceed=False,
                    metrics={
                        'local_size': local_size,
                        'broker_size': broker_size,
                        'drift_pct': drift_pct
                    },
                    recommended_action="Reconcile position state with broker"
                )
        
        return ValidationResult(
            level=ValidationLevel.PASS,
            category=ValidationCategory.POSITION_RECONCILIATION,
            validator_name="PositionValidator.validate_position_reconciliation",
            message=f"Position reconciled: local={local_size}, broker={broker_size}",
            symbol=symbol,
            broker=broker,
            account_id=account_id,
            metrics={'local_size': local_size, 'broker_size': broker_size}
        )
    
    def validate_unrealized_pnl(
        self,
        symbol: str,
        entry_price: float,
        current_price: float,
        size: float,
        side: str,
        calculated_pnl: float,
        broker: str = "unknown",
        account_id: str = "default"
    ) -> ValidationResult:
        """
        Validate unrealized P&L calculation
        
        Args:
            symbol: Trading symbol
            entry_price: Entry price
            current_price: Current price
            size: Position size
            side: 'buy' or 'sell'
            calculated_pnl: Calculated P&L to validate
            broker: Broker name
            account_id: Account identifier
            
        Returns:
            ValidationResult
        """
        # Calculate expected P&L
        if side in ['buy', 'long']:
            expected_pnl = (current_price - entry_price) * size
        else:  # sell/short
            expected_pnl = (entry_price - current_price) * size
        
        # Check if calculation matches
        pnl_diff = abs(calculated_pnl - expected_pnl)
        pnl_diff_pct = abs(pnl_diff / max(abs(expected_pnl), 0.01)) * 100
        
        if pnl_diff_pct > 10:  # More than 10% difference
            return ValidationResult(
                level=ValidationLevel.WARNING,
                category=ValidationCategory.POST_TRADE,
                validator_name="PositionValidator.validate_unrealized_pnl",
                message=f"P&L calculation mismatch: {pnl_diff_pct:.1f}% difference",
                symbol=symbol,
                broker=broker,
                account_id=account_id,
                metrics={
                    'calculated_pnl': calculated_pnl,
                    'expected_pnl': expected_pnl,
                    'difference': pnl_diff,
                    'difference_pct': pnl_diff_pct
                },
                recommended_action="Verify P&L calculation logic"
            )
        
        return ValidationResult(
            level=ValidationLevel.PASS,
            category=ValidationCategory.POST_TRADE,
            validator_name="PositionValidator.validate_unrealized_pnl",
            message="P&L calculation validated",
            symbol=symbol,
            broker=broker,
            account_id=account_id,
            metrics={'pnl': calculated_pnl}
        )
    
    def validate_position_state_machine(
        self,
        symbol: str,
        current_state: str,
        new_state: str,
        broker: str = "unknown",
        account_id: str = "default"
    ) -> ValidationResult:
        """
        Validate position state transitions
        
        Args:
            symbol: Trading symbol
            current_state: Current state
            new_state: New state to transition to
            broker: Broker name
            account_id: Account identifier
            
        Returns:
            ValidationResult
        """
        # Valid state transitions
        valid_transitions = {
            'none': ['opening'],
            'opening': ['open', 'failed'],
            'open': ['closing', 'liquidating'],
            'closing': ['closed', 'failed'],
            'liquidating': ['closed'],
            'closed': ['none'],
            'failed': ['none']
        }
        
        allowed_states = valid_transitions.get(current_state, [])
        
        if new_state not in allowed_states:
            return ValidationResult(
                level=ValidationLevel.ERROR,
                category=ValidationCategory.POSITION_RECONCILIATION,
                validator_name="PositionValidator.validate_position_state_machine",
                message=f"Invalid state transition: {current_state} → {new_state}",
                symbol=symbol,
                broker=broker,
                account_id=account_id,
                can_proceed=False,
                details={
                    'current_state': current_state,
                    'new_state': new_state,
                    'allowed_states': allowed_states
                },
                recommended_action="Review position state logic"
            )
        
        return ValidationResult(
            level=ValidationLevel.PASS,
            category=ValidationCategory.POSITION_RECONCILIATION,
            validator_name="PositionValidator.validate_position_state_machine",
            message=f"Valid state transition: {current_state} → {new_state}",
            symbol=symbol,
            broker=broker,
            account_id=account_id
        )
