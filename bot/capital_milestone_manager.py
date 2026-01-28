"""
NIJA Capital Milestone Manager

Tracks progress toward capital goals, locks in gains at psychological breakpoints,
and adjusts trading strategy as milestones are achieved.

Key Features:
- Predefined milestone targets ($100, $250, $500, $1K, $5K, $25K, etc.)
- Automatic profit locking at milestones
- Position sizing graduation tied to milestone achievement
- Celebration/notification system for motivation
- Progress tracking and time-to-goal projections

Author: NIJA Trading Systems
Version: 1.0
Date: January 28, 2026
"""

import logging
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import json
from pathlib import Path

logger = logging.getLogger("nija.milestones")


@dataclass
class Milestone:
    """A capital growth milestone"""
    name: str
    target_amount: float
    achieved: bool = False
    achieved_date: Optional[datetime] = None
    locked_profit_pct: float = 0.10  # % of profit to lock in at this milestone
    description: str = ""
    
    def __lt__(self, other):
        """Enable sorting by target amount"""
        return self.target_amount < other.target_amount


@dataclass
class MilestoneConfig:
    """Configuration for milestone management"""
    # Auto-lock profits at milestones
    enable_profit_locking: bool = True
    lock_profit_pct: float = 0.10  # Lock 10% of profits at each milestone
    
    # Position size adjustments after milestones
    enable_position_scaling: bool = True
    position_increase_pct: float = 0.20  # Increase position size 20% after milestone
    
    # Notifications
    enable_notifications: bool = True
    celebrate_milestones: bool = True
    
    # Time projections
    enable_projections: bool = True
    projection_confidence_min_days: int = 7  # Minimum days for reliable projections


