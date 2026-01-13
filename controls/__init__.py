"""
NIJA Hard Controls - Risk Protection System

Implements mandatory safety controls that protect both users and the platform.
These controls CANNOT be disabled or bypassed by users.

Hard Controls:
1. Max % per trade (2-10%)
2. Daily loss limits
3. Global kill switch
4. Per-user kill switch
5. Strategy locking (users cannot modify core logic)
6. Auto-disable on errors/API abuse
"""

import logging
from typing import Dict, Optional, List
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger("nija.controls")


class KillSwitchStatus(Enum):
    """Kill switch status."""
    ACTIVE = "active"
    TRIGGERED = "triggered"
    DISABLED = "disabled"


@dataclass
class DailyLossTracker:
    """Tracks daily losses for a user."""
    user_id: str
    date: datetime
    total_loss_usd: float = 0.0
    trade_count: int = 0
    last_trade_time: Optional[datetime] = None
    
    def reset_if_new_day(self):
        """Reset tracker if it's a new day."""
        if self.date.date() != datetime.now().date():
            self.date = datetime.now()
            self.total_loss_usd = 0.0
            self.trade_count = 0
            self.last_trade_time = None
            logger.info(f"Reset daily loss tracker for user {self.user_id}")
    
    def record_loss(self, loss_usd: float):
        """Record a loss."""
        self.reset_if_new_day()
        self.total_loss_usd += loss_usd
        self.trade_count += 1
        self.last_trade_time = datetime.now()


