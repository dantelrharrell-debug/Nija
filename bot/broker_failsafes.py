# bot/broker_failsafes.py
"""
NIJA Broker-Specific Failsafe System
Hard limits and circuit breakers to protect capital across all brokers

Features:
- Daily stop loss limits (auto-shutdown when hit)
- Max loss per trade enforcement
- Max drawdown protection
- Position size limits
- Emergency circuit breakers
- Broker-specific risk profiles

Version: 1.0
Date: December 30, 2025
"""

import logging
import json
import os
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

logger = logging.getLogger("nija.broker_failsafes")


class FailsafeStatus(Enum):
    """Status of failsafe checks"""
    PASS = "pass"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY_STOP = "emergency_stop"


@dataclass
class FailsafeState:
    """Current state of failsafe system"""
    daily_pnl: float = 0.0
    daily_trades: int = 0
    max_drawdown_today: float = 0.0
    last_reset: str = ""
    consecutive_losses: int = 0
    emergency_stop_active: bool = False
    circuit_breaker_count: int = 0

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'FailsafeState':
        return cls(**data)


class BrokerFailsafes:
    """
    Broker-agnostic failsafe system with hard limits

    Prevents catastrophic losses through multi-layer protection:
    1. Daily stop loss (circuit breaker)
    2. Max loss per trade (pre-trade validation)
    3. Max drawdown protection (running portfolio check)
    4. Position size limits (risk management)
    5. Emergency shutdown (multi-breach protection)
    """

    def __init__(self, broker_name: str = "coinbase", account_balance: float = None):
        """
        Initialize failsafe system for specific broker

        Args:
            broker_name: Name of broker (coinbase, binance, kraken, okx)
            account_balance: Current account balance in USD (MUST be provided - no defaults)
        """
        if account_balance is None or account_balance <= 0:
            raise ValueError(
                f"Account balance must be provided and > 0 for {broker_name}. "
                f"Got: {account_balance}. Capital must be fetched live from exchange."
            )

        self.broker_name = broker_name.lower()
        self.account_balance = account_balance

        # Load broker-specific risk profile
        self.risk_profile = self._load_risk_profile()

        # Load or initialize state
        self.state_file = f"failsafe_state_{self.broker_name}.json"
        self.state = self._load_state()

        # Check if we need daily reset
        self._check_daily_reset()

        logger.info(f"✅ Broker failsafes initialized for {broker_name}")
        logger.info(f"   Daily stop loss: {self.risk_profile['daily_stop_loss_pct']*100}%")
        logger.info(f"   Max loss per trade: {self.risk_profile['max_loss_per_trade_pct']*100}%")
        logger.info(f"   Max drawdown: {self.risk_profile['max_drawdown_pct']*100}%")

    def _load_risk_profile(self) -> Dict:
        """Load broker-specific risk profile with hard limits"""

        # Try to load from exchange_risk_profiles.py if available
        try:
            from exchange_risk_profiles import get_exchange_risk_manager, ExchangeType
            manager = get_exchange_risk_manager()

            # Map broker name to ExchangeType
            broker_map = {
                'coinbase': ExchangeType.COINBASE,
                'alpaca': ExchangeType.ALPACA,
                'binance': ExchangeType.BINANCE,
                'okx': ExchangeType.OKX,
                'kraken': ExchangeType.KRAKEN,
            }

            exchange_type = broker_map.get(self.broker_name.lower())
            if not exchange_type:
                raise ValueError(f"Unknown broker: {self.broker_name}")

            profile = manager.get_profile(exchange_type)

            # Convert to our format
            return {
                'daily_stop_loss_pct': 0.10,  # Conservative default
                'max_loss_per_trade_pct': profile.max_stop_loss_pct,
                'max_drawdown_pct': 0.15,  # Conservative default
                'max_position_size_pct': profile.max_position_size_pct,
                'max_trades_per_day': profile.max_trades_per_day,
                'min_profit_target_pct': profile.min_take_profit_pct,
                'circuit_breaker_threshold': 3,  # Consecutive losses trigger review
            }
        except (ImportError, Exception) as e:
            logger.warning(f"Could not load exchange risk profiles: {e}")
            # Fall back to conservative defaults

        # Default failsafe limits (conservative)
        return {
            'daily_stop_loss_pct': 0.10,  # -10% daily loss triggers shutdown
            'max_loss_per_trade_pct': 0.02,  # -2% max loss per trade
            'max_drawdown_pct': 0.15,  # -15% from peak triggers emergency stop
            'max_position_size_pct': 0.25,  # 25% max per position
            'max_trades_per_day': 50,  # Prevent overtrading
            'min_profit_target_pct': 0.015,  # 1.5% minimum target (covers fees)
            'circuit_breaker_threshold': 3,  # 3 consecutive losses = pause
        }

    def _load_state(self) -> FailsafeState:
        """Load failsafe state from file"""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    return FailsafeState.from_dict(data)
        except Exception as e:
            logger.warning(f"Could not load failsafe state: {e}")

        # Return fresh state
        return FailsafeState(last_reset=datetime.now().date().isoformat())

    def _save_state(self):
        """Save current failsafe state to file"""
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.state.to_dict(), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save failsafe state: {e}")

    def update_account_balance(self, new_balance: float) -> None:
        """
        Update account balance dynamically (called before each allocation cycle).

        Args:
            new_balance: New account balance fetched live from exchange
        """
        if new_balance is None or new_balance < 0:
            logger.warning(f"⚠️ Invalid balance update: {new_balance}, keeping current: ${self.account_balance:.2f}")
            return

        old_balance = self.account_balance
        self.account_balance = new_balance

        if abs(new_balance - old_balance) / old_balance > 0.01:  # Log if >1% change
            logger.info(f"💰 Account balance updated: ${old_balance:.2f} → ${new_balance:.2f}")

    def _check_daily_reset(self):
        """Reset daily counters at start of new day"""
        today = datetime.now().date().isoformat()

        if self.state.last_reset != today:
            logger.info(f"📅 Daily reset: {self.state.last_reset} → {today}")
            logger.info(f"   Previous P&L: ${self.state.daily_pnl:.2f}")
            logger.info(f"   Previous trades: {self.state.daily_trades}")

            # Reset daily counters
            self.state.daily_pnl = 0.0
            self.state.daily_trades = 0
            self.state.max_drawdown_today = 0.0
            self.state.last_reset = today

            # Keep consecutive losses and circuit breaker count across days
            # (only manual review should reset these)

            self._save_state()

    def validate_trade(self, position_size: float, stop_loss_pct: float,
                      profit_target_pct: float) -> Tuple[FailsafeStatus, str]:
        """
        Validate trade before execution

        Args:
            position_size: Proposed position size in USD
            stop_loss_pct: Stop loss as percentage (negative, e.g., -0.02)
            profit_target_pct: Profit target as percentage (positive, e.g., 0.03)

        Returns:
            Tuple of (status, message)
        """

        # Check 1: Emergency stop active
        if self.state.emergency_stop_active:
            return (FailsafeStatus.EMERGENCY_STOP,
                   "❌ EMERGENCY STOP ACTIVE - Trading disabled until manual review")

        # Check 2: Daily stop loss hit
        daily_loss_pct = self.state.daily_pnl / self.account_balance
        if daily_loss_pct <= -self.risk_profile['daily_stop_loss_pct']:
            self._trigger_emergency_stop("Daily stop loss hit")
            return (FailsafeStatus.EMERGENCY_STOP,
                   f"❌ DAILY STOP LOSS HIT: {daily_loss_pct*100:.2f}% "
                   f"(limit: {-self.risk_profile['daily_stop_loss_pct']*100:.2f}%)")

        # Check 3: Max drawdown exceeded
        if self.state.max_drawdown_today <= -self.risk_profile['max_drawdown_pct']:
            self._trigger_emergency_stop("Max drawdown exceeded")
            return (FailsafeStatus.EMERGENCY_STOP,
                   f"❌ MAX DRAWDOWN EXCEEDED: {self.state.max_drawdown_today*100:.2f}% "
                   f"(limit: {-self.risk_profile['max_drawdown_pct']*100:.2f}%)")

        # Check 4: Max trades per day
        if self.state.daily_trades >= self.risk_profile['max_trades_per_day']:
            return (FailsafeStatus.CRITICAL,
                   f"⚠️ Max trades per day reached: {self.state.daily_trades} "
                   f"(limit: {self.risk_profile['max_trades_per_day']})")

        # Check 5: Position size too large
        position_pct = position_size / self.account_balance
        if position_pct > self.risk_profile['max_position_size_pct']:
            return (FailsafeStatus.CRITICAL,
                   f"⚠️ Position too large: {position_pct*100:.2f}% "
                   f"(max: {self.risk_profile['max_position_size_pct']*100:.2f}%)")

        # Check 6: Stop loss too wide
        if abs(stop_loss_pct) > self.risk_profile['max_loss_per_trade_pct']:
            return (FailsafeStatus.WARNING,
                   f"⚠️ Stop loss too wide: {stop_loss_pct*100:.2f}% "
                   f"(max: {-self.risk_profile['max_loss_per_trade_pct']*100:.2f}%)")

        # Check 7: Profit target too small (won't cover fees)
        if profit_target_pct < self.risk_profile['min_profit_target_pct']:
            return (FailsafeStatus.WARNING,
                   f"⚠️ Profit target too small: {profit_target_pct*100:.2f}% "
                   f"(min: {self.risk_profile['min_profit_target_pct']*100:.2f}%)")

        # Check 8: Consecutive losses (circuit breaker warning)
        if self.state.consecutive_losses >= self.risk_profile['circuit_breaker_threshold']:
            return (FailsafeStatus.WARNING,
                   f"⚠️ Circuit breaker warning: {self.state.consecutive_losses} consecutive losses. "
                   f"Consider pausing to review strategy.")

        # All checks passed
        return (FailsafeStatus.PASS, "✅ Trade validation passed")

    def record_trade_result(self, pnl_dollars: float, pnl_pct: float):
        """
        Record trade result and update failsafe counters

        Args:
            pnl_dollars: Profit/loss in dollars
            pnl_pct: Profit/loss as percentage
        """
        # Update daily P&L
        self.state.daily_pnl += pnl_dollars
        self.state.daily_trades += 1

        # Track drawdown
        if self.state.daily_pnl < 0:
            drawdown_pct = self.state.daily_pnl / self.account_balance
            if drawdown_pct < self.state.max_drawdown_today:
                self.state.max_drawdown_today = drawdown_pct

        # Track consecutive losses
        if pnl_dollars < 0:
            self.state.consecutive_losses += 1
            logger.warning(f"📉 Loss recorded: ${pnl_dollars:.2f} ({pnl_pct:.2f}%) "
                         f"- Consecutive losses: {self.state.consecutive_losses}")

            # Check circuit breaker
            if self.state.consecutive_losses >= self.risk_profile['circuit_breaker_threshold']:
                self.state.circuit_breaker_count += 1
                logger.error(f"🔴 CIRCUIT BREAKER: {self.state.consecutive_losses} consecutive losses!")
                logger.error(f"   Consider pausing trading for review")

                # Auto-trigger emergency stop if 2+ circuit breakers in one day
                if self.state.circuit_breaker_count >= 2:
                    self._trigger_emergency_stop("Multiple circuit breakers triggered")
        else:
            # Reset consecutive losses on win
            if self.state.consecutive_losses > 0:
                logger.info(f"✅ Win breaks losing streak of {self.state.consecutive_losses}")
            self.state.consecutive_losses = 0

        # Log daily status
        daily_pnl_pct = (self.state.daily_pnl / self.account_balance) * 100
        logger.info(f"📊 Daily P&L: ${self.state.daily_pnl:.2f} ({daily_pnl_pct:+.2f}%) "
                   f"| Trades: {self.state.daily_trades} "
                   f"| Max DD: {self.state.max_drawdown_today*100:.2f}%")

        # Check if approaching limits
        self._check_warning_thresholds()

        # Save state
        self._save_state()

    def _check_warning_thresholds(self):
        """Check if approaching failsafe limits and warn"""

        # Daily P&L warning at 70% of limit
        daily_loss_pct = self.state.daily_pnl / self.account_balance
        warning_threshold = -self.risk_profile['daily_stop_loss_pct'] * 0.7

        if daily_loss_pct <= warning_threshold:
            remaining = (self.risk_profile['daily_stop_loss_pct'] + daily_loss_pct) * self.account_balance
            logger.warning(f"⚠️ APPROACHING DAILY STOP LOSS: {daily_loss_pct*100:.2f}% "
                         f"(${remaining:.2f} remaining before shutdown)")

        # Drawdown warning at 80% of limit
        drawdown_warning = -self.risk_profile['max_drawdown_pct'] * 0.8
        if self.state.max_drawdown_today <= drawdown_warning:
            logger.warning(f"⚠️ APPROACHING MAX DRAWDOWN: {self.state.max_drawdown_today*100:.2f}%")

        # Trade count warning at 90% of limit
        trade_warning = int(self.risk_profile['max_trades_per_day'] * 0.9)
        if self.state.daily_trades >= trade_warning:
            logger.warning(f"⚠️ APPROACHING TRADE LIMIT: {self.state.daily_trades} "
                         f"(limit: {self.risk_profile['max_trades_per_day']})")

    def _trigger_emergency_stop(self, reason: str):
        """
        Trigger emergency stop - requires manual intervention

        Args:
            reason: Why emergency stop was triggered
        """
        self.state.emergency_stop_active = True
        self._save_state()

        # Create lock file
        lock_file = "TRADING_LOCKED.conf"
        try:
            with open(lock_file, 'w') as f:
                f.write(f"TRADING_DISABLED=true\n")
                f.write(f"ALLOW_NEW_POSITIONS=false\n")
                f.write(f"EMERGENCY_STOP=true\n")
                f.write(f"REASON={reason}\n")
                f.write(f"TIMESTAMP={datetime.now().isoformat()}\n")
                f.write(f"BROKER={self.broker_name}\n")
        except Exception as e:
            logger.error(f"Failed to create trading lock file: {e}")

        logger.critical(f"🚨 EMERGENCY STOP TRIGGERED: {reason}")
        logger.critical(f"🚨 All trading halted for {self.broker_name}")
        logger.critical(f"🚨 Manual review required - check {lock_file}")
        logger.critical(f"🚨 To resume: Review logs, fix issues, then delete {lock_file}")

    def manual_reset(self, operator_name: str, reason: str):
        """
        Manually reset emergency stop - use with extreme caution

        Args:
            operator_name: Who is resetting (for audit trail)
            reason: Why reset is justified
        """
        logger.warning(f"⚠️ MANUAL RESET initiated by {operator_name}")
        logger.warning(f"   Reason: {reason}")

        # Reset emergency state
        self.state.emergency_stop_active = False
        self.state.consecutive_losses = 0
        self.state.circuit_breaker_count = 0

        # Remove lock file
        lock_file = "TRADING_LOCKED.conf"
        try:
            if os.path.exists(lock_file):
                os.remove(lock_file)
                logger.info(f"✅ Removed {lock_file}")
        except Exception as e:
            logger.error(f"Failed to remove lock file: {e}")

        # Save state
        self._save_state()

        logger.info(f"✅ Emergency stop reset complete")
        logger.warning(f"⚠️ Monitor closely after manual reset")

    def get_status_report(self) -> Dict:
        """Get current failsafe status report"""

        daily_pnl_pct = (self.state.daily_pnl / self.account_balance) * 100

        # Calculate remaining limits
        remaining_daily_loss_pct = (self.risk_profile['daily_stop_loss_pct'] * 100) + daily_pnl_pct
        remaining_drawdown_pct = (self.risk_profile['max_drawdown_pct'] * 100) + (self.state.max_drawdown_today * 100)
        remaining_trades = self.risk_profile['max_trades_per_day'] - self.state.daily_trades

        return {
            'broker': self.broker_name,
            'emergency_stop_active': self.state.emergency_stop_active,
            'daily_pnl_dollars': self.state.daily_pnl,
            'daily_pnl_percent': daily_pnl_pct,
            'daily_trades': self.state.daily_trades,
            'max_drawdown_percent': self.state.max_drawdown_today * 100,
            'consecutive_losses': self.state.consecutive_losses,
            'circuit_breaker_count': self.state.circuit_breaker_count,
            'limits': {
                'daily_stop_loss_pct': self.risk_profile['daily_stop_loss_pct'] * 100,
                'max_loss_per_trade_pct': self.risk_profile['max_loss_per_trade_pct'] * 100,
                'max_drawdown_pct': self.risk_profile['max_drawdown_pct'] * 100,
                'max_trades_per_day': self.risk_profile['max_trades_per_day'],
            },
            'remaining': {
                'daily_loss_pct': remaining_daily_loss_pct,
                'drawdown_pct': remaining_drawdown_pct,
                'trades': remaining_trades,
            }
        }


