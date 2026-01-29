"""
NIJA Smart Daily Profit Locking System
=======================================

Protects profits by implementing progressive locking mechanisms:

1. **Daily Profit Targets** - Set and track daily profit goals
2. **Progressive Profit Locking** - Lock portions of profit at key milestones
3. **Trailing Profit Protection** - Protect gains as they grow
4. **Auto-Reduce Risk Mode** - Reduce position sizes after hitting targets

Key Features:
- Lock 25% of profits at 50% of daily target
- Lock 50% of profits at 100% of daily target
- Lock 75% of profits at 150% of daily target
- Reduce risk exposure after hitting daily goal
- Prevent profit give-backs

Author: NIJA Trading Systems
Version: 2.0 - Elite Profit Engine
Date: January 29, 2026
"""

import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from enum import Enum
import json
from pathlib import Path

logger = logging.getLogger("nija.profit_locking")


class ProfitLockLevel(Enum):
    """Profit locking milestone levels"""
    NONE = "none"  # No locking yet
    LEVEL_1 = "level_1"  # 25% locked at 50% of target
    LEVEL_2 = "level_2"  # 50% locked at 100% of target
    LEVEL_3 = "level_3"  # 75% locked at 150% of target
    LEVEL_4 = "level_4"  # 90% locked at 200% of target


class TradingMode(Enum):
    """Trading mode based on profit status"""
    NORMAL = "normal"  # Regular trading
    CONSERVATIVE = "conservative"  # After hitting target, reduce risk
    PROTECTIVE = "protective"  # Large profit locked, minimal new positions
    STOPPED = "stopped"  # Stop trading for the day


@dataclass
class DailyProfitState:
    """Daily profit tracking state"""
    date: str
    starting_balance: float
    current_balance: float
    daily_profit: float
    daily_target: float
    locked_profit: float
    lock_level: str
    trading_mode: str
    trades_today: int
    winning_trades: int
    
    @property
    def target_progress_pct(self) -> float:
        """Calculate progress toward daily target as percentage"""
        if self.daily_target == 0:
            return 0.0
        return (self.daily_profit / self.daily_target) * 100
    
    @property
    def win_rate_today(self) -> float:
        """Calculate today's win rate"""
        if self.trades_today == 0:
            return 0.0
        return (self.winning_trades / self.trades_today) * 100


