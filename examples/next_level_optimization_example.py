"""
Next-Level Optimization Integration Example
===========================================

Demonstrates how to integrate all four optimization systems into
a trading strategy:

1. RL Exit Optimizer - Smart profit-taking
2. Regime Strategy Selector - Adaptive strategy per market regime  
3. Portfolio Risk Engine - Correlation-aware risk management
4. Execution Optimizer - Fee-optimized order execution

This example shows a complete trading loop using all optimizations.

Author: NIJA Trading Systems
Date: January 29, 2026
"""

import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("nija.example")

# Import optimization modules
try:
    from bot.rl_exit_optimizer import get_rl_exit_optimizer, ExitState
    from bot.regime_strategy_selector import RegimeBasedStrategySelector
    from bot.portfolio_risk_engine import get_portfolio_risk_engine
    from bot.execution_optimizer import get_execution_optimizer
except ImportError:
    # Fallback for running from examples directory
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'bot'))
    
    from rl_exit_optimizer import get_rl_exit_optimizer, ExitState
    from regime_strategy_selector import RegimeBasedStrategySelector
    from portfolio_risk_engine import get_portfolio_risk_engine
    from execution_optimizer import get_execution_optimizer


class OptimizedTradingStrategy:
    """
    Trading strategy integrating all four next-level optimizations
    
    This is a reference implementation showing how to use:
    - RL-based exit optimization
    - Regime-adaptive strategy selection
    - Portfolio-level risk management with correlations
    - Fee-optimized order execution
    """
    
    def __init__(self, initial_capital: float = 10000.0):
        """
        Initialize optimized trading strategy
        
        Args:
            initial_capital: Starting capital in USD
        """
        self.capital = initial_capital
        self.initial_capital = initial_capital
        
        # Initialize optimization modules
        logger.info("Initializing optimization modules...")
        
        # 1. RL Exit Optimizer
        self.rl_exit = get_rl_exit_optimizer(config={
            'learning_rate': 0.1,
            'discount_factor': 0.95,
            'exploration_rate': 0.2,
        })
        
        # 2. Regime Strategy Selector
        self.regime_selector = RegimeBasedStrategySelector(config={
            'strong_trend_adx': 30,
            'weak_trend_adx': 20,
            'high_volatility_atr_pct': 4.0,
        })
        
        # 3. Portfolio Risk Engine
        self.risk_engine = get_portfolio_risk_engine(config={
            'max_total_exposure': 0.80,
            'max_correlation_group_exposure': 0.30,
            'correlation_threshold': 0.7,
        })
        
        # 4. Execution Optimizer
        self.execution_optimizer = get_execution_optimizer(config={
            'maker_fee': 0.004,
            'taker_fee': 0.006,
            'max_spread_for_maker': 0.002,
        })
        
        # Trading state
        self.positions: Dict[str, Dict] = {}
        self.trade_history: list = []
        
        logger.info("✅ All optimization modules initialized")
        logger.info(f"Starting capital: ${self.capital:,.2f}")
    
    def analyze_entry_opportunity(
        self,
        symbol: str,
        df: pd.DataFrame,
        indicators: Dict,
        current_price: float,
        spread_pct: float
    ) -> Optional[Dict]:
        """
        Analyze if we should enter a position using regime-based strategy
        
        Args:
            symbol: Trading pair
            df: Price DataFrame
            indicators: Technical indicators
            current_price: Current market price
            spread_pct: Bid-ask spread (%)
            
        Returns:
            Entry signal dict or None
        """
        # 1. Detect regime and select strategy
        strategy_result = self.regime_selector.select_strategy(df, indicators)
        
        logger.info(f"\n{'='*70}")
        logger.info(f"ANALYZING ENTRY: {symbol}")
        logger.info(f"{'='*70}")
        logger.info(f"Regime: {strategy_result.regime_detection.regime.value}")
        logger.info(f"Strategy: {strategy_result.selected_strategy.value}")
        logger.info(f"Confidence: {strategy_result.regime_detection.confidence:.2%}")
        
        # 2. Check if regime was detected and strategy is available
        if self.regime_selector.current_regime is None:
            logger.info("❌ No regime detected - skipping")
            return None
        
        # Get strategy params from current detection
        playbook = strategy_result.strategy_params
        
        if playbook is None:
            logger.info("❌ No strategy playbook available - skipping")
            return None
        
        # 4. Calculate base position size from strategy
        base_size_pct = playbook.position_sizing.get('base_pct', 0.04)
        
        # 5. Get correlation-adjusted position size
        adjusted_size_pct = self.risk_engine.get_position_size_adjustment(
            symbol=symbol,
            base_size_pct=base_size_pct,
            portfolio_value=self.capital
        )
        
        position_size_usd = self.capital * adjusted_size_pct
        position_size_base = position_size_usd / current_price
        
        logger.info(f"Base Position Size: {base_size_pct*100:.1f}% (${position_size_usd:,.2f})")
        logger.info(f"Adjusted for Correlation: {adjusted_size_pct*100:.1f}%")
        
        # 6. Check portfolio risk limits
        can_add = self.risk_engine.add_position(
            symbol=symbol,
            size_usd=position_size_usd,
            direction='long',  # Assuming long for this example
            portfolio_value=self.capital
        )
        
        if not can_add:
            logger.info("❌ Position rejected by portfolio risk engine")
            return None
        
        # 7. Optimize execution
        exec_params = self.execution_optimizer.optimize_single_order(
            symbol=symbol,
            side='buy',
            size=position_size_base,
            current_price=current_price,
            spread_pct=spread_pct,
            urgency=0.5
        )
        
        logger.info(f"✅ Entry Signal Generated")
        logger.info(f"Order Type: {exec_params['order_type'].upper()}")
        logger.info(f"Estimated Fee: {exec_params['estimated_fee_pct']*100:.2f}%")
        logger.info(f"Reasoning: {exec_params['reasoning']}")
        
        return {
            'symbol': symbol,
            'side': 'buy',
            'size': position_size_base,
            'size_usd': position_size_usd,
            'regime': strategy_result.regime_detection.regime.value,
            'strategy': strategy_result.selected_strategy.value,
            'execution': exec_params,
            'entry_price': current_price,
        }
    
    def manage_exit(
        self,
        symbol: str,
        position: Dict,
        current_price: float,
        indicators: Dict
    ) -> Optional[Dict]:
        """
        Manage exit using RL-based optimization
        
        Args:
            symbol: Trading pair
            position: Current position data
            current_price: Current market price
            indicators: Technical indicators
            
        Returns:
            Exit signal dict or None
        """
        # Calculate position metrics
        entry_price = position['entry_price']
        entry_time = position['entry_time']
        size = position['size']
        
        profit_pct = (current_price - entry_price) / entry_price
        time_in_trade = (datetime.now() - entry_time).total_seconds() / 60  # minutes
        
        # Get volatility and trend from indicators
        volatility = float(indicators.get('atr', pd.Series([0])).iloc[-1]) / current_price
        trend_strength = float(indicators.get('adx', pd.Series([0])).iloc[-1]) / 100
        
        # Create exit state
        exit_state = ExitState(
            profit_pct=profit_pct,
            volatility=min(1.0, volatility),
            trend_strength=min(1.0, trend_strength),
            time_in_trade=int(time_in_trade),
            position_size_pct=position['size_usd'] / self.capital
        )
        
        # Get RL exit recommendation
        exit_action = self.rl_exit.select_action(exit_state, training=False)
        
        logger.info(f"\n{'='*70}")
        logger.info(f"EXIT ANALYSIS: {symbol}")
        logger.info(f"{'='*70}")
        logger.info(f"Unrealized P&L: {profit_pct*100:+.2f}%")
        logger.info(f"Time in Trade: {time_in_trade:.0f} minutes")
        logger.info(f"RL Recommendation: {exit_action.action_type.upper()} ({exit_action.exit_pct*100:.0f}%)")
        logger.info(f"Expected Value: {exit_action.expected_value:.3f}")
        
        if exit_action.exit_pct > 0:
            # Execute partial or full exit
            exit_size = size * exit_action.exit_pct
            exit_value = exit_size * current_price
            
            logger.info(f"✅ Executing {exit_action.action_type} exit")
            logger.info(f"Exit Size: {exit_size:.6f} ({exit_action.exit_pct*100:.0f}%)")
            logger.info(f"Exit Value: ${exit_value:,.2f}")
            
            return {
                'symbol': symbol,
                'side': 'sell',
                'size': exit_size,
                'exit_pct': exit_action.exit_pct,
                'action_type': exit_action.action_type,
                'exit_price': current_price,
                'realized_pnl_pct': profit_pct,
            }
        
        return None
    
    def get_portfolio_status(self) -> Dict:
        """
        Get comprehensive portfolio status
        
        Returns:
            Dictionary with portfolio metrics
        """
        # Calculate portfolio risk metrics
        risk_metrics = self.risk_engine.calculate_portfolio_metrics(self.capital)
        
        # Get regime stats
        regime_stats = self.regime_selector.get_regime_stats()
        
        # Get RL stats
        rl_stats = self.rl_exit.get_stats()
        
        # Get execution stats
        exec_stats = self.execution_optimizer.get_stats()
        
        return {
            'capital': self.capital,
            'return_pct': (self.capital - self.initial_capital) / self.initial_capital * 100,
            'num_positions': len(self.positions),
            'risk_metrics': risk_metrics,
            'regime_stats': regime_stats,
            'rl_stats': rl_stats,
            'execution_stats': exec_stats,
        }
    
    def print_portfolio_summary(self):
        """Print comprehensive portfolio summary"""
        status = self.get_portfolio_status()
        
        print("\n" + "=" * 70)
        print("📊 PORTFOLIO SUMMARY")
        print("=" * 70)
        print(f"Capital: ${status['capital']:,.2f}")
        print(f"Return: {status['return_pct']:+.2f}%")
        print(f"Open Positions: {status['num_positions']}")
        print("")
        
        print("Risk Metrics:")
        rm = status['risk_metrics']
        print(f"  Total Exposure: ${rm.total_exposure:,.2f} ({rm.total_exposure_pct*100:.1f}%)")
        print(f"  Long: ${rm.long_exposure:,.2f}")
        print(f"  Short: ${rm.short_exposure:,.2f}")
        print(f"  Net: ${rm.net_exposure:,.2f}")
        print(f"  Correlation Risk: {rm.correlation_risk:.2f}")
        print(f"  Diversification Ratio: {rm.diversification_ratio:.2f}")
        print(f"  VaR (95%): ${rm.var_95:,.2f}")
        print("")
        
        print("Regime Strategy:")
        rs = status['regime_stats']
        print(f"  Current Regime: {rs.get('current_regime', 'none').upper()}")
        print(f"  Current Strategy: {rs.get('current_strategy', 'none').upper()}")
        print("")
        
        print("RL Exit Optimizer:")
        rl = status['rl_stats']
        print(f"  Q-Table Size: {rl['q_table_size']} states")
        print(f"  Total Updates: {rl['total_updates']}")
        print(f"  Exploration Rate: {rl['epsilon']:.3f}")
        print("")
        
        print("Execution Optimizer:")
        ex = status['execution_stats']
        print(f"  Total Executed: {ex['total_executed']}")
        print(f"  Total Fees Saved: ${ex['total_fees_saved']:.2f}")
        print(f"  Avg Savings/Trade: ${ex['avg_fee_savings_per_trade']:.2f}")
        print("=" * 70)


