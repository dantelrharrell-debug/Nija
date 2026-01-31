"""
NIJA Paper Trading Graduation System
====================================

Progressive system for graduating users from paper trading to real trading.
Ensures users demonstrate competency before risking real capital.

Graduation Criteria:
- Minimum time in paper trading (30 days recommended)
- Minimum number of trades executed (20+)
- Positive win rate (>40%)
- Consistent risk management (proper position sizing)
- Understanding of platform features (completion checklist)

Safety Features:
- Progressive capital limits after graduation
- Graduated position sizing
- Mandatory risk acknowledgment
- Reversible to paper trading
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from enum import Enum

logger = logging.getLogger(__name__)


class TradingMode(Enum):
    """Trading mode states"""
    PAPER = "paper"              # Paper trading only
    GRADUATED = "graduated"      # Eligible for live trading
    LIVE_RESTRICTED = "live_restricted"  # Live with limited capital
    LIVE_FULL = "live_full"      # Full live trading access


class GraduationStatus(Enum):
    """Graduation eligibility status"""
    NOT_ELIGIBLE = "not_eligible"
    IN_PROGRESS = "in_progress"
    ELIGIBLE = "eligible"
    GRADUATED = "graduated"


@dataclass
class GraduationCriteria:
    """Individual graduation criterion"""
    criterion_id: str
    name: str
    description: str
    required: bool
    met: bool
    progress: float  # 0-100%
    details: str


@dataclass
class GraduationProgress:
    """User's graduation progress tracking"""
    user_id: str
    trading_mode: TradingMode
    status: GraduationStatus
    paper_trading_start_date: str
    days_in_paper_trading: int
    total_paper_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    max_drawdown: float
    average_position_size: float
    risk_score: float  # 0-100, higher is better
    criteria_met: List[str]
    criteria_not_met: List[str]
    graduation_date: Optional[str] = None
    live_trading_enabled_date: Optional[str] = None


