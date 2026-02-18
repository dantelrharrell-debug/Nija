"""
NIJA Position Architecture System (Phase 2: The Skeleton)

Institutional-grade position management and exposure control.
Prevents capital violations and ensures portfolio-aware trading.

Features:
- Hard max open positions per tier
- Per-symbol exposure cap
- Capital reserve buffer (20% idle)
- Daily max loss lock
- Weekly drawdown lock
- Auto position reduction during volatility spikes
- Position age tracking and forced exits
- Zombie position detection

Author: NIJA Trading Systems
Version: 1.0
Date: February 18, 2026
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path

logger = logging.getLogger("nija.position_architecture")


class PositionState(Enum):
    """Position lifecycle states"""
    ACTIVE = "ACTIVE"
    STALE = "STALE"       # No movement for 12+ hours
    AGED = "AGED"         # Open for 24+ hours
    ZOMBIE = "ZOMBIE"     # Stale + aged + underwater
    LIQUIDATING = "LIQUIDATING"


@dataclass
class PositionMetrics:
    """Position health metrics"""
    age_hours: float
    unrealized_pnl_pct: float
    last_update_hours: float
    volatility: float
    liquidity_score: float
    
    def get_health_score(self) -> float:
        """Calculate position health score (0-100)"""
        score = 100.0
        
        # Penalize age
        if self.age_hours > 24:
            score -= min(30, (self.age_hours - 24) / 24 * 10)
        
        # Penalize stale positions
        if self.last_update_hours > 12:
            score -= min(20, (self.last_update_hours - 12) / 12 * 10)
        
        # Penalize underwater positions
        if self.unrealized_pnl_pct < 0:
            score -= min(30, abs(self.unrealized_pnl_pct) * 2)
        
        # Penalize low liquidity
        if self.liquidity_score < 50:
            score -= (50 - self.liquidity_score) * 0.4
        
        return max(0, score)


@dataclass
class ExposureLimits:
    """Capital exposure limits"""
    max_total_exposure_pct: float = 0.80  # 80% max of account
    capital_reserve_pct: float = 0.20      # 20% idle buffer
    max_per_symbol_pct: float = 0.15       # 15% per symbol
    max_correlated_sector_pct: float = 0.40  # 40% in correlated assets
    
    def validate_exposure(self, current_exposure_pct: float, 
                         proposed_exposure_pct: float) -> Tuple[bool, str]:
        """
        Validate if new exposure is within limits.
        
        Returns:
            (is_valid, reason)
        """
        total_after = current_exposure_pct + proposed_exposure_pct
        
        if total_after > self.max_total_exposure_pct:
            return False, f"Total exposure would be {total_after:.1%} > max {self.max_total_exposure_pct:.1%}"
        
        if proposed_exposure_pct > self.max_per_symbol_pct:
            return False, f"Single position {proposed_exposure_pct:.1%} > max {self.max_per_symbol_pct:.1%}"
        
        return True, "OK"


@dataclass
class DrawdownLock:
    """Drawdown protection lock"""
    daily_max_loss_pct: float = 0.05      # 5% daily max loss
    weekly_max_loss_pct: float = 0.10     # 10% weekly max loss
    daily_loss_pct: float = 0.0
    weekly_loss_pct: float = 0.0
    daily_lock_active: bool = False
    weekly_lock_active: bool = False
    lock_until: Optional[datetime] = None
    
    def update_loss(self, loss_pct: float):
        """Update loss tracking"""
        self.daily_loss_pct += abs(loss_pct)
        self.weekly_loss_pct += abs(loss_pct)
        
        # Check if locks should be activated
        if self.daily_loss_pct >= self.daily_max_loss_pct:
            self.daily_lock_active = True
            self.lock_until = datetime.now() + timedelta(hours=24)
            logger.critical(
                f"🚨 DAILY LOSS LOCK ACTIVATED: {self.daily_loss_pct:.2%} loss >= {self.daily_max_loss_pct:.2%} limit"
            )
        
        if self.weekly_loss_pct >= self.weekly_max_loss_pct:
            self.weekly_lock_active = True
            self.lock_until = datetime.now() + timedelta(days=7)
            logger.critical(
                f"🚨 WEEKLY LOSS LOCK ACTIVATED: {self.weekly_loss_pct:.2%} loss >= {self.weekly_max_loss_pct:.2%} limit"
            )
    
    def is_locked(self) -> Tuple[bool, Optional[str]]:
        """Check if trading is locked due to drawdown"""
        now = datetime.now()
        
        # Check if locks have expired
        if self.lock_until and now >= self.lock_until:
            if self.daily_lock_active and self.weekly_lock_active:
                # Only clear daily if weekly hasn't expired
                if (now - self.lock_until).days < 7:
                    self.daily_lock_active = False
                    self.daily_loss_pct = 0.0
                else:
                    self.daily_lock_active = False
                    self.weekly_lock_active = False
                    self.daily_loss_pct = 0.0
                    self.weekly_loss_pct = 0.0
            elif self.daily_lock_active:
                self.daily_lock_active = False
                self.daily_loss_pct = 0.0
        
        if self.daily_lock_active:
            return True, f"Daily loss lock active ({self.daily_loss_pct:.2%} lost)"
        
        if self.weekly_lock_active:
            return True, f"Weekly loss lock active ({self.weekly_loss_pct:.2%} lost)"
        
        return False, None
    
    def reset_daily(self):
        """Reset daily counters (call at market open)"""
        self.daily_loss_pct = 0.0
        if not self.weekly_lock_active:
            self.daily_lock_active = False
    
    def reset_weekly(self):
        """Reset weekly counters (call weekly)"""
        self.weekly_loss_pct = 0.0
        self.weekly_lock_active = False
        self.lock_until = None


class PositionArchitecture:
    """
    Manages position architecture and exposure control.
    
    Provides institutional-grade position management:
    - Hard position caps per tier
    - Exposure limits and validation
    - Drawdown protection locks
    - Position health monitoring
    - Automatic position reduction
    """
    
    def __init__(self, tier_name: str, account_balance: float, 
                 max_positions: int, data_dir: str = "./data"):
        """
        Initialize position architecture.
        
        Args:
            tier_name: Capital tier name
            account_balance: Current account balance
            max_positions: Maximum allowed positions for tier
            data_dir: Data directory for persistence
        """
        self.tier_name = tier_name
        self.account_balance = account_balance
        self.max_positions = max_positions
        
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        
        # Exposure limits
        self.exposure_limits = ExposureLimits()
        
        # Drawdown lock
        self.drawdown_lock = DrawdownLock()
        
        # Position tracking
        self.positions: Dict[str, Dict] = {}  # symbol -> position data
        self.position_states: Dict[str, PositionState] = {}
        self.position_metrics: Dict[str, PositionMetrics] = {}
        
        # Symbol exposure tracking
        self.symbol_exposure: Dict[str, float] = {}  # symbol -> exposure_pct
        
        # Volatility spike detection
        self.recent_volatility: List[float] = []
        self.volatility_spike_threshold = 2.0  # 2x normal
        
        logger.info(
            f"🏗️ Position Architecture initialized - "
            f"Tier: {tier_name} | Max Positions: {max_positions} | "
            f"Balance: ${account_balance:.2f}"
        )
    
    def can_open_position(self, symbol: str, size_usd: float) -> Tuple[bool, str]:
        """
        Check if a new position can be opened.
        
        Args:
            symbol: Trading symbol
            size_usd: Proposed position size in USD
            
        Returns:
            (can_open, reason)
        """
        # Check 1: Hard position count limit
        current_count = len(self.positions)
        if current_count >= self.max_positions:
            return False, f"At max positions ({current_count}/{self.max_positions})"
        
        # Check 2: Drawdown lock
        is_locked, lock_reason = self.drawdown_lock.is_locked()
        if is_locked:
            return False, f"Drawdown lock active: {lock_reason}"
        
        # Check 3: Duplicate position check
        if symbol in self.positions:
            return False, f"Position already exists for {symbol}"
        
        # Check 4: Exposure validation
        proposed_exposure_pct = size_usd / self.account_balance
        current_exposure_pct = self._calculate_total_exposure()
        
        is_valid, reason = self.exposure_limits.validate_exposure(
            current_exposure_pct, proposed_exposure_pct
        )
        if not is_valid:
            return False, f"Exposure limit: {reason}"
        
        # Check 5: Capital reserve buffer
        total_after = current_exposure_pct + proposed_exposure_pct
        reserve_after = 1.0 - total_after
        if reserve_after < self.exposure_limits.capital_reserve_pct:
            return False, f"Insufficient reserve buffer ({reserve_after:.1%} < {self.exposure_limits.capital_reserve_pct:.1%})"
        
        # Check 6: Volatility spike
        if self._is_volatility_spike():
            return False, "Volatility spike detected - position opening paused"
        
        return True, "OK"
    
    def register_position(self, symbol: str, size_usd: float, entry_price: float,
                         side: str, stop_loss: float):
        """Register a new position"""
        self.positions[symbol] = {
            'symbol': symbol,
            'size_usd': size_usd,
            'entry_price': entry_price,
            'current_price': entry_price,
            'side': side,
            'stop_loss': stop_loss,
            'opened_at': datetime.now(),
            'last_updated': datetime.now(),
            'unrealized_pnl': 0.0,
        }
        
        self.position_states[symbol] = PositionState.ACTIVE
        self.symbol_exposure[symbol] = size_usd / self.account_balance
        
        logger.info(
            f"📥 Position registered: {symbol} | "
            f"Size: ${size_usd:.2f} | "
            f"Entry: ${entry_price:.2f} | "
            f"Positions: {len(self.positions)}/{self.max_positions}"
        )
    
    def update_position(self, symbol: str, current_price: float):
        """Update position with current price"""
        if symbol not in self.positions:
            return
        
        pos = self.positions[symbol]
        pos['current_price'] = current_price
        pos['last_updated'] = datetime.now()
        
        # Calculate unrealized P&L
        if pos['side'] == 'LONG':
            pos['unrealized_pnl'] = (current_price - pos['entry_price']) / pos['entry_price']
        else:  # SHORT
            pos['unrealized_pnl'] = (pos['entry_price'] - current_price) / pos['entry_price']
        
        # Update metrics
        self._update_position_metrics(symbol)
    
    def close_position(self, symbol: str, exit_price: float, pnl_usd: float):
        """Close a position"""
        if symbol not in self.positions:
            return
        
        pos = self.positions[symbol]
        pnl_pct = pnl_usd / pos['size_usd']
        
        # Update drawdown lock if loss
        if pnl_pct < 0:
            self.drawdown_lock.update_loss(abs(pnl_pct))
        
        # Remove position
        del self.positions[symbol]
        del self.position_states[symbol]
        del self.symbol_exposure[symbol]
        if symbol in self.position_metrics:
            del self.position_metrics[symbol]
        
        logger.info(
            f"📤 Position closed: {symbol} | "
            f"Exit: ${exit_price:.2f} | "
            f"P&L: ${pnl_usd:.2f} ({pnl_pct:.2%}) | "
            f"Positions: {len(self.positions)}/{self.max_positions}"
        )
    
    def _update_position_metrics(self, symbol: str):
        """Update position health metrics"""
        if symbol not in self.positions:
            return
        
        pos = self.positions[symbol]
        now = datetime.now()
        
        age_hours = (now - pos['opened_at']).total_seconds() / 3600
        last_update_hours = (now - pos['last_updated']).total_seconds() / 3600
        unrealized_pnl_pct = pos['unrealized_pnl']
        
        metrics = PositionMetrics(
            age_hours=age_hours,
            unrealized_pnl_pct=unrealized_pnl_pct,
            last_update_hours=last_update_hours,
            volatility=self._estimate_volatility(symbol),
            liquidity_score=75.0  # Simplified - would use real liquidity data
        )
        
        self.position_metrics[symbol] = metrics
        
        # Update position state
        health_score = metrics.get_health_score()
        
        if age_hours > 24 and last_update_hours > 12 and unrealized_pnl_pct < -0.05:
            self.position_states[symbol] = PositionState.ZOMBIE
        elif age_hours > 24:
            self.position_states[symbol] = PositionState.AGED
        elif last_update_hours > 12:
            self.position_states[symbol] = PositionState.STALE
        else:
            self.position_states[symbol] = PositionState.ACTIVE
        
        # Log warnings for unhealthy positions
        if health_score < 40:
            logger.warning(
                f"⚠️ Unhealthy position: {symbol} | "
                f"Health: {health_score:.1f} | "
                f"State: {self.position_states[symbol].value} | "
                f"Age: {age_hours:.1f}h | "
                f"P&L: {unrealized_pnl_pct:.2%}"
            )
    
    def _calculate_total_exposure(self) -> float:
        """Calculate total portfolio exposure as % of account"""
        total = sum(self.symbol_exposure.values())
        return total
    
    def _estimate_volatility(self, symbol: str) -> float:
        """Estimate position volatility (simplified)"""
        if symbol not in self.positions:
            return 0.0
        
        pos = self.positions[symbol]
        price_change = abs(pos['current_price'] - pos['entry_price']) / pos['entry_price']
        return price_change
    
    def _is_volatility_spike(self) -> bool:
        """Detect if market volatility has spiked"""
        if len(self.recent_volatility) < 10:
            return False
        
        avg_volatility = sum(self.recent_volatility[-10:]) / 10
        current_volatility = self.recent_volatility[-1]
        
        return current_volatility > avg_volatility * self.volatility_spike_threshold
    
    def get_positions_to_force_close(self) -> List[str]:
        """Get list of positions that should be force-closed"""
        force_close = []
        
        for symbol, state in self.position_states.items():
            if state == PositionState.ZOMBIE:
                force_close.append(symbol)
                logger.warning(f"🧟 Zombie position detected: {symbol} - Force close recommended")
            elif state == PositionState.AGED:
                metrics = self.position_metrics.get(symbol)
                if metrics and metrics.unrealized_pnl_pct < -0.02:
                    force_close.append(symbol)
                    logger.warning(f"⏰ Aged losing position: {symbol} - Force close recommended")
        
        return force_close
    
    def should_reduce_positions(self) -> Tuple[bool, int]:
        """
        Check if positions should be reduced due to volatility.
        
        Returns:
            (should_reduce, target_count)
        """
        if self._is_volatility_spike():
            # Reduce to 50% of max during volatility spikes
            target_count = max(1, self.max_positions // 2)
            current_count = len(self.positions)
            
            if current_count > target_count:
                logger.warning(
                    f"📉 Volatility spike - Recommending position reduction: "
                    f"{current_count} -> {target_count}"
                )
                return True, target_count
        
        return False, len(self.positions)
    
    def get_architecture_status(self) -> Dict:
        """Get current architecture status"""
        total_exposure = self._calculate_total_exposure()
        reserve = 1.0 - total_exposure
        is_locked, lock_reason = self.drawdown_lock.is_locked()
        
        return {
            'tier': self.tier_name,
            'account_balance': self.account_balance,
            'positions': {
                'current': len(self.positions),
                'max': self.max_positions,
                'utilization_pct': len(self.positions) / self.max_positions if self.max_positions > 0 else 0
            },
            'exposure': {
                'total_pct': total_exposure,
                'reserve_pct': reserve,
                'by_symbol': self.symbol_exposure.copy()
            },
            'drawdown_lock': {
                'active': is_locked,
                'reason': lock_reason,
                'daily_loss_pct': self.drawdown_lock.daily_loss_pct,
                'weekly_loss_pct': self.drawdown_lock.weekly_loss_pct
            },
            'position_health': {
                symbol: {
                    'state': self.position_states[symbol].value,
                    'health_score': self.position_metrics[symbol].get_health_score() if symbol in self.position_metrics else 0,
                    'age_hours': self.position_metrics[symbol].age_hours if symbol in self.position_metrics else 0
                }
                for symbol in self.positions.keys()
            }
        }
    
    def print_status(self):
        """Print architecture status"""
        status = self.get_architecture_status()
        
        logger.info(f"\n{'='*60}")
        logger.info(f"🏗️ POSITION ARCHITECTURE STATUS")
        logger.info(f"{'='*60}")
        logger.info(f"Tier: {status['tier']} | Balance: ${status['account_balance']:.2f}")
        logger.info(f"Positions: {status['positions']['current']}/{status['positions']['max']} "
                   f"({status['positions']['utilization_pct']:.0%})")
        logger.info(f"Exposure: {status['exposure']['total_pct']:.1%} | "
                   f"Reserve: {status['exposure']['reserve_pct']:.1%}")
        
        if status['drawdown_lock']['active']:
            logger.info(f"🚨 DRAWDOWN LOCK: {status['drawdown_lock']['reason']}")
        
        if status['position_health']:
            logger.info(f"\nPosition Health:")
            for symbol, health in status['position_health'].items():
                logger.info(f"  {symbol}: {health['state']} | "
                           f"Health: {health['health_score']:.0f} | "
                           f"Age: {health['age_hours']:.1f}h")
        
        logger.info(f"{'='*60}\n")


# Global instance
_position_architecture = None


def get_position_architecture(tier_name: str, account_balance: float, 
                             max_positions: int) -> PositionArchitecture:
    """Get or create position architecture instance"""
    global _position_architecture
    if _position_architecture is None or \
       _position_architecture.tier_name != tier_name or \
       abs(_position_architecture.account_balance - account_balance) > 1.0:
        _position_architecture = PositionArchitecture(tier_name, account_balance, max_positions)
    return _position_architecture
