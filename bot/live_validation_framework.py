"""
Live Validation Framework

Comprehensive validation framework for live trading operations.
Orchestrates all validators to ensure safe, reliable trading.

Author: NIJA Trading Systems
Date: January 30, 2026
"""

import logging
import time
from typing import List, Optional, Dict, Any
from datetime import datetime

from bot.validation_models import (
    ValidationResult,
    ValidationLevel,
    ValidationCategory,
    ValidationContext,
    ValidationMetrics
)
from bot.validators import (
    PriceValidator,
    PositionValidator,
    OrderValidator,
    RiskValidator,
    FeeValidator
)

logger = logging.getLogger("nija.validation_framework")


class LiveValidationFramework:
    """
    Comprehensive live trading validation framework
    
    Provides:
    - Pre-trade validation
    - Order execution validation
    - Post-trade validation
    - Real-time monitoring
    - Risk validation
    """
    
    def __init__(
        self,
        # Price validator config
        max_price_age_seconds: int = 60,
        max_spread_pct: float = 2.0,
        max_price_change_pct: float = 10.0,
        
        # Order validator config
        order_timeout_seconds: int = 300,
        enable_idempotency: bool = True,
        
        # Position validator config
        max_position_size_pct: float = 50.0,
        max_position_drift_pct: float = 5.0,
        
        # Risk validator config
        max_daily_loss_pct: float = 5.0,
        max_drawdown_pct: float = 15.0,
        max_open_positions: int = 10,
        max_leverage: float = 3.0,
        
        # Fee validator config
        custom_fee_rates: Optional[Dict[str, float]] = None,
        min_profit_over_fees_ratio: float = 2.0,
        
        # Framework config
        enable_validation: bool = True,
        fail_fast: bool = False
    ):
        """
        Initialize Live Validation Framework
        
        Args:
            See individual validator classes for parameter documentation
            enable_validation: Enable/disable all validation
            fail_fast: Stop on first error vs collect all errors
        """
        self.enable_validation = enable_validation
        self.fail_fast = fail_fast
        
        # Initialize validators
        self.price_validator = PriceValidator(
            max_price_age_seconds=max_price_age_seconds,
            max_spread_pct=max_spread_pct,
            max_price_change_pct=max_price_change_pct
        )
        
        self.order_validator = OrderValidator(
            order_timeout_seconds=order_timeout_seconds,
            enable_idempotency=enable_idempotency
        )
        
        self.position_validator = PositionValidator(
            max_position_size_pct=max_position_size_pct,
            max_position_drift_pct=max_position_drift_pct
        )
        
        self.risk_validator = RiskValidator(
            max_daily_loss_pct=max_daily_loss_pct,
            max_drawdown_pct=max_drawdown_pct,
            max_open_positions=max_open_positions,
            max_leverage=max_leverage
        )
        
        self.fee_validator = FeeValidator(
            custom_fee_rates=custom_fee_rates,
            min_profit_over_fees_ratio=min_profit_over_fees_ratio
        )
        
        # Metrics
        self.metrics = ValidationMetrics()
        
        logger.info("=" * 80)
        logger.info("Live Validation Framework Initialized")
        logger.info("=" * 80)
        logger.info(f"  Validation Enabled: {self.enable_validation}")
        logger.info(f"  Fail Fast Mode: {self.fail_fast}")
        logger.info(f"  Price Age Limit: {max_price_age_seconds}s")
        logger.info(f"  Max Spread: {max_spread_pct}%")
        logger.info(f"  Max Daily Loss: {max_daily_loss_pct}%")
        logger.info(f"  Max Drawdown: {max_drawdown_pct}%")
        logger.info(f"  Max Open Positions: {max_open_positions}")
        logger.info(f"  Max Leverage: {max_leverage}x")
        logger.info("=" * 80)
    
    def _record_result(self, result: ValidationResult, duration_ms: float):
        """Record validation result in metrics"""
        self.metrics.record_validation(result, duration_ms)
        
        # Log result
        if result.level in [ValidationLevel.ERROR, ValidationLevel.CRITICAL]:
            logger.error(str(result))
        elif result.level == ValidationLevel.WARNING:
            logger.warning(str(result))
        elif result.level == ValidationLevel.INFO:
            logger.info(str(result))
        else:
            logger.debug(str(result))
    
    def validate_pre_trade(
        self,
        ctx: ValidationContext,
        current_price: Optional[float] = None,
        bid: Optional[float] = None,
        ask: Optional[float] = None,
        account_balance: Optional[float] = None,
        open_positions: Optional[int] = None
    ) -> List[ValidationResult]:
        """
        Run all pre-trade validations
        
        Args:
            ctx: Validation context
            current_price: Current market price
            bid: Bid price
            ask: Ask price
            account_balance: Account balance
            open_positions: Number of open positions
            
        Returns:
            List of validation results
        """
        if not self.enable_validation:
            return []
        
        results: List[ValidationResult] = []
        start_time = time.time()
        
        # Price validation
        if current_price is not None:
            # Price integrity
            result = self.price_validator.validate_price_integrity(
                symbol=ctx.symbol,
                price=current_price,
                broker=ctx.broker
            )
            duration_ms = (time.time() - start_time) * 1000
            self._record_result(result, duration_ms)
            results.append(result)
            
            if self.fail_fast and result.is_blocking():
                return results
            
            # Price freshness
            result = self.price_validator.validate_price_freshness(
                symbol=ctx.symbol,
                price=current_price,
                timestamp=ctx.timestamp,
                broker=ctx.broker
            )
            duration_ms = (time.time() - start_time) * 1000
            self._record_result(result, duration_ms)
            results.append(result)
            
            if self.fail_fast and result.is_blocking():
                return results
            
            # Price movement
            result = self.price_validator.validate_price_movement(
                symbol=ctx.symbol,
                current_price=current_price,
                broker=ctx.broker
            )
            duration_ms = (time.time() - start_time) * 1000
            self._record_result(result, duration_ms)
            results.append(result)
        
        # Spread validation
        if bid is not None and ask is not None:
            result = self.price_validator.validate_spread(
                symbol=ctx.symbol,
                bid=bid,
                ask=ask,
                broker=ctx.broker
            )
            duration_ms = (time.time() - start_time) * 1000
            self._record_result(result, duration_ms)
            results.append(result)
            
            if self.fail_fast and result.is_blocking():
                return results
        
        # Order submission validation
        result = self.order_validator.validate_order_submission(
            symbol=ctx.symbol,
            side=ctx.side,
            size=ctx.size,
            account_id=ctx.account_id,
            broker=ctx.broker,
            order_id=ctx.order_id
        )
        duration_ms = (time.time() - start_time) * 1000
        self._record_result(result, duration_ms)
        results.append(result)
        
        if self.fail_fast and result.is_blocking():
            return results
        
        # Position size validation
        if account_balance is not None and current_price is not None:
            result = self.position_validator.validate_position_size(
                symbol=ctx.symbol,
                size=ctx.size,
                account_balance=account_balance,
                current_price=current_price,
                broker=ctx.broker,
                account_id=ctx.account_id
            )
            duration_ms = (time.time() - start_time) * 1000
            self._record_result(result, duration_ms)
            results.append(result)
            
            if self.fail_fast and result.is_blocking():
                return results
        
        # Position count validation
        if open_positions is not None:
            result = self.risk_validator.validate_position_count(
                open_positions=open_positions,
                broker=ctx.broker,
                account_id=ctx.account_id
            )
            duration_ms = (time.time() - start_time) * 1000
            self._record_result(result, duration_ms)
            results.append(result)
            
            if self.fail_fast and result.is_blocking():
                return results
        
        # Fee validation
        if current_price is not None:
            result = self.fee_validator.validate_minimum_trade_size(
                size=ctx.size,
                price=current_price,
                broker=ctx.broker,
                symbol=ctx.symbol,
                account_id=ctx.account_id
            )
            duration_ms = (time.time() - start_time) * 1000
            self._record_result(result, duration_ms)
            results.append(result)
        
        return results
    
    def validate_order_execution(
        self,
        order_id: str,
        broker_response: Dict[str, Any],
        broker: str
    ) -> List[ValidationResult]:
        """
        Validate order execution
        
        Args:
            order_id: Order ID
            broker_response: Response from broker
            broker: Broker name
            
        Returns:
            List of validation results
        """
        if not self.enable_validation:
            return []
        
        results: List[ValidationResult] = []
        start_time = time.time()
        
        # Order confirmation
        result = self.order_validator.validate_order_confirmation(
            order_id=order_id,
            broker_response=broker_response,
            broker=broker
        )
        duration_ms = (time.time() - start_time) * 1000
        self._record_result(result, duration_ms)
        results.append(result)
        
        # Order timeout check
        result = self.order_validator.check_order_timeout(
            order_id=order_id,
            broker=broker
        )
        duration_ms = (time.time() - start_time) * 1000
        self._record_result(result, duration_ms)
        results.append(result)
        
        return results
    
    def validate_post_trade(
        self,
        order_id: str,
        fill_price: float,
        expected_price: Optional[float],
        broker: str,
        symbol: str,
        side: str,
        size: float,
        entry_price: Optional[float] = None,
        calculated_pnl: Optional[float] = None
    ) -> List[ValidationResult]:
        """
        Validate post-trade execution
        
        Args:
            order_id: Order ID
            fill_price: Actual fill price
            expected_price: Expected price
            broker: Broker name
            symbol: Trading symbol
            side: 'buy' or 'sell'
            size: Position size
            entry_price: Entry price for P&L validation
            calculated_pnl: Calculated P&L to validate
            
        Returns:
            List of validation results
        """
        if not self.enable_validation:
            return []
        
        results: List[ValidationResult] = []
        start_time = time.time()
        
        # Fill price validation
        result = self.order_validator.validate_fill_price(
            order_id=order_id,
            fill_price=fill_price,
            expected_price=expected_price,
            broker=broker
        )
        duration_ms = (time.time() - start_time) * 1000
        self._record_result(result, duration_ms)
        results.append(result)
        
        # P&L validation (if closing position)
        if entry_price is not None and calculated_pnl is not None:
            result = self.position_validator.validate_unrealized_pnl(
                symbol=symbol,
                entry_price=entry_price,
                current_price=fill_price,
                size=size,
                side=side,
                calculated_pnl=calculated_pnl,
                broker=broker
            )
            duration_ms = (time.time() - start_time) * 1000
            self._record_result(result, duration_ms)
            results.append(result)
        
        return results
    
    def validate_risk_limits(
        self,
        account_id: str,
        broker: str,
        starting_balance: float,
        current_balance: float,
        peak_balance: float,
        daily_pnl: float,
        open_positions: int,
        total_position_value: float
    ) -> List[ValidationResult]:
        """
        Validate risk limits
        
        Args:
            account_id: Account identifier
            broker: Broker name
            starting_balance: Starting balance for day
            current_balance: Current balance
            peak_balance: Peak balance (all-time)
            daily_pnl: Daily P&L
            open_positions: Number of open positions
            total_position_value: Total value of all positions
            
        Returns:
            List of validation results
        """
        if not self.enable_validation:
            return []
        
        results: List[ValidationResult] = []
        start_time = time.time()
        
        # Daily loss limit
        result = self.risk_validator.validate_daily_loss_limit(
            starting_balance=starting_balance,
            current_balance=current_balance,
            daily_pnl=daily_pnl,
            broker=broker,
            account_id=account_id
        )
        duration_ms = (time.time() - start_time) * 1000
        self._record_result(result, duration_ms)
        results.append(result)
        
        if self.fail_fast and result.is_blocking():
            return results
        
        # Drawdown limit
        result = self.risk_validator.validate_drawdown_limit(
            peak_balance=peak_balance,
            current_balance=current_balance,
            broker=broker,
            account_id=account_id
        )
        duration_ms = (time.time() - start_time) * 1000
        self._record_result(result, duration_ms)
        results.append(result)
        
        if self.fail_fast and result.is_blocking():
            return results
        
        # Position count
        result = self.risk_validator.validate_position_count(
            open_positions=open_positions,
            broker=broker,
            account_id=account_id
        )
        duration_ms = (time.time() - start_time) * 1000
        self._record_result(result, duration_ms)
        results.append(result)
        
        # Leverage
        result = self.risk_validator.validate_leverage(
            total_position_value=total_position_value,
            account_balance=current_balance,
            broker=broker,
            account_id=account_id
        )
        duration_ms = (time.time() - start_time) * 1000
        self._record_result(result, duration_ms)
        results.append(result)
        
        return results
    
    def record_order_submission(
        self,
        order_id: str,
        symbol: str,
        side: str,
        size: float,
        price: Optional[float],
        account_id: str,
        broker: str
    ):
        """Record order submission for tracking"""
        self.order_validator.record_order_submission(
            order_id=order_id,
            symbol=symbol,
            side=side,
            size=size,
            price=price,
            account_id=account_id,
            broker=broker
        )
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get validation metrics"""
        return self.metrics.to_dict()
    
    def get_validation_summary(self) -> str:
        """Get human-readable validation summary"""
        metrics = self.metrics.to_dict()
        
        summary = [
            "=" * 80,
            "LIVE VALIDATION FRAMEWORK - STATUS",
            "=" * 80,
            f"  Total Validations: {metrics['total_validations']}",
            f"  Pass Rate: {metrics['pass_rate_pct']:.2f}%",
            f"  Error Rate: {metrics['error_rate_pct']:.2f}%",
            f"  Avg Validation Time: {metrics['avg_validation_time_ms']:.2f}ms",
            f"  Max Validation Time: {metrics['max_validation_time_ms']:.2f}ms",
            "",
            "  By Category:",
        ]
        
        for category, count in metrics['by_category'].items():
            summary.append(f"    {category}: {count}")
        
        if metrics['recent_failures']:
            summary.append("")
            summary.append("  Recent Failures:")
            for failure in metrics['recent_failures'][-5:]:
                summary.append(f"    {failure}")
        
        summary.append("=" * 80)
        
        return "\n".join(summary)
    
    def has_blocking_results(self, results: List[ValidationResult]) -> bool:
        """Check if any results are blocking"""
        return any(result.is_blocking() for result in results)
    
    def get_blocking_results(self, results: List[ValidationResult]) -> List[ValidationResult]:
        """Get only blocking results"""
        return [result for result in results if result.is_blocking()]
    
    def cleanup(self):
        """Cleanup old data"""
        self.order_validator.cleanup_old_orders()
        logger.info("Validation framework cleanup completed")


# Singleton instance
_framework_instance: Optional[LiveValidationFramework] = None


def get_validation_framework(**kwargs) -> LiveValidationFramework:
    """
    Get singleton validation framework instance
    
    Args:
        **kwargs: Configuration parameters (only used on first call)
        
    Returns:
        LiveValidationFramework instance
    """
    global _framework_instance
    
    if _framework_instance is None:
        _framework_instance = LiveValidationFramework(**kwargs)
    
    return _framework_instance