class HardControls:
    """
    Enforces mandatory safety controls.
    These controls protect users and the platform from excessive losses.
    """
    
    # Hard-coded limits (cannot be changed by users)
    MIN_POSITION_PCT = 0.02   # 2% minimum per trade
    MAX_POSITION_PCT = 0.10   # 10% maximum per trade
    MAX_DAILY_TRADES = 50     # Maximum trades per day per user
    ERROR_THRESHOLD = 5       # Max API errors before auto-disable
    
    def __init__(self):
        self.global_kill_switch = KillSwitchStatus.ACTIVE
        self.user_kill_switches: Dict[str, KillSwitchStatus] = {}
        self.daily_loss_trackers: Dict[str, DailyLossTracker] = {}
        self.user_error_counts: Dict[str, int] = {}
        self.strategy_locked = True  # Strategy is always locked
        
        # Enable trading for master account and all user accounts
        self._initialize_trading_accounts()
        
        logger.info("Hard controls initialized")
        logger.info(f"Position limits: {self.MIN_POSITION_PCT*100:.0f}% - {self.MAX_POSITION_PCT*100:.0f}%")
    
    def _initialize_trading_accounts(self):
        """
        Initialize trading accounts with ACTIVE status.
        Enables trading for master account and all configured user accounts.
        Dynamically loads users from configuration files.
        """
        # Enable master account
        self.user_kill_switches['master'] = KillSwitchStatus.ACTIVE
        logger.info("✅ Master account trading ENABLED")
        
        # Dynamically load and enable all configured user accounts
        try:
            from config import get_user_config_loader
            
            # Check if user config loader is available
            # (will be None if config.user_loader module failed to import)
            if get_user_config_loader is None or not callable(get_user_config_loader):
                self._log_fallback_to_master("User config loader module not available")
                return
            
            # Get the singleton loader instance
            # Note: The singleton loads users on first access via load_all_users()
            loader = get_user_config_loader()
            
            # Get all enabled users and deduplicate by user_id
            # Users may appear multiple times if they have accounts on multiple brokers
            # (e.g., tania_gilbert has both Kraken and Alpaca accounts)
            # We keep the first occurrence of each unique user_id
            enabled_users = loader.get_all_enabled_users()
            seen_user_ids = set()
            
            for user in enabled_users:
                if user.user_id not in seen_user_ids:
                    seen_user_ids.add(user.user_id)
                    self.user_kill_switches[user.user_id] = KillSwitchStatus.ACTIVE
                    logger.info(f"✅ User account '{user.user_id}' ({user.name}) trading ENABLED")
            
            if not enabled_users:
                logger.info("ℹ️  No user accounts configured in config files")
        
        except ImportError as e:
            self._log_fallback_to_master(f"Could not import user config loader: {e}")
        except (FileNotFoundError, OSError) as e:
            self._log_fallback_to_master(f"Config files not accessible: {e}")
        except Exception as e:
            self._log_fallback_to_master(f"Unexpected error loading user accounts: {e}")
        
        logger.info(f"📊 Total accounts enabled for trading: {len(self.user_kill_switches)}")
    
    def _log_fallback_to_master(self, reason: str):
        """Log warning message when falling back to master-only mode."""
        logger.warning(f"⚠️  {reason}")
        logger.warning("   Continuing with master account only")
        logger.info(f"📊 Total accounts enabled for trading: {len(self.user_kill_switches)}")
    
    def validate_position_size(
        self,
        user_id: str,
        position_size_usd: float,
        account_balance: float
    ) -> tuple[bool, Optional[str]]:
        """
        Validate position size against hard limits.
        
        Args:
            user_id: User identifier
            position_size_usd: Requested position size in USD
            account_balance: User's account balance
            
        Returns:
            (is_valid, error_message)
        """
        # Calculate position percentage
        if account_balance <= 0:
            return False, "Invalid account balance"
        
        position_pct = position_size_usd / account_balance
        
        # Check minimum
        if position_pct < self.MIN_POSITION_PCT:
            min_usd = account_balance * self.MIN_POSITION_PCT
            return False, f"Position too small: ${position_size_usd:.2f} (minimum ${min_usd:.2f}, {self.MIN_POSITION_PCT*100:.0f}%)"
        
        # Check maximum
        if position_pct > self.MAX_POSITION_PCT:
            max_usd = account_balance * self.MAX_POSITION_PCT
            return False, f"Position too large: ${position_size_usd:.2f} (maximum ${max_usd:.2f}, {self.MAX_POSITION_PCT*100:.0f}%)"
        
        return True, None
    
    def check_daily_loss_limit(
        self,
        user_id: str,
        max_daily_loss_usd: float
    ) -> tuple[bool, Optional[str]]:
        """
        Check if user has exceeded daily loss limit.
        
        Args:
            user_id: User identifier
            max_daily_loss_usd: Maximum daily loss allowed
            
        Returns:
            (can_trade, error_message)
        """
        if user_id not in self.daily_loss_trackers:
            self.daily_loss_trackers[user_id] = DailyLossTracker(
                user_id=user_id,
                date=datetime.now()
            )
        
        tracker = self.daily_loss_trackers[user_id]
        tracker.reset_if_new_day()
        
        if tracker.total_loss_usd >= max_daily_loss_usd:
            return False, f"Daily loss limit reached: ${tracker.total_loss_usd:.2f} / ${max_daily_loss_usd:.2f}"
        
        return True, None
    
    def check_daily_trade_limit(self, user_id: str) -> tuple[bool, Optional[str]]:
        """
        Check if user has exceeded daily trade limit.
        
        Args:
            user_id: User identifier
            
        Returns:
            (can_trade, error_message)
        """
        if user_id not in self.daily_loss_trackers:
            return True, None
        
        tracker = self.daily_loss_trackers[user_id]
        tracker.reset_if_new_day()
        
        if tracker.trade_count >= self.MAX_DAILY_TRADES:
            return False, f"Daily trade limit reached: {tracker.trade_count} / {self.MAX_DAILY_TRADES}"
        
        return True, None
    
    def trigger_global_kill_switch(self, reason: str):
        """
        Trigger global kill switch (stops all trading).
        
        Args:
            reason: Reason for triggering kill switch
        """
        self.global_kill_switch = KillSwitchStatus.TRIGGERED
        logger.critical(f"🚨 GLOBAL KILL SWITCH TRIGGERED: {reason}")
    
    def trigger_user_kill_switch(self, user_id: str, reason: str):
        """
        Trigger kill switch for specific user.
        
        Args:
            user_id: User identifier
            reason: Reason for triggering kill switch
        """
        self.user_kill_switches[user_id] = KillSwitchStatus.TRIGGERED
        logger.warning(f"🚨 User {user_id} kill switch triggered: {reason}")
    
    def reset_global_kill_switch(self):
        """Reset global kill switch (requires manual intervention)."""
        self.global_kill_switch = KillSwitchStatus.ACTIVE
        logger.info("Global kill switch reset")
    
    def reset_user_kill_switch(self, user_id: str):
        """Reset user kill switch."""
        self.user_kill_switches[user_id] = KillSwitchStatus.ACTIVE
        logger.info(f"User {user_id} kill switch reset")
    
    def can_trade(self, user_id: str) -> tuple[bool, Optional[str]]:
        """
        Check if user can trade (checks all kill switches).
        
        Args:
            user_id: User identifier
            
        Returns:
            (can_trade, error_message)
        """
        # Check global kill switch
        if self.global_kill_switch == KillSwitchStatus.TRIGGERED:
            return False, "Global trading halted (kill switch triggered)"
        
        # Check user kill switch
        if user_id in self.user_kill_switches:
            if self.user_kill_switches[user_id] == KillSwitchStatus.TRIGGERED:
                return False, "User trading halted (kill switch triggered)"
        
        return True, None
    
    def record_api_error(self, user_id: str) -> bool:
        """
        Record API error and auto-disable if threshold exceeded.
        
        Args:
            user_id: User identifier
            
        Returns:
            bool: True if user should be disabled
        """
        if user_id not in self.user_error_counts:
            self.user_error_counts[user_id] = 0
        
        self.user_error_counts[user_id] += 1
        
        if self.user_error_counts[user_id] >= self.ERROR_THRESHOLD:
            self.trigger_user_kill_switch(
                user_id,
                f"Excessive API errors ({self.user_error_counts[user_id]})"
            )
            return True
        
        return False
    
    def reset_error_count(self, user_id: str):
        """Reset error count for user."""
        self.user_error_counts[user_id] = 0
        logger.info(f"Reset error count for user {user_id}")
    
    def is_strategy_locked(self) -> bool:
        """Check if strategy modification is locked."""
        return self.strategy_locked
    
    def record_trade_loss(self, user_id: str, loss_usd: float):
        """
        Record a trade loss for daily tracking.
        
        Args:
            user_id: User identifier
            loss_usd: Loss amount in USD (positive number)
        """
        if user_id not in self.daily_loss_trackers:
            self.daily_loss_trackers[user_id] = DailyLossTracker(
                user_id=user_id,
                date=datetime.now()
            )
        
        self.daily_loss_trackers[user_id].record_loss(loss_usd)


# Global hard controls instance
_hard_controls = HardControls()


def get_hard_controls() -> HardControls:
    """Get global hard controls instance."""
    return _hard_controls


__all__ = [
    'HardControls',
    'KillSwitchStatus',
    'DailyLossTracker',
    'get_hard_controls',
]
