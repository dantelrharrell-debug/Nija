"""
Broker-Specific Trading Configurations

Each broker has different fee structures, capabilities, and optimal strategies:
- Coinbase: Higher fees, crypto only, buy-focused
- Kraken: Lower fees, crypto + futures/options, bidirectional
- Alpaca: Stock trading, different market dynamics
- Binance: International crypto exchange
- OKX: Derivatives and spot trading

This module provides broker-specific configurations for optimal profitability.
"""

from typing import Dict, Optional
from enum import Enum
import logging

logger = logging.getLogger("nija.broker_configs")

# Import broker-specific configs
try:
    from .coinbase_config import CoinbaseConfig
    from .kraken_config import KrakenConfig
    from .default_config import DefaultConfig
except ImportError:
    # Fallback if submodules not yet loaded
    CoinbaseConfig = None
    KrakenConfig = None
    DefaultConfig = None


class BrokerConfigType(Enum):
    """Supported broker configurations"""
    COINBASE = "coinbase"
    KRAKEN = "kraken"
    ALPACA = "alpaca"
    BINANCE = "binance"
    OKX = "okx"
    DEFAULT = "default"


def get_broker_config(broker_type: str):
    """
    Get broker-specific configuration.
    
    Args:
        broker_type: Broker type string (e.g., 'coinbase', 'kraken')
        
    Returns:
        Broker-specific configuration object
    """
    broker_type_lower = broker_type.lower()
    
    if broker_type_lower == "coinbase" and CoinbaseConfig:
        return CoinbaseConfig()
    elif broker_type_lower == "kraken" and KrakenConfig:
        return KrakenConfig()
    elif DefaultConfig:
        return DefaultConfig()
    else:
        # Fallback to a basic config
        logger.warning(f"No specific config for {broker_type}, using defaults")
        return None


__all__ = [
    'BrokerConfigType',
    'get_broker_config',
    'CoinbaseConfig',
    'KrakenConfig',
    'DefaultConfig'
]
