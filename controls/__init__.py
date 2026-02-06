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
7. LIVE CAPITAL VERIFIED - Explicit verification required for live trading
"""

import logging
import os
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
    
    # ABSOLUTE MAXIMUM POSITION SIZE (UNBYPASABLE)
    # This is a fail-safe that cannot be overridden under any circumstances
    # Even if other checks fail, this prevents catastrophic position sizes
    ABSOLUTE_MAX_POSITION_PCT = 0.15  # 15% absolute hard cap
    ABSOLUTE_MAX_POSITION_USD = 10000.0  # $10,000 absolute hard cap
    
    # Position validation tracking for audit trail
    _position_validations: List[Dict[str, any]] = []

    def __init__(self):
        self.global_kill_switch = KillSwitchStatus.ACTIVE
        self.user_kill_switches: Dict[str, KillSwitchStatus] = {}
        self.daily_loss_trackers: Dict[str, DailyLossTracker] = {}
        self.user_error_counts: Dict[str, int] = {}
        self.strategy_locked = True  # Strategy is always locked

        # CRITICAL SAFETY: LIVE CAPITAL VERIFIED kill-switch
        # This is the MASTER safety switch that must be explicitly enabled
        # to allow live trading with real capital. Defaults to False (disabled).
        # Set LIVE_CAPITAL_VERIFIED=true in .env to enable live trading.
        self.live_capital_verified = self._check_live_capital_verification()

        # Enable trading for platform account and all user accounts
        self._initialize_trading_accounts()

        logger.info("Hard controls initialized")
        logger.info(f"Position limits: {self.MIN_POSITION_PCT*100:.0f}% - {self.MAX_POSITION_PCT*100:.0f}%")
        logger.info(f"ABSOLUTE MAX: {self.ABSOLUTE_MAX_POSITION_PCT*100:.0f}% or ${self.ABSOLUTE_MAX_POSITION_USD:.0f} (UNBYPASABLE)")

        # Log verification status prominently
        if self.live_capital_verified:
            logger.warning("=" * 80)
            logger.warning("🔴 LIVE CAPITAL VERIFIED: TRUE - REAL MONEY TRADING ENABLED")
            logger.warning("=" * 80)
        else:
            logger.info("=" * 80)
            logger.info("🟢 LIVE CAPITAL VERIFIED: FALSE - TRADING DISABLED (SAFE MODE)")
            logger.info("   To enable live trading, set LIVE_CAPITAL_VERIFIED=true in .env")
            logger.info("=" * 80)

    def _initialize_trading_accounts(self):
        """
        Initialize trading accounts with ACTIVE status.
        Enables trading for platform account and all configured user accounts.
        Dynamically loads users from configuration files.
        """
        # Enable platform account
        self.user_kill_switches['platform'] = KillSwitchStatus.ACTIVE
        logger.info("✅ Platform account trading ENABLED")

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

    def _check_live_capital_verification(self) -> bool:
        """
        Check if LIVE CAPITAL VERIFIED is enabled.

        This is the MASTER kill-switch that must be explicitly set to 'true'
        in the environment variables to allow live trading.

        Returns:
            bool: True if live capital trading is verified and enabled
        """
        # Check environment variable (must be explicitly set to 'true')
        verified_str = os.getenv('LIVE_CAPITAL_VERIFIED', 'false').lower().strip()

        # Only accept explicit 'true', '1', 'yes', or 'enabled'
        verified = verified_str in ['true', '1', 'yes', 'enabled']

        return verified

    def _log_fallback_to_master(self, reason: str):
        """Log warning message when falling back to master-only mode."""
        logger.warning(f"⚠️  {reason}")
        logger.warning("   Continuing with platform account only")
        logger.info(f"📊 Total accounts enabled for trading: {len(self.user_kill_switches)}")

    def validate_position_size(
        self,
        user_id: str,
        position_size_usd: float,
        account_balance: float,
        symbol: Optional[str] = None,
        log_to_audit: bool = True
    ) -> tuple[bool, Optional[str]]:
        """
        Validate position size against hard limits with UNBYPASABLE fail-safe.
        
        This method enforces THREE layers of protection:
        1. Standard limits (2-10%)
        2. Absolute percentage cap (15%)
        3. Absolute USD cap ($10,000)
        
        ALL THREE must pass. No exceptions, no overrides.

        Args:
            user_id: User identifier
            position_size_usd: Requested position size in USD
            account_balance: User's account balance
            symbol: Trading symbol (for audit logging)
            log_to_audit: Whether to log to audit trail

        Returns:
            (is_valid, error_message)
        """
        # Calculate position percentage
        if account_balance <= 0:
            rejection_reason = "Invalid account balance"
            self._log_position_validation(user_id, symbol, position_size_usd,
                                          account_balance, False, rejection_reason)
            return False, rejection_reason

        position_pct = position_size_usd / account_balance

        # LAYER 1: Check minimum
        if position_pct < self.MIN_POSITION_PCT:
            min_usd = account_balance * self.MIN_POSITION_PCT
            rejection_reason = f"Position too small: ${position_size_usd:.2f} (minimum ${min_usd:.2f}, {self.MIN_POSITION_PCT*100:.0f}%)"
            self._log_position_validation(user_id, symbol, position_size_usd,
                                          account_balance, False, rejection_reason)
            return False, rejection_reason

        # LAYER 2: Check standard maximum
        if position_pct > self.MAX_POSITION_PCT:
            max_usd = account_balance * self.MAX_POSITION_PCT
            rejection_reason = f"Position too large: ${position_size_usd:.2f} (maximum ${max_usd:.2f}, {self.MAX_POSITION_PCT*100:.0f}%)"
            self._log_position_validation(user_id, symbol, position_size_usd,
                                          account_balance, False, rejection_reason)
            return False, rejection_reason
        
        # LAYER 3: ABSOLUTE PERCENTAGE CAP (UNBYPASABLE)
        if position_pct > self.ABSOLUTE_MAX_POSITION_PCT:
            rejection_reason = (f"🚨 ABSOLUTE MAXIMUM EXCEEDED: {position_pct*100:.2f}% "
                              f"(hard cap: {self.ABSOLUTE_MAX_POSITION_PCT*100:.0f}%) - "
                              f"THIS LIMIT CANNOT BE BYPASSED")
            logger.critical(rejection_reason)
            self._log_position_validation(user_id, symbol, position_size_usd,
                                          account_balance, False, rejection_reason,
                                          enforced_limit="ABSOLUTE_MAX_POSITION_PCT")
            return False, rejection_reason
        
        # LAYER 4: ABSOLUTE USD CAP (UNBYPASABLE)
        if position_size_usd > self.ABSOLUTE_MAX_POSITION_USD:
            rejection_reason = (f"🚨 ABSOLUTE USD MAXIMUM EXCEEDED: ${position_size_usd:.2f} "
                              f"(hard cap: ${self.ABSOLUTE_MAX_POSITION_USD:.0f}) - "
                              f"THIS LIMIT CANNOT BE BYPASSED")
            logger.critical(rejection_reason)
            self._log_position_validation(user_id, symbol, position_size_usd,
                                          account_balance, False, rejection_reason,
                                          enforced_limit="ABSOLUTE_MAX_POSITION_USD")
            return False, rejection_reason

        # All checks passed
        self._log_position_validation(user_id, symbol, position_size_usd,
                                      account_balance, True, None)
        return True, None
    
    def _log_position_validation(
        self,
        user_id: str,
        symbol: Optional[str],
        position_size_usd: float,
        account_balance: float,
        approved: bool,
        rejection_reason: Optional[str],
        enforced_limit: Optional[str] = None
    ) -> None:
        """
        Log position validation to audit trail.
        
        Args:
            user_id: User identifier
            symbol: Trading symbol
            position_size_usd: Requested position size
            account_balance: Account balance
            approved: Whether validation passed
            rejection_reason: Reason if rejected
            enforced_limit: Which limit was enforced
        """
        validation_record = {
            'timestamp': datetime.now().isoformat(),
            'user_id': user_id,
            'symbol': symbol,
            'position_size_usd': position_size_usd,
            'account_balance': account_balance,
            'position_pct': (position_size_usd / account_balance * 100) if account_balance > 0 else 0,
            'approved': approved,
            'rejection_reason': rejection_reason,
            'enforced_limit': enforced_limit,
        }
        
        # Add to internal tracking (limited to last 1000 validations)
        self._position_validations.append(validation_record)
        if len(self._position_validations) > 1000:
            self._position_validations.pop(0)
        
        # Log to audit logger if available
        try:
            from bot.trading_audit_logger import get_audit_logger
            audit_logger = get_audit_logger()
            audit_logger.log_position_validation(
                user_id=user_id,
                symbol=symbol or "UNKNOWN",
                requested_size_usd=position_size_usd,
                account_balance_usd=account_balance,
                is_approved=approved,
                rejection_reason=rejection_reason,
                enforced_limit=enforced_limit
            )
        except ImportError:
            # Audit logger not available - validation still recorded internally
            pass

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
        # CRITICAL: Check LIVE CAPITAL VERIFIED first (master kill-switch)
        if not self.live_capital_verified:
            return False, "🔴 LIVE CAPITAL VERIFIED: FALSE - Trading disabled. Set LIVE_CAPITAL_VERIFIED=true in .env to enable live trading."

        # Check global kill switch
        if self.global_kill_switch == KillSwitchStatus.TRIGGERED:
            return False, "Global trading halted (kill switch triggered)"

        # Check user kill switch
        if user_id in self.user_kill_switches:
            if self.user_kill_switches[user_id] == KillSwitchStatus.TRIGGERED:
                return False, "User trading halted (kill switch triggered)"

        return True, None

    def record_api_error(self, user_id: str, error_type: str = "general") -> bool:
        """
        Record API error and auto-disable if threshold exceeded.

        Args:
            user_id: User identifier
            error_type: Type of error (general, nonce, auth, connection)

        Returns:
            bool: True if user should be disabled
        """
        if user_id not in self.user_error_counts:
            self.user_error_counts[user_id] = 0

        self.user_error_counts[user_id] += 1
        error_count = self.user_error_counts[user_id]

        # Log the error with type
        logger.warning(f"⚠️  API error for user {user_id}: {error_type} (count: {error_count}/{self.ERROR_THRESHOLD})")

        if error_count >= self.ERROR_THRESHOLD:
            self.trigger_user_kill_switch(
                user_id,
                f"Excessive API errors ({error_count}): {error_type}"
            )
            logger.critical(f"🚨 AUTO-DISABLED user {user_id} due to {error_count} {error_type} errors")
            return True

        return False

    def reset_error_count(self, user_id: str):
        """Reset error count for user."""
        self.user_error_counts[user_id] = 0
        logger.info(f"Reset error count for user {user_id}")

    def is_strategy_locked(self) -> bool:
        """Check if strategy modification is locked."""
        return self.strategy_locked

    def is_live_capital_verified(self) -> bool:
        """
        Check if LIVE CAPITAL VERIFIED is enabled.

        Returns:
            bool: True if live capital trading is verified and enabled
        """
        return self.live_capital_verified

    def get_verification_status(self) -> Dict[str, any]:
        """
        Get detailed verification status for dashboard display.

        Returns:
            Dict with verification details
        """
        return {
            'live_capital_verified': self.live_capital_verified,
            'global_kill_switch': self.global_kill_switch.value,
            'can_trade': self.live_capital_verified and self.global_kill_switch == KillSwitchStatus.ACTIVE,
            'env_var_name': 'LIVE_CAPITAL_VERIFIED',
            'env_var_value': os.getenv('LIVE_CAPITAL_VERIFIED', 'not set'),
        }

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
    
    def get_position_validation_history(
        self,
        user_id: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, any]]:
        """
        Get recent position validation history for audit purposes.
        
        Args:
            user_id: Filter by user ID (None for all users)
            limit: Maximum number of records to return
        
        Returns:
            List of validation records
        """
        # Filter by user if specified
        if user_id:
            filtered = [v for v in self._position_validations if v['user_id'] == user_id]
        else:
            filtered = self._position_validations
        
        # Return most recent records
        return filtered[-limit:] if len(filtered) > limit else filtered
    
    def get_rejection_stats(self, user_id: Optional[str] = None) -> Dict[str, any]:
        """
        Get statistics on position validation rejections.
        
        Args:
            user_id: Filter by user ID (None for all users)
        
        Returns:
            Dict with rejection statistics
        """
        # Get relevant validations
        if user_id:
            validations = [v for v in self._position_validations if v['user_id'] == user_id]
        else:
            validations = self._position_validations
        
        if not validations:
            return {
                'total_validations': 0,
                'approved': 0,
                'rejected': 0,
                'rejection_rate': 0.0,
                'rejection_reasons': {},
            }
        
        approved = sum(1 for v in validations if v['approved'])
        rejected = sum(1 for v in validations if not v['approved'])
        
        # Count rejection reasons
        rejection_reasons = {}
        for v in validations:
            if not v['approved'] and v['rejection_reason']:
                # Extract key reason (first few words)
                reason_key = v['rejection_reason'].split(':')[0]
                rejection_reasons[reason_key] = rejection_reasons.get(reason_key, 0) + 1
        
        return {
            'total_validations': len(validations),
            'approved': approved,
            'rejected': rejected,
            'rejection_rate': (rejected / len(validations) * 100) if validations else 0,
            'rejection_reasons': rejection_reasons,
        }


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
