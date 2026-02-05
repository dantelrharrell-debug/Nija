"""
NIJA Trading Journal Module

Comprehensive trade logging system for performance analysis and ML model improvement.

Features:
- Log all trades with complete context (features, signals, outcomes)
- Track entry/exit details and P&L
- Generate performance analytics
- Export data for ML training
- Identify patterns in winning/losing trades

Author: NIJA Trading Systems
Version: 1.0
Date: December 2024
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import json
import os
import logging

logger = logging.getLogger("nija.trade_journal")


class TradeJournal:
    """
    Comprehensive trading journal for logging and analyzing all trades.

    Each trade record includes:
    - Entry details (price, size, time, features, signals)
    - Exit details (price, time, reason, P&L)
    - AI scores and confidence
    - Market conditions at entry/exit
    - Trade metadata and tags
    """

    def __init__(self, journal_dir: str = "./data/trade_journal"):
        """
        Initialize trade journal.

        Args:
            journal_dir: Directory to store journal files
        """
        self.journal_dir = journal_dir
        os.makedirs(journal_dir, exist_ok=True)

        # Journal files
        self.trades_file = os.path.join(journal_dir, "trades.csv")
        self.daily_summary_file = os.path.join(journal_dir, "daily_summary.csv")
        self.performance_metrics_file = os.path.join(journal_dir, "performance_metrics.json")

        # In-memory storage for active trades
        self.active_trades: Dict[str, Dict] = {}

        # Load existing journal if it exists
        if os.path.exists(self.trades_file):
            self.trades_df = pd.read_csv(self.trades_file)
            logger.info(f"Loaded {len(self.trades_df)} trades from journal")
        else:
            self.trades_df = pd.DataFrame()
            logger.info("New trade journal created")

        logger.info(f"Trade Journal initialized: {journal_dir}")

    def log_entry(self, trade_id: str, symbol: str, side: str, entry_price: float,
                  position_size: float, stop_loss: float, take_profit_levels: Dict[str, float],
                  features: Dict[str, float], ai_signal: Dict[str, Any],
                  market_conditions: Dict[str, Any], notes: str = "") -> None:
        """
        Log a trade entry.

        Args:
            trade_id: Unique trade identifier
            symbol: Trading symbol
            side: 'long' or 'short'
            entry_price: Entry price
            position_size: Position size in USD
            stop_loss: Stop loss price
            take_profit_levels: Dict with tp1, tp2, tp3
            features: Market features at entry
            ai_signal: AI signal details (score, confidence, etc.)
            market_conditions: Market regime, volatility, etc.
            notes: Optional notes
        """
        entry_time = datetime.now()

        trade_record = {
            'trade_id': trade_id,
            'entry_time': entry_time,
            'symbol': symbol,
            'side': side,
            'entry_price': entry_price,
            'position_size': position_size,
            'stop_loss': stop_loss,
            'tp1': take_profit_levels.get('tp1', 0),
            'tp2': take_profit_levels.get('tp2', 0),
            'tp3': take_profit_levels.get('tp3', 0),
            'ai_score': ai_signal.get('score', 0),
            'ai_confidence': ai_signal.get('confidence', 0),
            'ai_signal_type': ai_signal.get('signal', 'neutral'),
            'adx': features.get('adx', 0),
            'rsi': features.get('rsi', 50),
            'atr_pct': features.get('atr_pct', 0),
            'volume_ratio': features.get('volume_ratio', 1.0),
            'ema_alignment': features.get('ema_alignment', 0),
            'market_regime': market_conditions.get('regime', 'unknown'),
            'volatility_state': market_conditions.get('volatility', 'normal'),
            'features_json': json.dumps(features),
            'market_conditions_json': json.dumps(market_conditions),
            'notes': notes,
            'status': 'active'
        }

        # Store in active trades
        self.active_trades[trade_id] = trade_record

        logger.info(f"Entry logged: {trade_id} - {symbol} {side} @ {entry_price:.2f}, "
                   f"AI Score: {ai_signal.get('score', 0):.1f}, "
                   f"Confidence: {ai_signal.get('confidence', 0):.2f}")

    def log_exit(self, trade_id: str, exit_price: float, exit_reason: str,
                 partial_exit: bool = False, exit_pct: float = 1.0) -> Optional[Dict]:
        """
        Log a trade exit (full or partial).

        Args:
            trade_id: Trade identifier
            exit_price: Exit price
            exit_reason: Reason for exit (e.g., 'TP1 hit', 'stop loss', 'signal reversal')
            partial_exit: Whether this is a partial exit
            exit_pct: Percentage of position exited (default 1.0 = 100%)

        Returns:
            Dict with trade summary or None if trade not found
        """
        if trade_id not in self.active_trades:
            logger.warning(f"Trade {trade_id} not found in active trades")
            return None

        trade = self.active_trades[trade_id]
        exit_time = datetime.now()

        # Calculate P&L
        entry_price = trade['entry_price']
        position_size = trade['position_size']
        side = trade['side']

        if side == 'long':
            pnl_pct = ((exit_price - entry_price) / entry_price) * 100
        else:  # short
            pnl_pct = ((entry_price - exit_price) / entry_price) * 100

        pnl_dollars = (pnl_pct / 100) * position_size * exit_pct

        # Calculate hold time
        entry_time = trade['entry_time']
        hold_time = exit_time - entry_time
        hold_minutes = int(hold_time.total_seconds() / 60)

        # Determine outcome
        # PROFIT GATE: No neutral outcomes - if not profitable, it's a loss
        # After fees, breakeven or zero P&L means money was lost on fees
        if pnl_dollars > 0:
            outcome = 'win'
        else:
            # Any trade that doesn't make money (including breakeven) is a loss
            # This ensures honest accounting - fees mean breakeven = loss
            outcome = 'loss'

        # Update trade record
        if partial_exit:
            # For partial exits, we'll create a separate row
            exit_record = trade.copy()
            exit_record['exit_time'] = exit_time
            exit_record['exit_price'] = exit_price
            exit_record['exit_reason'] = exit_reason
            exit_record['exit_pct'] = exit_pct
            exit_record['hold_minutes'] = hold_minutes
            exit_record['pnl_pct'] = pnl_pct
            exit_record['pnl_dollars'] = pnl_dollars
            exit_record['outcome'] = outcome
            exit_record['status'] = 'partial_exit'

            # Reduce position size in active trade
            trade['position_size'] *= (1.0 - exit_pct)
        else:
            # Full exit - complete the trade
            trade['exit_time'] = exit_time
            trade['exit_price'] = exit_price
            trade['exit_reason'] = exit_reason
            trade['exit_pct'] = exit_pct
            trade['hold_minutes'] = hold_minutes
            trade['pnl_pct'] = pnl_pct
            trade['pnl_dollars'] = pnl_dollars
            trade['outcome'] = outcome
            trade['status'] = 'closed'

            exit_record = trade

            # Remove from active trades
            del self.active_trades[trade_id]

        # Append to journal
        self._append_to_journal(exit_record)

        logger.info(f"Exit logged: {trade_id} - {exit_reason}, "
                   f"P&L: ${pnl_dollars:.2f} ({pnl_pct:.2f}%), "
                   f"Hold: {hold_minutes}m, Outcome: {outcome}")

        return exit_record

    def _append_to_journal(self, trade_record: Dict) -> None:
        """
        Append trade record to journal CSV.

        Args:
            trade_record: Complete trade record
        """
        try:
            df = pd.DataFrame([trade_record])

            if os.path.exists(self.trades_file):
                df.to_csv(self.trades_file, mode='a', header=False, index=False)
            else:
                df.to_csv(self.trades_file, mode='w', header=True, index=False)

            # Update in-memory dataframe
            if len(self.trades_df) == 0:
                self.trades_df = df
            else:
                self.trades_df = pd.concat([self.trades_df, df], ignore_index=True)

        except Exception as e:
            logger.error(f"Error appending to journal: {e}")

    def get_active_trades(self) -> List[Dict]:
        """
        Get list of currently active trades.

        Returns:
            List of active trade records
        """
        return list(self.active_trades.values())

    def get_recent_trades(self, n: int = 10) -> pd.DataFrame:
        """
        Get N most recent closed trades.

        Args:
            n: Number of trades to return

        Returns:
            DataFrame of recent trades
        """
        if len(self.trades_df) == 0:
            return pd.DataFrame()

        closed_trades = self.trades_df[self.trades_df['status'] == 'closed']
        return closed_trades.tail(n)

    def calculate_performance_metrics(self, days: int = 30) -> Dict[str, Any]:
        """
        Calculate comprehensive performance metrics.

        Args:
            days: Number of days to analyze (default 30)

        Returns:
            Dict with performance metrics
        """
        if len(self.trades_df) == 0:
            return {'error': 'No trades in journal'}

        # Filter to closed trades in time period
        cutoff_date = datetime.now() - timedelta(days=days)

        trades = self.trades_df[
            (self.trades_df['status'] == 'closed') &
            (pd.to_datetime(self.trades_df['entry_time']) >= cutoff_date)
        ].copy()

        if len(trades) == 0:
            return {'error': f'No trades in last {days} days'}

        # Basic metrics
        total_trades = len(trades)
        wins = len(trades[trades['outcome'] == 'win'])
        losses = len(trades[trades['outcome'] == 'loss'])
        # PROFIT GATE: No breakeven outcomes - removed from metrics

        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

        # P&L metrics
        total_pnl = trades['pnl_dollars'].sum()
        avg_win = trades[trades['outcome'] == 'win']['pnl_dollars'].mean() if wins > 0 else 0
        avg_loss = trades[trades['outcome'] == 'loss']['pnl_dollars'].mean() if losses > 0 else 0

        # Risk metrics
        profit_factor = abs(avg_win * wins / (avg_loss * losses)) if (losses > 0 and avg_loss != 0) else float('inf')

        max_win = trades['pnl_dollars'].max()
        max_loss = trades['pnl_dollars'].min()

        # Time metrics
        avg_hold_time = trades['hold_minutes'].mean()

        # AI metrics
        avg_confidence_wins = trades[trades['outcome'] == 'win']['ai_confidence'].mean() if wins > 0 else 0
        avg_confidence_losses = trades[trades['outcome'] == 'loss']['ai_confidence'].mean() if losses > 0 else 0

        # Daily metrics
        trades['date'] = pd.to_datetime(trades['entry_time']).dt.date
        daily_pnl = trades.groupby('date')['pnl_dollars'].sum()

        best_day = daily_pnl.max()
        worst_day = daily_pnl.min()
        avg_daily_pnl = daily_pnl.mean()

        # Calculate drawdown
        cumulative_pnl = daily_pnl.cumsum()
        running_max = cumulative_pnl.expanding().max()
        drawdown = cumulative_pnl - running_max
        max_drawdown = drawdown.min()

        metrics = {
            'period_days': days,
            'total_trades': total_trades,
            'wins': wins,
            'losses': losses,
            # PROFIT GATE: No breakeven outcomes tracked
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'max_win': max_win,
            'max_loss': max_loss,
            'avg_hold_time_minutes': avg_hold_time,
            'avg_confidence_wins': avg_confidence_wins,
            'avg_confidence_losses': avg_confidence_losses,
            'best_day': best_day,
            'worst_day': worst_day,
            'avg_daily_pnl': avg_daily_pnl,
            'max_drawdown': max_drawdown,
            'trading_days': len(daily_pnl)
        }

        # Save to file
        with open(self.performance_metrics_file, 'w') as f:
            json.dump(metrics, f, indent=2, default=str)

        return metrics

    def analyze_winning_patterns(self) -> Dict[str, Any]:
        """
        Analyze patterns in winning trades.

        Returns:
            Dict with analysis of common factors in winning trades
        """
        if len(self.trades_df) == 0:
            return {'error': 'No trades to analyze'}

        wins = self.trades_df[self.trades_df['outcome'] == 'win']
        losses = self.trades_df[self.trades_df['outcome'] == 'loss']

        if len(wins) == 0:
            return {'error': 'No winning trades to analyze'}

        analysis = {
            'winning_trades': {
                'avg_ai_confidence': wins['ai_confidence'].mean(),
                'avg_ai_score': wins['ai_score'].mean(),
                'avg_adx': wins['adx'].mean(),
                'avg_rsi': wins['rsi'].mean(),
                'avg_volume_ratio': wins['volume_ratio'].mean(),
                'most_common_regime': wins['market_regime'].mode()[0] if len(wins) > 0 and len(wins['market_regime'].mode()) > 0 else 'unknown',
                'avg_hold_time': wins['hold_minutes'].mean()
            }
        }

        if len(losses) > 0:
            loss_regime_mode = losses['market_regime'].mode()
            analysis['losing_trades'] = {
                'avg_ai_confidence': losses['ai_confidence'].mean(),
                'avg_ai_score': losses['ai_score'].mean(),
                'avg_adx': losses['adx'].mean(),
                'avg_rsi': losses['rsi'].mean(),
                'avg_volume_ratio': losses['volume_ratio'].mean(),
                'most_common_regime': loss_regime_mode[0] if len(loss_regime_mode) > 0 else 'unknown',
                'avg_hold_time': losses['hold_minutes'].mean()
            }

            # Differences
            analysis['differences'] = {
                'confidence_diff': analysis['winning_trades']['avg_ai_confidence'] - analysis['losing_trades']['avg_ai_confidence'],
                'score_diff': analysis['winning_trades']['avg_ai_score'] - analysis['losing_trades']['avg_ai_score'],
                'adx_diff': analysis['winning_trades']['avg_adx'] - analysis['losing_trades']['avg_adx']
            }

        return analysis

    def export_for_ml_training(self, output_file: Optional[str] = None) -> str:
        """
        Export journal data in format suitable for ML training.

        Args:
            output_file: Output file path (optional)

        Returns:
            str: Path to exported file
        """
        if output_file is None:
            output_file = os.path.join(self.journal_dir, "ml_training_data.csv")

        if len(self.trades_df) == 0:
            logger.warning("No trades to export")
            return ""

        # Select relevant columns for ML
        ml_columns = [
            'symbol', 'side', 'ai_score', 'ai_confidence', 'adx', 'rsi', 'atr_pct',
            'volume_ratio', 'ema_alignment', 'market_regime', 'volatility_state',
            'outcome', 'pnl_pct', 'hold_minutes'
        ]

        available_columns = [col for col in ml_columns if col in self.trades_df.columns]
        ml_data = self.trades_df[available_columns].copy()

        # Save
        ml_data.to_csv(output_file, index=False)
        logger.info(f"Exported {len(ml_data)} trades for ML training: {output_file}")

        return output_file

    def print_summary(self, days: int = 7) -> None:
        """
        Print a human-readable summary of recent performance.

        Args:
            days: Number of days to summarize
        """
        metrics = self.calculate_performance_metrics(days)

        if 'error' in metrics:
            print(f"\n{metrics['error']}")
            return

        print("\n" + "="*60)
        print(f"TRADING JOURNAL SUMMARY - Last {days} Days")
        print("="*60)
        print(f"Total Trades: {metrics['total_trades']}")
        print(f"Wins: {metrics['wins']} | Losses: {metrics['losses']}")
        # PROFIT GATE: No breakeven outcomes to report
        print(f"Win Rate: {metrics['win_rate']:.1f}%")
        print(f"\nP&L Performance:")
        print(f"  Total P&L: ${metrics['total_pnl']:.2f}")
        print(f"  Avg Win: ${metrics['avg_win']:.2f}")
        print(f"  Avg Loss: ${metrics['avg_loss']:.2f}")
        print(f"  Profit Factor: {metrics['profit_factor']:.2f}")
        print(f"\nDaily Performance:")
        print(f"  Trading Days: {metrics['trading_days']}")
        print(f"  Avg Daily P&L: ${metrics['avg_daily_pnl']:.2f}")
        print(f"  Best Day: ${metrics['best_day']:.2f}")
        print(f"  Worst Day: ${metrics['worst_day']:.2f}")
        print(f"  Max Drawdown: ${metrics['max_drawdown']:.2f}")
        print(f"\nAI Performance:")
        print(f"  Avg Confidence (Wins): {metrics['avg_confidence_wins']:.2f}")
        print(f"  Avg Confidence (Losses): {metrics['avg_confidence_losses']:.2f}")
        print("="*60 + "\n")
