"""
MINIMUM NOTIONAL GATE AT ENTRY
================================
Enhancement 1: Prevents sub-$X entries from ever opening

This module provides a configurable minimum notional value gate that prevents
opening positions below a specified threshold, reducing reliance on cleanup
over time.

Author: NIJA Trading Systems
Created: February 8, 2026
"""

import logging
from typing import Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger("nija.min_notional_gate")


@dataclass
class NotionalGateConfig:
    """Configuration for minimum notional gate"""
    enabled: bool = True
    min_entry_notional_usd: float = 25.0  # $25 minimum entry size
    allow_stop_loss_bypass: bool = True  # Allow stop losses to bypass the gate
    
    # Broker-specific overrides (optional)
    broker_specific_limits: dict = None
    
    def __post_init__(self):
        """Initialize mutable defaults"""
        if self.broker_specific_limits is None:
            self.broker_specific_limits = {
                'coinbase': 25.0,   # $25 minimum (profitability threshold)
                'kraken': 10.0,     # $10 minimum (lower fees)
                'binance': 10.0,    # $10 minimum (lower fees)
                'okx': 10.0,        # $10 minimum (lower fees)
                'alpaca': 1.0,      # $1 minimum (stocks, no crypto fees)
            }
    
    def get_min_notional_for_broker(self, broker_name: str) -> float:
        """
        Get minimum notional for specific broker
        
        Args:
            broker_name: Name of the broker (e.g., 'coinbase', 'kraken')
        
        Returns:
            Minimum notional value in USD
        """
        if not self.broker_specific_limits:
            return self.min_entry_notional_usd
        
        return self.broker_specific_limits.get(
            broker_name.lower(), 
            self.min_entry_notional_usd
        )


class MinimumNotionalGate:
    """
    Minimum Notional Gate - Prevents dust entries at source
    
    Philosophy: "Better to not enter than to enter dust"
    - Reduces cleanup burden
    - Improves capital efficiency
    - Simplifies position management
    """
    
    def __init__(self, config: Optional[NotionalGateConfig] = None):
        """
        Initialize minimum notional gate
        
        Args:
            config: NotionalGateConfig instance, or None for defaults
        """
        self.config = config or NotionalGateConfig()
        
        if self.config.enabled:
            logger.info("✅ Minimum Notional Gate ENABLED")
            logger.info(f"   Default Minimum Entry: ${self.config.min_entry_notional_usd:.2f} USD")
            logger.info(f"   Stop Loss Bypass: {'ALLOWED' if self.config.allow_stop_loss_bypass else 'BLOCKED'}")
            
            if self.config.broker_specific_limits:
                logger.info("   Broker-Specific Limits:")
                for broker, limit in self.config.broker_specific_limits.items():
                    logger.info(f"      {broker.upper()}: ${limit:.2f}")
        else:
            logger.warning("⚠️ Minimum Notional Gate DISABLED")
    
    def validate_entry_size(
        self, 
        symbol: str, 
        size_usd: float, 
        is_stop_loss: bool = False,
        broker_name: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate that entry size meets minimum notional requirements
        
        Args:
            symbol: Trading symbol (e.g., 'BTC-USD')
            size_usd: Position size in USD
            is_stop_loss: True if this is a stop loss order (may bypass gate)
            broker_name: Name of the broker (for broker-specific limits)
        
        Returns:
            Tuple of (is_valid: bool, rejection_reason: Optional[str])
        """
        # Gate disabled - allow all entries
        if not self.config.enabled:
            return True, None
        
        # Stop loss bypass check
        if is_stop_loss and self.config.allow_stop_loss_bypass:
            logger.debug(f"⚠️ Allowing stop loss order bypass for {symbol} (${size_usd:.2f})")
            return True, None
        
        # Get applicable minimum notional
        if broker_name:
            min_notional = self.config.get_min_notional_for_broker(broker_name)
        else:
            min_notional = self.config.min_entry_notional_usd
        
        # Validate size
        if size_usd < min_notional:
            reason = (
                f"Entry size ${size_usd:.2f} below minimum notional "
                f"${min_notional:.2f} USD"
            )
            if broker_name:
                reason += f" ({broker_name} requirement)"
            
            logger.warning(f"🚫 MINIMUM NOTIONAL GATE: Entry rejected for {symbol}")
            logger.warning(f"   Size: ${size_usd:.2f} < ${min_notional:.2f} minimum")
            logger.warning(f"   Reason: Prevents dust accumulation at source")
            
            return False, reason
        
        # Valid entry size
        logger.debug(f"✅ Notional gate passed: {symbol} ${size_usd:.2f} >= ${min_notional:.2f}")
        return True, None
    
    def get_minimum_for_symbol(
        self, 
        symbol: str, 
        broker_name: Optional[str] = None
    ) -> float:
        """
        Get minimum notional requirement for a symbol
        
        Args:
            symbol: Trading symbol
            broker_name: Broker name (optional, for broker-specific limits)
        
        Returns:
            Minimum notional value in USD
        """
        if broker_name:
            return self.config.get_min_notional_for_broker(broker_name)
        return self.config.min_entry_notional_usd
    
    def adjust_size_to_minimum(
        self, 
        size_usd: float, 
        broker_name: Optional[str] = None
    ) -> float:
        """
        Adjust size to meet minimum notional if below threshold
        
        Args:
            size_usd: Requested position size in USD
            broker_name: Broker name (optional)
        
        Returns:
            Adjusted size (either original or minimum, whichever is larger)
        """
        if not self.config.enabled:
            return size_usd
        
        min_notional = (
            self.config.get_min_notional_for_broker(broker_name) 
            if broker_name 
            else self.config.min_entry_notional_usd
        )
        
        if size_usd < min_notional:
            logger.info(f"📈 Auto-adjusting size from ${size_usd:.2f} to ${min_notional:.2f} (minimum)")
            return min_notional
        
        return size_usd


# Singleton instance for global access
_default_gate = None


def get_minimum_notional_gate(config: Optional[NotionalGateConfig] = None) -> MinimumNotionalGate:
    """
    Get the default minimum notional gate instance
    
    Args:
        config: Optional configuration (used only on first call)
    
    Returns:
        MinimumNotionalGate instance
    """
    global _default_gate
    
    if _default_gate is None:
        _default_gate = MinimumNotionalGate(config)
    
    return _default_gate


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Create gate with default config
    gate = MinimumNotionalGate()
    
    # Test various entry sizes
    test_cases = [
        ("BTC-USD", 50.0, False, "coinbase"),   # Valid
        ("ETH-USD", 10.0, False, "coinbase"),   # Too small for Coinbase
        ("SOL-USD", 15.0, False, "kraken"),     # Valid for Kraken
        ("MATIC-USD", 5.0, False, "kraken"),    # Too small even for Kraken
        ("BTC-USD", 5.0, True, "coinbase"),     # Stop loss - allowed
    ]
    
    logger.info("\n" + "=" * 70)
    logger.info("MINIMUM NOTIONAL GATE TEST CASES")
    logger.info("=" * 70)
    
    for symbol, size, is_sl, broker in test_cases:
        valid, reason = gate.validate_entry_size(symbol, size, is_sl, broker)
        
        status = "✅ ALLOWED" if valid else "🚫 REJECTED"
        logger.info(f"\n{status}: {symbol} @ ${size:.2f} ({broker})")
        if is_sl:
            logger.info(f"   Type: Stop Loss Order")
        if reason:
            logger.info(f"   Reason: {reason}")
    
    logger.info("\n" + "=" * 70)
