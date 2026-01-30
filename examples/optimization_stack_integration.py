"""
NIJA Optimization Stack Integration Example
===========================================

Example of how to integrate the optimization stack into your trading strategy.

Author: NIJA Trading Systems
Version: 1.0
Date: January 30, 2026
"""

import logging
from typing import Dict, Optional
from datetime import datetime

# Import optimization stack
from bot.optimization_stack import (
    OptimizationStack,
    OptimizationLayer,
    create_optimization_stack
)
from bot.optimization_stack_config import get_optimization_config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("nija.optimization_example")


class OptimizedTradingStrategy:
    """
    Example trading strategy with full optimization stack integration
    """
    
    def __init__(self):
        """Initialize strategy with optimization stack"""
        logger.info("=" * 80)
        logger.info("🚀 Initializing Optimized Trading Strategy")
        logger.info("=" * 80)
        
        # Create and configure optimization stack
        self.optimization_stack = create_optimization_stack(enable_all=True)
        
        # Strategy parameters (will be optimized)
        self.params = {
            'rsi_oversold': 30.0,
            'rsi_overbought': 70.0,
            'stop_loss_pct': 0.02,
            'take_profit_pct': 0.04,
            'position_size_pct': 0.05,
        }
        
        # Performance tracking
        self.total_trades = 0
        self.winning_trades = 0
        self.total_pnl = 0.0
        
        logger.info("✅ Strategy initialized with optimization stack")
    
    def analyze_market(self, symbol: str) -> Dict:
        """
        Analyze market conditions with optimization stack
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Market analysis with optimized parameters
        """
        # Simulate market data (in real usage, fetch from broker)
        market_data = self._get_market_data(symbol)
        
        # Apply Kalman filtering for noise reduction
        if OptimizationLayer.STABILITY in self.optimization_stack.active_layers:
            market_data['rsi_filtered'] = self.optimization_stack.get_filtered_value(
                'rsi', market_data['rsi']
            )
            market_data['volatility_filtered'] = self.optimization_stack.get_filtered_value(
                'volatility', market_data['volatility']
            )
        
        # Get optimized entry timing parameters
        entry_params = self.optimization_stack.optimize_entry_timing(market_data)
        
        # Update strategy parameters with optimized values
        self.params.update(entry_params)
        
        return {
            'symbol': symbol,
            'market_data': market_data,
            'optimized_params': entry_params,
            'current_regime': self.optimization_stack.regime_switcher.current_regime,
        }
    
    def calculate_position_size(self, symbol: str, account_balance: float) -> float:
        """
        Calculate optimized position size
        
        Args:
            symbol: Trading symbol
            account_balance: Current account balance
            
        Returns:
            Optimized position size in USD
        """
        # Base position size
        base_size = account_balance * self.params['position_size_pct']
        
        # Get market data for optimization
        market_data = self._get_market_data(symbol)
        
        # Optimize position size using volatility-adaptive sizing
        optimized_size = self.optimization_stack.optimize_position_size(
            symbol=symbol,
            market_data=market_data,
            base_size=base_size
        )
        
        logger.info(f"Position Size: ${base_size:.2f} -> ${optimized_size:.2f} (optimized)")
        
        return optimized_size
    
    def enter_trade(self, symbol: str, side: str, account_balance: float) -> Optional[Dict]:
        """
        Enter a trade with optimization
        
        Args:
            symbol: Trading symbol
            side: 'buy' or 'sell'
            account_balance: Current account balance
            
        Returns:
            Trade details if entry conditions met, None otherwise
        """
        # Analyze market with optimization
        analysis = self.analyze_market(symbol)
        market_data = analysis['market_data']
        optimized_params = analysis['optimized_params']
        
        # Check entry conditions
        should_enter = False
        if side == 'buy':
            rsi_threshold = optimized_params.get('rsi_oversold', 30.0)
            should_enter = market_data['rsi'] < rsi_threshold
        elif side == 'sell':
            rsi_threshold = optimized_params.get('rsi_overbought', 70.0)
            should_enter = market_data['rsi'] > rsi_threshold
        
        if not should_enter:
            logger.info(f"❌ No entry signal for {symbol} {side}")
            return None
        
        # Calculate optimized position size
        position_size = self.calculate_position_size(symbol, account_balance)
        
        # Get regime-adjusted risk parameters
        regime = self.optimization_stack.regime_switcher.current_regime
        regime_params = self.optimization_stack.regime_switcher.get_regime_parameters(regime)
        
        stop_loss_pct = self.params['stop_loss_pct'] * regime_params['stop_loss_multiplier']
        take_profit_pct = self.params['take_profit_pct'] * regime_params['take_profit_multiplier']
        
        # Create trade
        trade = {
            'symbol': symbol,
            'side': side,
            'size': position_size,
            'entry_price': market_data['price'],
            'stop_loss': market_data['price'] * (1 - stop_loss_pct if side == 'buy' else 1 + stop_loss_pct),
            'take_profit': market_data['price'] * (1 + take_profit_pct if side == 'buy' else 1 - take_profit_pct),
            'regime': regime,
            'timestamp': datetime.utcnow(),
            'optimized_params': optimized_params,
        }
        
        self.total_trades += 1
        
        logger.info("=" * 80)
        logger.info(f"✅ ENTERING {side.upper()} TRADE")
        logger.info("=" * 80)
        logger.info(f"Symbol: {symbol}")
        logger.info(f"Size: ${position_size:.2f}")
        logger.info(f"Entry: ${market_data['price']:.2f}")
        logger.info(f"Stop Loss: ${trade['stop_loss']:.4f} ({stop_loss_pct*100:.2f}%)")
        logger.info(f"Take Profit: ${trade['take_profit']:.4f} ({take_profit_pct*100:.2f}%)")
        logger.info(f"Regime: {regime}")
        logger.info("=" * 80)
        
        return trade
    
    def exit_trade(self, trade: Dict, exit_price: float, reason: str = "signal"):
        """
        Exit a trade and update statistics
        
        Args:
            trade: Trade to exit
            exit_price: Exit price
            reason: Exit reason
        """
        # Calculate P&L (percentage-based for simplicity)
        if trade['side'] == 'buy':
            pnl_pct = ((exit_price - trade['entry_price']) / trade['entry_price']) * 100
        else:
            pnl_pct = ((trade['entry_price'] - exit_price) / trade['entry_price']) * 100
        
        pnl = (pnl_pct / 100) * trade['size']
        
        # Update statistics
        self.total_pnl += pnl
        if pnl > 0:
            self.winning_trades += 1
        
        logger.info("=" * 80)
        logger.info(f"🎯 EXITING TRADE ({reason})")
        logger.info("=" * 80)
        logger.info(f"Symbol: {trade['symbol']}")
        logger.info(f"P&L: ${pnl:.2f} ({pnl_pct:+.2f}%)")
        logger.info(f"Total P&L: ${self.total_pnl:.2f}")
        logger.info(f"Win Rate: {self.get_win_rate()*100:.1f}%")
        logger.info("=" * 80)
        
        # Update Bayesian optimizer with trade performance
        if self.optimization_stack.bayesian_optimizer and OptimizationLayer.FAST in self.optimization_stack.active_layers:
            # Use P&L percentage as performance metric
            self.optimization_stack.bayesian_optimizer.update(
                parameters=trade.get('optimized_params', {}),
                performance=pnl_pct
            )
    
    def get_win_rate(self) -> float:
        """Get current win rate"""
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades
    
    def get_performance_summary(self) -> Dict:
        """
        Get comprehensive performance summary
        
        Returns:
            Performance metrics dictionary
        """
        # Get optimization stack metrics
        stack_metrics = self.optimization_stack.get_performance_metrics()
        
        return {
            'strategy_metrics': {
                'total_trades': self.total_trades,
                'winning_trades': self.winning_trades,
                'win_rate': self.get_win_rate(),
                'total_pnl': self.total_pnl,
                'avg_pnl_per_trade': self.total_pnl / max(1, self.total_trades),
            },
            'optimization_metrics': stack_metrics.to_dict(),
            'current_params': self.params,
        }
    
    def log_performance_summary(self):
        """Log comprehensive performance summary"""
        summary = self.get_performance_summary()
        
        logger.info("=" * 80)
        logger.info("📈 PERFORMANCE SUMMARY")
        logger.info("=" * 80)
        
        # Strategy metrics
        sm = summary['strategy_metrics']
        logger.info(f"\n💼 Trading Performance:")
        logger.info(f"   Total Trades: {sm['total_trades']}")
        logger.info(f"   Win Rate: {sm['win_rate']*100:.1f}%")
        logger.info(f"   Total P&L: ${sm['total_pnl']:.2f}")
        logger.info(f"   Avg P&L per Trade: ${sm['avg_pnl_per_trade']:.2f}")
        
        # Optimization metrics
        om = summary['optimization_metrics']
        logger.info(f"\n🔥 Optimization Stack Gains:")
        logger.info(f"   Total Gain: +{om['total_gain_pct']:.2f}%")
        logger.info(f"   Volatility Adaptive: +{om['volatility_adaptive_gain']:.2f}%")
        logger.info(f"   Entry Timing: +{om['entry_timing_gain']:.2f}%")
        logger.info(f"   Regime Switching: +{om['regime_switching_gain']:.2f}%")
        
        logger.info("=" * 80)
        
        # Log stack status
        self.optimization_stack.log_status()
    
    def _get_market_data(self, symbol: str) -> Dict:
        """
        Get market data (simulated for example)
        
        In real usage, this would fetch from your broker
        """
        import random
        
        return {
            'symbol': symbol,
            'price': 50000 + random.uniform(-1000, 1000),
            'rsi': random.uniform(20, 80),
            'volatility': random.uniform(0.5, 2.5),
            'volume': random.uniform(0.8, 1.5),
            'drawdown': random.uniform(0, 0.08),
            'correlation': random.uniform(0.2, 0.8),
        }