def run_example():
    """Run example trading loop with all optimizations"""
    
    print("\n" + "=" * 70)
    print("🚀 NEXT-LEVEL OPTIMIZATION INTEGRATION EXAMPLE")
    print("=" * 70)
    
    # Initialize strategy
    strategy = OptimizedTradingStrategy(initial_capital=10000.0)
    
    # Mock market data (in real system, this comes from broker/data feed)
    print("\n📈 Simulating market data...")
    
    # Create trending market scenario
    dates = pd.date_range('2024-01-01', periods=100, freq='1h')
    df = pd.DataFrame({
        'timestamp': dates,
        'close': 50000 + np.cumsum(np.random.randn(100) * 50),
        'high': 50100 + np.cumsum(np.random.randn(100) * 50),
        'low': 49900 + np.cumsum(np.random.randn(100) * 50),
        'volume': np.random.randint(100, 500, 100),
    })
    
    indicators = {
        'adx': pd.Series([32.0] * 100),  # Strong trend
        'atr': pd.Series([500.0] * 100),
        'rsi': pd.Series([55.0] * 100),
        'bb_upper': pd.Series([51000.0] * 100),
        'bb_lower': pd.Series([49000.0] * 100),
    }
    
    current_price = float(df['close'].iloc[-1])
    spread_pct = 0.0015  # 0.15% spread
    
    print(f"Current Price: ${current_price:,.2f}")
    print(f"Spread: {spread_pct*100:.2f}%")
    
    # Analyze entry opportunity
    print("\n" + "=" * 70)
    print("PHASE 1: ENTRY ANALYSIS")
    print("=" * 70)
    
    entry_signal = strategy.analyze_entry_opportunity(
        symbol='BTC-USD',
        df=df,
        indicators=indicators,
        current_price=current_price,
        spread_pct=spread_pct
    )
    
    if entry_signal:
        print("\n✅ Entry signal generated!")
        
        # Simulate position entry
        strategy.positions['BTC-USD'] = {
            'symbol': 'BTC-USD',
            'size': entry_signal['size'],
            'size_usd': entry_signal['size_usd'],
            'entry_price': current_price,
            'entry_time': datetime.now(),
            'regime': entry_signal['regime'],
            'strategy': entry_signal['strategy'],
        }
    
    # Simulate price movement (profit scenario)
    print("\n" + "=" * 70)
    print("PHASE 2: EXIT ANALYSIS (After Price Movement)")
    print("=" * 70)
    
    # Price moved up 3%
    new_price = current_price * 1.03
    print(f"New Price: ${new_price:,.2f} (+3.0%)")
    
    if 'BTC-USD' in strategy.positions:
        exit_signal = strategy.manage_exit(
            symbol='BTC-USD',
            position=strategy.positions['BTC-USD'],
            current_price=new_price,
            indicators=indicators
        )
        
        if exit_signal:
            print(f"\n✅ Exit signal generated!")
            
            # Update capital (simulate trade)
            pnl = exit_signal['size'] * (new_price - current_price)
            strategy.capital += pnl
            
            # Record for RL learning
            # In real system, we'd update RL after trade closes
            print(f"Realized P&L: ${pnl:,.2f}")
    
    # Print final portfolio summary
    print("\n" + "=" * 70)
    print("PHASE 3: PORTFOLIO STATUS")
    print("=" * 70)
    
    strategy.print_portfolio_summary()
    
    print("\n" + "=" * 70)
    print("✅ EXAMPLE COMPLETE")
    print("=" * 70)
    print("\nThis example demonstrated:")
    print("1. ✅ Regime detection and adaptive strategy selection")
    print("2. ✅ Correlation-aware position sizing")
    print("3. ✅ Portfolio risk limit enforcement")
    print("4. ✅ Fee-optimized order execution")
    print("5. ✅ RL-based exit optimization")
    print("\nAll four next-level optimization systems working together!")
    print("=" * 70)


if __name__ == "__main__":
    run_example()
