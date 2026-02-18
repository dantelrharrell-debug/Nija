"""
NIJA Capital Tier Scaling System (Phase 3: The Growth System)

Institutional-grade capital tier system with dynamic behavior based on account size.
Allows NIJA to scale from $50 to $250k without rewriting logic.

Features:
- Dynamic tier detection and auto-assignment
- Institutional tier model ($50-$250k range)
- Tier-specific risk percentage calculations
- Tier-specific max position counts
- Tier-appropriate behavior modifications
- Tier transition logging and milestone system
- Capital-based aggression scaling
- Diversification requirements per tier
- Stability prioritization for high tiers

Author: NIJA Trading Systems
Version: 1.0
Date: February 18, 2026
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path

logger = logging.getLogger("nija.capital_tiers")


class TierLevel(Enum):
    """Capital tier levels"""
    MICRO = "MICRO"               # $50-$500
    GROWTH = "GROWTH"             # $500-$5k
    PRO = "PRO"                   # $5k-$50k
    INSTITUTIONAL = "INSTITUTIONAL"  # $50k-$250k


@dataclass
class TierConfiguration:
    """Configuration for a capital tier"""
    tier_level: TierLevel
    min_capital: float
    max_capital: float
    
    # Risk parameters
    risk_per_trade_pct: Tuple[float, float]  # (min, max) risk %
    max_positions: Tuple[int, int]            # (min, max) positions
    
    # Behavior parameters
    aggression_level: float          # 0-1, higher = more aggressive
    diversification_required: bool   # Must spread across symbols
    min_symbols_for_full_allocation: int  # Min symbols before using max positions
    
    # Profit targets
    min_profit_target_pct: float
    max_profit_target_pct: float
    
    # Stop loss
    max_stop_loss_pct: float
    
    # Trading frequency
    max_daily_trades: int
    cooldown_after_loss_minutes: int
    
    # Capital preservation
    daily_loss_limit_pct: float
    weekly_loss_limit_pct: float
    
    # Behavior flags
    allow_aggressive_entries: bool
    require_high_confidence: bool
    prioritize_stability: bool
    
    def get_recommended_risk_pct(self, confidence: float) -> float:
        """
        Get recommended risk percentage based on confidence.
        
        Args:
            confidence: Signal confidence (0-1)
            
        Returns:
            Risk percentage (0-1)
        """
        min_risk, max_risk = self.risk_per_trade_pct
        
        # Scale risk based on confidence
        risk_range = max_risk - min_risk
        risk_pct = min_risk + (risk_range * confidence)
        
        return risk_pct
    
    def get_recommended_positions(self, available_symbols: int) -> int:
        """
        Get recommended position count based on available symbols.
        
        Args:
            available_symbols: Number of symbols meeting entry criteria
            
        Returns:
            Recommended position count
        """
        min_pos, max_pos = self.max_positions
        
        if not self.diversification_required:
            return max_pos
        
        # Scale positions based on symbol availability
        if available_symbols < self.min_symbols_for_full_allocation:
            # Limit positions if not enough diverse symbols
            return min(min_pos, available_symbols)
        else:
            # Can use full allocation
            return max_pos


# Institutional Tier Model
TIER_CONFIGURATIONS = {
    TierLevel.MICRO: TierConfiguration(
        tier_level=TierLevel.MICRO,
        min_capital=50.0,
        max_capital=500.0,
        risk_per_trade_pct=(0.02, 0.03),  # 2-3% per trade
        max_positions=(1, 2),               # 1-2 positions
        aggression_level=0.8,               # High precision mode
        diversification_required=False,
        min_symbols_for_full_allocation=1,
        min_profit_target_pct=0.015,       # 1.5% minimum
        max_profit_target_pct=0.05,        # 5% maximum
        max_stop_loss_pct=0.01,            # 1% max stop
        max_daily_trades=10,
        cooldown_after_loss_minutes=60,
        daily_loss_limit_pct=0.05,         # 5% daily max loss
        weekly_loss_limit_pct=0.10,        # 10% weekly max loss
        allow_aggressive_entries=True,
        require_high_confidence=True,
        prioritize_stability=False,
    ),
    
    TierLevel.GROWTH: TierConfiguration(
        tier_level=TierLevel.GROWTH,
        min_capital=500.0,
        max_capital=5000.0,
        risk_per_trade_pct=(0.01, 0.02),  # 1-2% per trade
        max_positions=(3, 5),               # 3-5 positions
        aggression_level=0.6,               # Controlled scaling
        diversification_required=True,
        min_symbols_for_full_allocation=3,
        min_profit_target_pct=0.02,        # 2% minimum
        max_profit_target_pct=0.06,        # 6% maximum
        max_stop_loss_pct=0.015,           # 1.5% max stop
        max_daily_trades=15,
        cooldown_after_loss_minutes=45,
        daily_loss_limit_pct=0.04,         # 4% daily max loss
        weekly_loss_limit_pct=0.08,        # 8% weekly max loss
        allow_aggressive_entries=True,
        require_high_confidence=True,
        prioritize_stability=False,
    ),
    
    TierLevel.PRO: TierConfiguration(
        tier_level=TierLevel.PRO,
        min_capital=5000.0,
        max_capital=50000.0,
        risk_per_trade_pct=(0.005, 0.01), # 0.5-1% per trade
        max_positions=(5, 10),              # 5-10 positions
        aggression_level=0.4,               # Capital preservation focus
        diversification_required=True,
        min_symbols_for_full_allocation=5,
        min_profit_target_pct=0.02,        # 2% minimum
        max_profit_target_pct=0.08,        # 8% maximum
        max_stop_loss_pct=0.01,            # 1% max stop
        max_daily_trades=20,
        cooldown_after_loss_minutes=30,
        daily_loss_limit_pct=0.03,         # 3% daily max loss
        weekly_loss_limit_pct=0.06,        # 6% weekly max loss
        allow_aggressive_entries=False,
        require_high_confidence=True,
        prioritize_stability=True,
    ),
    
    TierLevel.INSTITUTIONAL: TierConfiguration(
        tier_level=TierLevel.INSTITUTIONAL,
        min_capital=50000.0,
        max_capital=250000.0,
        risk_per_trade_pct=(0.0025, 0.005), # 0.25-0.5% per trade
        max_positions=(10, 20),              # 10+ positions
        aggression_level=0.2,                # Stability priority
        diversification_required=True,
        min_symbols_for_full_allocation=10,
        min_profit_target_pct=0.025,        # 2.5% minimum
        max_profit_target_pct=0.10,         # 10% maximum
        max_stop_loss_pct=0.008,            # 0.8% max stop
        max_daily_trades=30,
        cooldown_after_loss_minutes=15,
        daily_loss_limit_pct=0.02,          # 2% daily max loss
        weekly_loss_limit_pct=0.04,         # 4% weekly max loss
        allow_aggressive_entries=False,
        require_high_confidence=True,
        prioritize_stability=True,
    ),
}


class CapitalTierSystem:
    """
    Manages capital tier detection, transition, and behavior modification.
    
    Provides dynamic behavior scaling from $50 to $250k+:
    - Automatic tier detection and assignment
    - Tier-specific risk and position parameters
    - Milestone tracking and celebration
    - Smooth tier transitions
    - Behavior modification based on capital size
    """
    
    def __init__(self, initial_balance: float, data_dir: str = "./data"):
        """
        Initialize capital tier system.
        
        Args:
            initial_balance: Starting account balance
            data_dir: Data directory for persistence
        """
        self.current_balance = initial_balance
        self.current_tier = self._detect_tier(initial_balance)
        
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        
        self.milestone_file = self.data_dir / "capital_milestones.json"
        self.tier_history_file = self.data_dir / "tier_history.jsonl"
        
        # Load milestone data
        self.milestones = self._load_milestones()
        
        # Track tier transitions
        self.tier_transition_count = 0
        
        logger.info(
            f"💰 Capital Tier System initialized - "
            f"Balance: ${initial_balance:.2f} | "
            f"Tier: {self.current_tier.value}"
        )
        
        # Log initial tier assignment
        self._log_tier_assignment(initial_balance, self.current_tier, "INITIAL")
    
    def _detect_tier(self, balance: float) -> TierLevel:
        """Detect appropriate tier for given balance"""
        for tier_level, config in TIER_CONFIGURATIONS.items():
            if config.min_capital <= balance <= config.max_capital:
                return tier_level
        
        # Handle edge cases
        if balance < TIER_CONFIGURATIONS[TierLevel.MICRO].min_capital:
            return TierLevel.MICRO
        
        return TierLevel.INSTITUTIONAL
    
    def _load_milestones(self) -> Dict:
        """Load milestone data from disk"""
        if self.milestone_file.exists():
            try:
                with open(self.milestone_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Could not load milestones: {e}")
        
        # Initialize milestones
        milestones = {
            'achieved': [],
            'targets': [100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000, 250000],
            'highest_balance': self.current_balance,
            'tier_upgrades': []
        }
        self._save_milestones(milestones)
        return milestones
    
    def _save_milestones(self, milestones: Dict):
        """Save milestone data to disk"""
        try:
            with open(self.milestone_file, 'w') as f:
                json.dump(milestones, f, indent=2)
        except Exception as e:
            logger.error(f"Could not save milestones: {e}")
    
    def _log_tier_assignment(self, balance: float, tier: TierLevel, reason: str):
        """Log tier assignment to history file"""
        record = {
            'timestamp': datetime.now().isoformat(),
            'balance': balance,
            'tier': tier.value,
            'reason': reason,
        }
        
        try:
            with open(self.tier_history_file, 'a') as f:
                f.write(json.dumps(record) + '\n')
        except Exception as e:
            logger.error(f"Could not log tier assignment: {e}")
    
    def update_balance(self, new_balance: float):
        """
        Update current balance and check for tier transitions.
        
        Args:
            new_balance: New account balance
        """
        old_balance = self.current_balance
        old_tier = self.current_tier
        
        self.current_balance = new_balance
        new_tier = self._detect_tier(new_balance)
        
        # Check for tier transition
        if new_tier != old_tier:
            self._handle_tier_transition(old_tier, new_tier, old_balance, new_balance)
        
        # Check for milestone achievements
        self._check_milestones(new_balance)
        
        # Update highest balance
        if new_balance > self.milestones['highest_balance']:
            self.milestones['highest_balance'] = new_balance
            self._save_milestones(self.milestones)
    
    def _handle_tier_transition(self, old_tier: TierLevel, new_tier: TierLevel,
                                old_balance: float, new_balance: float):
        """Handle tier transition"""
        self.current_tier = new_tier
        self.tier_transition_count += 1
        
        # Determine if upgrade or downgrade
        tier_order = [TierLevel.MICRO, TierLevel.GROWTH, TierLevel.PRO, TierLevel.INSTITUTIONAL]
        old_idx = tier_order.index(old_tier)
        new_idx = tier_order.index(new_tier)
        
        is_upgrade = new_idx > old_idx
        
        # Log transition
        self._log_tier_assignment(
            new_balance, new_tier, 
            f"{'UPGRADE' if is_upgrade else 'DOWNGRADE'}_FROM_{old_tier.value}"
        )
        
        # Record in milestones
        if is_upgrade:
            self.milestones['tier_upgrades'].append({
                'timestamp': datetime.now().isoformat(),
                'from_tier': old_tier.value,
                'to_tier': new_tier.value,
                'balance': new_balance
            })
            self._save_milestones(self.milestones)
        
        # Log celebration or warning
        if is_upgrade:
            logger.info(
                f"\n{'='*60}\n"
                f"🎉 TIER UPGRADE! 🎉\n"
                f"{'='*60}\n"
                f"From: {old_tier.value} (${old_balance:.2f})\n"
                f"To: {new_tier.value} (${new_balance:.2f})\n"
                f"New Capabilities:\n"
                f"  - Max Positions: {self.get_config().max_positions}\n"
                f"  - Risk per Trade: {self.get_config().risk_per_trade_pct[0]:.2%}-{self.get_config().risk_per_trade_pct[1]:.2%}\n"
                f"  - Aggression: {self.get_config().aggression_level:.0%}\n"
                f"{'='*60}\n"
            )
        else:
            logger.warning(
                f"\n{'='*60}\n"
                f"⚠️ TIER DOWNGRADE\n"
                f"{'='*60}\n"
                f"From: {old_tier.value} (${old_balance:.2f})\n"
                f"To: {new_tier.value} (${new_balance:.2f})\n"
                f"Adjusted Parameters:\n"
                f"  - Max Positions: {self.get_config().max_positions}\n"
                f"  - Risk per Trade: {self.get_config().risk_per_trade_pct[0]:.2%}-{self.get_config().risk_per_trade_pct[1]:.2%}\n"
                f"{'='*60}\n"
            )
    
    def _check_milestones(self, balance: float):
        """Check and celebrate milestone achievements"""
        for target in self.milestones['targets']:
            if target not in self.milestones['achieved'] and balance >= target:
                self.milestones['achieved'].append(target)
                self._save_milestones(self.milestones)
                
                logger.info(
                    f"\n{'='*60}\n"
                    f"🏆 MILESTONE ACHIEVED! 🏆\n"
                    f"{'='*60}\n"
                    f"Account Balance: ${balance:.2f}\n"
                    f"Milestone: ${target:,.0f}\n"
                    f"Progress: {len(self.milestones['achieved'])}/{len(self.milestones['targets'])} milestones\n"
                    f"{'='*60}\n"
                )
    
    def get_config(self) -> TierConfiguration:
        """Get configuration for current tier"""
        return TIER_CONFIGURATIONS[self.current_tier]
    
    def get_tier_info(self) -> Dict:
        """Get current tier information"""
        config = self.get_config()
        
        # Calculate position in tier
        tier_progress = 0.0
        if config.max_capital > config.min_capital:
            tier_progress = (self.current_balance - config.min_capital) / \
                          (config.max_capital - config.min_capital)
        
        # Find next milestone
        next_milestone = None
        for target in self.milestones['targets']:
            if target > self.current_balance:
                next_milestone = target
                break
        
        return {
            'tier': self.current_tier.value,
            'balance': self.current_balance,
            'tier_range': f"${config.min_capital:.0f}-${config.max_capital:.0f}",
            'tier_progress_pct': tier_progress,
            'next_milestone': next_milestone,
            'milestones_achieved': len(self.milestones['achieved']),
            'total_milestones': len(self.milestones['targets']),
            'highest_balance': self.milestones['highest_balance'],
            'tier_transitions': self.tier_transition_count,
            'config': {
                'risk_per_trade': config.risk_per_trade_pct,
                'max_positions': config.max_positions,
                'aggression_level': config.aggression_level,
                'max_daily_trades': config.max_daily_trades,
                'daily_loss_limit': config.daily_loss_limit_pct,
                'require_high_confidence': config.require_high_confidence,
                'prioritize_stability': config.prioritize_stability,
            }
        }
    
    def calculate_position_size(self, signal_confidence: float, 
                               available_capital: float) -> float:
        """
        Calculate position size based on tier and confidence.
        
        Args:
            signal_confidence: Signal confidence (0-1)
            available_capital: Available capital for trading
            
        Returns:
            Position size in USD
        """
        config = self.get_config()
        
        # Get tier-recommended risk
        risk_pct = config.get_recommended_risk_pct(signal_confidence)
        
        # Calculate position size
        position_size = available_capital * risk_pct
        
        return position_size
    
    def should_accept_signal(self, confidence: float, quality_score: float) -> Tuple[bool, str]:
        """
        Determine if signal should be accepted based on tier requirements.
        
        Args:
            confidence: Signal confidence (0-1)
            quality_score: Signal quality (0-100)
            
        Returns:
            (should_accept, reason)
        """
        config = self.get_config()
        
        # High confidence requirement check
        if config.require_high_confidence and confidence < 0.65:
            return False, f"Tier {self.current_tier.value} requires high confidence (≥65%)"
        
        # Stability priority check (stricter quality requirements)
        if config.prioritize_stability and quality_score < 75:
            return False, f"Tier {self.current_tier.value} prioritizes stability (quality ≥75)"
        
        # Aggression level check (lower aggression = stricter requirements)
        min_confidence = 0.5 + (0.2 * (1.0 - config.aggression_level))
        if confidence < min_confidence:
            return False, f"Confidence {confidence:.0%} below tier threshold {min_confidence:.0%}"
        
        return True, "OK"
    
    def print_status(self):
        """Print tier status"""
        info = self.get_tier_info()
        config = self.get_config()
        
        logger.info(f"\n{'='*60}")
        logger.info(f"💰 CAPITAL TIER STATUS")
        logger.info(f"{'='*60}")
        logger.info(f"Current Tier: {info['tier']}")
        logger.info(f"Balance: ${info['balance']:.2f}")
        logger.info(f"Tier Range: {info['tier_range']}")
        logger.info(f"Tier Progress: {info['tier_progress_pct']:.0%}")
        
        if info['next_milestone']:
            progress_to_milestone = (info['balance'] / info['next_milestone']) * 100
            logger.info(f"Next Milestone: ${info['next_milestone']:,.0f} ({progress_to_milestone:.1f}%)")
        
        logger.info(f"Milestones: {info['milestones_achieved']}/{info['total_milestones']}")
        logger.info(f"Highest Balance: ${info['highest_balance']:.2f}")
        
        logger.info(f"\nTier Configuration:")
        logger.info(f"  Max Positions: {config.max_positions[0]}-{config.max_positions[1]}")
        logger.info(f"  Risk per Trade: {config.risk_per_trade_pct[0]:.2%}-{config.risk_per_trade_pct[1]:.2%}")
        logger.info(f"  Aggression: {config.aggression_level:.0%}")
        logger.info(f"  Max Daily Trades: {config.max_daily_trades}")
        logger.info(f"  Daily Loss Limit: {config.daily_loss_limit_pct:.1%}")
        logger.info(f"  High Confidence Required: {config.require_high_confidence}")
        logger.info(f"  Stability Priority: {config.prioritize_stability}")
        
        logger.info(f"{'='*60}\n")


# Global instance
_capital_tier_system = None


def get_capital_tier_system(balance: float) -> CapitalTierSystem:
    """Get or create capital tier system instance"""
    global _capital_tier_system
    if _capital_tier_system is None:
        _capital_tier_system = CapitalTierSystem(balance)
    else:
        _capital_tier_system.update_balance(balance)
    return _capital_tier_system