class PaperTradingGraduationSystem:
    """
    Manages user progression from paper trading to live trading.
    Implements safety checks and gradual capital unlocking.
    """

    # Graduation Requirements
    MIN_DAYS_PAPER_TRADING = 30
    MIN_TOTAL_TRADES = 20
    MIN_WIN_RATE = 40.0  # 40%
    MIN_RISK_SCORE = 60.0  # Out of 100
    MAX_ACCEPTABLE_DRAWDOWN = 30.0  # 30% max drawdown

    # Progressive Capital Limits after Graduation
    LIVE_RESTRICTED_MAX_POSITION = 100  # $100 max position initially
    LIVE_RESTRICTED_MAX_TOTAL = 500     # $500 max total capital
    LIVE_FULL_UNLOCK_DAYS = 14          # Days in restricted before full unlock

    def __init__(self, user_id: str, data_dir: str = "data/graduation"):
        self.user_id = user_id
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.user_file = self.data_dir / f"{user_id}_graduation.json"
        self.progress = self._load_progress()

    def _load_progress(self) -> GraduationProgress:
        """Load user's graduation progress"""
        if self.user_file.exists():
            try:
                with open(self.user_file, 'r') as f:
                    data = json.load(f)
                    return GraduationProgress(
                        user_id=data['user_id'],
                        trading_mode=TradingMode(data['trading_mode']),
                        status=GraduationStatus(data['status']),
                        paper_trading_start_date=data['paper_trading_start_date'],
                        days_in_paper_trading=data['days_in_paper_trading'],
                        total_paper_trades=data['total_paper_trades'],
                        winning_trades=data['winning_trades'],
                        losing_trades=data['losing_trades'],
                        win_rate=data['win_rate'],
                        total_pnl=data['total_pnl'],
                        max_drawdown=data['max_drawdown'],
                        average_position_size=data['average_position_size'],
                        risk_score=data['risk_score'],
                        criteria_met=data['criteria_met'],
                        criteria_not_met=data['criteria_not_met'],
                        graduation_date=data.get('graduation_date'),
                        live_trading_enabled_date=data.get('live_trading_enabled_date')
                    )
            except Exception as e:
                logger.error(f"Error loading graduation progress: {e}")

        # Create new progress for new user
        return GraduationProgress(
            user_id=self.user_id,
            trading_mode=TradingMode.PAPER,
            status=GraduationStatus.NOT_ELIGIBLE,
            paper_trading_start_date=datetime.utcnow().isoformat(),
            days_in_paper_trading=0,
            total_paper_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=0.0,
            total_pnl=0.0,
            max_drawdown=0.0,
            average_position_size=0.0,
            risk_score=0.0,
            criteria_met=[],
            criteria_not_met=[]
        )

    def _save_progress(self):
        """Save graduation progress to disk"""
        try:
            # Convert dataclass to dict and handle enums
            progress_dict = asdict(self.progress)
            progress_dict['trading_mode'] = self.progress.trading_mode.value
            progress_dict['status'] = self.progress.status.value
            
            with open(self.user_file, 'w') as f:
                json.dump(progress_dict, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving graduation progress: {e}")

    def update_from_paper_account(self, paper_account_stats: Dict):
        """
        Update graduation progress from paper trading account statistics.
        Call this method periodically (e.g., daily) to track progress.
        """
        # Calculate days in paper trading
        start_date = datetime.fromisoformat(self.progress.paper_trading_start_date)
        days_trading = (datetime.utcnow() - start_date).days

        # Update basic stats
        self.progress.days_in_paper_trading = days_trading
        self.progress.total_paper_trades = paper_account_stats.get('total_trades', 0)
        self.progress.winning_trades = paper_account_stats.get('winning_trades', 0)
        self.progress.losing_trades = paper_account_stats.get('losing_trades', 0)
        self.progress.win_rate = paper_account_stats.get('win_rate', 0.0)
        self.progress.total_pnl = paper_account_stats.get('total_pnl', 0.0)
        self.progress.max_drawdown = paper_account_stats.get('max_drawdown', 0.0)
        self.progress.average_position_size = paper_account_stats.get('avg_position_size', 0.0)

        # Calculate risk score
        self.progress.risk_score = self._calculate_risk_score()

        # Evaluate graduation criteria
        self._evaluate_criteria()

        # Update status
        self._update_status()

        self._save_progress()
        logger.info(f"Updated graduation progress for user {self.user_id}")

    def _calculate_risk_score(self) -> float:
        """
        Calculate risk management score (0-100).
        Higher score = better risk management.
        """
        score = 0.0

        # Win rate component (30 points max)
        if self.progress.win_rate >= 50:
            score += 30
        elif self.progress.win_rate >= 40:
            score += 20
        elif self.progress.win_rate >= 30:
            score += 10

        # Drawdown management (30 points max)
        if self.progress.max_drawdown <= 10:
            score += 30
        elif self.progress.max_drawdown <= 20:
            score += 20
        elif self.progress.max_drawdown <= 30:
            score += 10

        # Consistency (20 points max - based on trade count)
        if self.progress.total_paper_trades >= 50:
            score += 20
        elif self.progress.total_paper_trades >= 30:
            score += 15
        elif self.progress.total_paper_trades >= 20:
            score += 10

        # Profitability (20 points max)
        if self.progress.total_pnl > 500:
            score += 20
        elif self.progress.total_pnl > 200:
            score += 15
        elif self.progress.total_pnl > 0:
            score += 10

        return round(score, 2)

    def _evaluate_criteria(self):
        """Evaluate all graduation criteria"""
        met = []
        not_met = []

        # Criterion 1: Time requirement
        if self.progress.days_in_paper_trading >= self.MIN_DAYS_PAPER_TRADING:
            met.append("time_requirement")
        else:
            not_met.append("time_requirement")

        # Criterion 2: Trade volume
        if self.progress.total_paper_trades >= self.MIN_TOTAL_TRADES:
            met.append("trade_volume")
        else:
            not_met.append("trade_volume")

        # Criterion 3: Win rate
        if self.progress.win_rate >= self.MIN_WIN_RATE:
            met.append("win_rate")
        else:
            not_met.append("win_rate")

        # Criterion 4: Risk management
        if self.progress.risk_score >= self.MIN_RISK_SCORE:
            met.append("risk_management")
        else:
            not_met.append("risk_management")

        # Criterion 5: Drawdown control
        if self.progress.max_drawdown <= self.MAX_ACCEPTABLE_DRAWDOWN:
            met.append("drawdown_control")
        else:
            not_met.append("drawdown_control")

        self.progress.criteria_met = met
        self.progress.criteria_not_met = not_met

    def _update_status(self):
        """Update graduation status based on criteria"""
        if self.progress.trading_mode == TradingMode.LIVE_FULL:
            self.progress.status = GraduationStatus.GRADUATED
        elif self.progress.trading_mode == TradingMode.LIVE_RESTRICTED:
            self.progress.status = GraduationStatus.GRADUATED
        elif len(self.progress.criteria_not_met) == 0:
            self.progress.status = GraduationStatus.ELIGIBLE
        elif len(self.progress.criteria_met) > 0:
            self.progress.status = GraduationStatus.IN_PROGRESS
        else:
            self.progress.status = GraduationStatus.NOT_ELIGIBLE

    def get_criteria_details(self) -> List[GraduationCriteria]:
        """Get detailed breakdown of all graduation criteria"""
        criteria = []

        # Time requirement
        time_progress = min(100, (self.progress.days_in_paper_trading / self.MIN_DAYS_PAPER_TRADING) * 100)
        criteria.append(GraduationCriteria(
            criterion_id="time_requirement",
            name="Paper Trading Duration",
            description=f"Trade in paper mode for at least {self.MIN_DAYS_PAPER_TRADING} days",
            required=True,
            met="time_requirement" in self.progress.criteria_met,
            progress=time_progress,
            details=f"{self.progress.days_in_paper_trading}/{self.MIN_DAYS_PAPER_TRADING} days completed"
        ))

        # Trade volume
        trade_progress = min(100, (self.progress.total_paper_trades / self.MIN_TOTAL_TRADES) * 100)
        criteria.append(GraduationCriteria(
            criterion_id="trade_volume",
            name="Minimum Trades",
            description=f"Execute at least {self.MIN_TOTAL_TRADES} paper trades",
            required=True,
            met="trade_volume" in self.progress.criteria_met,
            progress=trade_progress,
            details=f"{self.progress.total_paper_trades}/{self.MIN_TOTAL_TRADES} trades completed"
        ))

        # Win rate
        win_rate_progress = min(100, (self.progress.win_rate / self.MIN_WIN_RATE) * 100)
        criteria.append(GraduationCriteria(
            criterion_id="win_rate",
            name="Win Rate",
            description=f"Maintain at least {self.MIN_WIN_RATE}% win rate",
            required=True,
            met="win_rate" in self.progress.criteria_met,
            progress=win_rate_progress,
            details=f"{self.progress.win_rate:.1f}% (target: {self.MIN_WIN_RATE}%)"
        ))

        # Risk management
        risk_progress = min(100, (self.progress.risk_score / self.MIN_RISK_SCORE) * 100)
        criteria.append(GraduationCriteria(
            criterion_id="risk_management",
            name="Risk Management Score",
            description=f"Achieve risk score of at least {self.MIN_RISK_SCORE}/100",
            required=True,
            met="risk_management" in self.progress.criteria_met,
            progress=risk_progress,
            details=f"{self.progress.risk_score:.1f}/100 (target: {self.MIN_RISK_SCORE})"
        ))

        # Drawdown control
        drawdown_progress = 100 if self.progress.max_drawdown <= self.MAX_ACCEPTABLE_DRAWDOWN else 50
        criteria.append(GraduationCriteria(
            criterion_id="drawdown_control",
            name="Drawdown Control",
            description=f"Keep maximum drawdown under {self.MAX_ACCEPTABLE_DRAWDOWN}%",
            required=True,
            met="drawdown_control" in self.progress.criteria_met,
            progress=drawdown_progress,
            details=f"{self.progress.max_drawdown:.1f}% (limit: {self.MAX_ACCEPTABLE_DRAWDOWN}%)"
        ))

        return criteria

    def is_eligible_for_graduation(self) -> bool:
        """Check if user meets all graduation requirements"""
        return self.progress.status == GraduationStatus.ELIGIBLE

    def graduate_to_live_trading(self) -> Dict:
        """
        Graduate user to live trading with initial restrictions.
        Returns graduation result with next steps.
        """
        if not self.is_eligible_for_graduation():
            return {
                'success': False,
                'message': 'User does not meet graduation requirements',
                'criteria_not_met': self.progress.criteria_not_met
            }

        # Mark as graduated
        self.progress.trading_mode = TradingMode.LIVE_RESTRICTED
        self.progress.status = GraduationStatus.GRADUATED
        self.progress.graduation_date = datetime.utcnow().isoformat()
        self.progress.live_trading_enabled_date = datetime.utcnow().isoformat()

        self._save_progress()

        logger.info(f"✅ User {self.user_id} graduated to live trading (restricted mode)")

        return {
            'success': True,
            'message': 'Congratulations! You have graduated to live trading.',
            'trading_mode': TradingMode.LIVE_RESTRICTED.value,
            'restrictions': {
                'max_position_size': self.LIVE_RESTRICTED_MAX_POSITION,
                'max_total_capital': self.LIVE_RESTRICTED_MAX_TOTAL,
                'unlock_full_after_days': self.LIVE_FULL_UNLOCK_DAYS
            },
            'graduation_date': self.progress.graduation_date
        }

    def check_full_access_eligibility(self) -> bool:
        """Check if user is eligible for full live trading access"""
        if self.progress.trading_mode != TradingMode.LIVE_RESTRICTED:
            return False

        if not self.progress.live_trading_enabled_date:
            return False

        # Check if enough time has passed in restricted mode
        enabled_date = datetime.fromisoformat(self.progress.live_trading_enabled_date)
        days_in_restricted = (datetime.utcnow() - enabled_date).days

        return days_in_restricted >= self.LIVE_FULL_UNLOCK_DAYS

    def unlock_full_live_trading(self) -> Dict:
        """Unlock full live trading access"""
        if not self.check_full_access_eligibility():
            enabled_date = datetime.fromisoformat(self.progress.live_trading_enabled_date)
            days_in_restricted = (datetime.utcnow() - enabled_date).days
            days_remaining = self.LIVE_FULL_UNLOCK_DAYS - days_in_restricted

            return {
                'success': False,
                'message': f'Full access unlocks in {days_remaining} days',
                'days_remaining': days_remaining
            }

        self.progress.trading_mode = TradingMode.LIVE_FULL
        self._save_progress()

        logger.info(f"✅ User {self.user_id} unlocked full live trading access")

        return {
            'success': True,
            'message': 'Full live trading access unlocked!',
            'trading_mode': TradingMode.LIVE_FULL.value
        }

    def revert_to_paper_trading(self) -> Dict:
        """Allow user to voluntarily revert to paper trading"""
        previous_mode = self.progress.trading_mode
        self.progress.trading_mode = TradingMode.PAPER
        self._save_progress()

        logger.info(f"User {self.user_id} reverted from {previous_mode.value} to paper trading")

        return {
            'success': True,
            'message': 'Reverted to paper trading mode',
            'previous_mode': previous_mode.value
        }

    def get_current_limits(self) -> Dict:
        """Get current trading limits based on mode"""
        if self.progress.trading_mode == TradingMode.PAPER:
            return {
                'mode': 'paper',
                'max_position_size': None,  # Unlimited in paper
                'max_total_capital': None,
                'restrictions': 'Paper trading only - no real capital at risk'
            }
        elif self.progress.trading_mode == TradingMode.LIVE_RESTRICTED:
            return {
                'mode': 'live_restricted',
                'max_position_size': self.LIVE_RESTRICTED_MAX_POSITION,
                'max_total_capital': self.LIVE_RESTRICTED_MAX_TOTAL,
                'restrictions': f'Limited to ${self.LIVE_RESTRICTED_MAX_TOTAL} total capital'
            }
        elif self.progress.trading_mode == TradingMode.LIVE_FULL:
            return {
                'mode': 'live_full',
                'max_position_size': None,  # Determined by user's account
                'max_total_capital': None,
                'restrictions': 'No platform restrictions (subject to broker limits)'
            }

    def print_graduation_summary(self):
        """Print user-friendly graduation progress summary"""
        criteria = self.get_criteria_details()

        print("\n" + "=" * 80)
        print(f"📊 GRADUATION PROGRESS - User: {self.user_id}")
        print("=" * 80)
        print(f"Status: {self.progress.status.value.upper()}")
        print(f"Trading Mode: {self.progress.trading_mode.value.upper()}")
        print(f"Days in Paper Trading: {self.progress.days_in_paper_trading}")
        print(f"Risk Score: {self.progress.risk_score}/100")
        print("=" * 80)

        print("\n📋 GRADUATION CRITERIA:")
        for criterion in criteria:
            status_icon = "✅" if criterion.met else "⏳"
            print(f"{status_icon} {criterion.name}: {criterion.progress:.1f}%")
            print(f"   {criterion.details}")

        if self.progress.status == GraduationStatus.ELIGIBLE:
            print("\n🎉 ELIGIBLE FOR GRADUATION!")
            print("   You can now enable live trading with initial restrictions.")
        elif self.progress.status == GraduationStatus.GRADUATED:
            print("\n✅ GRADUATED!")
            limits = self.get_current_limits()
            print(f"   Mode: {limits['mode']}")
            print(f"   {limits['restrictions']}")

        print("=" * 80 + "\n")


def create_graduation_system(user_id: str) -> PaperTradingGraduationSystem:
    """Factory function to create graduation system for a user"""
    return PaperTradingGraduationSystem(user_id)


if __name__ == "__main__":
    # Example usage
    system = create_graduation_system("test_user_123")

    # Simulate paper trading stats
    paper_stats = {
        'total_trades': 25,
        'winning_trades': 15,
        'losing_trades': 10,
        'win_rate': 60.0,
        'total_pnl': 350.0,
        'max_drawdown': 12.5,
        'avg_position_size': 50.0
    }

    system.update_from_paper_account(paper_stats)
    system.print_graduation_summary()
