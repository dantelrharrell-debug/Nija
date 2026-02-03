"""
NIJA Education Mode - Learn Trading Without Risk

This module implements the Education Mode onboarding system where users
can learn trading with simulated funds before connecting real broker accounts.

Key Features:
- Simulated $10,000 starting balance
- Full trading functionality with virtual money
- Progress tracking (win rate, risk control, etc.)
- Clear "Not Real Money" indicators
- Optional graduation to live trading

Author: NIJA Trading Systems
Version: 1.0
Date: February 3, 2026
"""

import logging
from enum import Enum
from typing import Dict, Any, Optional
from datetime import datetime
from dataclasses import dataclass, field

from bot.paper_trading import get_paper_account

logger = logging.getLogger(__name__)


class UserMode(Enum):
    """User trading mode"""
    EDUCATION = "education"  # Simulated trading with virtual money
    LIVE_TRADING = "live_trading"  # Real money trading with broker connection


@dataclass
class EducationProgress:
    """Track user progress in education mode"""
    
    user_id: str
    started_at: datetime = field(default_factory=datetime.now)
    
    # Trading metrics
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    current_balance: float = 10000.0
    
    # Progress milestones
    completed_first_trade: bool = False
    reached_10_trades: bool = False
    reached_50_trades: bool = False
    achieved_positive_pnl: bool = False
    maintained_risk_control: bool = False
    
    def get_win_rate(self) -> float:
        """Calculate win rate percentage"""
        total = self.winning_trades + self.losing_trades
        if total == 0:
            return 0.0
        return (self.winning_trades / total) * 100.0
    
    def get_profit_percentage(self) -> float:
        """Calculate profit as percentage of initial balance"""
        return (self.total_pnl / 10000.0) * 100.0
    
    def get_progress_percentage(self) -> int:
        """Calculate overall progress percentage"""
        milestones = [
            self.completed_first_trade,
            self.reached_10_trades,
            self.reached_50_trades,
            self.achieved_positive_pnl,
            self.maintained_risk_control
        ]
        completed = sum(1 for m in milestones if m)
        return int((completed / len(milestones)) * 100)
    
    def is_ready_for_live_trading(self) -> bool:
        """Check if user meets criteria for live trading upgrade"""
        # Minimum requirements for live trading
        return (
            self.total_trades >= 10 and
            self.get_win_rate() >= 50.0 and
            self.total_pnl > 0 and
            self.max_drawdown < 20.0
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses"""
        return {
            'user_id': self.user_id,
            'started_at': self.started_at.isoformat(),
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': round(self.get_win_rate(), 2),
            'total_pnl': round(self.total_pnl, 2),
            'profit_percentage': round(self.get_profit_percentage(), 2),
            'max_drawdown': round(self.max_drawdown, 2),
            'current_balance': round(self.current_balance, 2),
            'progress_percentage': self.get_progress_percentage(),
            'milestones': {
                'completed_first_trade': self.completed_first_trade,
                'reached_10_trades': self.reached_10_trades,
                'reached_50_trades': self.reached_50_trades,
                'achieved_positive_pnl': self.achieved_positive_pnl,
                'maintained_risk_control': self.maintained_risk_control
            },
            'ready_for_live_trading': self.is_ready_for_live_trading()
        }


class EducationModeManager:
    """Manage education mode for users"""
    
    def __init__(self):
        self.user_progress: Dict[str, EducationProgress] = {}
        logger.info("EducationModeManager initialized")
    
    def initialize_user(self, user_id: str) -> EducationProgress:
        """Initialize education mode for a new user"""
        if user_id not in self.user_progress:
            self.user_progress[user_id] = EducationProgress(user_id=user_id)
            logger.info(f"Initialized education mode for user {user_id}")
        return self.user_progress[user_id]
    
    def get_progress(self, user_id: str) -> Optional[EducationProgress]:
        """Get user's education progress"""
        return self.user_progress.get(user_id)
    
    def update_from_paper_account(self, user_id: str) -> EducationProgress:
        """Update progress from paper trading account stats"""
        progress = self.initialize_user(user_id)
        
        # Get paper trading stats
        paper_account = get_paper_account()
        stats = paper_account.get_stats()
        
        # Update metrics
        progress.total_trades = stats['total_trades']
        progress.winning_trades = stats['winning_trades']
        progress.losing_trades = stats['losing_trades']
        progress.total_pnl = stats['total_pnl']
        progress.current_balance = stats['balance']
        
        # Update milestones
        if progress.total_trades >= 1:
            progress.completed_first_trade = True
        if progress.total_trades >= 10:
            progress.reached_10_trades = True
        if progress.total_trades >= 50:
            progress.reached_50_trades = True
        if progress.total_pnl > 0:
            progress.achieved_positive_pnl = True
        
        # Check risk control (max drawdown < 15%)
        if progress.max_drawdown < 15.0:
            progress.maintained_risk_control = True
        
        logger.info(f"Updated education progress for user {user_id}: {progress.total_trades} trades, {progress.get_win_rate():.1f}% win rate")
        
        return progress
    
    def get_onboarding_status(self, user_id: str) -> Dict[str, Any]:
        """Get onboarding status for UI"""
        progress = self.get_progress(user_id)
        
        if not progress:
            return {
                'mode': UserMode.EDUCATION.value,
                'is_new_user': True,
                'show_welcome': True,
                'progress': None
            }
        
        return {
            'mode': UserMode.EDUCATION.value,
            'is_new_user': False,
            'show_welcome': False,
            'progress': progress.to_dict(),
            'next_steps': self._get_next_steps(progress),
            'ui_messages': self._get_ui_messages(progress)
        }
    
    def _get_next_steps(self, progress: EducationProgress) -> list:
        """Get suggested next steps for user"""
        steps = []
        
        if not progress.completed_first_trade:
            steps.append({
                'title': 'Make Your First Trade',
                'description': 'Start learning by making your first simulated trade',
                'action': 'start_trading'
            })
        elif progress.total_trades < 10:
            steps.append({
                'title': f'Complete {10 - progress.total_trades} More Trades',
                'description': 'Build experience with simulated trading',
                'action': 'continue_trading'
            })
        elif not progress.achieved_positive_pnl:
            steps.append({
                'title': 'Achieve Profitability',
                'description': 'Learn to make profitable trades consistently',
                'action': 'improve_strategy'
            })
        elif progress.is_ready_for_live_trading():
            steps.append({
                'title': 'Ready for Live Trading!',
                'description': 'You\'ve met the requirements. Connect your broker to start trading with real money.',
                'action': 'upgrade_to_live'
            })
        else:
            steps.append({
                'title': 'Keep Improving',
                'description': 'Continue practicing to meet live trading requirements',
                'action': 'continue_trading'
            })
        
        return steps
    
    def _get_ui_messages(self, progress: EducationProgress) -> Dict[str, str]:
        """Get UI messages for display"""
        return {
            'mode_badge': '📚 Education Mode',
            'balance_label': 'Simulated Balance (Not Real Money)',
            'trade_disclaimer': 'All trades are simulated with virtual money. No real funds are at risk.',
            'trust_message': 'Your funds never touch our platform. Trades execute directly on your broker.',
            'control_message': 'You\'re always in control. You can stop trading anytime.'
        }


# Global singleton instance
_education_manager = None


def get_education_manager() -> EducationModeManager:
    """Get or create education mode manager singleton"""
    global _education_manager
    if _education_manager is None:
        _education_manager = EducationModeManager()
    return _education_manager
