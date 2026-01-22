"""
Enhanced Strategy Backtesting Script
=====================================

Backtests the NIJA APEX v7.1 strategy with:
- Enhanced entry scoring (0-100 weighted)
- Market regime detection
- Regime-specific performance tracking

Usage:
    python bot/backtest_enhanced_strategy.py --symbol BTC-USD --days 90
    python bot/backtest_enhanced_strategy.py --symbol ETH-USD --days 30 --initial-balance 10000
"""

import sys
import os
import argparse
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("nija.backtest")

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

try:
    from bot.nija_apex_strategy_v71 import NIJAApexStrategyV71
    from bot.enhanced_entry_scoring import EnhancedEntryScorer
    from bot.market_regime_detector import RegimeDetector, MarketRegime
    from bot.indicators import calculate_vwap, calculate_ema, calculate_rsi, calculate_macd, calculate_atr, calculate_adx
except ImportError:
    from nija_apex_strategy_v71 import NIJAApexStrategyV71
    from enhanced_entry_scoring import EnhancedEntryScorer
    from market_regime_detector import RegimeDetector, MarketRegime
    from indicators import calculate_vwap, calculate_ema, calculate_rsi, calculate_macd, calculate_atr, calculate_adx


class EnhancedBacktest:
    """
    Enhanced backtesting engine with regime tracking
    """
    
    def __init__(self, initial_balance: float = 10000.0, config: Dict = None):
        """
        Initialize backtest
        
        Args:
            initial_balance: Starting balance in USD
            config: Strategy configuration
        """
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        self.config = config or {}
        
        # Initialize strategy
        self.strategy = NIJAApexStrategyV71(broker_client=None, config=self.config)
        
        # Trade tracking
        self.trades: List[Dict] = []
        self.positions: Dict = {}
        self.equity_curve: List[Dict] = []
        
        # Regime tracking
        self.regime_stats = {
            MarketRegime.TRENDING: {'trades': [], 'signals': 0},
            MarketRegime.RANGING: {'trades': [], 'signals': 0},
            MarketRegime.VOLATILE: {'trades': [], 'signals': 0}
        }
        
        logger.info(f"Enhanced backtest initialized with ${initial_balance:,.2f}")
    
    def run_backtest(self, df: pd.DataFrame, symbol: str, commission: float = 0.001) -> Dict:
        """
        Run backtest on historical data
        
        Args:
            df: DataFrame with OHLCV data
            symbol: Trading symbol
            commission: Commission per trade (0.001 = 0.1%)
            
        Returns:
            Backtest results dictionary
        """
        logger.info(f"Starting enhanced backtest for {symbol}")
        logger.info(f"Data: {len(df)} candles from {df.index[0]} to {df.index[-1]}")
        
        min_candles = 100
        if len(df) < min_candles:
            logger.error(f"Insufficient data: {len(df)} candles (need {min_candles}+)")
            return self._empty_results()
        
        # Reset state
        self.positions = {}
        self.trades = []
        self.equity_curve = []
        self.current_balance = self.initial_balance
        self.regime_stats = {
            MarketRegime.TRENDING: {'trades': [], 'signals': 0},
            MarketRegime.RANGING: {'trades': [], 'signals': 0},
            MarketRegime.VOLATILE: {'trades': [], 'signals': 0}
        }
        
        # Process each candle
        for i in range(min_candles, len(df)):
            # Get historical data up to current candle
            historical_df = df.iloc[:i+1].copy()
            current_candle = df.iloc[i]
            current_price = current_candle['close']
            
            # Record equity
            total_equity = self._calculate_total_equity(current_price)
            self.equity_curve.append({
                'timestamp': current_candle.name,
                'equity': total_equity,
                'cash': self.current_balance,
                'position_value': total_equity - self.current_balance
            })
            
            # Check if we have a position
            if len(self.positions) > 0:
                # Manage existing position
                self._manage_position(historical_df, current_candle, commission)
            else:
                # Look for entry
                self._check_entry(historical_df, symbol, current_candle, commission)
        
        # Close any remaining positions
        final_price = df.iloc[-1]['close']
        if len(self.positions) > 0:
            for position_id in list(self.positions.keys()):
                self._close_position(position_id, final_price, 1.0, commission, "End of backtest", None)
        
        # Calculate statistics
        results = self._calculate_statistics()
        
        # Print results
        self._print_results(results)
        
        return results
    
    def _check_entry(self, df: pd.DataFrame, symbol: str, current_candle: pd.Series, commission: float):
        """Check for entry opportunity"""
        # Analyze market
        analysis = self.strategy.analyze_market(df, symbol, self.current_balance)
        
        if analysis['action'] in ['enter_long', 'enter_short']:
            side = 'long' if analysis['action'] == 'enter_long' else 'short'
            entry_price = current_candle['close']
            position_size_usd = analysis['position_size']
            
            # Check if we have enough balance
            if position_size_usd > self.current_balance:
                logger.warning(f"Insufficient balance: ${position_size_usd:.2f} > ${self.current_balance:.2f}")
                return
            
            # Track regime signal
            if 'metadata' in analysis and 'regime' in analysis['metadata']:
                regime_str = analysis['metadata']['regime']
                regime = MarketRegime(regime_str)
                self.regime_stats[regime]['signals'] += 1
            
            # Open position
            self._open_position(
                symbol, side, entry_price, position_size_usd,
                analysis['stop_loss'], analysis['take_profit'],
                analysis.get('score', 0), analysis.get('metadata', {}),
                commission
            )
    
    def _open_position(self, symbol: str, side: str, entry_price: float,
                      size_usd: float, stop_loss: float, take_profit: Dict,
                      score: float, metadata: Dict, commission: float):
        """Open a new position"""
        # Calculate commission
        commission_cost = size_usd * commission
        
        # Deduct from balance
        self.current_balance -= (size_usd + commission_cost)
        
        # Create position
        position_id = f"{symbol}_{len(self.trades)}"
        position = {
            'id': position_id,
            'symbol': symbol,
            'side': side,
            'entry_price': entry_price,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'size_usd': size_usd,
            'commission': commission_cost,
            'entry_time': datetime.now(),
            'score': score,
            'metadata': metadata
        }
        
        self.positions[position_id] = position
        
        regime = metadata.get('regime', 'unknown') if metadata else 'unknown'
        logger.info(f"Opened {side} position: {symbol} @ ${entry_price:.4f}, "
                   f"Size: ${size_usd:.2f}, Regime: {regime}, Score: {score:.1f}")
    
    def _manage_position(self, df: pd.DataFrame, current_candle: pd.Series, commission: float):
        """Manage existing position"""
        current_price = current_candle['close']
        
        for position_id, position in list(self.positions.items()):
            # Calculate current P&L
            if position['side'] == 'long':
                pnl_pct = (current_price - position['entry_price']) / position['entry_price']
            else:
                pnl_pct = (position['entry_price'] - current_price) / position['entry_price']
            
            # Check stop loss
            if position['side'] == 'long' and current_price <= position['stop_loss']:
                self._close_position(position_id, current_price, 1.0, commission, "Stop loss", position['metadata'].get('regime'))
            elif position['side'] == 'short' and current_price >= position['stop_loss']:
                self._close_position(position_id, current_price, 1.0, commission, "Stop loss", position['metadata'].get('regime'))
            
            # Check take profit (TP1)
            elif 'tp1' in position['take_profit']:
                tp1 = position['take_profit']['tp1']
                if position['side'] == 'long' and current_price >= tp1:
                    self._close_position(position_id, current_price, 0.5, commission, "Take profit TP1", position['metadata'].get('regime'))
                elif position['side'] == 'short' and current_price <= tp1:
                    self._close_position(position_id, current_price, 0.5, commission, "Take profit TP1", position['metadata'].get('regime'))
    
    def _close_position(self, position_id: str, exit_price: float, exit_percentage: float,
                       commission: float, reason: str, regime_str: str = None):
        """Close a position"""
        if position_id not in self.positions:
            return
        
        position = self.positions[position_id]
        
        # Calculate exit size
        exit_size_usd = position['size_usd'] * exit_percentage
        
        # Calculate P&L
        if position['side'] == 'long':
            pnl_pct = (exit_price - position['entry_price']) / position['entry_price']
        else:
            pnl_pct = (position['entry_price'] - exit_price) / position['entry_price']
        
        pnl = exit_size_usd * pnl_pct
        
        # Commission on exit
        exit_commission = exit_size_usd * commission
        
        # Net P&L
        net_pnl = pnl - exit_commission - (position['commission'] * exit_percentage)
        
        # Add to balance
        self.current_balance += (exit_size_usd + pnl - exit_commission)
        
        # Record trade
        trade = {
            'symbol': position['symbol'],
            'side': position['side'],
            'entry_price': position['entry_price'],
            'exit_price': exit_price,
            'size_usd': exit_size_usd,
            'pnl': net_pnl,
            'pnl_pct': pnl_pct,
            'exit_percentage': exit_percentage,
            'reason': reason,
            'score': position.get('score', 0),
            'regime': regime_str or position.get('metadata', {}).get('regime', 'unknown')
        }
        
        self.trades.append(trade)
        
        # Track by regime
        if regime_str:
            try:
                regime = MarketRegime(regime_str)
                self.regime_stats[regime]['trades'].append(trade)
            except:
                pass
        
        logger.info(f"Closed {exit_percentage*100:.0f}% of {position['side']} position: "
                   f"{position['symbol']} @ ${exit_price:.4f}, P&L: ${net_pnl:.2f} ({pnl_pct*100:.2f}%), "
                   f"Reason: {reason}, Regime: {regime_str or 'unknown'}")
        
        # Remove position if fully closed
        if exit_percentage >= 1.0:
            del self.positions[position_id]
        else:
            position['size_usd'] *= (1 - exit_percentage)
    
    def _calculate_total_equity(self, current_price: float) -> float:
        """Calculate total equity"""
        position_value = 0.0
        
        for position in self.positions.values():
            if position['side'] == 'long':
                pnl_pct = (current_price - position['entry_price']) / position['entry_price']
            else:
                pnl_pct = (position['entry_price'] - current_price) / position['entry_price']
            
            position_value += position['size_usd'] * (1 + pnl_pct)
        
        return self.current_balance + position_value
    
    def _calculate_statistics(self) -> Dict:
        """Calculate backtest statistics"""
        if len(self.trades) == 0:
            return self._empty_results()
        
        # Overall statistics
        winning_trades = [t for t in self.trades if t['pnl'] > 0]
        losing_trades = [t for t in self.trades if t['pnl'] < 0]
        
        total_trades = len(self.trades)
        win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0
        
        avg_win = np.mean([t['pnl'] for t in winning_trades]) if winning_trades else 0
        avg_loss = np.mean([t['pnl'] for t in losing_trades]) if losing_trades else 0
        
        # Equity curve statistics
        equity_values = [e['equity'] for e in self.equity_curve]
        peak_equity = np.max(equity_values) if equity_values else self.initial_balance
        
        # Calculate drawdown
        running_max = np.maximum.accumulate(equity_values)
        drawdown = (equity_values - running_max) / running_max
        max_drawdown = np.min(drawdown) if len(drawdown) > 0 else 0
        
        # Return metrics
        total_return = (self.current_balance - self.initial_balance) / self.initial_balance
        
        # Sharpe ratio
        if len(equity_values) > 1:
            returns = np.diff(equity_values) / equity_values[:-1]
            sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) > 0 else 0
        else:
            sharpe = 0
        
        # Regime-specific statistics
        regime_breakdown = {}
        for regime, data in self.regime_stats.items():
            trades = data['trades']
            if trades:
                regime_wins = [t for t in trades if t['pnl'] > 0]
                regime_breakdown[regime.value] = {
                    'total_trades': len(trades),
                    'signals': data['signals'],
                    'win_rate': len(regime_wins) / len(trades) if trades else 0,
                    'avg_pnl': np.mean([t['pnl'] for t in trades]),
                    'total_pnl': sum([t['pnl'] for t in trades])
                }
            else:
                regime_breakdown[regime.value] = {
                    'total_trades': 0,
                    'signals': data['signals'],
                    'win_rate': 0,
                    'avg_pnl': 0,
                    'total_pnl': 0
                }
        
        return {
            'initial_balance': self.initial_balance,
            'final_balance': self.current_balance,
            'total_return': total_return,
            'total_return_pct': total_return * 100,
            'total_trades': total_trades,
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': win_rate,
            'win_rate_pct': win_rate * 100,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': abs(avg_win / avg_loss) if avg_loss != 0 else 0,
            'max_drawdown': max_drawdown,
            'max_drawdown_pct': max_drawdown * 100,
            'sharpe_ratio': sharpe,
            'peak_equity': peak_equity,
            'regime_breakdown': regime_breakdown,
            'trades': self.trades,
            'equity_curve': self.equity_curve
        }
    
    def _empty_results(self) -> Dict:
        """Return empty results"""
        return {
            'initial_balance': self.initial_balance,
            'final_balance': self.current_balance,
            'total_return': 0.0,
            'total_return_pct': 0.0,
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'win_rate': 0.0,
            'win_rate_pct': 0.0,
            'avg_win': 0.0,
            'avg_loss': 0.0,
            'profit_factor': 0.0,
            'max_drawdown': 0.0,
            'max_drawdown_pct': 0.0,
            'sharpe_ratio': 0.0,
            'peak_equity': self.initial_balance,
            'regime_breakdown': {},
            'trades': [],
            'equity_curve': []
        }
    
    def _print_results(self, results: Dict):
        """Print backtest results"""
        print("\n" + "="*80)
        print("NIJA APEX v7.1 ENHANCED STRATEGY - BACKTEST RESULTS")
        print("="*80)
        
        print(f"\n💰 Performance:")
        print(f"  Initial Balance:  ${results['initial_balance']:,.2f}")
        print(f"  Final Balance:    ${results['final_balance']:,.2f}")
        print(f"  Total Return:     {results['total_return_pct']:+.2f}%")
        print(f"  Peak Equity:      ${results['peak_equity']:,.2f}")
        print(f"  Max Drawdown:     {results['max_drawdown_pct']:.2f}%")
        
        print(f"\n📊 Trade Statistics:")
        print(f"  Total Trades:     {results['total_trades']}")
        print(f"  Winning Trades:   {results['winning_trades']}")
        print(f"  Losing Trades:    {results['losing_trades']}")
        print(f"  Win Rate:         {results['win_rate_pct']:.1f}%")
        
        print(f"\n💵 Trade Averages:")
        print(f"  Average Win:      ${results['avg_win']:,.2f}")
        print(f"  Average Loss:     ${results['avg_loss']:,.2f}")
        print(f"  Profit Factor:    {results['profit_factor']:.2f}")
        
        print(f"\n📈 Risk Metrics:")
        print(f"  Sharpe Ratio:     {results['sharpe_ratio']:.2f}")
        
        # Regime breakdown
        if results['regime_breakdown']:
            print(f"\n🎯 Regime Performance Breakdown:")
            for regime, stats in results['regime_breakdown'].items():
                print(f"\n  {regime.upper()}:")
                print(f"    Signals:       {stats['signals']}")
                print(f"    Trades:        {stats['total_trades']}")
                print(f"    Win Rate:      {stats['win_rate']*100:.1f}%")
                print(f"    Avg P&L:       ${stats['avg_pnl']:.2f}")
                print(f"    Total P&L:     ${stats['total_pnl']:.2f}")
        
        print("\n" + "="*80 + "\n")


