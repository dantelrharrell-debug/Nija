"""
NIJA Profit Confirmation Logger

Solves two critical problems:
1. Reduces position count explosion by tracking profit confirmations separately
2. Defines exact "profit proven" criteria to eliminate guesswork

Design Principles:
- A profit is "proven" when NET profit (after fees) exceeds minimum threshold
- Profit must be held for minimum time to avoid false confirmations
- Each position has ONE profit confirmation state (not multiple partial states)
- Position count explosion is prevented by consolidating profit tracking

Features:
- Simple 24-72h profit reports
- Tracks starting/ending equity
- Calculates win rate, avg R, and total fees
- Standardized profit confirmation logs

Author: NIJA Trading Systems
Date: February 6, 2026
"""

import logging
import json
from typing import Dict, Optional, List
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock

logger = logging.getLogger("nija.profit_confirmation")


class ProfitConfirmationLogger:
    """
    Centralized profit confirmation tracking and logging.
    
    Key Features:
    1. Clear "profit proven" criteria (NET profit after fees)
    2. Position count explosion prevention
    3. Standardized profit confirmation log format
    4. Comprehensive profit confirmation metrics
    """
    
    # Profit Confirmation Criteria
    MIN_NET_PROFIT_PCT = 0.005  # 0.5% minimum NET profit (after fees) to confirm
    MIN_HOLD_TIME_SECONDS = 120  # 2 minutes minimum hold before profit confirmation
    PROFIT_GIVEBACK_THRESHOLD = 0.003  # 0.3% pullback triggers immediate exit
    
    def __init__(self, data_dir: str = "./data"):
        """
        Initialize profit confirmation logger.
        
        Args:
            data_dir: Directory for profit confirmation state file
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True, parents=True)
        self.confirmations_file = self.data_dir / "profit_confirmations.json"
        
        # Profit confirmation state
        self.confirmed_profits: Dict[str, Dict] = {}  # symbol -> confirmation data
        self.lock = Lock()
        
        # Statistics
        self.total_confirmations = 0
        self.total_givebacks = 0
        self.total_profit_taken_usd = 0.0
        self.total_profit_given_back_usd = 0.0
        
        # Trade history for reporting (last 72 hours)
        self.trade_history: List[Dict] = []
        
        # Load existing confirmations
        self._load_confirmations()
        
        logger.info("✅ Profit Confirmation Logger initialized")
        logger.info(f"   Min NET profit: {self.MIN_NET_PROFIT_PCT*100:.2f}%")
        logger.info(f"   Min hold time: {self.MIN_HOLD_TIME_SECONDS}s")
        logger.info(f"   Giveback threshold: {self.PROFIT_GIVEBACK_THRESHOLD*100:.2f}%")
    
    def _load_confirmations(self):
        """Load profit confirmations from file"""
        if not self.confirmations_file.exists():
            logger.info("No saved profit confirmations found (first run)")
            return
        
        try:
            with open(self.confirmations_file, 'r') as f:
                data = json.load(f)
            
            self.confirmed_profits = data.get('confirmations', {})
            self.total_confirmations = data.get('total_confirmations', 0)
            self.total_givebacks = data.get('total_givebacks', 0)
            self.total_profit_taken_usd = data.get('total_profit_taken_usd', 0.0)
            self.total_profit_given_back_usd = data.get('total_profit_given_back_usd', 0.0)
            self.trade_history = data.get('trade_history', [])
            
            logger.info(f"📊 Loaded profit confirmation history:")
            logger.info(f"   Total confirmations: {self.total_confirmations}")
            logger.info(f"   Total givebacks: {self.total_givebacks}")
            logger.info(f"   Profit taken: ${self.total_profit_taken_usd:.2f}")
            logger.info(f"   Profit given back: ${self.total_profit_given_back_usd:.2f}")
            
        except Exception as e:
            logger.error(f"Error loading profit confirmations: {e}")
            self.confirmed_profits = {}
    
    def _save_confirmations(self):
        """Save profit confirmations to file (assumes lock is held)"""
        try:
            data = {
                'confirmations': self.confirmed_profits,
                'total_confirmations': self.total_confirmations,
                'total_givebacks': self.total_givebacks,
                'total_profit_taken_usd': self.total_profit_taken_usd,
                'total_profit_given_back_usd': self.total_profit_given_back_usd,
                'trade_history': self.trade_history,
                'last_updated': datetime.now().isoformat()
            }
            
            # Atomic write
            temp_file = self.confirmations_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)
            temp_file.replace(self.confirmations_file)
            
        except Exception as e:
            logger.error(f"Error saving profit confirmations: {e}")
    
    def check_profit_proven(
        self,
        symbol: str,
        entry_price: float,
        current_price: float,
        entry_time: datetime,
        position_size_usd: float,
        broker_fee_pct: float,
        side: str = 'long'
    ) -> Dict[str, any]:
        """
        Check if profit is "proven" for a position.
        
        Profit is PROVEN when ALL criteria are met:
        1. NET profit (after fees) exceeds MIN_NET_PROFIT_PCT
        2. Position held for at least MIN_HOLD_TIME_SECONDS
        3. Profit is increasing or stable (not giving back)
        
        Args:
            symbol: Trading symbol
            entry_price: Position entry price
            current_price: Current market price
            entry_time: Position entry timestamp
            position_size_usd: Position size in USD
            broker_fee_pct: Broker round-trip fee percentage (e.g., 0.014 for 1.4%)
            side: Position side ('long' or 'short')
        
        Returns:
            Dict with:
                - proven: bool (is profit proven?)
                - gross_profit_pct: float (gross profit percentage)
                - net_profit_pct: float (net profit after fees)
                - net_profit_usd: float (net profit in USD)
                - hold_time_seconds: float (how long position held)
                - criteria_met: dict (which criteria are met)
                - action: str (recommended action)
        """
        # Calculate gross profit
        if side == 'long':
            gross_profit_pct = (current_price - entry_price) / entry_price
        else:  # short
            gross_profit_pct = (entry_price - current_price) / entry_price
        
        # Calculate net profit (after fees)
        net_profit_pct = gross_profit_pct - broker_fee_pct
        net_profit_usd = position_size_usd * net_profit_pct
        
        # Check hold time
        hold_time_seconds = (datetime.now() - entry_time).total_seconds()
        hold_time_met = hold_time_seconds >= self.MIN_HOLD_TIME_SECONDS
        
        # Check profit threshold
        profit_threshold_met = net_profit_pct >= self.MIN_NET_PROFIT_PCT
        
        # Check for profit giveback (if we've tracked this position before)
        with self.lock:
            previous_max_profit = 0.0
            if symbol in self.confirmed_profits:
                previous_max_profit = self.confirmed_profits[symbol].get('max_net_profit_pct', 0.0)
        
        # Is profit giving back?
        is_giveback = net_profit_pct < (previous_max_profit - self.PROFIT_GIVEBACK_THRESHOLD)
        
        # Update max profit if this is a new high
        if net_profit_pct > previous_max_profit:
            with self.lock:
                if symbol not in self.confirmed_profits:
                    self.confirmed_profits[symbol] = {}
                self.confirmed_profits[symbol]['max_net_profit_pct'] = net_profit_pct
                self.confirmed_profits[symbol]['max_profit_time'] = datetime.now().isoformat()
                self._save_confirmations()
        
        # Determine if profit is proven
        profit_proven = (
            profit_threshold_met and 
            hold_time_met and 
            not is_giveback
        )
        
        # Determine recommended action
        if is_giveback and previous_max_profit > self.MIN_NET_PROFIT_PCT:
            action = "IMMEDIATE_EXIT_GIVEBACK"
        elif profit_proven:
            action = "PROFIT_CONFIRMED_TAKE_NOW"
        elif profit_threshold_met and not hold_time_met:
            action = "WAIT_FOR_HOLD_TIME"
        elif hold_time_met and not profit_threshold_met:
            action = "WAIT_FOR_PROFIT_THRESHOLD"
        else:
            action = "HOLD_POSITION"
        
        return {
            'proven': profit_proven,
            'gross_profit_pct': gross_profit_pct,
            'net_profit_pct': net_profit_pct,
            'net_profit_usd': net_profit_usd,
            'hold_time_seconds': hold_time_seconds,
            'previous_max_profit_pct': previous_max_profit,
            'is_giveback': is_giveback,
            'criteria_met': {
                'profit_threshold': profit_threshold_met,
                'hold_time': hold_time_met,
                'no_giveback': not is_giveback
            },
            'action': action
        }
    
    def log_profit_confirmation(
        self,
        symbol: str,
        entry_price: float,
        exit_price: float,
        position_size_usd: float,
        net_profit_pct: float,
        net_profit_usd: float,
        hold_time_seconds: float,
        exit_type: str = "PROFIT_CONFIRMED",
        fees_paid_usd: float = 0.0,
        risk_amount_usd: float = 0.0
    ):
        """
        Log a profit confirmation event with standardized format.
        
        Args:
            symbol: Trading symbol
            entry_price: Position entry price
            exit_price: Position exit price
            position_size_usd: Position size in USD
            net_profit_pct: NET profit percentage (after fees)
            net_profit_usd: NET profit in USD (after fees)
            hold_time_seconds: How long position was held
            exit_type: Type of exit (PROFIT_CONFIRMED, PROFIT_GIVEBACK, etc.)
            fees_paid_usd: Total fees paid on this trade
            risk_amount_usd: Initial risk amount (for R calculation)
        """
        timestamp = datetime.now()
        
        with self.lock:
            # Update statistics
            if exit_type == "PROFIT_CONFIRMED":
                self.total_confirmations += 1
                self.total_profit_taken_usd += net_profit_usd
            elif exit_type == "PROFIT_GIVEBACK":
                self.total_givebacks += 1
                if net_profit_usd < 0:
                    self.total_profit_given_back_usd += abs(net_profit_usd)
            
            # Add to trade history
            trade_record = {
                'timestamp': timestamp.isoformat(),
                'symbol': symbol,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'position_size_usd': position_size_usd,
                'net_profit_pct': net_profit_pct,
                'net_profit_usd': net_profit_usd,
                'fees_paid_usd': fees_paid_usd,
                'risk_amount_usd': risk_amount_usd,
                'hold_time_seconds': hold_time_seconds,
                'exit_type': exit_type,
                'is_winner': net_profit_usd > 0
            }
            
            # Calculate R (reward/risk ratio) if risk is known
            if risk_amount_usd > 0:
                trade_record['r_multiple'] = net_profit_usd / risk_amount_usd
            
            self.trade_history.append(trade_record)
            
            # Keep only last 72 hours of history
            cutoff_time = timestamp - timedelta(hours=72)
            self.trade_history = [
                t for t in self.trade_history 
                if datetime.fromisoformat(t['timestamp']) >= cutoff_time
            ]
            
            # Save updated statistics
            self._save_confirmations()
        
        # Standardized log format
        logger.info("=" * 80)
        logger.info(f"💰 PROFIT CONFIRMATION LOG - {exit_type}")
        logger.info("=" * 80)
        logger.info(f"Symbol: {symbol}")
        logger.info(f"Entry Price: ${entry_price:.4f}")
        logger.info(f"Exit Price: ${exit_price:.4f}")
        logger.info(f"Position Size: ${position_size_usd:.2f}")
        logger.info(f"NET Profit: {net_profit_pct*100:+.2f}% (${net_profit_usd:+.2f})")
        logger.info(f"Hold Time: {hold_time_seconds:.0f}s ({hold_time_seconds/60:.1f} minutes)")
        logger.info(f"Timestamp: {datetime.now().isoformat()}")
        logger.info("=" * 80)
        
        # Clean up tracking for this position
        with self.lock:
            if symbol in self.confirmed_profits:
                del self.confirmed_profits[symbol]
                self._save_confirmations()
    
    def get_confirmation_summary(self) -> Dict:
        """
        Get summary of profit confirmations vs givebacks.
        
        Returns:
            Dict with confirmation statistics
        """
        with self.lock:
            total_events = self.total_confirmations + self.total_givebacks
            confirmation_rate = (
                self.total_confirmations / total_events * 100
                if total_events > 0 else 0
            )
            
            net_profit = self.total_profit_taken_usd - self.total_profit_given_back_usd
            
            return {
                'total_confirmations': self.total_confirmations,
                'total_givebacks': self.total_givebacks,
                'confirmation_rate': confirmation_rate,
                'total_profit_taken_usd': self.total_profit_taken_usd,
                'total_profit_given_back_usd': self.total_profit_given_back_usd,
                'net_profit_usd': net_profit,
                'active_tracking_count': len(self.confirmed_profits)
            }
    
    def log_daily_summary(self):
        """Log daily profit confirmation summary"""
        summary = self.get_confirmation_summary()
        
        logger.info("=" * 80)
        logger.info("📊 DAILY PROFIT CONFIRMATION SUMMARY")
        logger.info("=" * 80)
        logger.info(f"Total Profit Confirmations: {summary['total_confirmations']}")
        logger.info(f"Total Profit Givebacks: {summary['total_givebacks']}")
        logger.info(f"Confirmation Rate: {summary['confirmation_rate']:.1f}%")
        logger.info(f"Total Profit Taken: ${summary['total_profit_taken_usd']:.2f}")
        logger.info(f"Total Profit Given Back: ${summary['total_profit_given_back_usd']:.2f}")
        logger.info(f"NET Profit: ${summary['net_profit_usd']:+.2f}")
        logger.info(f"Active Position Tracking: {summary['active_tracking_count']}")
        logger.info("=" * 80)
    
    def cleanup_stale_tracking(self, active_positions: List[str]) -> int:
        """
        Clean up tracking for positions that no longer exist.
        Prevents position count explosion from orphaned tracking entries.
        
        Args:
            active_positions: List of currently active position symbols
        
        Returns:
            Number of stale tracking entries removed
        """
        with self.lock:
            active_set = set(active_positions)
            tracked_set = set(self.confirmed_profits.keys())
            
            # Find stale entries (tracked but not active)
            stale_entries = tracked_set - active_set
            
            if stale_entries:
                logger.warning(f"🧹 Cleaning up {len(stale_entries)} stale profit tracking entries")
                for symbol in stale_entries:
                    logger.info(f"   Removing stale tracking: {symbol}")
                    del self.confirmed_profits[symbol]
                
                self._save_confirmations()
                return len(stale_entries)
            
            return 0
    
    def clear_all(self) -> bool:
        """Clear all profit confirmations (emergency use only)"""
        try:
            with self.lock:
                count = len(self.confirmed_profits)
                self.confirmed_profits = {}
                self._save_confirmations()
                logger.warning(f"Cleared all {count} profit confirmations")
                return True
        except Exception as e:
            logger.error(f"Error clearing profit confirmations: {e}")
            return False
    
    def generate_simple_report(
        self,
        starting_equity: float,
        ending_equity: float,
        hours: int = 24
    ) -> str:
        """
        Generate a simple profit report for the last N hours.
        
        Args:
            starting_equity: Starting equity at beginning of time window
            ending_equity: Current ending equity
            hours: Time window in hours (default 24, max 72)
        
        Returns:
            Formatted report string
        """
        hours = min(hours, 72)  # Cap at 72 hours
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        # Filter trades to time window
        with self.lock:
            recent_trades = [
                t for t in self.trade_history
                if datetime.fromisoformat(t['timestamp']) >= cutoff_time
            ]
        
        # Calculate statistics
        trade_count = len(recent_trades)
        
        if trade_count == 0:
            return self._format_empty_report(starting_equity, ending_equity, hours)
        
        # Win rate
        winners = [t for t in recent_trades if t['is_winner']]
        win_rate = (len(winners) / trade_count) * 100 if trade_count > 0 else 0
        
        # Average R (reward/risk ratio)
        r_multiples = [t.get('r_multiple', 0) for t in recent_trades if 'r_multiple' in t]
        avg_r = sum(r_multiples) / len(r_multiples) if r_multiples else 0
        
        # Total fees
        total_fees = sum(t.get('fees_paid_usd', 0) for t in recent_trades)
        
        # Net P&L
        net_pnl = ending_equity - starting_equity
        
        # Format report
        report_lines = [
            "=" * 60,
            f"PROFIT REPORT - Last {hours}h",
            "=" * 60,
            "",
            f"Starting equity: ${starting_equity:,.2f}",
            f"Ending equity:   ${ending_equity:,.2f}",
            f"Net P&L:         ${net_pnl:+,.2f} ({(net_pnl/starting_equity*100) if starting_equity > 0 else 0:+.2f}%)",
            "",
            "Closed trades:",
            f"  Count:      {trade_count}",
            f"  Avg R:      {avg_r:.2f}R" if r_multiples else "  Avg R:      N/A (risk not tracked)",
            f"  Win rate:   {win_rate:.1f}%",
            f"  Fees total: ${total_fees:.2f}",
            "",
            "=" * 60
        ]
        
        return "\n".join(report_lines)
    
    def _format_empty_report(
        self,
        starting_equity: float,
        ending_equity: float,
        hours: int
    ) -> str:
        """Format report when no trades in time window"""
        net_pnl = ending_equity - starting_equity
        
        report_lines = [
            "=" * 60,
            f"PROFIT REPORT - Last {hours}h",
            "=" * 60,
            "",
            f"Starting equity: ${starting_equity:,.2f}",
            f"Ending equity:   ${ending_equity:,.2f}",
            f"Net P&L:         ${net_pnl:+,.2f}",
            "",
            "Closed trades:",
            "  Count:      0",
            "  Avg R:      N/A",
            "  Win rate:   N/A",
            "  Fees total: $0.00",
            "",
            "=" * 60
        ]
        
        return "\n".join(report_lines)
    
    def print_simple_report(
        self,
        starting_equity: float,
        ending_equity: float,
        hours: int = 24
    ):
        """
        Generate and print a simple profit report.
        
        Args:
            starting_equity: Starting equity at beginning of time window
            ending_equity: Current ending equity
            hours: Time window in hours (default 24, max 72)
        """
        report = self.generate_simple_report(starting_equity, ending_equity, hours)
        logger.info("\n" + report)
