"""
NIJA Apex Strategy v7.1 - Backtesting Module
==============================================

Backtest the Apex strategy on historical data.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple
from datetime import datetime, timedelta
import logging

from apex_strategy_v7 import ApexStrategyV7
from apex_config import EXECUTION

logger = logging.getLogger("nija.apex.backtest")


class ApexBacktest:
    """
    Backtesting engine for Apex Strategy v7.1
    """

    def __init__(self, initial_balance: float = 10000.0, enable_ai: bool = False):
        """
        Initialize backtest

        Args:
            initial_balance: Starting balance in USD
            enable_ai: Enable AI engine (if model available)
        """
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        self.strategy = ApexStrategyV7(initial_balance, enable_ai=enable_ai)

        self.trades: List[Dict] = []
        self.positions: Dict[str, Dict] = {}
        self.equity_curve: List[Dict] = []

        logger.info(f"Backtest initialized with ${initial_balance:,.2f}")

    def run_backtest(
        self,
        df: pd.DataFrame,
        symbol: str,
        commission: float = 0.001
    ) -> Dict:
        """
        Run backtest on historical data

        Args:
            df: DataFrame with OHLCV data
            symbol: Trading symbol
            commission: Commission per trade as decimal (0.001 = 0.1%)

        Returns:
            dict: Backtest results and statistics
        """
        logger.info(f"Starting backtest for {symbol} with {len(df)} candles")

        # Ensure we have enough data
        min_candles = EXECUTION['min_candles_required']
        if len(df) < min_candles:
            logger.error(f"Insufficient data: {len(df)} candles (need {min_candles}+)")
            return self._empty_results()

        # Reset state
        self.positions = {}
        self.trades = []
        self.equity_curve = []
        self.current_balance = self.initial_balance

        # Process each candle
        for i in range(min_candles, len(df)):
            # Get historical data up to current candle
            historical_df = df.iloc[:i+1].copy()
            current_candle = df.iloc[i]

            # Record equity
            total_equity = self._calculate_total_equity(current_candle['close'])
            self.equity_curve.append({
                'timestamp': current_candle.name if hasattr(current_candle, 'name') else i,
                'equity': total_equity,
                'cash': self.current_balance,
                'position_value': total_equity - self.current_balance,
            })

            # Update existing positions
            positions_to_close = []
            for position_id, position in self.positions.items():
                update_result = self.strategy.update_position(
                    position_id,
                    historical_df,
                    position
                )

                if update_result['action'] == 'exit':
                    # Close position
                    exit_price = current_candle['close']
                    pnl = self._close_position(
                        position_id,
                        exit_price,
                        update_result['exit_percentage'],
                        commission,
                        update_result['reason']
                    )
                    positions_to_close.append(position_id)

                elif update_result['action'] == 'update_stop':
                    # Update stop loss
                    self.positions[position_id]['stop_loss'] = update_result['new_stop']

            # Remove closed positions
            for position_id in positions_to_close:
                if position_id in self.positions:
                    del self.positions[position_id]

            # Check for new entry opportunities (if no positions)
            if len(self.positions) == 0:
                entry_analysis = self.strategy.analyze_entry_opportunity(
                    historical_df,
                    symbol
                )

                if entry_analysis['should_enter']:
                    # Open new position
                    self._open_position(
                        symbol,
                        entry_analysis,
                        current_candle['close'],
                        commission
                    )

        # Close any remaining positions at end
        final_price = df.iloc[-1]['close']
        for position_id in list(self.positions.keys()):
            self._close_position(
                position_id,
                final_price,
                1.0,
                commission,
                "End of backtest"
            )

        # Calculate statistics
        results = self._calculate_statistics()

        logger.info(f"Backtest complete: {len(self.trades)} trades, "
                   f"Final balance: ${self.current_balance:,.2f}")

        return results

    def _open_position(
        self,
        symbol: str,
        entry_analysis: Dict,
        entry_price: float,
        commission: float
    ):
        """Open a new position"""
        position_size_usd = entry_analysis['position_size_usd']

        # Check if we have enough balance
        if position_size_usd > self.current_balance:
            logger.warning(f"Insufficient balance for position: ${position_size_usd:,.2f} > ${self.current_balance:,.2f}")
            return

        # Calculate commission
        commission_cost = position_size_usd * commission

        # Deduct from balance
        self.current_balance -= (position_size_usd + commission_cost)

        # Create position
        position_id = f"{symbol}_{len(self.trades)}"
        position = {
            'id': position_id,
            'symbol': symbol,
            'side': entry_analysis['side'],
            'entry_price': entry_price,
            'stop_loss': entry_analysis['stop_loss'],
            'take_profit_levels': entry_analysis['take_profit_levels'],
            'size_usd': position_size_usd,
            'commission': commission_cost,
            'entry_time': datetime.now(),
            'trend_quality': entry_analysis['trend_quality'],
            'score': entry_analysis['score'],
        }

        self.positions[position_id] = position
        self.strategy.risk_manager.add_position(position)

        logger.info(f"Opened {entry_analysis['side']} position: {symbol} @ ${entry_price:.4f}, "
                   f"Size: ${position_size_usd:.2f}, Stop: ${entry_analysis['stop_loss']:.4f}")

    def _close_position(
        self,
        position_id: str,
        exit_price: float,
        exit_percentage: float,
        commission: float,
        reason: str
    ) -> float:
        """Close a position (fully or partially)"""
        if position_id not in self.positions:
            return 0.0

        position = self.positions[position_id]

        # Calculate exit size
        exit_size_usd = position['size_usd'] * exit_percentage

        # Calculate P&L
        if position['side'] == 'long':
            pnl_pct = (exit_price - position['entry_price']) / position['entry_price']
        else:  # short
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
            'trend_quality': position['trend_quality'],
            'score': position['score'],
        }

        self.trades.append(trade)
        self.strategy.risk_manager.update_daily_pnl(net_pnl)

        logger.info(f"Closed {exit_percentage*100:.0f}% of {position['side']} position: "
                   f"{position['symbol']} @ ${exit_price:.4f}, P&L: ${net_pnl:.2f} ({pnl_pct*100:.2f}%), "
                   f"Reason: {reason}")

        # If full exit, remove position
        if exit_percentage >= 1.0:
            self.strategy.risk_manager.remove_position(position_id)
        else:
            # Reduce position size
            position['size_usd'] *= (1 - exit_percentage)

        return net_pnl

    def _calculate_total_equity(self, current_price: float) -> float:
        """Calculate total equity (cash + position value)"""
        position_value = 0.0

        for position in self.positions.values():
            if position['side'] == 'long':
                pnl_pct = (current_price - position['entry_price']) / position['entry_price']
            else:  # short
                pnl_pct = (position['entry_price'] - current_price) / position['entry_price']

            position_value += position['size_usd'] * (1 + pnl_pct)

        return self.current_balance + position_value

    def _calculate_statistics(self) -> Dict:
        """Calculate backtest statistics"""
        if len(self.trades) == 0:
            return self._empty_results()

        # Trade statistics
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

        # Sharpe ratio (simplified - assumes daily returns)
        if len(equity_values) > 1:
            returns = np.diff(equity_values) / equity_values[:-1]
            sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) > 0 else 0
        else:
            sharpe = 0

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
            'trades': self.trades,
            'equity_curve': self.equity_curve,
        }

    def _empty_results(self) -> Dict:
        """Return empty results structure"""
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
            'trades': [],
            'equity_curve': [],
        }

    def print_results(self, results: Dict):
        """Print backtest results in a formatted way"""
        print("\n" + "="*60)
        print("APEX STRATEGY v7.1 - BACKTEST RESULTS")
        print("="*60)

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

        print("\n" + "="*60 + "\n")