def example_trading_session():
    """Run an example trading session with optimization"""
    logger.info("\n\n")
    logger.info("=" * 80)
    logger.info("🎯 STARTING OPTIMIZED TRADING SESSION")
    logger.info("=" * 80)
    
    # Create optimized strategy
    strategy = OptimizedTradingStrategy()
    
    # Simulate trading session
    account_balance = 10000.0
    symbols = ['BTC-USD', 'ETH-USD', 'SOL-USD']
    
    # Enter some trades
    trades = []
    for symbol in symbols:
        trade = strategy.enter_trade(symbol, 'buy', account_balance)
        if trade:
            trades.append(trade)
    
    # Simulate some exits
    for i, trade in enumerate(trades):
        # Simulate random price movement
        import random
        price_change = random.uniform(-0.03, 0.05)  # -3% to +5%
        exit_price = trade['entry_price'] * (1 + price_change)
        
        # Exit after some time
        strategy.exit_trade(trade, exit_price, reason="take_profit" if price_change > 0 else "stop_loss")
    
    # Show final performance summary
    logger.info("\n\n")
    strategy.log_performance_summary()


def example_custom_configuration():
    """Example with custom configuration"""
    logger.info("\n\n")
    logger.info("=" * 80)
    logger.info("🔧 CUSTOM OPTIMIZATION CONFIGURATION EXAMPLE")
    logger.info("=" * 80)
    
    # Create stack with custom config
    stack = OptimizationStack()
    
    # Enable only specific layers
    stack.enable_layer(OptimizationLayer.FAST, parameter_bounds={
        'rsi_oversold': (25.0, 35.0),
        'rsi_overbought': (65.0, 75.0),
    })
    stack.enable_layer(OptimizationLayer.EMERGENCY)
    stack.enable_layer(OptimizationLayer.STABILITY)
    
    logger.info("✅ Custom optimization stack configured")
    stack.log_status()


if __name__ == "__main__":
    # Run example trading session
    example_trading_session()
    
    # Run custom configuration example
    example_custom_configuration()
