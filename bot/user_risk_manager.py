"""
NIJA User Risk Manager
======================

Per-user risk management with configurable limits.

Features:
- Individual risk limits per user
- Position size caps
- Daily loss limits
- Maximum drawdown tracking
- Risk level monitoring
"""

import os
import json
import logging
import threading
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict

logger = logging.getLogger('nija.risk')

# Data directory for risk config files
_data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


@dataclass
class UserRiskLimits:
    """Risk limits for a user."""
    user_id: str

    # Position sizing - UPDATED Jan 21, 2026: OPTION 2 (20% max for better trade sizing)
    max_position_pct: float = 0.20  # 20% max per trade (increased from 10%)
    min_position_pct: float = 0.02  # 2% min per trade
    max_open_positions: int = 5     # Max concurrent positions

    # Loss limits
    max_daily_loss_usd: float = 100.0    # Max daily loss in USD
    max_daily_loss_pct: float = 0.05     # Max daily loss as % of balance (5%)
    max_weekly_loss_usd: float = 500.0   # Max weekly loss
    max_drawdown_pct: float = 0.15       # Max drawdown from peak (15%)

    # Trade limits
    max_daily_trades: int = 20           # Max trades per day
    max_leverage: float = 1.0            # Leverage (1.0 = no leverage)

    # Circuit breaker
    circuit_breaker_loss_pct: float = 0.03  # Halt trading at 3% daily loss

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'UserRiskLimits':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class UserRiskState:
    """Current risk state for a user."""
    user_id: str
    balance: float = 0.0
    peak_balance: float = 0.0

    # Daily tracking
    daily_pnl: float = 0.0
    daily_trades: int = 0
    daily_losses: float = 0.0
    last_trade_date: Optional[str] = None

    # Weekly tracking
    weekly_pnl: float = 0.0
    weekly_start_date: Optional[str] = None

    # Drawdown
    current_drawdown_pct: float = 0.0

    # Circuit breaker
    circuit_breaker_triggered: bool = False

    def reset_if_new_day(self):
        """Reset daily stats if it's a new day."""
        today = datetime.now().date().isoformat()

        if self.last_trade_date != today:
            self.daily_pnl = 0.0
            self.daily_trades = 0
            self.daily_losses = 0.0
            self.last_trade_date = today
            self.circuit_breaker_triggered = False

    def reset_if_new_week(self):
        """Reset weekly stats if it's a new week."""
        now = datetime.now()
        week_start = (now - timedelta(days=now.weekday())).date().isoformat()

        if self.weekly_start_date != week_start:
            self.weekly_pnl = 0.0
            self.weekly_start_date = week_start