def generate_sample_data(symbol: str, days: int = 90) -> pd.DataFrame:
    """
    Generate sample OHLCV data for backtesting
    
    In production, this should fetch real historical data from exchange API
    """
    logger.info(f"Generating sample data for {symbol} ({days} days)")
    
    # Generate timestamps (1-hour candles) - use lowercase 'h' for newer pandas versions
    end_time = datetime.now()
    start_time = end_time - timedelta(days=days)
    timestamps = pd.date_range(start=start_time, end=end_time, freq='1h')
    
    # Generate synthetic price data with trend
    np.random.seed(42)
    base_price = 50000 if 'BTC' in symbol else 3000 if 'ETH' in symbol else 100
    
    # Create trending price action
    trend = np.cumsum(np.random.randn(len(timestamps)) * base_price * 0.01)
    prices = base_price + trend
    
    # Generate OHLCV data
    data = []
    for i, ts in enumerate(timestamps):
        close = prices[i]
        open_price = close * (1 + np.random.randn() * 0.005)
        high = max(open_price, close) * (1 + abs(np.random.randn()) * 0.01)
        low = min(open_price, close) * (1 - abs(np.random.randn()) * 0.01)
        volume = abs(np.random.randn() * 1000000)
        
        data.append({
            'timestamp': ts,
            'open': open_price,
            'high': high,
            'low': low,
            'close': close,
            'volume': volume
        })
    
    df = pd.DataFrame(data)
    df.set_index('timestamp', inplace=True)
    
    return df


def main():
    """Main backtest function"""
    parser = argparse.ArgumentParser(description='Backtest NIJA APEX v7.1 Enhanced Strategy')
    parser.add_argument('--symbol', type=str, default='BTC-USD', help='Trading symbol')
    parser.add_argument('--days', type=int, default=90, help='Number of days to backtest')
    parser.add_argument('--initial-balance', type=float, default=10000.0, help='Initial balance')
    parser.add_argument('--commission', type=float, default=0.001, help='Commission rate (0.001 = 0.1%)')
    
    args = parser.parse_args()
    
    # Generate or load historical data
    df = generate_sample_data(args.symbol, args.days)
    
    # Run backtest
    backtest = EnhancedBacktest(initial_balance=args.initial_balance)
    results = backtest.run_backtest(df, args.symbol, commission=args.commission)
    
    logger.info("Backtest complete!")
    
    return results


if __name__ == '__main__':
    main()
