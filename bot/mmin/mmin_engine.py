"""
MMIN Engine - Multi-Market Intelligence Network
================================================

Main orchestration engine that coordinates all MMIN components.

GOD MODE Features:
- Cross-market learning (crypto ↔ forex ↔ equities)
- Transfer learning across asset classes
- Macro regime forecasting
- Global capital routing
- Correlation-aware portfolio intelligence
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import logging

from .data_collector import MultiMarketDataCollector
from .correlation_analyzer import CrossMarketCorrelationAnalyzer
from .macro_regime_forecaster import MacroRegimeForecaster, MacroRegime
from .transfer_learning import TransferLearningEngine
from .global_capital_router import GlobalCapitalRouter
from .mmin_config import MMIN_ENGINE_CONFIG, MARKET_CATEGORIES

logger = logging.getLogger("nija.mmin")


class MMINEngine:
    """
    Multi-Market Intelligence Network Engine
    
    The GOD-MODE trading intelligence that:
    1. Monitors multiple asset classes simultaneously
    2. Learns patterns and transfers knowledge across markets
    3. Forecasts macro regimes
    4. Routes capital intelligently
    5. Provides correlation-aware signals
    
    This transforms NIJA into a global autonomous trading intelligence.
    """
    
    def __init__(self, broker_manager=None, config: Dict = None):
        """
        Initialize MMIN Engine
        
        Args:
            broker_manager: BrokerManager instance for market access
            config: Optional configuration dictionary
        """
        self.config = config or MMIN_ENGINE_CONFIG
        self.enabled = self.config['enabled']
        self.mode = self.config['mode']
        self.intelligence_level = self.config['intelligence_level']
        
        # Initialize components
        self.data_collector = MultiMarketDataCollector(broker_manager)
        self.correlation_analyzer = CrossMarketCorrelationAnalyzer()
        self.macro_forecaster = MacroRegimeForecaster()
        self.transfer_learning = TransferLearningEngine()
        self.capital_router = GlobalCapitalRouter()
        
        # State tracking
        self.last_update = {}
        self.current_signals: Dict[str, Dict] = {}
        self.active_markets: List[str] = []
        
        # Performance tracking
        self.performance_metrics = {
            'total_signals': 0,
            'successful_signals': 0,
            'cross_market_confirmations': 0,
            'regime_changes': 0,
        }
        
        logger.info(f"MMINEngine initialized (mode={self.mode}, intelligence={self.intelligence_level})")
    
    def analyze_markets(self, timeframe: str = '1h', 
                       limit: int = 500) -> Dict:
        """
        Main analysis loop - analyze all markets
        
        Args:
            timeframe: Data timeframe
            limit: Number of candles to analyze
            
        Returns:
            Comprehensive market analysis
        """
        logger.info("=== MMIN Market Analysis Started ===")
        
        # 1. Collect multi-market data
        market_data = self.data_collector.collect_all_markets(timeframe, limit)
        
        if not market_data:
            logger.warning("No market data collected")
            return {'status': 'no_data'}
        
        # 2. Calculate cross-market correlations
        correlations = self._analyze_correlations(market_data)
        
        # 3. Forecast macro regime
        regime_forecast = self.macro_forecaster.forecast_regime(market_data)
        
        # 4. Find cross-market patterns
        patterns = self._discover_patterns(market_data)
        
        # 5. Calculate optimal capital allocation
        allocation = self._calculate_allocation(market_data, correlations, regime_forecast)
        
        # 6. Generate trading signals with cross-market confirmation
        signals = self._generate_signals(market_data, correlations, regime_forecast, patterns)
        
        # 7. Compile analysis
        analysis = {
            'timestamp': datetime.now(),
            'markets_analyzed': len(market_data),
            'macro_regime': regime_forecast,
            'correlations': correlations,
            'patterns': patterns,
            'capital_allocation': allocation,
            'signals': signals,
            'performance': self.performance_metrics,
            'intelligence_level': self.intelligence_level,
        }
        
        logger.info(f"=== MMIN Analysis Complete: {len(signals)} signals, "
                   f"regime={regime_forecast['regime'].value} ===")
        
        return analysis
    
    def _analyze_correlations(self, market_data: Dict[str, Dict[str, pd.DataFrame]]) -> Dict:
        """Analyze cross-market correlations"""
        # Prepare synchronized data
        symbols_map = {}
        for market_type, symbols_data in market_data.items():
            for symbol in symbols_data.keys():
                symbols_map[symbol] = market_type
        
        synchronized_df = self.data_collector.get_synchronized_data(symbols_map)
        
        if synchronized_df.empty:
            return {}
        
        # Calculate correlations
        correlations = self.correlation_analyzer.calculate_correlations(synchronized_df)
        
        # Find significant pairs
        if correlations:
            primary_window = list(correlations.keys())[0]
            corr_matrix = correlations[primary_window]
            significant_pairs = self.correlation_analyzer.find_correlated_pairs(corr_matrix)
            
            # Detect correlation regime
            regime = self.correlation_analyzer.get_correlation_regime(synchronized_df)
            
            return {
                'correlation_matrices': correlations,
                'significant_pairs': significant_pairs[:10],  # Top 10
                'correlation_regime': regime,
                'diversification_opportunities': self._find_diversification_opps(corr_matrix),
            }
        
        return {}
    
    def _find_diversification_opps(self, corr_matrix: pd.DataFrame) -> List[str]:
        """Find low-correlated assets for diversification"""
        # Find pairs with low correlation
        low_corr_pairs = []
        symbols = corr_matrix.columns.tolist()
        
        for i, sym1 in enumerate(symbols):
            for sym2 in symbols[i+1:]:
                corr = abs(corr_matrix.loc[sym1, sym2])
                if corr < 0.3:  # Low correlation
                    low_corr_pairs.append((sym1, sym2, corr))
        
        # Sort by lowest correlation
        low_corr_pairs.sort(key=lambda x: x[2])
        
        return [f"{s1} ↔ {s2} (r={corr:.2f})" for s1, s2, corr in low_corr_pairs[:5]]
    
    def _discover_patterns(self, market_data: Dict[str, Dict[str, pd.DataFrame]]) -> Dict:
        """Discover patterns and apply transfer learning"""
        patterns = {
            'discovered': [],
            'transferred': [],
        }
        
        # Analyze each market for patterns
        for market_type, symbols_data in market_data.items():
            for symbol, df in symbols_data.items():
                # Extract features
                features = self.transfer_learning.extract_features(df, market_type)
                
                # Find similar patterns from other markets
                similar = self.transfer_learning.find_similar_patterns(
                    df, market_type, min_confidence=0.6
                )
                
                if similar:
                    patterns['discovered'].append({
                        'symbol': symbol,
                        'market': market_type,
                        'similar_patterns': len(similar),
                        'best_match': similar[0] if similar else None,
                    })
        
        return patterns
    
    def _calculate_allocation(self, market_data: Dict[str, Dict[str, pd.DataFrame]],
                             correlations: Dict, regime_forecast: Dict) -> Dict:
        """Calculate optimal capital allocation"""
        # Prepare market metrics
        market_metrics = {}
        
        for market_type in market_data.keys():
            # Calculate simple performance metrics for each market
            market_metrics[market_type] = {
                'sharpe_ratio': np.random.uniform(1.0, 2.5),  # Placeholder
                'win_rate': np.random.uniform(0.5, 0.7),  # Placeholder
                'profit_factor': np.random.uniform(1.5, 2.5),  # Placeholder
                'opportunity_count': len(market_data[market_type]),
            }
        
        # Get correlation matrix
        corr_matrix = None
        if correlations and 'correlation_matrices' in correlations:
            matrices = correlations['correlation_matrices']
            if matrices:
                corr_matrix = list(matrices.values())[0]
        
        # Calculate allocation
        total_capital = 100000.0  # Example capital
        allocation = self.capital_router.calculate_allocation(
            market_metrics,
            corr_matrix,
            regime_forecast['regime'].value,
            total_capital
        )
        
        return {
            'allocations': allocation,
            'total_capital': total_capital,
            'strategy': self.capital_router.strategy,
        }
    
    def _generate_signals(self, market_data: Dict[str, Dict[str, pd.DataFrame]],
                         correlations: Dict, regime_forecast: Dict,
                         patterns: Dict) -> List[Dict]:
        """Generate trading signals with cross-market confirmation"""
        signals = []
        
        min_confirmations = self.config['cross_market_signals_required']
        regime = regime_forecast['regime']
        
        # Get trading implications from regime
        implications = regime_forecast['trading_implications']
        preferred_markets = implications['preferred_markets']
        
        # Scan each market for opportunities
        for market_type, symbols_data in market_data.items():
            # Skip if not preferred in current regime
            if market_type not in preferred_markets:
                continue
            
            for symbol, df in symbols_data.items():
                # Basic signal generation (simplified)
                signal = self._generate_market_signal(
                    symbol, df, market_type, regime, correlations
                )
                
                if signal and signal['confidence'] >= 0.6:
                    # Check for cross-market confirmation
                    confirmations = self._get_cross_market_confirmations(
                        signal, market_data, correlations
                    )
                    
                    if confirmations >= min_confirmations:
                        signal['cross_market_confirmations'] = confirmations
                        signal['regime_aligned'] = True
                        signals.append(signal)
                        self.performance_metrics['total_signals'] += 1
        
        logger.info(f"Generated {len(signals)} high-confidence signals")
        return signals
    
    def _generate_market_signal(self, symbol: str, df: pd.DataFrame,
                               market_type: str, regime: MacroRegime,
                               correlations: Dict) -> Optional[Dict]:
        """Generate signal for a specific market"""
        if len(df) < 20:
            return None
        
        # Calculate basic indicators
        close = df['close'].iloc[-1]
        sma_20 = df['close'].rolling(20).mean().iloc[-1]
        returns = df['close'].pct_change()
        volatility = returns.std()
        
        # Simple momentum signal
        momentum = (close - sma_20) / sma_20
        
        if momentum > 0.02:  # Bullish
            signal_type = 'long'
            confidence = min(abs(momentum) * 10, 1.0)
        elif momentum < -0.02:  # Bearish
            signal_type = 'short'
            confidence = min(abs(momentum) * 10, 1.0)
        else:
            return None
        
        return {
            'symbol': symbol,
            'market_type': market_type,
            'signal_type': signal_type,
            'confidence': confidence,
            'price': close,
            'regime': regime.value,
            'timestamp': datetime.now(),
        }
    
    def _get_cross_market_confirmations(self, signal: Dict,
                                       market_data: Dict[str, Dict[str, pd.DataFrame]],
                                       correlations: Dict) -> int:
        """Count cross-market confirmations for a signal"""
        confirmations = 0
        
        # Check correlated assets for similar signals
        if not correlations or 'significant_pairs' not in correlations:
            return 0
        
        significant_pairs = correlations['significant_pairs']
        symbol = signal['symbol']
        signal_type = signal['signal_type']
        
        # Find correlated pairs involving this symbol
        for sym1, sym2, corr in significant_pairs:
            if sym1 == symbol or sym2 == symbol:
                # Check if correlated symbol has similar signal
                other_symbol = sym2 if sym1 == symbol else sym1
                
                # Find market for other symbol
                for market_type, symbols_data in market_data.items():
                    if other_symbol in symbols_data:
                        other_df = symbols_data[other_symbol]
                        
                        # Check momentum direction
                        if len(other_df) >= 20:
                            other_close = other_df['close'].iloc[-1]
                            other_sma = other_df['close'].rolling(20).mean().iloc[-1]
                            other_momentum = (other_close - other_sma) / other_sma
                            
                            # If positive correlation and same direction
                            if corr > 0:
                                if (signal_type == 'long' and other_momentum > 0) or \
                                   (signal_type == 'short' and other_momentum < 0):
                                    confirmations += 1
                            # If negative correlation and opposite direction
                            elif corr < 0:
                                if (signal_type == 'long' and other_momentum < 0) or \
                                   (signal_type == 'short' and other_momentum > 0):
                                    confirmations += 1
        
        return confirmations
    
    def get_status(self) -> Dict:
        """Get MMIN engine status"""
        return {
            'enabled': self.enabled,
            'mode': self.mode,
            'intelligence_level': self.intelligence_level,
            'active_markets': len(self.active_markets),
            'current_regime': self.macro_forecaster.current_regime.value,
            'regime_confidence': self.macro_forecaster.regime_confidence,
            'performance': self.performance_metrics,
            'data_quality': self.data_collector.get_quality_metrics(),
            'learning_stats': self.transfer_learning.get_learning_stats(),
            'allocation_stats': self.capital_router.get_allocation_stats(),
        }
    
    def enable(self):
        """Enable MMIN engine"""
        self.enabled = True
        logger.info("MMIN Engine ENABLED")
    
    def disable(self):
        """Disable MMIN engine"""
        self.enabled = False
        logger.info("MMIN Engine DISABLED")
