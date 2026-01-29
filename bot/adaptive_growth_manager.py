# adaptive_growth_manager.py
"""
NIJA Adaptive Growth Manager
Automatically adjusts trading strategy as account balance grows

Features:
- Reduces aggressiveness as account grows
- Learns from winning trades
- Adjusts risk parameters based on account milestones
- Performance-based strategy optimization

Version: 1.0
"""

import logging
from typing import Dict, Tuple
from datetime import datetime, timedelta

logger = logging.getLogger("nija.growth_manager")


class AdaptiveGrowthManager:
    """
    Manages strategy adjustments based on account growth and performance

    Growth Stages:
    - Stage 1 ($0-$50): ULTRA AGGRESSIVE - Maximize growth
    - Stage 2 ($50-$200): AGGRESSIVE - Build capital
    - Stage 3 ($200-$500): MODERATE - Protect gains
    - Stage 4 ($500+): CONSERVATIVE - Sustainable income
    """

    # Define growth stages with their parameters
    GROWTH_STAGES = {
        'ultra_aggressive': {
            'balance_range': (0, 300),  # EXTENDED: Stay ultra-aggressive until $300
            'min_adx': 0,  # REMOVED: Accept any trend strength
            'volume_threshold': 0.0,  # REMOVED: Accept any volume
            'filter_agreement': 2,  # LOWERED: Only 2/5 filters needed
            'min_position_pct': 0.05,  # 5% minimum to reduce fee drag
            'max_position_pct': 0.15,  # 15% maximum per trade
            'max_exposure': 0.50,  # 50% total exposure cap
            'description': 'ULTRA AGGRESSIVE - Controlled growth mode'
        },
        'aggressive': {
            'balance_range': (300, 1000),
            'min_adx': 5,  # LOWERED: More trades
            'volume_threshold': 0.05,  # LOWERED: 5% volume
            'filter_agreement': 2,  # LOWERED: 2/5 filters
            'min_position_pct': 0.04,  # 4%
            'max_position_pct': 0.12,  # 12%
            'max_exposure': 0.45,  # 45%
            'description': 'AGGRESSIVE - Building capital with lower exposure'
        },
        'moderate': {
            'balance_range': (1000, 3000),
            'min_adx': 10,
            'volume_threshold': 0.10,  # 10% volume
            'filter_agreement': 3,  # 3/5 filters
            'min_position_pct': 0.03,  # 3%
            'max_position_pct': 0.08,  # 8%
            'max_exposure': 0.35,  # 35%
            'description': 'MODERATE - Approaching goal'
        },
        'conservative': {
            'balance_range': (3000, float('inf')),
            'min_adx': 15,
            'volume_threshold': 0.15,  # 15% volume
            'filter_agreement': 3,  # 3/5 filters
            'min_position_pct': 0.02,  # 2%
            'max_position_pct': 0.05,  # 5%
            'max_exposure': 0.30,  # 30%
            'description': 'CONSERVATIVE - Goal reached, protect gains'
        }
    }

    def __init__(self):
        """Initialize Adaptive Growth Manager"""
        self.current_stage = 'ultra_aggressive'
        self.stage_entered_at = datetime.now()
        self.performance_history = []
        self.last_balance_check = 0.0

        logger.info("🧠 Adaptive Growth Manager initialized")
        logger.info(f"   Starting stage: {self.GROWTH_STAGES[self.current_stage]['description']}")

    def get_stage_for_balance(self, balance: float) -> str:
        """
        Determine which growth stage the account is in based on balance

        Args:
            balance: Current account balance

        Returns:
            Stage name (e.g., 'ultra_aggressive', 'aggressive', etc.)
        """
        for stage_name, stage_config in self.GROWTH_STAGES.items():
            min_balance, max_balance = stage_config['balance_range']
            if min_balance <= balance < max_balance:
                return stage_name

        # Default to conservative if balance exceeds all ranges
        return 'conservative'

    def update_stage(self, current_balance: float) -> Tuple[bool, Dict]:
        """
        Check if account has grown to a new stage and update parameters

        Args:
            current_balance: Current account balance

        Returns:
            Tuple of (stage_changed, new_config)
        """
        new_stage = self.get_stage_for_balance(current_balance)
        stage_changed = new_stage != self.current_stage

        if stage_changed:
            old_stage = self.current_stage
            self.current_stage = new_stage
            self.stage_entered_at = datetime.now()

            logger.info("=" * 70)
            logger.info("🎉 ACCOUNT GROWTH MILESTONE REACHED!")
            logger.info("=" * 70)
            logger.info(f"Balance: ${current_balance:.2f}")
            logger.info(f"Old Stage: {self.GROWTH_STAGES[old_stage]['description']}")
            logger.info(f"New Stage: {self.GROWTH_STAGES[new_stage]['description']}")
            logger.info("")
            logger.info("STRATEGY ADJUSTMENTS:")

            new_config = self.GROWTH_STAGES[new_stage]
            logger.info(f"  ADX Threshold: {new_config['min_adx']}")
            logger.info(f"  Volume Threshold: {new_config['volume_threshold']*100:.0f}%")
            logger.info(f"  Filter Agreement: {new_config['filter_agreement']}/5")
            logger.info(f"  Position Size: {new_config['min_position_pct']*100:.0f}%-{new_config['max_position_pct']*100:.0f}%")
            logger.info(f"  Max Exposure: {new_config['max_exposure']*100:.0f}%")
            logger.info("=" * 70)

        self.last_balance_check = current_balance
        return stage_changed, self.GROWTH_STAGES[self.current_stage]

    def get_current_config(self) -> Dict:
        """
        Get current strategy configuration for active stage

        Returns:
            Dictionary with strategy parameters
        """
        return self.GROWTH_STAGES[self.current_stage]

    def get_position_size_pct(self) -> float:
        """
        Get position size percentage for current growth stage

        Returns:
            Position size as percentage of account balance (0.05 to 0.15 for ultra aggressive)
        """
        config = self.GROWTH_STAGES[self.current_stage]

        # Use the MAXIMUM of the stage range to ensure smaller positions on small accounts
        # This prevents ultra-aggressive sizing that creates unprofitable micro-trades on tiny accounts
        position_pct = config['max_position_pct']

        logger.debug(f"Position size: {position_pct*100:.0f}% ({self.current_stage})")
        return position_pct

    def get_min_position_usd(self) -> float:
        """
        Get hard minimum position size in USD to avoid Coinbase fee drag

        Positions smaller than this will lose money to trading fees (0.5-0.6%).
        Need at least 1-2% profit margin to overcome fees on small positions.

        Returns:
            Minimum USD amount per single position (hard floor)
        """
        # Hard floor: $2.00 minimum per position
        # At $2.00: Coinbase fee (0.6%) = $0.012, need 1% gain = very achievable
        # At $1.00: Fee = $0.006, profit margin too thin, slippage kills it
        MIN_POSITION_USD = 2.00
        return MIN_POSITION_USD

    def get_max_position_usd(self) -> float:
        """
        Get hard maximum position size in USD (hard cap regardless of percentage)

        Returns:
            Maximum USD amount per single position (hard limit)
        """
        # Hard cap: $100 maximum per position - prevents over-leveraging
        MAX_POSITION_USD = 100.0
        return MAX_POSITION_USD

    def record_performance(self, win_rate: float, avg_profit: float, total_trades: int):
        """
        Record trading performance metrics for learning

        Args:
            win_rate: Current win rate (0.0 to 1.0)
            avg_profit: Average profit per trade
            total_trades: Total number of trades executed
        """
        performance_record = {
            'timestamp': datetime.now(),
            'stage': self.current_stage,
            'win_rate': win_rate,
            'avg_profit': avg_profit,
            'total_trades': total_trades
        }

        self.performance_history.append(performance_record)

        # Keep only last 100 records
        if len(self.performance_history) > 100:
            self.performance_history = self.performance_history[-100:]

        logger.debug(f"Performance recorded: Win rate {win_rate*100:.1f}%, Avg profit ${avg_profit:.2f}")

    def should_reduce_risk(self) -> bool:
        """
        Determine if risk should be temporarily reduced based on recent performance

        Returns:
            True if risk should be reduced
        """
        if len(self.performance_history) < 5:
            return False

        # Check last 5 trades for declining performance
        recent = self.performance_history[-5:]
        recent_win_rates = [p['win_rate'] for p in recent]

        # If win rate dropping below 40%, reduce risk
        avg_recent_win_rate = sum(recent_win_rates) / len(recent_win_rates)

        if avg_recent_win_rate < 0.40:
            logger.warning(f"⚠️ Win rate low ({avg_recent_win_rate*100:.1f}%) - Temporarily reducing risk")
            return True

        return False

    def get_progress_to_next_milestone(self, current_balance: float) -> Dict:
        """
        Calculate progress to next growth milestone

        Args:
            current_balance: Current account balance

        Returns:
            Dictionary with progress information
        """
        current_stage_config = self.GROWTH_STAGES[self.current_stage]
        _, max_balance = current_stage_config['balance_range']

        if max_balance == float('inf'):
            return {
                'next_milestone': None,
                'progress_pct': 100.0,
                'remaining': 0.0,
                'message': 'Maximum stage reached!'
            }

        min_balance, _ = current_stage_config['balance_range']
        progress = (current_balance - min_balance) / (max_balance - min_balance)
        remaining = max_balance - current_balance

        return {
            'next_milestone': max_balance,
            'progress_pct': progress * 100,
            'remaining': remaining,
            'message': f'${remaining:.2f} until next stage'
        }
