"""
Price Validator

Validates price data freshness, integrity, and market conditions.

Author: NIJA Trading Systems
Date: January 30, 2026
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import math

from bot.validation_models import ValidationResult, ValidationLevel, ValidationCategory

logger = logging.getLogger("nija.validators.price")


class PriceValidator:
    """Validates price data and market conditions"""
    
    def __init__(
        self,
        max_price_age_seconds: int = 60,
        max_spread_pct: float = 2.0,
        max_price_change_pct: float = 10.0
    ):
        """
        Initialize price validator
        
        Args:
            max_price_age_seconds: Maximum acceptable price data age
            max_spread_pct: Maximum acceptable bid-ask spread percentage
            max_price_change_pct: Maximum acceptable price change from last known price
        """
        self.max_price_age_seconds = max_price_age_seconds
        self.max_spread_pct = max_spread_pct
        self.max_price_change_pct = max_price_change_pct
        self.last_prices: Dict[str, tuple[float, datetime]] = {}
    
    def validate_price_freshness(
        self,
        symbol: str,
        price: float,
        timestamp: Optional[datetime] = None,
        broker: str = "unknown"
    ) -> ValidationResult:
        """
        Validate that price data is fresh and recent
        
        Args:
            symbol: Trading symbol
            price: Current price
            timestamp: Price timestamp (None = current time)
            broker: Broker name
            
        Returns:
            ValidationResult
        """
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        age_seconds = (datetime.utcnow() - timestamp).total_seconds()
        
        if age_seconds > self.max_price_age_seconds:
            return ValidationResult(
                level=ValidationLevel.ERROR,
                category=ValidationCategory.DATA_INTEGRITY,
                validator_name="PriceValidator.validate_price_freshness",
                message=f"Stale price data: {age_seconds:.1f}s old (max: {self.max_price_age_seconds}s)",
                symbol=symbol,
                broker=broker,
                can_proceed=False,
                metrics={'age_seconds': age_seconds, 'max_age_seconds': self.max_price_age_seconds},
                recommended_action="Fetch fresh price data before trading"
            )
        
        return ValidationResult(
            level=ValidationLevel.PASS,
            category=ValidationCategory.DATA_INTEGRITY,
            validator_name="PriceValidator.validate_price_freshness",
            message=f"Price data is fresh ({age_seconds:.1f}s old)",
            symbol=symbol,
            broker=broker,
            metrics={'age_seconds': age_seconds}
        )
    
    def validate_price_integrity(
        self,
        symbol: str,
        price: float,
        broker: str = "unknown"
    ) -> ValidationResult:
        """
        Validate price data integrity (not NaN, not negative, etc.)
        
        Args:
            symbol: Trading symbol
            price: Current price
            broker: Broker name
            
        Returns:
            ValidationResult
        """
        # Check for invalid values
        if price is None:
            return ValidationResult(
                level=ValidationLevel.CRITICAL,
                category=ValidationCategory.DATA_INTEGRITY,
                validator_name="PriceValidator.validate_price_integrity",
                message="Price is None",
                symbol=symbol,
                broker=broker,
                can_proceed=False,
                recommended_action="Do not trade - missing price data"
            )
        
        if math.isnan(price):
            return ValidationResult(
                level=ValidationLevel.CRITICAL,
                category=ValidationCategory.DATA_INTEGRITY,
                validator_name="PriceValidator.validate_price_integrity",
                message="Price is NaN",
                symbol=symbol,
                broker=broker,
                can_proceed=False,
                recommended_action="Do not trade - corrupted price data"
            )
        
        if math.isinf(price):
            return ValidationResult(
                level=ValidationLevel.CRITICAL,
                category=ValidationCategory.DATA_INTEGRITY,
                validator_name="PriceValidator.validate_price_integrity",
                message="Price is infinite",
                symbol=symbol,
                broker=broker,
                can_proceed=False,
                recommended_action="Do not trade - corrupted price data"
            )
        
        if price <= 0:
            return ValidationResult(
                level=ValidationLevel.CRITICAL,
                category=ValidationCategory.DATA_INTEGRITY,
                validator_name="PriceValidator.validate_price_integrity",
                message=f"Price is non-positive: {price}",
                symbol=symbol,
                broker=broker,
                can_proceed=False,
                recommended_action="Do not trade - invalid price"
            )
        
        return ValidationResult(
            level=ValidationLevel.PASS,
            category=ValidationCategory.DATA_INTEGRITY,
            validator_name="PriceValidator.validate_price_integrity",
            message="Price data integrity validated",
            symbol=symbol,
            broker=broker,
            metrics={'price': price}
        )
    
    def validate_spread(
        self,
        symbol: str,
        bid: float,
        ask: float,
        broker: str = "unknown"
    ) -> ValidationResult:
        """
        Validate bid-ask spread is reasonable
        
        Args:
            symbol: Trading symbol
            bid: Bid price
            ask: Ask price
            broker: Broker name
            
        Returns:
            ValidationResult
        """
        if bid <= 0 or ask <= 0:
            return ValidationResult(
                level=ValidationLevel.ERROR,
                category=ValidationCategory.DATA_INTEGRITY,
                validator_name="PriceValidator.validate_spread",
                message=f"Invalid bid/ask: bid={bid}, ask={ask}",
                symbol=symbol,
                broker=broker,
                can_proceed=False,
                recommended_action="Do not trade - invalid spread data"
            )
        
        if ask < bid:
            return ValidationResult(
                level=ValidationLevel.ERROR,
                category=ValidationCategory.DATA_INTEGRITY,
                validator_name="PriceValidator.validate_spread",
                message=f"Inverted spread: bid={bid} > ask={ask}",
                symbol=symbol,
                broker=broker,
                can_proceed=False,
                recommended_action="Do not trade - corrupted market data"
            )
        
        mid_price = (bid + ask) / 2
        spread_pct = ((ask - bid) / mid_price) * 100
        
        if spread_pct > self.max_spread_pct:
            return ValidationResult(
                level=ValidationLevel.WARNING,
                category=ValidationCategory.PRE_TRADE,
                validator_name="PriceValidator.validate_spread",
                message=f"Wide spread: {spread_pct:.2f}% (max: {self.max_spread_pct}%)",
                symbol=symbol,
                broker=broker,
                can_proceed=True,
                metrics={'spread_pct': spread_pct, 'bid': bid, 'ask': ask},
                recommended_action="Consider using limit orders to avoid excessive slippage"
            )
        
        return ValidationResult(
            level=ValidationLevel.PASS,
            category=ValidationCategory.PRE_TRADE,
            validator_name="PriceValidator.validate_spread",
            message=f"Spread acceptable: {spread_pct:.2f}%",
            symbol=symbol,
            broker=broker,
            metrics={'spread_pct': spread_pct, 'bid': bid, 'ask': ask}
        )
    
    def validate_price_movement(
        self,
        symbol: str,
        current_price: float,
        broker: str = "unknown"
    ) -> ValidationResult:
        """
        Validate price movement from last known price
        
        Args:
            symbol: Trading symbol
            current_price: Current price
            broker: Broker name
            
        Returns:
            ValidationResult
        """
        key = f"{broker}:{symbol}"
        
        # Store current price
        last_data = self.last_prices.get(key)
        self.last_prices[key] = (current_price, datetime.utcnow())
        
        # First time seeing this price
        if last_data is None:
            return ValidationResult(
                level=ValidationLevel.INFO,
                category=ValidationCategory.DATA_INTEGRITY,
                validator_name="PriceValidator.validate_price_movement",
                message="First price observation, baseline established",
                symbol=symbol,
                broker=broker,
                metrics={'price': current_price}
            )
        
        last_price, last_time = last_data
        
        # Calculate price change
        price_change_pct = abs((current_price - last_price) / last_price) * 100
        
        if price_change_pct > self.max_price_change_pct:
            return ValidationResult(
                level=ValidationLevel.WARNING,
                category=ValidationCategory.DATA_INTEGRITY,
                validator_name="PriceValidator.validate_price_movement",
                message=f"Large price movement: {price_change_pct:.2f}% (max: {self.max_price_change_pct}%)",
                symbol=symbol,
                broker=broker,
                can_proceed=True,
                metrics={
                    'price_change_pct': price_change_pct,
                    'last_price': last_price,
                    'current_price': current_price
                },
                recommended_action="Verify market conditions before trading - potential volatility spike"
            )
        
        return ValidationResult(
            level=ValidationLevel.PASS,
            category=ValidationCategory.DATA_INTEGRITY,
            validator_name="PriceValidator.validate_price_movement",
            message=f"Price movement normal: {price_change_pct:.2f}%",
            symbol=symbol,
            broker=broker,
            metrics={'price_change_pct': price_change_pct}
        )
