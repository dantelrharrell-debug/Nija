"""
NIJA Minimum Notional Guard
============================

Prevents opening positions below exchange minimum notional value.
This is a HARD RULE to prevent fragmentation and unprofitable micro-positions.

Key Features:
- Configurable minimum notional per exchange
- Kraken-friendly: $3-$5 USD default
- Blocks order placement if order_value < min_notional
- Works in conjunction with dust cleanup to prevent fragmentation

Author: NIJA Trading Systems
Version: 1.0
Date: February 8, 2026
"""

import logging
from typing import Optional, Dict, Tuple
from enum import Enum

logger = logging.getLogger("nija.minimum_notional")


class ExchangeMinimums(Enum):
    """Minimum notional values per exchange (USD)"""
    COINBASE = 2.0      # Coinbase minimum ~$2
    KRAKEN = 10.0       # Kraken minimum ~$10
    BINANCE = 10.0      # Binance minimum ~$10
    OKX = 10.0          # OKX minimum ~$10
    ALPACA = 1.0        # Alpaca minimum ~$1
    
    # Default/Conservative minimum
    DEFAULT = 5.0       # Safe default: $5 minimum


# Global minimum notional (can be overridden by exchange-specific values)
GLOBAL_MIN_NOTIONAL_USD = 5.0  # $5 USD - recommended for profitability

# Recommended minimum for different account sizes
# These ensure positions are large enough to overcome fees
MIN_NOTIONAL_BY_BALANCE = {
    'micro': 3.0,      # < $50 balance: $3 minimum (break-even threshold)
    'small': 5.0,      # $50-$500: $5 minimum (recommended)
    'medium': 10.0,    # $500-$5000: $10 minimum (optimal)
    'large': 15.0,     # > $5000: $15 minimum (institutional grade)
}


