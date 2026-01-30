"""
Order Validator

Validates order submission, confirmation, and execution.

Author: NIJA Trading Systems
Date: January 30, 2026
"""

import logging
from typing import Optional, Dict, Any, Set
from datetime import datetime, timedelta
import hashlib

from bot.validation_models import ValidationResult, ValidationLevel, ValidationCategory

logger = logging.getLogger("nija.validators.order")


class OrderValidator:
    """Validates order execution and prevents double-execution"""
    
    def __init__(
        self,
        order_timeout_seconds: int = 300,
        enable_idempotency: bool = True
    ):
        """
        Initialize order validator
        
        Args:
            order_timeout_seconds: Maximum time before order is considered timed out
            enable_idempotency: Enable double-execution prevention
        """
        self.order_timeout_seconds = order_timeout_seconds
        self.enable_idempotency = enable_idempotency
        
        # Track submitted orders
        self.submitted_orders: Dict[str, Dict[str, Any]] = {}
        self.executed_order_hashes: Set[str] = set()
    
    def _generate_order_hash(
        self,
        symbol: str,
        side: str,
        size: float,
        account_id: str,
        broker: str
    ) -> str:
        """Generate unique hash for order to prevent duplicates"""
        order_str = f"{broker}:{account_id}:{symbol}:{side}:{size}"
        return hashlib.sha256(order_str.encode()).hexdigest()[:16]
    
    def validate_order_submission(
        self,
        symbol: str,
        side: str,
        size: float,
        account_id: str,
        broker: str,
        order_id: Optional[str] = None
    ) -> ValidationResult:
        """
        Validate order before submission
        
        Args:
            symbol: Trading symbol
            side: 'buy' or 'sell'
            size: Order size
            account_id: Account identifier
            broker: Broker name
            order_id: Optional order ID
            
        Returns:
            ValidationResult
        """
        # Validate basic parameters
        if size <= 0:
            return ValidationResult(
                level=ValidationLevel.ERROR,
                category=ValidationCategory.PRE_TRADE,
                validator_name="OrderValidator.validate_order_submission",
                message=f"Invalid order size: {size}",
                symbol=symbol,
                broker=broker,
                account_id=account_id,
                can_proceed=False,
                recommended_action="Order size must be positive"
            )
        
        if side not in ['buy', 'sell', 'long', 'short']:
            return ValidationResult(
                level=ValidationLevel.ERROR,
                category=ValidationCategory.PRE_TRADE,
                validator_name="OrderValidator.validate_order_submission",
                message=f"Invalid order side: {side}",
                symbol=symbol,
                broker=broker,
                account_id=account_id,
                can_proceed=False,
                recommended_action="Side must be 'buy' or 'sell'"
            )
        
        # Check for double execution
        if self.enable_idempotency:
            order_hash = self._generate_order_hash(symbol, side, size, account_id, broker)
            
            if order_hash in self.executed_order_hashes:
                return ValidationResult(
                    level=ValidationLevel.ERROR,
                    category=ValidationCategory.ORDER_EXECUTION,
                    validator_name="OrderValidator.validate_order_submission",
                    message="Duplicate order detected - same order already executed",
                    symbol=symbol,
                    broker=broker,
                    account_id=account_id,
                    can_proceed=False,
                    details={'order_hash': order_hash},
                    recommended_action="Do not resubmit - order already executed"
                )
        
        return ValidationResult(
            level=ValidationLevel.PASS,
            category=ValidationCategory.PRE_TRADE,
            validator_name="OrderValidator.validate_order_submission",
            message="Order submission validated",
            symbol=symbol,
            broker=broker,
            account_id=account_id,
            order_id=order_id
        )
    
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
        """
        Record order submission for tracking
        
        Args:
            order_id: Order ID from broker
            symbol: Trading symbol
            side: 'buy' or 'sell'
            size: Order size
            price: Order price
            account_id: Account identifier
            broker: Broker name
        """
        self.submitted_orders[order_id] = {
            'symbol': symbol,
            'side': side,
            'size': size,
            'price': price,
            'account_id': account_id,
            'broker': broker,
            'submission_time': datetime.utcnow(),
            'status': 'pending'
        }
        
        logger.info(f"Order recorded: {order_id} - {symbol} {side} {size}")
    
    def validate_order_confirmation(
        self,
        order_id: str,
        broker_response: Dict[str, Any],
        broker: str
    ) -> ValidationResult:
        """
        Validate order confirmation from broker
        
        Args:
            order_id: Order ID
            broker_response: Response from broker API
            broker: Broker name
            
        Returns:
            ValidationResult
        """
        # Check if order was tracked
        order_data = self.submitted_orders.get(order_id)
        
        if order_data is None:
            return ValidationResult(
                level=ValidationLevel.WARNING,
                category=ValidationCategory.ORDER_EXECUTION,
                validator_name="OrderValidator.validate_order_confirmation",
                message="Order confirmation for untracked order",
                broker=broker,
                order_id=order_id,
                details={'broker_response': broker_response},
                recommended_action="Review order tracking system"
            )
        
        # Check for broker-specific confirmation fields
        # This is a generic check - extend for specific brokers
        if not broker_response:
            return ValidationResult(
                level=ValidationLevel.ERROR,
                category=ValidationCategory.ORDER_EXECUTION,
                validator_name="OrderValidator.validate_order_confirmation",
                message="Empty broker response",
                broker=broker,
                order_id=order_id,
                symbol=order_data['symbol'],
                account_id=order_data['account_id'],
                can_proceed=False,
                recommended_action="Check broker connectivity and retry"
            )
        
        # Update order status
        order_data['status'] = 'confirmed'
        order_data['confirmation_time'] = datetime.utcnow()
        order_data['broker_response'] = broker_response
        
        return ValidationResult(
            level=ValidationLevel.PASS,
            category=ValidationCategory.ORDER_EXECUTION,
            validator_name="OrderValidator.validate_order_confirmation",
            message="Order confirmation validated",
            broker=broker,
            order_id=order_id,
            symbol=order_data['symbol'],
            account_id=order_data['account_id']
        )
    
    def validate_fill_price(
        self,
        order_id: str,
        fill_price: float,
        expected_price: Optional[float],
        max_slippage_pct: float = 1.0,
        broker: str = "unknown"
    ) -> ValidationResult:
        """
        Validate order fill price against expected price
        
        Args:
            order_id: Order ID
            fill_price: Actual fill price
            expected_price: Expected price (None = skip check)
            max_slippage_pct: Maximum acceptable slippage percentage
            broker: Broker name
            
        Returns:
            ValidationResult
        """
        order_data = self.submitted_orders.get(order_id, {})
        symbol = order_data.get('symbol', 'unknown')
        side = order_data.get('side', 'unknown')
        
        # Validate fill price integrity
        if fill_price <= 0:
            return ValidationResult(
                level=ValidationLevel.ERROR,
                category=ValidationCategory.POST_TRADE,
                validator_name="OrderValidator.validate_fill_price",
                message=f"Invalid fill price: {fill_price}",
                broker=broker,
                order_id=order_id,
                symbol=symbol,
                can_proceed=False,
                recommended_action="Verify order fill with broker"
            )
        
        # Check slippage if expected price provided
        if expected_price is not None and expected_price > 0:
            slippage_pct = abs((fill_price - expected_price) / expected_price) * 100
            
            # For buys, higher fill price is bad slippage
            # For sells, lower fill price is bad slippage
            if side in ['buy', 'long']:
                actual_slippage = ((fill_price - expected_price) / expected_price) * 100
            else:
                actual_slippage = ((expected_price - fill_price) / expected_price) * 100
            
            if slippage_pct > max_slippage_pct:
                level = ValidationLevel.WARNING if slippage_pct < max_slippage_pct * 2 else ValidationLevel.ERROR
                
                return ValidationResult(
                    level=level,
                    category=ValidationCategory.POST_TRADE,
                    validator_name="OrderValidator.validate_fill_price",
                    message=f"High slippage: {slippage_pct:.2f}% (max: {max_slippage_pct}%)",
                    broker=broker,
                    order_id=order_id,
                    symbol=symbol,
                    can_proceed=(level == ValidationLevel.WARNING),
                    metrics={
                        'fill_price': fill_price,
                        'expected_price': expected_price,
                        'slippage_pct': slippage_pct,
                        'actual_slippage': actual_slippage
                    },
                    recommended_action="Consider using limit orders to control execution price"
                )
        
        # Update order with fill price
        if order_id in self.submitted_orders:
            self.submitted_orders[order_id]['fill_price'] = fill_price
            self.submitted_orders[order_id]['fill_time'] = datetime.utcnow()
            
            # Mark as executed for idempotency
            if self.enable_idempotency:
                order_hash = self._generate_order_hash(
                    order_data['symbol'],
                    order_data['side'],
                    order_data['size'],
                    order_data['account_id'],
                    order_data['broker']
                )
                self.executed_order_hashes.add(order_hash)
        
        return ValidationResult(
            level=ValidationLevel.PASS,
            category=ValidationCategory.POST_TRADE,
            validator_name="OrderValidator.validate_fill_price",
            message="Fill price validated",
            broker=broker,
            order_id=order_id,
            symbol=symbol,
            metrics={'fill_price': fill_price}
        )
    
    def check_order_timeout(
        self,
        order_id: str,
        broker: str = "unknown"
    ) -> ValidationResult:
        """
        Check if order has timed out
        
        Args:
            order_id: Order ID
            broker: Broker name
            
        Returns:
            ValidationResult
        """
        order_data = self.submitted_orders.get(order_id)
        
        if order_data is None:
            return ValidationResult(
                level=ValidationLevel.INFO,
                category=ValidationCategory.ORDER_EXECUTION,
                validator_name="OrderValidator.check_order_timeout",
                message="Order not tracked",
                broker=broker,
                order_id=order_id
            )
        
        submission_time = order_data['submission_time']
        age_seconds = (datetime.utcnow() - submission_time).total_seconds()
        
        if age_seconds > self.order_timeout_seconds:
            return ValidationResult(
                level=ValidationLevel.WARNING,
                category=ValidationCategory.ORDER_EXECUTION,
                validator_name="OrderValidator.check_order_timeout",
                message=f"Order timeout: {age_seconds:.1f}s (max: {self.order_timeout_seconds}s)",
                broker=broker,
                order_id=order_id,
                symbol=order_data['symbol'],
                account_id=order_data['account_id'],
                metrics={'age_seconds': age_seconds},
                recommended_action="Cancel pending order and retry if needed"
            )
        
        return ValidationResult(
            level=ValidationLevel.PASS,
            category=ValidationCategory.ORDER_EXECUTION,
            validator_name="OrderValidator.check_order_timeout",
            message=f"Order age acceptable: {age_seconds:.1f}s",
            broker=broker,
            order_id=order_id,
            symbol=order_data['symbol'],
            metrics={'age_seconds': age_seconds}
        )
    
    def cleanup_old_orders(self, max_age_hours: int = 24):
        """Remove old order records from memory"""
        cutoff_time = datetime.utcnow() - timedelta(hours=max_age_hours)
        
        orders_to_remove = [
            order_id for order_id, data in self.submitted_orders.items()
            if data['submission_time'] < cutoff_time
        ]
        
        for order_id in orders_to_remove:
            del self.submitted_orders[order_id]
        
        if orders_to_remove:
            logger.info(f"Cleaned up {len(orders_to_remove)} old order records")