class SmartDailyProfitLocker:
    """
    Manages daily profit locking and protection mechanisms
    """
    
    # Data persistence
    DATA_DIR = Path(__file__).parent.parent / "data"
    STATE_FILE = DATA_DIR / "daily_profit_state.json"
    HISTORY_FILE = DATA_DIR / "daily_profit_history.json"
    
    def __init__(self, base_capital: float, config: Dict = None):
        """
        Initialize Smart Daily Profit Locker
        
        Args:
            base_capital: Base account capital
            config: Optional configuration dictionary
        """
        self.base_capital = base_capital
        self.config = config or {}
        
        # Daily profit target (default 2% of base capital per day)
        self.daily_target_pct = self.config.get('daily_target_pct', 0.02)  # 2%
        self.daily_target = base_capital * self.daily_target_pct
        
        # Profit locking thresholds (as % of daily target)
        self.lock_thresholds = {
            ProfitLockLevel.LEVEL_1: 0.50,  # Lock 25% profit at 50% of target
            ProfitLockLevel.LEVEL_2: 1.00,  # Lock 50% profit at 100% of target
            ProfitLockLevel.LEVEL_3: 1.50,  # Lock 75% profit at 150% of target
            ProfitLockLevel.LEVEL_4: 2.00,  # Lock 90% profit at 200% of target
        }
        
        # Profit lock percentages at each level
        self.lock_percentages = {
            ProfitLockLevel.LEVEL_1: 0.25,  # Lock 25% of profit
            ProfitLockLevel.LEVEL_2: 0.50,  # Lock 50% of profit
            ProfitLockLevel.LEVEL_3: 0.75,  # Lock 75% of profit
            ProfitLockLevel.LEVEL_4: 0.90,  # Lock 90% of profit
        }
        
        # Trading mode transitions
        self.stop_trading_at_target_pct = self.config.get('stop_trading_at_target_pct', None)  # None = never stop
        
        # Daily state tracking
        self.today_date = str(date.today())
        self.starting_balance = base_capital
        self.current_balance = base_capital
        self.daily_profit = 0.0
        self.locked_profit = 0.0
        self.current_lock_level = ProfitLockLevel.NONE
        self.trading_mode = TradingMode.NORMAL
        self.trades_today = 0
        self.winning_trades = 0
        
        # History tracking
        self.daily_history: List[Dict] = []
        
        # Ensure data directory exists
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        
        # Load existing state or initialize
        self._load_state()
        
        logger.info("=" * 70)
        logger.info("🔒 Smart Daily Profit Locking System Initialized")
        logger.info("=" * 70)
        logger.info(f"Base Capital: ${self.base_capital:,.2f}")
        logger.info(f"Daily Target: ${self.daily_target:,.2f} ({self.daily_target_pct*100:.1f}%)")
        logger.info(f"Today's Date: {self.today_date}")
        logger.info(f"Starting Balance: ${self.starting_balance:,.2f}")
        logger.info("=" * 70)
    
    def _load_state(self):
        """Load daily state from persistent storage"""
        if not self.STATE_FILE.exists():
            return
        
        try:
            with open(self.STATE_FILE, 'r') as f:
                data = json.load(f)
            
            saved_date = data.get('date', '')
            
            # If it's a new day, reset state
            if saved_date != self.today_date:
                logger.info(f"📅 New day detected. Resetting daily state.")
                self._reset_daily_state()
                return
            
            # Load saved state
            self.starting_balance = data.get('starting_balance', self.base_capital)
            self.current_balance = data.get('current_balance', self.base_capital)
            self.daily_profit = data.get('daily_profit', 0.0)
            self.locked_profit = data.get('locked_profit', 0.0)
            self.current_lock_level = ProfitLockLevel(data.get('lock_level', 'none'))
            self.trading_mode = TradingMode(data.get('trading_mode', 'normal'))
            self.trades_today = data.get('trades_today', 0)
            self.winning_trades = data.get('winning_trades', 0)
            
            logger.info(f"✅ Loaded daily state for {self.today_date}")
            
        except Exception as e:
            logger.warning(f"Failed to load daily state: {e}")
            self._reset_daily_state()
    
    def _save_state(self):
        """Save current daily state"""
        try:
            data = {
                'date': self.today_date,
                'starting_balance': self.starting_balance,
                'current_balance': self.current_balance,
                'daily_profit': self.daily_profit,
                'daily_target': self.daily_target,
                'locked_profit': self.locked_profit,
                'lock_level': self.current_lock_level.value,
                'trading_mode': self.trading_mode.value,
                'trades_today': self.trades_today,
                'winning_trades': self.winning_trades,
                'last_updated': datetime.now().isoformat(),
            }
            
            with open(self.STATE_FILE, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.debug("💾 Daily profit state saved")
            
        except Exception as e:
            logger.error(f"Failed to save daily state: {e}")
    
    def _reset_daily_state(self):
        """Reset state for a new trading day"""
        # Save yesterday's results to history
        if self.daily_profit != 0 or self.trades_today > 0:
            self._save_to_history()
        
        # Reset for new day
        self.today_date = str(date.today())
        self.starting_balance = self.current_balance
        self.daily_profit = 0.0
        self.locked_profit = 0.0
        self.current_lock_level = ProfitLockLevel.NONE
        self.trading_mode = TradingMode.NORMAL
        self.trades_today = 0
        self.winning_trades = 0
        
        logger.info(f"🔄 Daily state reset for {self.today_date}")
        self._save_state()
    
    def _save_to_history(self):
        """Save current day's results to history"""
        try:
            # Load existing history
            if self.HISTORY_FILE.exists():
                with open(self.HISTORY_FILE, 'r') as f:
                    history = json.load(f)
            else:
                history = []
            
            # Add today's results
            today_record = {
                'date': self.today_date,
                'starting_balance': self.starting_balance,
                'ending_balance': self.current_balance,
                'daily_profit': self.daily_profit,
                'daily_target': self.daily_target,
                'locked_profit': self.locked_profit,
                'trades': self.trades_today,
                'winning_trades': self.winning_trades,
                'win_rate': (self.winning_trades / self.trades_today * 100) if self.trades_today > 0 else 0,
                'target_achieved': self.daily_profit >= self.daily_target,
            }
            
            history.append(today_record)
            
            # Keep only last 90 days
            if len(history) > 90:
                history = history[-90:]
            
            # Save
            with open(self.HISTORY_FILE, 'w') as f:
                json.dump(history, f, indent=2)
            
            logger.info(f"📊 Saved daily results to history")
            
        except Exception as e:
            logger.error(f"Failed to save to history: {e}")
    
    def record_trade(self, profit: float, is_win: bool):
        """
        Record a trade result and update profit locking
        
        Args:
            profit: Net profit/loss from trade
            is_win: True if trade was profitable
        """
        # Check if new day
        current_date = str(date.today())
        if current_date != self.today_date:
            self._reset_daily_state()
        
        # Update trade counts
        self.trades_today += 1
        if is_win:
            self.winning_trades += 1
        
        # Update balances and profit
        self.current_balance += profit
        self.daily_profit = self.current_balance - self.starting_balance
        
        # Check and update profit locking
        self._update_profit_locking()
        
        # Update trading mode
        self._update_trading_mode()
        
        # Save state
        self._save_state()
        
        logger.info(f"📊 Trade Recorded:")
        logger.info(f"   P/L: ${profit:+.2f}, Daily Profit: ${self.daily_profit:+.2f}")
        logger.info(f"   Target Progress: {self.get_target_progress_pct():.1f}%")
        logger.info(f"   Locked Profit: ${self.locked_profit:.2f}")
        logger.info(f"   Trading Mode: {self.trading_mode.value.upper()}")
    
    def _update_profit_locking(self):
        """Update profit locking based on current progress"""
        if self.daily_profit <= 0:
            # No profit to lock
            return
        
        # Calculate progress ratio
        progress_ratio = self.daily_profit / self.daily_target if self.daily_target > 0 else 0
        
        # Determine appropriate lock level
        new_lock_level = ProfitLockLevel.NONE
        
        for level, threshold in sorted(self.lock_thresholds.items(), key=lambda x: x[1], reverse=True):
            if progress_ratio >= threshold:
                new_lock_level = level
                break
        
        # If lock level increased, update locked profit
        if new_lock_level != self.current_lock_level:
            old_level = self.current_lock_level
            self.current_lock_level = new_lock_level
            
            if new_lock_level != ProfitLockLevel.NONE:
                lock_pct = self.lock_percentages[new_lock_level]
                self.locked_profit = self.daily_profit * lock_pct
                
                logger.info("=" * 70)
                logger.info(f"🔒 PROFIT LOCK ACTIVATED: {new_lock_level.value.upper()}")
                logger.info("=" * 70)
                logger.info(f"Daily Profit: ${self.daily_profit:.2f}")
                logger.info(f"Locked: ${self.locked_profit:.2f} ({lock_pct*100:.0f}% of profit)")
                logger.info(f"At Risk: ${self.daily_profit - self.locked_profit:.2f}")
                logger.info("=" * 70)
    
    def _update_trading_mode(self):
        """Update trading mode based on profit progress"""
        progress_pct = self.get_target_progress_pct()
        
        # Determine trading mode
        if self.stop_trading_at_target_pct and progress_pct >= self.stop_trading_at_target_pct:
            new_mode = TradingMode.STOPPED
        elif progress_pct >= 150:
            new_mode = TradingMode.PROTECTIVE
        elif progress_pct >= 100:
            new_mode = TradingMode.CONSERVATIVE
        else:
            new_mode = TradingMode.NORMAL
        
        # Log mode change
        if new_mode != self.trading_mode:
            old_mode = self.trading_mode
            self.trading_mode = new_mode
            
            logger.info(f"🔄 Trading Mode Changed: {old_mode.value.upper()} → {new_mode.value.upper()}")
    
    def get_target_progress_pct(self) -> float:
        """Get progress toward daily target as percentage"""
        if self.daily_target == 0:
            return 0.0
        return (self.daily_profit / self.daily_target) * 100
    
    def should_take_new_trade(self) -> bool:
        """
        Determine if new trades should be taken
        
        Returns:
            True if allowed to trade, False otherwise
        """
        if self.trading_mode == TradingMode.STOPPED:
            logger.warning("⛔ Trading stopped for the day (target achieved)")
            return False
        
        return True
    
    def get_position_size_multiplier(self) -> float:
        """
        Get position size multiplier based on trading mode
        
        Returns:
            Multiplier (1.0 = normal, <1.0 = reduced risk)
        """
        multipliers = {
            TradingMode.NORMAL: 1.00,  # Normal position sizing
            TradingMode.CONSERVATIVE: 0.60,  # Reduce to 60%
            TradingMode.PROTECTIVE: 0.30,  # Reduce to 30%
            TradingMode.STOPPED: 0.00,  # No new positions
        }
        
        return multipliers.get(self.trading_mode, 1.0)
    
    def get_daily_state(self) -> DailyProfitState:
        """
        Get current daily profit state
        
        Returns:
            DailyProfitState object
        """
        return DailyProfitState(
            date=self.today_date,
            starting_balance=self.starting_balance,
            current_balance=self.current_balance,
            daily_profit=self.daily_profit,
            daily_target=self.daily_target,
            locked_profit=self.locked_profit,
            lock_level=self.current_lock_level.value,
            trading_mode=self.trading_mode.value,
            trades_today=self.trades_today,
            winning_trades=self.winning_trades,
        )
    
    def get_profit_locking_report(self) -> str:
        """Generate detailed profit locking report"""
        state = self.get_daily_state()
        
        report = [
            "\n" + "=" * 90,
            "SMART DAILY PROFIT LOCKING REPORT",
            "=" * 90,
            f"Date: {state.date}",
            f"Trading Mode: {state.trading_mode.upper()}",
            "",
            "💰 TODAY'S PERFORMANCE",
            "-" * 90,
            f"  Starting Balance:  ${state.starting_balance:>12,.2f}",
            f"  Current Balance:   ${state.current_balance:>12,.2f}",
            f"  Daily Profit:      ${state.daily_profit:>12,.2f}",
            f"  Daily Target:      ${state.daily_target:>12,.2f}",
            f"  Progress:          {state.target_progress_pct:>12.1f}%",
            "",
            "🔒 PROFIT PROTECTION",
            "-" * 90,
            f"  Lock Level:        {state.lock_level.upper():>12s}",
            f"  Locked Profit:     ${state.locked_profit:>12,.2f}",
            f"  At Risk:           ${state.daily_profit - state.locked_profit:>12,.2f}",
            "",
            "📊 TRADING ACTIVITY",
            "-" * 90,
            f"  Trades Today:      {state.trades_today:>12,}",
            f"  Winning Trades:    {state.winning_trades:>12,}",
            f"  Win Rate:          {state.win_rate_today:>12.1f}%",
            "",
            "⚙️  RISK MANAGEMENT",
            "-" * 90,
            f"  Position Size Multiplier: {self.get_position_size_multiplier():>5.0%}",
            f"  Allow New Trades:         {'YES' if self.should_take_new_trade() else 'NO':>5s}",
            "=" * 90,
        ]
        
        return "\n".join(report)
    
    def update_balance(self, new_balance: float):
        """
        Update current balance (for manual corrections)
        
        Args:
            new_balance: New balance value
        """
        old_balance = self.current_balance
        self.current_balance = new_balance
        self.daily_profit = new_balance - self.starting_balance
        
        self._update_profit_locking()
        self._update_trading_mode()
        self._save_state()
        
        logger.info(f"💰 Balance Updated: ${old_balance:.2f} → ${new_balance:.2f}")


def get_smart_daily_profit_locker(base_capital: float, config: Dict = None) -> SmartDailyProfitLocker:
    """
    Factory function to create SmartDailyProfitLocker
    
    Args:
        base_capital: Base account capital
        config: Optional configuration
        
    Returns:
        SmartDailyProfitLocker instance
    """
    return SmartDailyProfitLocker(base_capital, config)


# Example usage
if __name__ == "__main__":
    import logging
    
    logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
    
    # Create profit locker
    config = {
        'daily_target_pct': 0.02,  # 2% daily target
    }
    locker = get_smart_daily_profit_locker(base_capital=10000.0, config=config)
    
    # Simulate some trades
    print("\n📈 Simulating trading day...\n")
    
    locker.record_trade(profit=50.0, is_win=True)  # Small win
    locker.record_trade(profit=75.0, is_win=True)  # Good win (now at $125 = 62.5% of target)
    locker.record_trade(profit=30.0, is_win=True)  # Another win (now at $155 = 77.5% of target)
    locker.record_trade(profit=50.0, is_win=True)  # Hit target! (now at $205 = 102.5% of target)
    
    # Print report
    print(locker.get_profit_locking_report())
    
    # Check if we should continue trading
    print(f"\n✅ Should take new trade: {locker.should_take_new_trade()}")
    print(f"   Position size multiplier: {locker.get_position_size_multiplier():.0%}")
