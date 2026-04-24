"""
Example: Integrating Optimization Stack with Existing APEX Strategy
===================================================================

This example shows how to integrate the optimization stack with
the existing NIJA APEX trading strategy.

Author: NIJA Trading Systems
Version: 1.0
Date: January 30, 2026
"""

import logging
from typing import Dict, Optional
from datetime import datetime

# Import optimization stack
from bot.optimization_stack import create_optimization_stack, OptimizationLayer
from bot.optimization_stack_config import get_optimization_config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("nija.apex_optimization_integration")


class OptimizedAPEXStrategy:
    """
    APEX Strategy enhanced with Optimization Stack
    
    This wraps the existing APEX strategy and adds all optimization layers
    for maximum performance.
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize optimized APEX strategy
        
        Args:
            config: Strategy configuration
        """
        logger.info("=" * 80)
        logger.info("🚀 Initializing Optimized APEX Strategy")
        logger.info("=" * 80)
        
        self.config = config or {}
        
        # Create optimization stack
        self.optimization_stack = create_optimization_stack(enable_all=True)
        
        # APEX strategy parameters (will be optimized)
        self.apex_params = {
            'rsi_9_oversold': 30.0,
            'rsi_9_overbought': 70.0,
            'rsi_14_oversold': 30.0,
            'rsi_14_overbought': 70.0,
            'stop_loss_pct': 0.02,
            'take_profit_pct': 0.04,
            'trailing_stop_pct': 0.015,
            'position_size_pct': 0.05,
        }
        
        # Performance tracking
        self.total_trades = 0
        self.winning_trades = 0
        self.total_pnl = 0.0
        
        logger.info("✅ Optimized APEX Strategy initialized")
        logger.info(f"   Optimization Stack: ENABLED")
        logger.info(f"   Active Layers: {len(self.optimization_stack.active_layers)}")
    
    def analyze_market(self, symbol: str, df) -> Dict:
        """
        Analyze market with optimization
        
        Args:
            symbol: Trading symbol
            df: Price data DataFrame
            
        Returns:
            Market analysis with optimized parameters
        """
        # Calculate technical indicators (simplified)
        market_data = self._calculate_indicators(df)
        
        # Apply Kalman filtering for noise reduction
        if OptimizationLayer.STABILITY in self.optimization_stack.active_layers:
            market_data['rsi_9_filtered'] = self.optimization_stack.get_filtered_value(
                'rsi', market_data['rsi_9']
            )
            market_data['rsi_14_filtered'] = self.optimization_stack.get_filtered_value(
                'rsi_14', market_data['rsi_14']
            )
            market_data['volatility_filtered'] = self.optimization_stack.get_filtered_value(
                'volatility', market_data['volatility']
            )
        
        # Get optimized entry parameters
        entry_params = self.optimization_stack.optimize_entry_timing(market_data)
        
        # Update APEX parameters with optimized values
        if 'rsi_oversold' in entry_params:
            self.apex_params['rsi_9_oversold'] = entry_params['rsi_oversold']
            self.apex_params['rsi_14_oversold'] = entry_params['rsi_oversold']
        if 'rsi_overbought' in entry_params:
            self.apex_params['rsi_9_overbought'] = entry_params['rsi_overbought']
            self.apex_params['rsi_14_overbought'] = entry_params['rsi_overbought']
        
        return {
            'symbol': symbol,
            'market_data': market_data,
            'optimized_params': entry_params,
            'current_regime': self.optimization_stack.regime_switcher.current_regime,
            'apex_params': self.apex_params,
        }
    
    def generate_signal(self, analysis: Dict) -> Optional[str]:
        """
        Generate trading signal (buy/sell/hold) using dual RSI
        
        Args:
            analysis: Market analysis from analyze_market()
            
        Returns:
            'buy', 'sell', or None
        """
        market_data = analysis['market_data']
        apex_params = analysis['apex_params']
        
        # Use filtered RSI values if available
        rsi_9 = market_data.get('rsi_9_filtered', market_data['rsi_9'])
        rsi_14 = market_data.get('rsi_14_filtered', market_data['rsi_14'])
        
        # Dual RSI buy signal
        if (rsi_9 < apex_params['rsi_9_oversold'] and 
            rsi_14 < apex_params['rsi_14_oversold']):
            return 'buy'
        
        # Dual RSI sell signal
        elif (rsi_9 > apex_params['rsi_9_overbought'] and 
              rsi_14 > apex_params['rsi_14_overbought']):
            return 'sell'
        
        return None
    
    def calculate_position_size(self, symbol: str, df, account_balance: float) -> float:
        """
        Calculate optimized position size
        
        Args:
            symbol: Trading symbol
            df: Price data
            account_balance: Account balance
            
        Returns:
            Optimized position size
        """
        # Base position size
        base_size = account_balance * self.apex_params['position_size_pct']
        
        # Get market data
        market_data = self._calculate_indicators(df)
        
        # Optimize with volatility-adaptive sizing
        optimized_size = self.optimization_stack.optimize_position_size(
            symbol=symbol,
            market_data=market_data,
            base_size=base_size
        )
        
        logger.info(f"📊 Position Size: ${base_size:.2f} -> ${optimized_size:.2f}")
        
        return optimized_size
    
    def execute_trade(self, symbol: str, df, account_balance: float) -> Optional[Dict]:
        """
        Execute trade with full optimization
        
        Args:
            symbol: Trading symbol
            df: Price data
            account_balance: Account balance
            
        Returns:
            Trade details or None
        """
        # Analyze market
        analysis = self.analyze_market(symbol, df)
        
        # Generate signal
        signal = self.generate_signal(analysis)
        
        if signal is None:
            logger.info(f"⏸️  No signal for {symbol}")
            return None
        
        # Calculate position size
        position_size = self.calculate_position_size(symbol, df, account_balance)
        
        # Get regime-adjusted risk parameters
        regime = analysis['current_regime']
        regime_params = self.optimization_stack.regime_switcher.get_regime_parameters(regime)
        
        # Adjust stop loss and take profit based on regime
        stop_loss_pct = (
            self.apex_params['stop_loss_pct'] * 
            regime_params['stop_loss_multiplier']
        )
        take_profit_pct = (
            self.apex_params['take_profit_pct'] * 
            regime_params['take_profit_multiplier']
        )
        
        # Get current price
        current_price = analysis['market_data']['price']
        
        # Create trade order
        trade = {
            'symbol': symbol,
            'signal': signal,
            'size': position_size,
            'entry_price': current_price,
            'stop_loss': current_price * (1 - stop_loss_pct if signal == 'buy' else 1 + stop_loss_pct),
            'take_profit': current_price * (1 + take_profit_pct if signal == 'buy' else 1 - take_profit_pct),
            'trailing_stop_pct': self.apex_params['trailing_stop_pct'],
            'regime': regime,
            'timestamp': datetime.utcnow(),
            'optimized_params': analysis['optimized_params'],
        }
        
        self.total_trades += 1
        
        logger.info("=" * 80)
        logger.info(f"✅ {signal.upper()} SIGNAL GENERATED")
        logger.info("=" * 80)
        logger.info(f"Symbol: {symbol}")
        logger.info(f"Size: ${position_size:.2f}")
        logger.info(f"Entry: ${current_price:.2f}")
        logger.info(f"Stop Loss: ${trade['stop_loss']:.4f} ({stop_loss_pct*100:.2f}%)")
        logger.info(f"Take Profit: ${trade['take_profit']:.4f} ({take_profit_pct*100:.2f}%)")
        logger.info(f"Regime: {regime}")
        logger.info(f"RSI-9: {analysis['market_data']['rsi_9']:.1f}")
        logger.info(f"RSI-14: {analysis['market_data']['rsi_14']:.1f}")
        logger.info("=" * 80)
        
        return trade
    
    def _calculate_indicators(self, df) -> Dict:
        """
        Calculate technical indicators (simplified for example)
        
        In real usage, this would use actual calculations
        """
        import random
        
        return {
            'price': 50000 + random.uniform(-1000, 1000),
            'rsi_9': random.uniform(20, 80),
            'rsi_14': random.uniform(20, 80),
            'volatility': random.uniform(0.5, 2.5),
            'volume': random.uniform(0.8, 1.5),
            'drawdown': random.uniform(0, 0.08),
            'correlation': random.uniform(0.2, 0.8),
        }
    
    def get_performance_summary(self) -> Dict:
        """Get comprehensive performance summary"""
        stack_metrics = self.optimization_stack.get_performance_metrics()
        
        return {
            'strategy_metrics': {
                'total_trades': self.total_trades,
                'winning_trades': self.winning_trades,
                'win_rate': self.winning_trades / max(1, self.total_trades),
                'total_pnl': self.total_pnl,
            },
            'optimization_metrics': stack_metrics.to_dict(),
            'current_params': self.apex_params,
        }


def example_optimized_apex_trading():
    """Example of running optimized APEX strategy"""
    logger.info("\n\n")
    logger.info("=" * 80)
    logger.info("🎯 RUNNING OPTIMIZED APEX STRATEGY")
    logger.info("=" * 80)
    
    # Create optimized strategy
    strategy = OptimizedAPEXStrategy()
    
    # Simulate trading
    account_balance = 10000.0
    symbols = ['BTC-USD', 'ETH-USD', 'SOL-USD']
    
    trades = []
    for symbol in symbols:
        # Create dummy price data (in real usage, fetch from broker)
        import pandas as pd
        df = pd.DataFrame()  # Placeholder
        
        # Execute trade
        trade = strategy.execute_trade(symbol, df, account_balance)
        if trade:
            trades.append(trade)
    
    # Show performance
    logger.info("\n\n")
    logger.info("=" * 80)
    logger.info("📈 OPTIMIZATION STACK STATUS")
    logger.info("=" * 80)
    strategy.optimization_stack.log_status()
    
    logger.info("\n✅ Optimized APEX strategy example complete")


if __name__ == "__main__":
    example_optimized_apex_trading()