# Convenience function for quick integration
def create_failsafe_for_broker(broker_name: str, account_balance: float) -> BrokerFailsafes:
    """
    Create failsafe system for specific broker

    Args:
        broker_name: Name of broker (coinbase, binance, kraken, okx)
        account_balance: Current account balance in USD

    Returns:
        BrokerFailsafes instance
    """
    return BrokerFailsafes(broker_name, account_balance)


# Example usage
if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s'
    )

    # Example: Coinbase with $1000 balance (always use live fetched balance)
    failsafe = create_failsafe_for_broker("coinbase", 1000.0)

    # Validate a trade
    status, message = failsafe.validate_trade(
        position_size=20.0,  # $20 position
        stop_loss_pct=-0.02,  # -2% stop
        profit_target_pct=0.03  # +3% target
    )

    print(f"\nTrade Validation: {status.value}")
    print(message)

    # Simulate some trades
    print("\n--- Simulating trades ---")
    failsafe.record_trade_result(pnl_dollars=0.60, pnl_pct=0.03)  # Win
    failsafe.record_trade_result(pnl_dollars=-0.40, pnl_pct=-0.02)  # Loss
    failsafe.record_trade_result(pnl_dollars=-0.40, pnl_pct=-0.02)  # Loss
    failsafe.record_trade_result(pnl_dollars=-0.40, pnl_pct=-0.02)  # Loss (triggers warning)

    # Get status report
    print("\n--- Status Report ---")
    report = failsafe.get_status_report()
    print(json.dumps(report, indent=2))