class CapitalMilestoneManager:
    """
    Manages capital growth milestones and celebrations
    
    Responsibilities:
    1. Track progress toward predefined milestones
    2. Lock in profits when milestones are reached
    3. Adjust position sizing based on achievements
    4. Provide motivation through progress tracking
    5. Project time to reach future milestones
    """
    
    # Predefined milestone ladder
    STANDARD_MILESTONES = [
        ("Starter Achievement", 100),
        ("Saver Threshold", 250),
        ("Investor Entry", 500),
        ("First $1K", 1000),
        ("Income Tier", 2500),
        ("Livable Entry", 5000),
        ("$10K Milestone", 10000),
        ("Baller Status", 25000),
        ("$50K Club", 50000),
        ("Six Figures", 100000),
    ]
    
    # Data persistence
    DATA_DIR = Path(__file__).parent.parent / "data"
    MILESTONE_FILE = DATA_DIR / "milestones.json"
    
    def __init__(self, base_capital: float, current_capital: float,
                 config: Optional[MilestoneConfig] = None,
                 custom_milestones: Optional[List[Tuple[str, float]]] = None):
        """
        Initialize Capital Milestone Manager
        
        Args:
            base_capital: Starting capital
            current_capital: Current capital
            config: Milestone configuration (optional)
            custom_milestones: Custom milestone list (optional)
        """
        self.config = config or MilestoneConfig()
        self.base_capital = base_capital
        self.current_capital = current_capital
        
        # Initialize milestones
        self.milestones: List[Milestone] = []
        milestone_list = custom_milestones or self.STANDARD_MILESTONES
        
        for name, amount in milestone_list:
            # Only include milestones above base capital
            if amount > base_capital:
                milestone = Milestone(
                    name=name,
                    target_amount=amount,
                    locked_profit_pct=self.config.lock_profit_pct,
                    description=f"Reach ${amount:,.0f} in capital"
                )
                self.milestones.append(milestone)
        
        # Sort by target amount
        self.milestones.sort()
        
        # Tracking
        self.total_locked_profit = 0.0
        self.milestone_history: List[Dict] = []
        self.start_date = datetime.now()
        
        # Ensure data directory exists
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        
        # Load existing state
        if not self._load_state():
            self._check_initial_achievements()
        
        logger.info("=" * 70)
        logger.info("🎯 Capital Milestone Manager Initialized")
        logger.info("=" * 70)
        logger.info(f"Starting Capital: ${self.base_capital:.2f}")
        logger.info(f"Current Capital: ${self.current_capital:.2f}")
        logger.info(f"Active Milestones: {len([m for m in self.milestones if not m.achieved])}")
        logger.info(f"Next Milestone: {self.get_next_milestone().name if self.get_next_milestone() else 'None'}")
        logger.info("=" * 70)
    
    def _load_state(self) -> bool:
        """Load state from persistent storage"""
        if not self.MILESTONE_FILE.exists():
            return False
        
        try:
            with open(self.MILESTONE_FILE, 'r') as f:
                data = json.load(f)
            
            self.base_capital = data.get('base_capital', self.base_capital)
            self.total_locked_profit = data.get('total_locked_profit', 0.0)
            self.start_date = datetime.fromisoformat(data.get('start_date', datetime.now().isoformat()))
            
            # Load milestone achievements
            achievements = data.get('achievements', {})
            for milestone in self.milestones:
                key = f"{milestone.target_amount:.0f}"
                if key in achievements:
                    milestone.achieved = achievements[key]['achieved']
                    if achievements[key].get('achieved_date'):
                        milestone.achieved_date = datetime.fromisoformat(achievements[key]['achieved_date'])
            
            logger.info(f"✅ Loaded milestone state from {self.MILESTONE_FILE}")
            return True
        except Exception as e:
            logger.warning(f"Failed to load milestone state: {e}")
            return False
    
    def _save_state(self):
        """Save state to persistent storage"""
        try:
            achievements = {}
            for milestone in self.milestones:
                key = f"{milestone.target_amount:.0f}"
                achievements[key] = {
                    'name': milestone.name,
                    'achieved': milestone.achieved,
                    'achieved_date': milestone.achieved_date.isoformat() if milestone.achieved_date else None
                }
            
            data = {
                'base_capital': self.base_capital,
                'current_capital': self.current_capital,
                'total_locked_profit': self.total_locked_profit,
                'start_date': self.start_date.isoformat(),
                'last_updated': datetime.now().isoformat(),
                'achievements': achievements
            }
            
            with open(self.MILESTONE_FILE, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.debug("💾 Milestone state saved")
        except Exception as e:
            logger.error(f"Failed to save milestone state: {e}")
    
    def _check_initial_achievements(self):
        """Check if current capital already exceeds any milestones"""
        for milestone in self.milestones:
            if self.current_capital >= milestone.target_amount and not milestone.achieved:
                # Mark as already achieved
                milestone.achieved = True
                milestone.achieved_date = datetime.now()
                logger.info(f"✅ Already achieved: {milestone.name} (${milestone.target_amount:,.0f})")
    
    def update_capital(self, new_capital: float):
        """
        Update current capital and check for milestone achievements
        
        Args:
            new_capital: New capital amount
        """
        old_capital = self.current_capital
        self.current_capital = new_capital
        
        # Check for newly achieved milestones
        for milestone in self.milestones:
            if not milestone.achieved and new_capital >= milestone.target_amount:
                self._achieve_milestone(milestone, old_capital, new_capital)
        
        self._save_state()
    
    def _achieve_milestone(self, milestone: Milestone, 
                          old_capital: float, new_capital: float):
        """
        Handle milestone achievement
        
        Args:
            milestone: The milestone that was achieved
            old_capital: Capital before achievement
            new_capital: Capital at achievement
        """
        milestone.achieved = True
        milestone.achieved_date = datetime.now()
        
        # Calculate profit to lock
        total_profit = new_capital - self.base_capital
        lock_amount = total_profit * milestone.locked_profit_pct if self.config.enable_profit_locking else 0.0
        
        if lock_amount > 0:
            self.total_locked_profit += lock_amount
        
        # Record in history
        achievement_record = {
            'timestamp': milestone.achieved_date.isoformat(),
            'milestone_name': milestone.name,
            'target_amount': milestone.target_amount,
            'actual_amount': new_capital,
            'locked_profit': lock_amount,
            'days_to_achieve': (milestone.achieved_date - self.start_date).days
        }
        self.milestone_history.append(achievement_record)
        
        # Celebrate!
        if self.config.celebrate_milestones:
            self._celebrate_achievement(milestone, lock_amount)
    
    def _celebrate_achievement(self, milestone: Milestone, locked_profit: float):
        """
        Celebrate milestone achievement with logging
        
        Args:
            milestone: The milestone achieved
            locked_profit: Amount of profit locked
        """
        logger.info("")
        logger.info("=" * 70)
        logger.info("🎉 MILESTONE ACHIEVED! 🎉")
        logger.info("=" * 70)
        logger.info(f"   {milestone.name}")
        logger.info(f"   Target: ${milestone.target_amount:,.2f}")
        logger.info(f"   Actual: ${self.current_capital:,.2f}")
        
        if milestone.achieved_date:
            days = (milestone.achieved_date - self.start_date).days
            logger.info(f"   Time: {days} days since start")
        
        if locked_profit > 0:
            logger.info(f"   Locked Profit: ${locked_profit:,.2f}")
            logger.info(f"   Total Locked: ${self.total_locked_profit:,.2f}")
        
        # Show next milestone
        next_milestone = self.get_next_milestone()
        if next_milestone:
            remaining = next_milestone.target_amount - self.current_capital
            logger.info(f"   Next: {next_milestone.name} (${remaining:,.2f} to go)")
        else:
            logger.info(f"   🏆 ALL MILESTONES ACHIEVED! 🏆")
        
        logger.info("=" * 70)
        logger.info("")
    
    def get_next_milestone(self) -> Optional[Milestone]:
        """Get the next unachieved milestone"""
        for milestone in self.milestones:
            if not milestone.achieved:
                return milestone
        return None
    
    def get_progress_to_next(self) -> Optional[Tuple[Milestone, float, float]]:
        """
        Get progress to next milestone
        
        Returns:
            Tuple of (milestone, progress_pct, amount_remaining) or None
        """
        next_milestone = self.get_next_milestone()
        if not next_milestone:
            return None
        
        total_gap = next_milestone.target_amount - self.base_capital
        current_progress = self.current_capital - self.base_capital
        
        progress_pct = (current_progress / total_gap * 100) if total_gap > 0 else 100.0
        amount_remaining = next_milestone.target_amount - self.current_capital
        
        return (next_milestone, progress_pct, amount_remaining)
    
    def get_time_to_next_milestone(self, daily_avg_profit: float) -> Optional[Tuple[Milestone, int]]:
        """
        Estimate days to reach next milestone
        
        Args:
            daily_avg_profit: Average daily profit
            
        Returns:
            Tuple of (milestone, estimated_days) or None
        """
        if daily_avg_profit <= 0:
            return None
        
        progress = self.get_progress_to_next()
        if not progress:
            return None
        
        milestone, _, remaining = progress
        days_to_milestone = int(remaining / daily_avg_profit)
        
        return (milestone, days_to_milestone)
    
    def get_position_size_multiplier(self) -> float:
        """
        Get position size multiplier based on milestones achieved
        
        Returns:
            Multiplier for position sizing (1.0 = base, >1.0 = increased)
        """
        if not self.config.enable_position_scaling:
            return 1.0
        
        # Count achieved milestones
        achieved_count = sum(1 for m in self.milestones if m.achieved)
        
        # Increase position size by configured % for each milestone
        multiplier = 1.0 + (achieved_count * self.config.position_increase_pct)
        
        return multiplier
    
    def get_milestone_report(self) -> str:
        """Generate detailed milestone report"""
        report = [
            "\n" + "=" * 90,
            "CAPITAL MILESTONE PROGRESS REPORT",
            "=" * 90,
            f"Starting Capital: ${self.base_capital:,.2f}",
            f"Current Capital: ${self.current_capital:,.2f}",
            f"Total Gain: ${self.current_capital - self.base_capital:,.2f} ({((self.current_capital/self.base_capital - 1)*100):.2f}%)",
            f"Locked Profit: ${self.total_locked_profit:,.2f}",
            ""
        ]
        
        # Current progress
        progress = self.get_progress_to_next()
        if progress:
            milestone, progress_pct, remaining = progress
            report.extend([
                "🎯 NEXT MILESTONE",
                "-" * 90,
                f"  {milestone.name}",
                f"  Target: ${milestone.target_amount:,.2f}",
                f"  Progress: {progress_pct:.1f}%",
                f"  Remaining: ${remaining:,.2f}",
                ""
            ])
            
            # Progress bar
            bar_length = 50
            filled = int(bar_length * progress_pct / 100)
            bar = "█" * filled + "░" * (bar_length - filled)
            report.append(f"  [{bar}] {progress_pct:.1f}%")
            report.append("")
        
        # All milestones
        achieved_count = sum(1 for m in self.milestones if m.achieved)
        total_count = len(self.milestones)
        
        report.extend([
            "📊 ALL MILESTONES",
            "-" * 90,
            f"  Achieved: {achieved_count}/{total_count}",
            ""
        ])
        
        for milestone in self.milestones:
            status = "✅" if milestone.achieved else "⏳"
            if milestone.achieved and milestone.achieved_date:
                days = (milestone.achieved_date - self.start_date).days
                report.append(f"  {status} {milestone.name:<25} ${milestone.target_amount:>10,.0f}  ({days} days)")
            else:
                report.append(f"  {status} {milestone.name:<25} ${milestone.target_amount:>10,.0f}")
        
        report.append("")
        
        # Recent achievements
        if self.milestone_history:
            report.extend([
                "🏆 RECENT ACHIEVEMENTS",
                "-" * 90
            ])
            for record in self.milestone_history[-5:]:
                timestamp = datetime.fromisoformat(record['timestamp'])
                report.append(
                    f"  {timestamp.strftime('%Y-%m-%d')}: {record['milestone_name']} "
                    f"(${record['actual_amount']:,.0f}) - {record['days_to_achieve']} days"
                )
            report.append("")
        
        # Position sizing adjustment
        if self.config.enable_position_scaling:
            multiplier = self.get_position_size_multiplier()
            report.extend([
                "⚙️  POSITION SIZE ADJUSTMENT",
                "-" * 90,
                f"  Milestones Achieved: {achieved_count}",
                f"  Position Multiplier: {multiplier:.2f}x",
                f"  Effect: Position sizes are {(multiplier-1)*100:.0f}% larger than base",
                ""
            ])
        
        report.append("=" * 90 + "\n")
        
        return "\n".join(report)
    
    def get_locked_profit(self) -> float:
        """Get total locked profit amount"""
        return self.total_locked_profit
    
    def get_achievement_percentage(self) -> float:
        """Get percentage of milestones achieved"""
        if not self.milestones:
            return 100.0
        achieved = sum(1 for m in self.milestones if m.achieved)
        return (achieved / len(self.milestones)) * 100


def get_milestone_manager(base_capital: float, current_capital: float,
                         custom_milestones: Optional[List[Tuple[str, float]]] = None) -> CapitalMilestoneManager:
    """
    Get or create milestone manager instance
    
    Args:
        base_capital: Starting capital
        current_capital: Current capital
        custom_milestones: Optional custom milestone list
        
    Returns:
        CapitalMilestoneManager instance
    """
    return CapitalMilestoneManager(base_capital, current_capital, 
                                  custom_milestones=custom_milestones)


if __name__ == "__main__":
    # Test/demonstration
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s - %(message)s'
    )
    
    # Create manager starting at $50, currently at $180
    manager = get_milestone_manager(50.0, 180.0)
    
    print(manager.get_milestone_report())
    
    # Simulate reaching $250
    print("\nReaching $250 milestone...\n")
    manager.update_capital(250.0)
    
    print(manager.get_milestone_report())
    
    # Simulate reaching $500
    print("\nReaching $500 milestone...\n")
    manager.update_capital(500.0)
    
    print(manager.get_milestone_report())
