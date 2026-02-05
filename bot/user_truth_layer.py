"""
USER TRUTH LAYER
================
Requirement C: User-facing truth layer

Provides brutally honest, simple daily P&L reporting:
- "Today you made +$0.42"
- "Today you lost -$0.18"

No vibes. No averages. No success rates without money.
Just the truth about money made or lost.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass
import json

logger = logging.getLogger(__name__)


@dataclass
class DailyTruth:
    """Simple daily P&L truth"""
    date: str
    net_pnl: float
    status: str  # "PROFIT" or "LOSS"
    message: str  # Human-readable truth


class UserTruthLayer:
    """
    Provides honest, user-facing P&L reporting
    
    Philosophy: Users deserve to know exactly how much money they made or lost.
    No hiding behind percentages, win rates, or other metrics.
    Just dollars and cents.
    """
    
    def __init__(self, storage_path: str = "/tmp/user_truth_layer.json"):
        """
        Args:
            storage_path: Where to persist daily truth records
        """
        self.storage_path = storage_path
        self.daily_records: Dict[str, DailyTruth] = {}
        self._load_records()
        
        logger.info("💰 UserTruthLayer initialized - No BS, just money")
    
    def _load_records(self):
        """Load historical records"""
        try:
            with open(self.storage_path, 'r') as f:
                data = json.load(f)
                for date_str, record in data.items():
                    self.daily_records[date_str] = DailyTruth(**record)
            logger.info(f"   Loaded {len(self.daily_records)} historical truth records")
        except FileNotFoundError:
            logger.info("   No historical records found (starting fresh)")
        except Exception as e:
            logger.warning(f"   Error loading records: {e}")
    
    def _save_records(self):
        """Persist records to disk"""
        try:
            data = {
                date: {
                    'date': truth.date,
                    'net_pnl': truth.net_pnl,
                    'status': truth.status,
                    'message': truth.message
                }
                for date, truth in self.daily_records.items()
            }
            with open(self.storage_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving truth records: {e}")
    
    def record_trade_pnl(self, pnl_dollars: float, timestamp: Optional[datetime] = None):
        """
        Record P&L from a trade
        
        Args:
            pnl_dollars: Net P&L in dollars (after fees)
            timestamp: When the trade closed (default: now)
        """
        if timestamp is None:
            timestamp = datetime.now()
        
        date_str = timestamp.strftime('%Y-%m-%d')
        
        if date_str not in self.daily_records:
            # Create new daily record
            self.daily_records[date_str] = DailyTruth(
                date=date_str,
                net_pnl=pnl_dollars,
                status="PROFIT" if pnl_dollars > 0 else "LOSS",
                message=self._create_truth_message(pnl_dollars)
            )
        else:
            # Update existing record
            record = self.daily_records[date_str]
            record.net_pnl += pnl_dollars
            record.status = "PROFIT" if record.net_pnl > 0 else "LOSS"
            record.message = self._create_truth_message(record.net_pnl)
        
        self._save_records()
        logger.info(f"📝 Truth recorded: {date_str} → {self.daily_records[date_str].message}")
    
    def _create_truth_message(self, net_pnl: float) -> str:
        """
        Create a simple, honest message about money
        
        No euphemisms. No spin. Just the truth.
        """
        if net_pnl > 0:
            return f"Today you made +${net_pnl:.2f}"
        elif net_pnl < 0:
            return f"Today you lost -${abs(net_pnl):.2f}"
        else:
            # Even $0.00 is a loss (because of time/opportunity cost)
            return "Today you made $0.00 (breakeven is a loss)"
    
    def get_today_truth(self) -> str:
        """
        Get today's P&L truth in simple English
        
        Returns:
            Simple statement like "Today you made +$0.42" or "Today you lost -$0.18"
        """
        today = datetime.now().strftime('%Y-%m-%d')
        
        if today in self.daily_records:
            return self.daily_records[today].message
        else:
            return "No trades today yet"
    
    def get_yesterday_truth(self) -> str:
        """Get yesterday's truth"""
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        
        if yesterday in self.daily_records:
            return self.daily_records[yesterday].message
        else:
            return "No trades yesterday"
    
    def get_truth_summary(self, days: int = 7) -> Dict:
        """
        Get truth summary for the last N days
        
        Returns honest statistics:
        - Total P&L
        - Profitable days count
        - Losing days count
        - Average daily P&L
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        relevant_records = [
            record for date_str, record in self.daily_records.items()
            if start_date <= datetime.strptime(date_str, '%Y-%m-%d') <= end_date
        ]
        
        if not relevant_records:
            return {
                'period_days': days,
                'total_pnl': 0.0,
                'profitable_days': 0,
                'losing_days': 0,
                'average_daily': 0.0,
                'truth': f"No trading activity in last {days} days"
            }
        
        total_pnl = sum(r.net_pnl for r in relevant_records)
        profitable_days = sum(1 for r in relevant_records if r.net_pnl > 0)
        losing_days = sum(1 for r in relevant_records if r.net_pnl < 0)
        avg_daily = total_pnl / len(relevant_records)
        
        # Create honest summary message
        if total_pnl > 0:
            truth = f"Last {days} days: Made ${total_pnl:.2f} ({profitable_days} profit days, {losing_days} loss days)"
        elif total_pnl < 0:
            truth = f"Last {days} days: Lost ${abs(total_pnl):.2f} ({profitable_days} profit days, {losing_days} loss days)"
        else:
            truth = f"Last {days} days: Broke even at $0.00 ({profitable_days} profit days, {losing_days} loss days)"
        
        return {
            'period_days': days,
            'trading_days': len(relevant_records),
            'total_pnl': total_pnl,
            'profitable_days': profitable_days,
            'losing_days': losing_days,
            'average_daily': avg_daily,
            'truth': truth,
            'status': 'PROFITABLE' if total_pnl > 0 else 'LOSING'
        }
    
    def get_current_balance_change(self, 
                                   starting_balance: float,
                                   current_balance: float) -> Dict:
        """
        Compare current balance to starting balance
        
        This is the ultimate truth - did the account grow or shrink?
        
        Args:
            starting_balance: Balance at start of period (e.g., 24h ago)
            current_balance: Current balance
        
        Returns:
            Dict with honest comparison
        """
        net_change = current_balance - starting_balance
        change_pct = (net_change / starting_balance * 100) if starting_balance > 0 else 0
        
        if net_change > 0:
            truth = f"Balance grew by ${net_change:.2f} (+{change_pct:.2f}%)"
            status = "PROFITABLE"
        elif net_change < 0:
            truth = f"Balance shrank by ${abs(net_change):.2f} ({change_pct:.2f}%)"
            status = "LOSING"
        else:
            truth = "Balance unchanged (no real growth)"
            status = "FLAT"
        
        return {
            'starting_balance': starting_balance,
            'current_balance': current_balance,
            'net_change': net_change,
            'change_pct': change_pct,
            'truth': truth,
            'status': status
        }
    
    def print_daily_report(self):
        """Print a simple daily truth report"""
        print("\n" + "="*60)
        print("💰 USER TRUTH LAYER - Daily Report")
        print("="*60)
        print(f"Today:     {self.get_today_truth()}")
        print(f"Yesterday: {self.get_yesterday_truth()}")
        print()
        
        # 7-day summary
        summary = self.get_truth_summary(7)
        print(f"Last 7 Days: {summary['truth']}")
        print(f"  Trading Days: {summary['trading_days']}")
        print(f"  Avg Daily: ${summary['average_daily']:.2f}")
        print(f"  Status: {summary['status']}")
        print("="*60)
    
    def get_user_facing_message(self, timeframe: str = 'today') -> str:
        """
        Get a user-facing message for display in UI
        
        Args:
            timeframe: 'today', 'yesterday', or 'week'
        
        Returns:
            Simple, honest message suitable for showing to users
        """
        if timeframe == 'today':
            return self.get_today_truth()
        elif timeframe == 'yesterday':
            return self.get_yesterday_truth()
        elif timeframe == 'week':
            summary = self.get_truth_summary(7)
            return summary['truth']
        else:
            return "Invalid timeframe"


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Initialize truth layer
    truth = UserTruthLayer()
    
    # Record some trades
    print("\n📝 Recording sample trades...")
    truth.record_trade_pnl(0.42, datetime.now())  # Made $0.42 today
    truth.record_trade_pnl(-0.18, datetime.now())  # Lost $0.18 today
    truth.record_trade_pnl(1.50, datetime.now() - timedelta(days=1))  # Made $1.50 yesterday
    truth.record_trade_pnl(-0.75, datetime.now() - timedelta(days=2))  # Lost $0.75 2 days ago
    
    # Print report
    truth.print_daily_report()
    
    # Test balance comparison
    print("\n📊 Balance Comparison:")
    comparison = truth.get_current_balance_change(
        starting_balance=61.20,
        current_balance=63.38
    )
    print(f"   {comparison['truth']}")
    print(f"   Status: {comparison['status']}")
