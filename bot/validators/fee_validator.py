"""
Fee Validator

Validates fee calculations and profitability checks.

Author: NIJA Trading Systems
Date: January 30, 2026
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime

from bot.validation_models import ValidationResult, ValidationLevel, ValidationCategory

logger = logging.getLogger("nija.validators.fee")


class FeeValidator:
    """Validates fees and profitability"""
    
    # Default fee rates by broker (as percentage)
    DEFAULT_FEE_RATES = {
        'coinbase': 0.60,  # 0.60% taker fee
        'kraken': 0.26,    # 0.26% taker fee
        'binance': 0.10,   # 0.10% taker fee
        'okx': 0.10,       # 0.10% taker fee
        'alpaca': 0.00     # No commission
    }
    
    def __init__(
        self,
        custom_fee_rates: Optional[Dict[str, float]] = None,
        min_profit_over_fees_ratio: float = 2.0
    ):
        """
        Initialize fee validator
        
        Args:
            custom_fee_rates: Custom fee rates by broker (overrides defaults)
            min_profit_over_fees_ratio: Minimum ratio of profit to total fees
        """
        self.fee_rates = self.DEFAULT_FEE_RATES.copy()
        if custom_fee_rates:
            self.fee_rates.update(custom_fee_rates)
        
        self.min_profit_over_fees_ratio = min_profit_over_fees_ratio
    
    def get_fee_rate(self, broker: str) -> float:
        """Get fee rate for broker"""
        return self.fee_rates.get(broker.lower(), 0.30)  # Default to 0.30% if unknown
    
    def calculate_entry_fee(
        self,
        size: float,
        price: float,
        broker: str
    ) -> float:
        """
        Calculate entry fee
        
        Args:
            size: Position size
            price: Entry price
            broker: Broker name
            
        Returns:
            Entry fee amount
        """
        fee_rate = self.get_fee_rate(broker)
        order_value = size * price
        return order_value * (fee_rate / 100)
    
    def calculate_exit_fee(
        self,
        size: float,
        price: float,
        broker: str
    ) -> float:
        """
        Calculate exit fee
        
        Args:
            size: Position size
            price: Exit price
            broker: Broker name
            
        Returns:
            Exit fee amount
        """
        fee_rate = self.get_fee_rate(broker)
        order_value = size * price
        return order_value * (fee_rate / 100)
    
    def calculate_total_fees(
        self,
        entry_size: float,
        entry_price: float,
        exit_price: float,
        broker: str
    ) -> float:
        """
        Calculate total fees for round trip
        
        Args:
            entry_size: Position size
            entry_price: Entry price
            exit_price: Exit price
            broker: Broker name
            
        Returns:
            Total fees (entry + exit)
        """
        entry_fee = self.calculate_entry_fee(entry_size, entry_price, broker)
        exit_fee = self.calculate_exit_fee(entry_size, exit_price, broker)
        return entry_fee + exit_fee
    
    def validate_fee_calculation(
        self,
        calculated_fee: float,
        order_value: float,
        broker: str,
        symbol: str = "unknown",
        account_id: str = "default"
    ) -> ValidationResult:
        """
        Validate fee calculation
        
        Args:
            calculated_fee: Calculated fee amount
            order_value: Order value
            broker: Broker name
            symbol: Trading symbol
            account_id: Account identifier
            
        Returns:
            ValidationResult
        """
        expected_fee = order_value * (self.get_fee_rate(broker) / 100)
        fee_diff_pct = abs((calculated_fee - expected_fee) / max(expected_fee, 0.01)) * 100
        
        if fee_diff_pct > 20:  # More than 20% difference
            return ValidationResult(
                level=ValidationLevel.WARNING,
                category=ValidationCategory.FEE_VALIDATION,
                validator_name="FeeValidator.validate_fee_calculation",
                message=f"Fee calculation mismatch: {fee_diff_pct:.1f}% difference",
                symbol=symbol,
                broker=broker,
                account_id=account_id,
                metrics={
                    'calculated_fee': calculated_fee,
                    'expected_fee': expected_fee,
                    'difference_pct': fee_diff_pct,
                    'order_value': order_value
                },
                recommended_action="Verify fee calculation against broker's actual fee structure"
            )
        
        return ValidationResult(
            level=ValidationLevel.PASS,
            category=ValidationCategory.FEE_VALIDATION,
            validator_name="FeeValidator.validate_fee_calculation",
            message="Fee calculation validated",
            symbol=symbol,
            broker=broker,
            account_id=account_id,
            metrics={'calculated_fee': calculated_fee, 'expected_fee': expected_fee}
        )
    
    def validate_profitability_floor(
        self,
        entry_price: float,
        exit_price: float,
        size: float,
        side: str,
        broker: str,
        symbol: str = "unknown",
        account_id: str = "default"
    ) -> ValidationResult:
        """
        Validate that potential profit exceeds fees by minimum ratio
        
        Args:
            entry_price: Entry price
            exit_price: Exit price
            size: Position size
            side: 'buy' or 'sell'
            broker: Broker name
            symbol: Trading symbol
            account_id: Account identifier
            
        Returns:
            ValidationResult
        """
        # Calculate gross profit
        if side in ['buy', 'long']:
            gross_profit = (exit_price - entry_price) * size
        else:  # sell/short
            gross_profit = (entry_price - exit_price) * size
        
        # Calculate total fees
        total_fees = self.calculate_total_fees(size, entry_price, exit_price, broker)
        
        # Calculate net profit
        net_profit = gross_profit - total_fees
        
        # Check profitability ratio
        if total_fees > 0:
            profit_to_fee_ratio = gross_profit / total_fees
        else:
            profit_to_fee_ratio = float('inf') if gross_profit > 0 else 0
        
        if profit_to_fee_ratio < self.min_profit_over_fees_ratio:
            return ValidationResult(
                level=ValidationLevel.WARNING,
                category=ValidationCategory.FEE_VALIDATION,
                validator_name="FeeValidator.validate_profitability_floor",
                message=f"Low profit-to-fee ratio: {profit_to_fee_ratio:.2f}x (min: {self.min_profit_over_fees_ratio}x)",
                symbol=symbol,
                broker=broker,
                account_id=account_id,
                can_proceed=True,
                metrics={
                    'gross_profit': gross_profit,
                    'total_fees': total_fees,
                    'net_profit': net_profit,
                    'profit_to_fee_ratio': profit_to_fee_ratio
                },
                recommended_action="Consider wider profit targets to ensure fees don't erode profits"
            )
        
        if net_profit < 0:
            return ValidationResult(
                level=ValidationLevel.WARNING,
                category=ValidationCategory.FEE_VALIDATION,
                validator_name="FeeValidator.validate_profitability_floor",
                message=f"Net profit negative after fees: ${net_profit:.2f}",
                symbol=symbol,
                broker=broker,
                account_id=account_id,
                metrics={
                    'gross_profit': gross_profit,
                    'total_fees': total_fees,
                    'net_profit': net_profit
                },
                recommended_action="Fees will consume all profit - consider wider targets"
            )
        
        return ValidationResult(
            level=ValidationLevel.PASS,
            category=ValidationCategory.FEE_VALIDATION,
            validator_name="FeeValidator.validate_profitability_floor",
            message=f"Profitability acceptable: {profit_to_fee_ratio:.2f}x profit-to-fee ratio",
            symbol=symbol,
            broker=broker,
            account_id=account_id,
            metrics={
                'gross_profit': gross_profit,
                'total_fees': total_fees,
                'net_profit': net_profit,
                'profit_to_fee_ratio': profit_to_fee_ratio
            }
        )
    
    def validate_minimum_trade_size(
        self,
        size: float,
        price: float,
        broker: str,
        min_order_value: float = 10.0,
        symbol: str = "unknown",
        account_id: str = "default"
    ) -> ValidationResult:
        """
        Validate trade size is large enough to be profitable after fees
        
        Args:
            size: Position size
            price: Price
            broker: Broker name
            min_order_value: Minimum order value
            symbol: Trading symbol
            account_id: Account identifier
            
        Returns:
            ValidationResult
        """
        order_value = size * price
        
        if order_value < min_order_value:
            return ValidationResult(
                level=ValidationLevel.ERROR,
                category=ValidationCategory.PRE_TRADE,
                validator_name="FeeValidator.validate_minimum_trade_size",
                message=f"Order too small: ${order_value:.2f} (min: ${min_order_value:.2f})",
                symbol=symbol,
                broker=broker,
                account_id=account_id,
                can_proceed=False,
                metrics={'order_value': order_value, 'min_order_value': min_order_value},
                recommended_action="Increase position size or skip trade - fees will erode all profit"
            )
        
        # Calculate fee as percentage of order
        fee_rate = self.get_fee_rate(broker)
        fee_amount = order_value * (fee_rate / 100)
        fee_impact_pct = (fee_amount / order_value) * 100
        
        # Warn if fees are high percentage of order
        if fee_impact_pct > 5:  # Fees > 5% of order value
            return ValidationResult(
                level=ValidationLevel.WARNING,
                category=ValidationCategory.FEE_VALIDATION,
                validator_name="FeeValidator.validate_minimum_trade_size",
                message=f"High fee impact: {fee_impact_pct:.2f}% of order value",
                symbol=symbol,
                broker=broker,
                account_id=account_id,
                metrics={
                    'order_value': order_value,
                    'fee_amount': fee_amount,
                    'fee_impact_pct': fee_impact_pct
                },
                recommended_action="Consider larger position size to reduce fee impact"
            )
        
        return ValidationResult(
            level=ValidationLevel.PASS,
            category=ValidationCategory.PRE_TRADE,
            validator_name="FeeValidator.validate_minimum_trade_size",
            message=f"Trade size acceptable: ${order_value:.2f}, {fee_impact_pct:.2f}% fee impact",
            symbol=symbol,
            broker=broker,
            account_id=account_id,
            metrics={'order_value': order_value, 'fee_impact_pct': fee_impact_pct}
        )