class MinimumNotionalGuard:
    """
    Enforces minimum notional value for all order placements.
    
    Prevents:
    - Fragmentation (many tiny positions)
    - Unprofitable micro-positions (fees > profit potential)
    - Exchange rejection due to minimum order size
    """
    
    def __init__(
        self,
        min_notional_usd: float = GLOBAL_MIN_NOTIONAL_USD,
        exchange_minimums: Optional[Dict[str, float]] = None,
        strict_mode: bool = True
    ):
        """
        Initialize minimum notional guard.
        
        Args:
            min_notional_usd: Global minimum notional value in USD
            exchange_minimums: Custom exchange-specific minimums
            strict_mode: If True, reject orders below minimum. If False, warn only.
        """
        self.min_notional_usd = min_notional_usd
        self.strict_mode = strict_mode
        
        # Initialize exchange minimums
        self.exchange_minimums = {}
        for exchange in ExchangeMinimums:
            self.exchange_minimums[exchange.name.lower()] = exchange.value
        
        # Override with custom minimums if provided
        if exchange_minimums:
            self.exchange_minimums.update(
                {k.lower(): v for k, v in exchange_minimums.items()}
            )
        
        logger.info(
            f"✅ Minimum Notional Guard initialized: "
            f"${self.min_notional_usd:.2f} global minimum, "
            f"strict_mode={self.strict_mode}"
        )
    
    def get_minimum_for_exchange(self, exchange: str) -> float:
        """
        Get minimum notional for specific exchange.
        
        Args:
            exchange: Exchange name (e.g., 'kraken', 'coinbase')
        
        Returns:
            float: Minimum notional in USD
        """
        exchange_lower = exchange.lower() if exchange else 'default'
        return self.exchange_minimums.get(exchange_lower, self.min_notional_usd)
    
    def get_minimum_for_balance(self, balance: float) -> float:
        """
        Get recommended minimum notional based on account balance.
        
        Args:
            balance: Account balance in USD
        
        Returns:
            float: Recommended minimum notional in USD
        """
        if balance < 50:
            return MIN_NOTIONAL_BY_BALANCE['micro']
        elif balance < 500:
            return MIN_NOTIONAL_BY_BALANCE['small']
        elif balance < 5000:
            return MIN_NOTIONAL_BY_BALANCE['medium']
        else:
            return MIN_NOTIONAL_BY_BALANCE['large']
    
    def validate_order_notional(
        self,
        size: float,
        price: float,
        exchange: Optional[str] = None,
        balance: Optional[float] = None,
        symbol: str = "unknown"
    ) -> Tuple[bool, Optional[str], Dict]:
        """
        Validate that order meets minimum notional requirements.
        
        Args:
            size: Order size in base currency
            price: Order price
            exchange: Exchange name (optional)
            balance: Account balance for adaptive minimums (optional)
            symbol: Trading symbol for logging
        
        Returns:
            Tuple of (is_valid, error_message, details)
        """
        # Calculate order notional value
        order_value = size * price
        
        # Determine applicable minimum
        if exchange:
            min_notional = self.get_minimum_for_exchange(exchange)
            min_source = f"{exchange} exchange minimum"
        elif balance:
            min_notional = self.get_minimum_for_balance(balance)
            min_source = "balance-adaptive minimum"
        else:
            min_notional = self.min_notional_usd
            min_source = "global minimum"
        
        # Check if order meets minimum
        meets_minimum = order_value >= min_notional
        
        # Prepare details
        details = {
            'order_value': order_value,
            'min_notional': min_notional,
            'min_source': min_source,
            'size': size,
            'price': price,
            'symbol': symbol,
            'exchange': exchange,
            'balance': balance,
            'deficit': max(0, min_notional - order_value)
        }
        
        # Generate result
        if meets_minimum:
            logger.debug(
                f"✅ Order meets minimum notional: {symbol} "
                f"${order_value:.2f} >= ${min_notional:.2f} ({min_source})"
            )
            return True, None, details
        else:
            deficit = min_notional - order_value
            error_msg = (
                f"Order below minimum notional: {symbol} "
                f"${order_value:.2f} < ${min_notional:.2f} ({min_source}). "
                f"Need ${deficit:.2f} more."
            )
            
            if self.strict_mode:
                logger.warning(f"❌ {error_msg}")
                return False, error_msg, details
            else:
                logger.warning(f"⚠️ {error_msg} (warning only)")
                return True, error_msg, details
    
    def should_block_order(
        self,
        size: float,
        price: float,
        exchange: Optional[str] = None,
        balance: Optional[float] = None,
        symbol: str = "unknown"
    ) -> bool:
        """
        Check if order should be blocked due to minimum notional.
        
        Args:
            size: Order size in base currency
            price: Order price
            exchange: Exchange name (optional)
            balance: Account balance (optional)
            symbol: Trading symbol for logging
        
        Returns:
            bool: True if order should be blocked, False if allowed
        """
        is_valid, error_msg, details = self.validate_order_notional(
            size, price, exchange, balance, symbol
        )
        
        # In strict mode, block if not valid
        # In warning mode, never block
        should_block = not is_valid and self.strict_mode
        
        if should_block:
            logger.error(
                f"🚫 BLOCKING ORDER: {symbol} - {error_msg}"
            )
        
        return should_block
    
    def get_minimum_size_for_price(
        self,
        price: float,
        exchange: Optional[str] = None,
        balance: Optional[float] = None
    ) -> float:
        """
        Calculate minimum order size for given price.
        
        Args:
            price: Order price
            exchange: Exchange name (optional)
            balance: Account balance (optional)
        
        Returns:
            float: Minimum order size in base currency
        """
        if price <= 0:
            return 0.0
        
        # Determine applicable minimum
        if exchange:
            min_notional = self.get_minimum_for_exchange(exchange)
        elif balance:
            min_notional = self.get_minimum_for_balance(balance)
        else:
            min_notional = self.min_notional_usd
        
        return min_notional / price
    
    def adjust_order_to_minimum(
        self,
        size: float,
        price: float,
        exchange: Optional[str] = None,
        balance: Optional[float] = None,
        symbol: str = "unknown"
    ) -> Tuple[float, bool]:
        """
        Adjust order size to meet minimum notional if needed.
        
        Args:
            size: Original order size
            price: Order price
            exchange: Exchange name (optional)
            balance: Account balance (optional)
            symbol: Trading symbol for logging
        
        Returns:
            Tuple of (adjusted_size, was_adjusted)
        """
        is_valid, error_msg, details = self.validate_order_notional(
            size, price, exchange, balance, symbol
        )
        
        if is_valid:
            # Already meets minimum
            return size, False
        
        # Calculate minimum size needed
        min_size = self.get_minimum_size_for_price(price, exchange, balance)
        
        logger.info(
            f"📊 Adjusting order size: {symbol} "
            f"{size:.8f} → {min_size:.8f} to meet minimum notional"
        )
        
        return min_size, True