class UserRiskManager:
    """
    Manages risk limits and state for individual users.

    Each user has their own risk profile with configurable limits.
    Automatically tracks and enforces risk constraints.
    """

    def __init__(self):
        """Initialize the user risk manager."""
        # Per-user locks for thread-safety
        self._user_locks: Dict[str, threading.Lock] = {}

        # Per-user risk limits
        self._user_limits: Dict[str, UserRiskLimits] = {}

        # Per-user risk state
        self._user_states: Dict[str, UserRiskState] = {}

        # Global lock for manager initialization
        self._manager_lock = threading.Lock()

        # Ensure data directory exists
        os.makedirs(_data_dir, exist_ok=True)

        logger.info("UserRiskManager initialized")

    def _get_limits_file(self, user_id: str) -> str:
        """Get the limits file path for a user."""
        safe_user_id = user_id.replace('/', '_').replace('\\', '_')
        return os.path.join(_data_dir, f"risk_limits_{safe_user_id}.json")

    def _get_state_file(self, user_id: str) -> str:
        """Get the state file path for a user."""
        safe_user_id = user_id.replace('/', '_').replace('\\', '_')
        return os.path.join(_data_dir, f"risk_state_{safe_user_id}.json")

    def _get_user_lock(self, user_id: str) -> threading.Lock:
        """Get or create a lock for a user."""
        with self._manager_lock:
            if user_id not in self._user_locks:
                self._user_locks[user_id] = threading.Lock()
            return self._user_locks[user_id]

    def _load_limits(self, user_id: str) -> UserRiskLimits:
        """Load risk limits from file or create defaults."""
        limits_file = self._get_limits_file(user_id)

        if os.path.exists(limits_file):
            try:
                with open(limits_file, 'r') as f:
                    data = json.load(f)
                    return UserRiskLimits.from_dict(data)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not load risk limits for {user_id}: {e}, using defaults")

        # Return defaults
        return UserRiskLimits(user_id=user_id)

    def _save_limits(self, limits: UserRiskLimits):
        """Save risk limits to file."""
        limits_file = self._get_limits_file(limits.user_id)

        try:
            temp_file = limits_file + '.tmp'
            with open(temp_file, 'w') as f:
                json.dump(limits.to_dict(), f, indent=2)
            os.replace(temp_file, limits_file)
        except IOError as e:
            logger.error(f"Could not save risk limits for {limits.user_id}: {e}")

    def _load_state(self, user_id: str) -> UserRiskState:
        """Load risk state from file or create new."""
        state_file = self._get_state_file(user_id)

        if os.path.exists(state_file):
            try:
                with open(state_file, 'r') as f:
                    data = json.load(f)
                    return UserRiskState(**data)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not load risk state for {user_id}: {e}, creating new")

        # Return new state
        return UserRiskState(user_id=user_id)

    def _save_state(self, state: UserRiskState):
        """Save risk state to file."""
        state_file = self._get_state_file(state.user_id)

        try:
            temp_file = state_file + '.tmp'
            with open(temp_file, 'w') as f:
                json.dump(asdict(state), f, indent=2)
            os.replace(temp_file, state_file)
        except IOError as e:
            logger.error(f"Could not save risk state for {state.user_id}: {e}")

    def get_limits(self, user_id: str) -> UserRiskLimits:
        """
        Get risk limits for a user.

        Args:
            user_id: User identifier

        Returns:
            UserRiskLimits: User's risk limits
        """
        lock = self._get_user_lock(user_id)

        with lock:
            if user_id not in self._user_limits:
                self._user_limits[user_id] = self._load_limits(user_id)
            return self._user_limits[user_id]

    def update_limits(self, user_id: str, **kwargs):
        """
        Update risk limits for a user.

        Args:
            user_id: User identifier
            **kwargs: Limit fields to update
        """
        lock = self._get_user_lock(user_id)

        with lock:
            limits = self.get_limits(user_id)

            # Update fields
            for key, value in kwargs.items():
                if hasattr(limits, key):
                    setattr(limits, key, value)

            # Save
            self._save_limits(limits)

            logger.info(f"Updated risk limits for {user_id}: {kwargs}")

    def update_balance(self, user_id: str, balance: float):
        """
        Update user's balance and calculate drawdown.

        Args:
            user_id: User identifier
            balance: Current balance
        """
        lock = self._get_user_lock(user_id)

        with lock:
            if user_id not in self._user_states:
                self._user_states[user_id] = self._load_state(user_id)

            state = self._user_states[user_id]
            state.balance = balance

            # Update peak
            if balance > state.peak_balance:
                state.peak_balance = balance

            # Calculate drawdown
            if state.peak_balance > 0:
                state.current_drawdown_pct = ((state.peak_balance - balance) / state.peak_balance) * 100

            self._save_state(state)

    def record_trade(self, user_id: str, pnl_usd: float):
        """
        Record a trade and update risk state.

        Args:
            user_id: User identifier
            pnl_usd: Trade PnL in USD
        """
        lock = self._get_user_lock(user_id)

        with lock:
            if user_id not in self._user_states:
                self._user_states[user_id] = self._load_state(user_id)

            state = self._user_states[user_id]

            # Reset if new day/week
            state.reset_if_new_day()
            state.reset_if_new_week()

            # Update daily stats
            state.daily_pnl += pnl_usd
            state.daily_trades += 1
            if pnl_usd < 0:
                state.daily_losses += abs(pnl_usd)

            # Update weekly stats
            state.weekly_pnl += pnl_usd

            # Check circuit breaker
            limits = self.get_limits(user_id)
            if state.balance > 0:
                daily_loss_pct = (state.daily_losses / state.balance) * 100
                if daily_loss_pct >= limits.circuit_breaker_loss_pct * 100:
                    state.circuit_breaker_triggered = True
                    logger.warning(f"🚨 Circuit breaker triggered for {user_id}: {daily_loss_pct:.2f}% daily loss")

            self._save_state(state)

    def _check_position_limit(self, user_id: str, current_position_count: int, limits: UserRiskLimits) -> Tuple[bool, Optional[str]]:
        """
        Helper method to check position count limit.
        
        Args:
            user_id: User identifier
            current_position_count: Current number of open positions
            limits: User's risk limits
        
        Returns:
            (allowed, error_message)
        """
        if current_position_count >= limits.max_open_positions:
            return False, f"Position limit reached ({current_position_count}/{limits.max_open_positions})"
        return True, None
    
    def can_trade(self, user_id: str, position_size_usd: float, current_position_count: int = 0) -> Tuple[bool, Optional[str]]:
        """
        Check if user can place a trade.

        Args:
            user_id: User identifier
            position_size_usd: Requested position size
            current_position_count: Current number of open positions

        Returns:
            (can_trade, error_message)
        """
        lock = self._get_user_lock(user_id)

        with lock:
            limits = self.get_limits(user_id)

            if user_id not in self._user_states:
                self._user_states[user_id] = self._load_state(user_id)

            state = self._user_states[user_id]
            state.reset_if_new_day()
            state.reset_if_new_week()

            # Check circuit breaker
            if state.circuit_breaker_triggered:
                return False, "Circuit breaker triggered (daily loss limit)"

            # Check position count limit (HARD CAP) - using helper method
            allowed, error = self._check_position_limit(user_id, current_position_count, limits)
            if not allowed:
                return False, error

            # Check daily trade limit
            if state.daily_trades >= limits.max_daily_trades:
                return False, f"Daily trade limit reached ({limits.max_daily_trades})"

            # Check position size
            if state.balance > 0:
                position_pct = (position_size_usd / state.balance) * 100

                if position_pct > limits.max_position_pct * 100:
                    return False, f"Position too large: {position_pct:.1f}% (max {limits.max_position_pct*100:.0f}%)"

                if position_pct < limits.min_position_pct * 100:
                    return False, f"Position too small: {position_pct:.1f}% (min {limits.min_position_pct*100:.0f}%)"

            # Check daily loss limit (USD)
            if state.daily_losses >= limits.max_daily_loss_usd:
                return False, f"Daily loss limit reached: ${state.daily_losses:.2f}"

            # Check daily loss limit (%)
            if state.balance > 0:
                daily_loss_pct = (state.daily_losses / state.balance) * 100
                if daily_loss_pct >= limits.max_daily_loss_pct * 100:
                    return False, f"Daily loss % limit reached: {daily_loss_pct:.1f}%"

            # Check weekly loss limit
            if abs(state.weekly_pnl) >= limits.max_weekly_loss_usd:
                return False, f"Weekly loss limit reached: ${abs(state.weekly_pnl):.2f}"

            # Check drawdown
            if state.current_drawdown_pct >= limits.max_drawdown_pct * 100:
                return False, f"Max drawdown exceeded: {state.current_drawdown_pct:.1f}%"

            return True, None
    
    def can_open_position(self, user_id: str, current_position_count: int) -> Tuple[bool, Optional[str]]:
        """
        Check if user can open a new position (position count check only).
        
        Args:
            user_id: User identifier
            current_position_count: Current number of open positions
        
        Returns:
            (can_open, error_message)
        """
        lock = self._get_user_lock(user_id)
        
        with lock:
            limits = self.get_limits(user_id)
            
            # Use helper method for consistent error messages
            allowed, error = self._check_position_limit(user_id, current_position_count, limits)
            if not allowed:
                # Make error message more specific for this method
                return False, f"Maximum open positions reached ({current_position_count}/{limits.max_open_positions})"
            
            return True, None

    def get_state(self, user_id: str) -> UserRiskState:
        """
        Get current risk state for a user.

        Args:
            user_id: User identifier

        Returns:
            UserRiskState: Current state
        """
        lock = self._get_user_lock(user_id)

        with lock:
            if user_id not in self._user_states:
                self._user_states[user_id] = self._load_state(user_id)

            state = self._user_states[user_id]
            state.reset_if_new_day()
            state.reset_if_new_week()

            return state

    def reset_circuit_breaker(self, user_id: str):
        """
        Reset circuit breaker for a user (manual intervention).

        Args:
            user_id: User identifier
        """
        lock = self._get_user_lock(user_id)

        with lock:
            if user_id in self._user_states:
                self._user_states[user_id].circuit_breaker_triggered = False
                self._save_state(self._user_states[user_id])
                logger.info(f"Reset circuit breaker for {user_id}")


# Global singleton instance
_user_risk_manager: Optional[UserRiskManager] = None
_init_lock = threading.Lock()


def get_user_risk_manager() -> UserRiskManager:
    """
    Get the global user risk manager instance (singleton).

    Returns:
        UserRiskManager: Global instance
    """
    global _user_risk_manager

    with _init_lock:
        if _user_risk_manager is None:
            _user_risk_manager = UserRiskManager()
        return _user_risk_manager


__all__ = [
    'UserRiskManager',
    'UserRiskLimits',
    'UserRiskState',
    'get_user_risk_manager',
]
