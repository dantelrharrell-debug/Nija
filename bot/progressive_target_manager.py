"""
NIJA Progressive Profit Target Manager
Automatically increases daily profit targets as goals are achieved

Features:
- Starts at $25/day target
- Automatically increases in $25 increments upon achievement
- Continues until reaching $1000/day goal
- Adjusts position sizing based on current target
- Tracks daily performance and progress
- Persistent storage of target history

Version: 1.0
Author: NIJA Trading Systems
"""

import json
import logging
from datetime import datetime, date
from pathlib import Path
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, asdict

logger = logging.getLogger("nija.progressive_targets")


@dataclass
class DailyTarget:
    """Daily profit target with tracking"""
    target_amount: float  # Daily profit target in USD
    start_date: str  # Date target became active (YYYY-MM-DD)
    achieved_date: Optional[str] = None  # Date target was achieved
    best_daily_profit: float = 0.0  # Best single day profit at this level
    total_days_at_level: int = 0  # Total days spent at this target level
    achievement_count: int = 0  # Number of times target was achieved


class ProgressiveTargetManager:
    """
    Manages progressive daily profit targets with automatic advancement
    
    Target Progression:
    - Level 1: $25/day
    - Level 2: $50/day
    - Level 3: $75/day
    - ... continues in $25 increments
    - Final Goal: $1000/day
    """
    
    # Configuration
    STARTING_TARGET = 25.0  # $25/day starting target
    TARGET_INCREMENT = 25.0  # $25 increment per level
    FINAL_GOAL = 1000.0  # $1000/day final goal
    MIN_DAYS_AT_LEVEL = 1  # Minimum days to prove consistency before advancement
    
    # File paths for persistent storage
    DATA_DIR = Path(__file__).parent.parent / "data"
    TARGET_FILE = DATA_DIR / "progressive_targets.json"
    HISTORY_FILE = DATA_DIR / "daily_profit_history.json"
    
    def __init__(self):
        """Initialize Progressive Target Manager"""
        self.current_target: DailyTarget
        self.target_history: list[DailyTarget] = []
        self.daily_profit_records: Dict[str, float] = {}
        
        # Ensure data directory exists
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        
        # Load existing state or initialize new
        self._load_state()
        
        logger.info("=" * 70)
        logger.info("🎯 Progressive Target Manager Initialized")
        logger.info("=" * 70)
        logger.info(f"Current Target: ${self.current_target.target_amount:.2f}/day")
        logger.info(f"Days at Level: {self.current_target.total_days_at_level}")
        logger.info(f"Achievement Count: {self.current_target.achievement_count}")
        logger.info(f"Progress to Goal: {self.get_progress_percentage():.1f}%")
        logger.info("=" * 70)
    
    def _load_state(self):
        """Load state from persistent storage"""
        if self.TARGET_FILE.exists():
            try:
                with open(self.TARGET_FILE, 'r') as f:
                    data = json.load(f)
                    self.current_target = DailyTarget(**data['current_target'])
                    self.target_history = [DailyTarget(**t) for t in data.get('history', [])]
                logger.info(f"✅ Loaded existing target state from {self.TARGET_FILE}")
            except Exception as e:
                logger.warning(f"Failed to load target state: {e}")
                self._initialize_new_state()
        else:
            self._initialize_new_state()
        
        # Load daily profit history
        if self.HISTORY_FILE.exists():
            try:
                with open(self.HISTORY_FILE, 'r') as f:
                    self.daily_profit_records = json.load(f)
                logger.info(f"✅ Loaded {len(self.daily_profit_records)} days of profit history")
            except Exception as e:
                logger.warning(f"Failed to load profit history: {e}")
                self.daily_profit_records = {}
    
    def _initialize_new_state(self):
        """Initialize with starting target"""
        self.current_target = DailyTarget(
            target_amount=self.STARTING_TARGET,
            start_date=str(date.today())
        )
        self.target_history = []
        logger.info(f"🆕 Initialized new target progression at ${self.STARTING_TARGET}/day")
    
    def _save_state(self):
        """Save current state to persistent storage"""
        try:
            # Save targets
            state = {
                'current_target': asdict(self.current_target),
                'history': [asdict(t) for t in self.target_history],
                'last_updated': datetime.now().isoformat()
            }
            with open(self.TARGET_FILE, 'w') as f:
                json.dump(state, f, indent=2)
            
            # Save daily profit history
            with open(self.HISTORY_FILE, 'w') as f:
                json.dump(self.daily_profit_records, f, indent=2)
            
            logger.debug("💾 Target state saved")
        except Exception as e:
            logger.error(f"Failed to save target state: {e}")
    
    def record_daily_profit(self, profit_amount: float, trading_date: Optional[date] = None) -> bool:
        """
        Record daily profit and check for target achievement
        
        Args:
            profit_amount: Total profit for the day in USD
            trading_date: Date of trading (defaults to today)
            
        Returns:
            True if target was achieved, False otherwise
        """
        if trading_date is None:
            trading_date = date.today()
        
        date_str = str(trading_date)
        
        # Record the profit
        self.daily_profit_records[date_str] = profit_amount
        
        # Update current target stats
        self.current_target.total_days_at_level += 1
        if profit_amount > self.current_target.best_daily_profit:
            self.current_target.best_daily_profit = profit_amount
        
        # Check if target was achieved
        target_achieved = profit_amount >= self.current_target.target_amount
        
        if target_achieved:
            self.current_target.achievement_count += 1
            logger.info("=" * 70)
            logger.info("🎉 DAILY TARGET ACHIEVED!")
            logger.info("=" * 70)
            logger.info(f"Target: ${self.current_target.target_amount:.2f}")
            logger.info(f"Actual Profit: ${profit_amount:.2f}")
            logger.info(f"Times Achieved at This Level: {self.current_target.achievement_count}")
            logger.info("=" * 70)
            
            # Check if we should advance to next level
            if self._should_advance_target():
                self._advance_to_next_target(date_str)
        else:
            shortfall = self.current_target.target_amount - profit_amount
            logger.info(f"Daily profit: ${profit_amount:.2f} (${shortfall:.2f} below target)")
        
        self._save_state()
        return target_achieved
    
    def _should_advance_target(self) -> bool:
        """
        Determine if we should advance to the next target level
        
        Criteria:
        - Must have achieved current target
        - Must have spent minimum days at current level
        - Must not already be at final goal
        
        Returns:
            True if should advance to next level
        """
        if self.current_target.target_amount >= self.FINAL_GOAL:
            return False
        
        if self.current_target.total_days_at_level < self.MIN_DAYS_AT_LEVEL:
            return False
        
        if self.current_target.achievement_count < 1:
            return False
        
        return True
    
    def _advance_to_next_target(self, achievement_date: str):
        """
        Advance to the next target level
        
        Args:
            achievement_date: Date current target was achieved
        """
        # Mark current target as achieved
        self.current_target.achieved_date = achievement_date
        
        # Save to history
        self.target_history.append(self.current_target)
        
        # Calculate next target
        next_target_amount = min(
            self.current_target.target_amount + self.TARGET_INCREMENT,
            self.FINAL_GOAL
        )
        
        logger.info("=" * 70)
        logger.info("🚀 ADVANCING TO NEXT TARGET LEVEL!")
        logger.info("=" * 70)
        logger.info(f"Previous Target: ${self.current_target.target_amount:.2f}/day")
        logger.info(f"Days at Level: {self.current_target.total_days_at_level}")
        logger.info(f"Best Daily Profit: ${self.current_target.best_daily_profit:.2f}")
        logger.info("")
        logger.info(f"New Target: ${next_target_amount:.2f}/day")
        logger.info(f"Progress to Goal: {(next_target_amount / self.FINAL_GOAL) * 100:.1f}%")
        logger.info("=" * 70)
        
        # Create new target
        self.current_target = DailyTarget(
            target_amount=next_target_amount,
            start_date=achievement_date
        )
        
        self._save_state()
    
    def get_current_target(self) -> float:
        """
        Get current daily profit target
        
        Returns:
            Current target amount in USD
        """
        return self.current_target.target_amount
    
    def get_progress_percentage(self) -> float:
        """
        Get progress towards final goal as percentage
        
        Returns:
            Progress percentage (0-100)
        """
        return (self.current_target.target_amount / self.FINAL_GOAL) * 100.0
    
    def get_position_size_multiplier(self) -> float:
        """
        Get position size multiplier based on current target level
        
        Higher targets suggest larger account, can use slightly larger positions
        while still maintaining safety
        
        Returns:
            Multiplier for base position size (1.0 to 1.5)
        """
        # Start at 1.0x for $25 target, scale up to 1.5x at $1000 target
        progress = self.get_progress_percentage() / 100.0
        multiplier = 1.0 + (progress * 0.5)  # Range: 1.0 to 1.5
        
        return multiplier
    
    def get_target_statistics(self) -> Dict:
        """
        Get comprehensive statistics about target progression
        
        Returns:
            Dictionary with detailed statistics
        """
        total_levels_completed = len(self.target_history)
        total_levels_to_goal = int((self.FINAL_GOAL - self.STARTING_TARGET) / self.TARGET_INCREMENT) + 1
        
        # Calculate average profit from recent days
        recent_days = 7
        recent_profits = []
        today = date.today()
        for i in range(recent_days):
            check_date = str(today - __import__('datetime').timedelta(days=i))
            if check_date in self.daily_profit_records:
                recent_profits.append(self.daily_profit_records[check_date])
        
        avg_recent_profit = sum(recent_profits) / len(recent_profits) if recent_profits else 0.0
        
        return {
            'current_target': self.current_target.target_amount,
            'final_goal': self.FINAL_GOAL,
            'progress_percentage': self.get_progress_percentage(),
            'levels_completed': total_levels_completed,
            'total_levels': total_levels_to_goal,
            'days_at_current_level': self.current_target.total_days_at_level,
            'achievement_count': self.current_target.achievement_count,
            'best_daily_profit': self.current_target.best_daily_profit,
            'avg_recent_profit': avg_recent_profit,
            'position_size_multiplier': self.get_position_size_multiplier(),
            'next_target': min(self.current_target.target_amount + self.TARGET_INCREMENT, self.FINAL_GOAL),
            'remaining_to_goal': self.FINAL_GOAL - self.current_target.target_amount
        }
    
    def print_status_report(self):
        """Print detailed status report"""
        stats = self.get_target_statistics()
        
        print("\n" + "=" * 70)
        print("🎯 PROGRESSIVE TARGET STATUS REPORT")
        print("=" * 70)
        print(f"\n📊 Current Status:")
        print(f"   Current Target: ${stats['current_target']:.2f}/day")
        print(f"   Progress to Goal: {stats['progress_percentage']:.1f}%")
        print(f"   Levels Completed: {stats['levels_completed']}/{stats['total_levels']}")
        print(f"\n📈 Current Level Performance:")
        print(f"   Days at Level: {stats['days_at_current_level']}")
        print(f"   Times Achieved: {stats['achievement_count']}")
        print(f"   Best Daily Profit: ${stats['best_daily_profit']:.2f}")
        print(f"\n🎲 Recent Performance:")
        print(f"   Average (7 days): ${stats['avg_recent_profit']:.2f}")
        print(f"\n🎯 Next Milestone:")
        print(f"   Next Target: ${stats['next_target']:.2f}/day")
        print(f"   Remaining to Goal: ${stats['remaining_to_goal']:.2f}/day")
        print(f"\n⚙️  Trading Adjustments:")
        print(f"   Position Size Multiplier: {stats['position_size_multiplier']:.2f}x")
        print("=" * 70 + "\n")
    
    def manual_set_target(self, target_amount: float) -> bool:
        """
        Manually set target (for testing or recovery)
        
        Args:
            target_amount: New target amount
            
        Returns:
            True if successful
        """
        if target_amount < self.STARTING_TARGET or target_amount > self.FINAL_GOAL:
            logger.error(f"Invalid target amount: ${target_amount:.2f}")
            return False
        
        # Round to nearest $25 increment
        rounded_target = round(target_amount / self.TARGET_INCREMENT) * self.TARGET_INCREMENT
        
        self.current_target = DailyTarget(
            target_amount=rounded_target,
            start_date=str(date.today())
        )
        
        self._save_state()
        logger.info(f"✅ Manually set target to ${rounded_target:.2f}/day")
        return True


# Convenience function for easy import
def get_progressive_target_manager() -> ProgressiveTargetManager:
    """Get singleton instance of ProgressiveTargetManager"""
    if not hasattr(get_progressive_target_manager, '_instance'):
        get_progressive_target_manager._instance = ProgressiveTargetManager()
    return get_progressive_target_manager._instance


if __name__ == "__main__":
    # Test/demonstration
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    manager = ProgressiveTargetManager()
    manager.print_status_report()
    
    # Simulate achieving today's target
    print("\nSimulating achievement of today's target...")
    manager.record_daily_profit(manager.get_current_target() + 5.0)
    
    manager.print_status_report()
