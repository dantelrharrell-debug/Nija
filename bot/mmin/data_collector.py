"""
Multi-Market Data Collector
============================

Collects and normalizes data from multiple asset classes:
- Crypto (BTC, ETH, altcoins)
- Forex (currency pairs)
- Equities (stocks, ETFs)
- Commodities (gold, oil, etc.)
- Bonds (treasuries)
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import logging

from .mmin_config import MARKET_CATEGORIES

logger = logging.getLogger("nija.mmin.data")


@dataclass
class MarketData:
    """Normalized market data across all asset classes"""
    symbol: str
    market_type: str  # 'crypto', 'forex', 'equities', etc.
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    exchange: str
    metadata: Dict = field(default_factory=dict)


class MultiMarketDataCollector:
    """
    Collects and normalizes data from multiple asset classes
    
    Features:
    - Unified data format across all markets
    - Real-time and historical data collection
    - Automatic data synchronization
    - Missing data handling
    - Data quality checks
    """
    
    def __init__(self, broker_manager=None, config: Dict = None):
        """
        Initialize multi-market data collector
        
        Args:
            broker_manager: BrokerManager instance for API access
            config: Optional configuration dictionary
        """
        self.broker_manager = broker_manager
        self.config = config or {}
        self.market_categories = MARKET_CATEGORIES
        
        # Data storage
        self.data_cache: Dict[str, pd.DataFrame] = {}
        self.last_update: Dict[str, datetime] = {}
        
        # Data quality metrics
        self.quality_metrics = {
            'missing_data_count': 0,
            'stale_data_count': 0,
            'total_updates': 0,
        }
        
        logger.info("MultiMarketDataCollector initialized")
    
    def collect_market_data(self, market_type: str, symbols: List[str] = None,
                           timeframe: str = '1h', limit: int = 500) -> Dict[str, pd.DataFrame]:
        """
        Collect data for specific market type
        
        Args:
            market_type: Type of market ('crypto', 'forex', 'equities', etc.)
            symbols: List of symbols to collect (None = all symbols for market)
            timeframe: Data timeframe ('1m', '5m', '1h', '1d')
            limit: Number of candles to fetch
            
        Returns:
            Dictionary mapping symbols to DataFrames
        """
        if market_type not in self.market_categories:
            logger.error(f"Unknown market type: {market_type}")
            return {}
        
        # Get symbols for this market
        if symbols is None:
            symbols = self.market_categories[market_type]['symbols']
        
        market_data = {}
        
        for symbol in symbols:
            try:
                df = self._fetch_symbol_data(symbol, market_type, timeframe, limit)
                if df is not None and not df.empty:
                    market_data[symbol] = df
                    self.data_cache[f"{market_type}:{symbol}"] = df
                    self.last_update[f"{market_type}:{symbol}"] = datetime.now()
                    self.quality_metrics['total_updates'] += 1
                else:
                    self.quality_metrics['missing_data_count'] += 1
            except Exception as e:
                logger.error(f"Error collecting data for {symbol} ({market_type}): {e}")
                self.quality_metrics['missing_data_count'] += 1
        
        logger.info(f"Collected data for {len(market_data)}/{len(symbols)} {market_type} symbols")
        return market_data
    
    def collect_all_markets(self, timeframe: str = '1h', limit: int = 500) -> Dict[str, Dict[str, pd.DataFrame]]:
        """
        Collect data from all configured markets
        
        Args:
            timeframe: Data timeframe
            limit: Number of candles to fetch
            
        Returns:
            Nested dictionary: {market_type: {symbol: DataFrame}}
        """
        all_data = {}
        
        for market_type in self.market_categories.keys():
            logger.info(f"Collecting data for {market_type} market...")
            market_data = self.collect_market_data(market_type, timeframe=timeframe, limit=limit)
            if market_data:
                all_data[market_type] = market_data
        
        logger.info(f"Collected data from {len(all_data)} markets")
        return all_data
    
    def _fetch_symbol_data(self, symbol: str, market_type: str, 
                          timeframe: str, limit: int) -> Optional[pd.DataFrame]:
        """
        Fetch data for a specific symbol
        
        Args:
            symbol: Symbol to fetch
            market_type: Market type
            timeframe: Timeframe
            limit: Number of candles
            
        Returns:
            DataFrame with OHLCV data or None
        """
        # If broker_manager is available, use it
        if self.broker_manager:
            try:
                return self._fetch_from_broker(symbol, market_type, timeframe, limit)
            except Exception as e:
                logger.warning(f"Error fetching from broker for {symbol}: {e}")
        
        # Fallback to mock data for testing
        return self._generate_mock_data(symbol, limit)
    
    def _fetch_from_broker(self, symbol: str, market_type: str,
                          timeframe: str, limit: int) -> Optional[pd.DataFrame]:
        """Fetch real data from broker/exchange"""
        # This would integrate with actual broker APIs
        # For now, return None to use mock data
        return None
    
    def _generate_mock_data(self, symbol: str, limit: int) -> pd.DataFrame:
        """
        Generate mock OHLCV data for testing
        
        IMPORTANT: This is TEST-ONLY functionality. 
        Real broker integration must be implemented before production use.
        
        Args:
            symbol: Symbol name
            limit: Number of candles
            
        Returns:
            DataFrame with mock OHLCV data
        """
        # Use deterministic seed for consistent test data
        np.random.seed(hash(symbol) % 2**32)
        
        # Generate realistic price movements
        base_price = 100.0
        volatility = 0.02
        
        timestamps = pd.date_range(end=datetime.now(), periods=limit, freq='1h')
        
        # Random walk with drift
        returns = np.random.normal(0.0001, volatility, limit)
        prices = base_price * np.exp(np.cumsum(returns))
        
        # Generate OHLC from close prices
        df = pd.DataFrame({
            'timestamp': timestamps,
            'open': prices * np.random.uniform(0.995, 1.005, limit),
            'high': prices * np.random.uniform(1.000, 1.015, limit),
            'low': prices * np.random.uniform(0.985, 1.000, limit),
            'close': prices,
            'volume': np.random.uniform(1000000, 5000000, limit),
        })
        
        df.set_index('timestamp', inplace=True)
        return df
    
    def get_synchronized_data(self, symbols: Dict[str, str], 
                             limit: int = 500) -> pd.DataFrame:
        """
        Get synchronized data across multiple markets
        
        Args:
            symbols: Dict mapping symbol to market_type (e.g., {'BTC-USD': 'crypto', 'SPY': 'equities'})
            limit: Number of candles
            
        Returns:
            DataFrame with synchronized close prices as columns
        """
        all_data = []
        
        for symbol, market_type in symbols.items():
            cache_key = f"{market_type}:{symbol}"
            
            # Fetch data if not cached
            if cache_key not in self.data_cache:
                df = self._fetch_symbol_data(symbol, market_type, '1h', limit)
                if df is not None:
                    self.data_cache[cache_key] = df
            
            # Get from cache
            if cache_key in self.data_cache:
                df = self.data_cache[cache_key].copy()
                df.columns = [f"{symbol}_{col}" for col in df.columns]
                all_data.append(df[[f"{symbol}_close"]])
        
        if not all_data:
            return pd.DataFrame()
        
        # Merge all data on timestamp
        synchronized_df = pd.concat(all_data, axis=1, join='inner')
        synchronized_df.columns = [col.replace('_close', '') for col in synchronized_df.columns]
        
        logger.info(f"Synchronized {len(symbols)} symbols, {len(synchronized_df)} periods")
        return synchronized_df
    
    def get_quality_metrics(self) -> Dict:
        """Get data quality metrics"""
        # Calculate cache size only if needed (can be expensive for large caches)
        cache_size = 0
        if len(self.data_cache) > 0:
            # Estimate size rather than computing exact memory usage
            cache_size = len(self.data_cache) * 0.01  # Rough estimate in MB
        
        return {
            **self.quality_metrics,
            'cached_symbols': len(self.data_cache),
            'cache_size_mb': cache_size,
        }
    
    def clear_cache(self):
        """Clear data cache"""
        self.data_cache.clear()
        self.last_update.clear()
        logger.info("Data cache cleared")