# Global singleton instance
_guard: Optional[MinimumNotionalGuard] = None


def get_notional_guard(
    min_notional_usd: float = GLOBAL_MIN_NOTIONAL_USD,
    strict_mode: bool = True
) -> MinimumNotionalGuard:
    """
    Get or create the global minimum notional guard instance.
    
    Args:
        min_notional_usd: Global minimum notional (only used on first call)
        strict_mode: Strict mode setting (only used on first call)
    
    Returns:
        MinimumNotionalGuard: Global instance
    """
    global _guard
    
    if _guard is None:
        _guard = MinimumNotionalGuard(
            min_notional_usd=min_notional_usd,
            strict_mode=strict_mode
        )
    
    return _guard


def validate_notional(
    size: float,
    price: float,
    exchange: Optional[str] = None,
    balance: Optional[float] = None,
    symbol: str = "unknown"
) -> Tuple[bool, Optional[str], Dict]:
    """
    Convenience function to validate order notional.
    
    Args:
        size: Order size in base currency
        price: Order price
        exchange: Exchange name (optional)
        balance: Account balance (optional)
        symbol: Trading symbol for logging
    
    Returns:
        Tuple of (is_valid, error_message, details)
    """
    guard = get_notional_guard()
    return guard.validate_order_notional(size, price, exchange, balance, symbol)


def should_block_order(
    size: float,
    price: float,
    exchange: Optional[str] = None,
    balance: Optional[float] = None,
    symbol: str = "unknown"
) -> bool:
    """
    Convenience function to check if order should be blocked.
    
    Args:
        size: Order size in base currency
        price: Order price
        exchange: Exchange name (optional)
        balance: Account balance (optional)
        symbol: Trading symbol for logging
    
    Returns:
        bool: True if order should be blocked, False if allowed
    """
    guard = get_notional_guard()
    return guard.should_block_order(size, price, exchange, balance, symbol)


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("\n=== Minimum Notional Guard Test ===\n")
    
    # Initialize guard
    guard = get_notional_guard(min_notional_usd=5.0, strict_mode=True)
    
    # Test cases
    test_cases = [
        # (size, price, exchange, balance, symbol)
        (0.01, 100.0, 'coinbase', 100.0, 'BTC-USD'),  # $1 - should fail
        (0.05, 100.0, 'coinbase', 100.0, 'BTC-USD'),  # $5 - should pass
        (0.001, 5000.0, 'kraken', 500.0, 'ETH-USD'),  # $5 - below Kraken min
        (0.003, 5000.0, 'kraken', 500.0, 'ETH-USD'),  # $15 - should pass
    ]
    
    for size, price, exchange, balance, symbol in test_cases:
        print(f"\nTest: {symbol} @ ${price} x {size} = ${size * price:.2f}")
        is_valid, error, details = guard.validate_order_notional(
            size, price, exchange, balance, symbol
        )
        print(f"  Valid: {is_valid}")
        if error:
            print(f"  Error: {error}")
        print(f"  Details: {details}")
    
    print("\n=== Test Complete ===\n")
