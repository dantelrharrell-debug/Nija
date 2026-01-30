"""
Risk Validator

Validates risk limits and portfolio risk metrics.

Author: NIJA Trading Systems
Date: January 30, 2026
"""

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

from bot.validation_models import ValidationResult, ValidationLevel, ValidationCategory

logger = logging.getLogger("nija.validators.risk")


class RiskValidator:
    """Validates risk limits and portfolio metrics"""
    
    def __init__(
        self,
        max_daily_loss_pct: float = 5.0,
        max_drawdown_pct: float = 15.0,
        max_open_positions: int = 10,
        max_leverage: float = 3.0
    ):
        """
        Initialize risk validator
        
        Args:
            max_daily_loss_pct: Maximum daily loss as % of starting balance
            max_drawdown_pct: Maximum drawdown as % from peak
            max_open_positions: Maximum number of open positions
            max_leverage: Maximum leverage allowed
        """
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.max_open_positions = max_open_positions
        self.max_leverage = max_leverage
    
    def validate_daily_loss_limit(
        self,
        starting_balance: float,
        current_balance: float,
        daily_pnl: float,
        broker: str = "unknown",
        account_id: str = "default"
    ) -> ValidationResult:
        """
        Validate daily loss limit
        
        Args:
            starting_balance: Starting balance for the day
            current_balance: Current balance
            daily_pnl: Daily P&L
            broker: Broker name
            account_id: Account identifier
            
        Returns:
            ValidationResult
        """
        if starting_balance <= 0:
            return ValidationResult(
                level=ValidationLevel.ERROR,
                category=ValidationCategory.RISK,
                validator_name="RiskValidator.validate_daily_loss_limit",
                message="Invalid starting balance",
                broker=broker,
                account_id=account_id,
                can_proceed=False
            )
        
        loss_pct = (daily_pnl / starting_balance) * 100
        
        if loss_pct < -self.max_daily_loss_pct:
            return ValidationResult(
                level=ValidationLevel.CRITICAL,
                category=ValidationCategory.CIRCUIT_BREAKER,
                validator_name="RiskValidator.validate_daily_loss_limit",
                message=f"Daily loss limit breached: {loss_pct:.2f}% (max: -{self.max_daily_loss_pct}%)",
                broker=broker,
                account_id=account_id,
                can_proceed=False,
                metrics={
                    'starting_balance': starting_balance,
                    'current_balance': current_balance,
                    'daily_pnl': daily_pnl,
                    'loss_pct': loss_pct
                },
                recommended_action="STOP TRADING - Daily loss limit reached. Review trades and reset tomorrow."
            )
        
        # Warning at 80% of limit
        warning_threshold = self.max_daily_loss_pct * 0.8
        if loss_pct < -warning_threshold:
            return ValidationResult(
                level=ValidationLevel.WARNING,
                category=ValidationCategory.RISK,
                validator_name="RiskValidator.validate_daily_loss_limit",
                message=f"Approaching daily loss limit: {loss_pct:.2f}% (max: -{self.max_daily_loss_pct}%)",
                broker=broker,
                account_id=account_id,
                metrics={'loss_pct': loss_pct},
                recommended_action="Reduce position sizes or stop trading"
            )
        
        return ValidationResult(
            level=ValidationLevel.PASS,
            category=ValidationCategory.RISK,
            validator_name="RiskValidator.validate_daily_loss_limit",
            message=f"Daily loss within limits: {loss_pct:.2f}%",
            broker=broker,
            account_id=account_id,
            metrics={'loss_pct': loss_pct}
        )
    
    def validate_drawdown_limit(
        self,
        peak_balance: float,
        current_balance: float,
        broker: str = "unknown",
        account_id: str = "default"
    ) -> ValidationResult:
        """
        Validate maximum drawdown limit
        
        Args:
            peak_balance: Peak balance (all-time high)
            current_balance: Current balance
            broker: Broker name
            account_id: Account identifier
            
        Returns:
            ValidationResult
        """
        if peak_balance <= 0:
            return ValidationResult(
                level=ValidationLevel.ERROR,
                category=ValidationCategory.RISK,
                validator_name="RiskValidator.validate_drawdown_limit",
                message="Invalid peak balance",
                broker=broker,
                account_id=account_id,
                can_proceed=False
            )
        
        drawdown_pct = ((peak_balance - current_balance) / peak_balance) * 100
        
        if drawdown_pct > self.max_drawdown_pct:
            return ValidationResult(
                level=ValidationLevel.CRITICAL,
                category=ValidationCategory.CIRCUIT_BREAKER,
                validator_name="RiskValidator.validate_drawdown_limit",
                message=f"Max drawdown exceeded: {drawdown_pct:.2f}% (max: {self.max_drawdown_pct}%)",
                broker=broker,
                account_id=account_id,
                can_proceed=False,
                metrics={
                    'peak_balance': peak_balance,
                    'current_balance': current_balance,
                    'drawdown_pct': drawdown_pct
                },
                recommended_action="STOP TRADING - Maximum drawdown reached. Review strategy."
            )
        
        # Warning at 80% of limit
        warning_threshold = self.max_drawdown_pct * 0.8
        if drawdown_pct > warning_threshold:
            return ValidationResult(
                level=ValidationLevel.WARNING,
                category=ValidationCategory.RISK,
                validator_name="RiskValidator.validate_drawdown_limit",
                message=f"Approaching max drawdown: {drawdown_pct:.2f}% (max: {self.max_drawdown_pct}%)",
                broker=broker,
                account_id=account_id,
                metrics={'drawdown_pct': drawdown_pct},
                recommended_action="Reduce trading activity and review strategy"
            )
        
        return ValidationResult(
            level=ValidationLevel.PASS,
            category=ValidationCategory.RISK,
            validator_name="RiskValidator.validate_drawdown_limit",
            message=f"Drawdown within limits: {drawdown_pct:.2f}%",
            broker=broker,
            account_id=account_id,
            metrics={'drawdown_pct': drawdown_pct}
        )
    
    def validate_position_count(
        self,
        open_positions: int,
        broker: str = "unknown",
        account_id: str = "default"
    ) -> ValidationResult:
        """
        Validate number of open positions
        
        Args:
            open_positions: Current number of open positions
            broker: Broker name
            account_id: Account identifier
            
        Returns:
            ValidationResult
        """
        if open_positions > self.max_open_positions:
            return ValidationResult(
                level=ValidationLevel.ERROR,
                category=ValidationCategory.RISK,
                validator_name="RiskValidator.validate_position_count",
                message=f"Too many open positions: {open_positions} (max: {self.max_open_positions})",
                broker=broker,
                account_id=account_id,
                can_proceed=False,
                metrics={'open_positions': open_positions},
                recommended_action="Close some positions before opening new ones"
            )
        
        # Warning at 80% of limit
        warning_threshold = int(self.max_open_positions * 0.8)
        if open_positions > warning_threshold:
            return ValidationResult(
                level=ValidationLevel.WARNING,
                category=ValidationCategory.RISK,
                validator_name="RiskValidator.validate_position_count",
                message=f"High number of open positions: {open_positions} (max: {self.max_open_positions})",
                broker=broker,
                account_id=account_id,
                metrics={'open_positions': open_positions},
                recommended_action="Consider consolidating positions"
            )
        
        return ValidationResult(
            level=ValidationLevel.PASS,
            category=ValidationCategory.RISK,
            validator_name="RiskValidator.validate_position_count",
            message=f"Position count acceptable: {open_positions}",
            broker=broker,
            account_id=account_id,
            metrics={'open_positions': open_positions}
        )
    
    def validate_leverage(
        self,
        total_position_value: float,
        account_balance: float,
        broker: str = "unknown",
        account_id: str = "default"
    ) -> ValidationResult:
        """
        Validate portfolio leverage
        
        Args:
            total_position_value: Total value of all positions
            account_balance: Account balance
            broker: Broker name
            account_id: Account identifier
            
        Returns:
            ValidationResult
        """
        if account_balance <= 0:
            return ValidationResult(
                level=ValidationLevel.ERROR,
                category=ValidationCategory.RISK,
                validator_name="RiskValidator.validate_leverage",
                message="Invalid account balance",
                broker=broker,
                account_id=account_id,
                can_proceed=False
            )
        
        leverage = total_position_value / account_balance
        
        if leverage > self.max_leverage:
            return ValidationResult(
                level=ValidationLevel.ERROR,
                category=ValidationCategory.RISK,
                validator_name="RiskValidator.validate_leverage",
                message=f"Leverage too high: {leverage:.2f}x (max: {self.max_leverage}x)",
                broker=broker,
                account_id=account_id,
                can_proceed=False,
                metrics={
                    'leverage': leverage,
                    'total_position_value': total_position_value,
                    'account_balance': account_balance
                },
                recommended_action="Reduce position sizes to lower leverage"
            )
        
        # Warning at 80% of limit
        warning_threshold = self.max_leverage * 0.8
        if leverage > warning_threshold:
            return ValidationResult(
                level=ValidationLevel.WARNING,
                category=ValidationCategory.RISK,
                validator_name="RiskValidator.validate_leverage",
                message=f"Leverage approaching limit: {leverage:.2f}x (max: {self.max_leverage}x)",
                broker=broker,
                account_id=account_id,
                metrics={'leverage': leverage},
                recommended_action="Monitor leverage closely"
            )
        
        return ValidationResult(
            level=ValidationLevel.PASS,
            category=ValidationCategory.RISK,
            validator_name="RiskValidator.validate_leverage",
            message=f"Leverage acceptable: {leverage:.2f}x",
            broker=broker,
            account_id=account_id,
            metrics={'leverage': leverage}
        )
    
    def validate_margin_requirements(
        self,
        required_margin: float,
        available_margin: float,
        broker: str = "unknown",
        account_id: str = "default"
    ) -> ValidationResult:
        """
        Validate margin requirements
        
        Args:
            required_margin: Required margin for position
            available_margin: Available margin in account
            broker: Broker name
            account_id: Account identifier
            
        Returns:
            ValidationResult
        """
        if available_margin < required_margin:
            return ValidationResult(
                level=ValidationLevel.ERROR,
                category=ValidationCategory.RISK,
                validator_name="RiskValidator.validate_margin_requirements",
                message=f"Insufficient margin: need ${required_margin:.2f}, have ${available_margin:.2f}",
                broker=broker,
                account_id=account_id,
                can_proceed=False,
                metrics={
                    'required_margin': required_margin,
                    'available_margin': available_margin,
                    'shortfall': required_margin - available_margin
                },
                recommended_action="Reduce position size or add funds"
            )
        
        # Warning if margin utilization > 80%
        margin_utilization_pct = (required_margin / available_margin) * 100
        if margin_utilization_pct > 80:
            return ValidationResult(
                level=ValidationLevel.WARNING,
                category=ValidationCategory.RISK,
                validator_name="RiskValidator.validate_margin_requirements",
                message=f"High margin utilization: {margin_utilization_pct:.1f}%",
                broker=broker,
                account_id=account_id,
                metrics={'margin_utilization_pct': margin_utilization_pct},
                recommended_action="Monitor margin closely to avoid liquidation risk"
            )
        
        return ValidationResult(
            level=ValidationLevel.PASS,
            category=ValidationCategory.RISK,
            validator_name="RiskValidator.validate_margin_requirements",
            message=f"Margin sufficient: {margin_utilization_pct:.1f}% utilization",
            broker=broker,
            account_id=account_id,
            metrics={'margin_utilization_pct': margin_utilization_pct}
        )
