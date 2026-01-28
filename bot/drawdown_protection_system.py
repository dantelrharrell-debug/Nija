"""
NIJA Drawdown Protection System

Automatically reduces position sizes and implements circuit breakers during
losing streaks to preserve capital and enable faster recovery.

Key Features:
- Automatic position size reduction during drawdowns
- Circuit breakers that halt trading when losses exceed thresholds
- Gradual recovery protocols (scale back up as performance improves)
- Protected minimum capital floors
- Integration with risk management and compounding systems

Author: NIJA Trading Systems
Version: 1.0
Date: January 28, 2026
"""

import logging
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import json
from pathlib import Path

logger = logging.getLogger("nija.drawdown_protection")


class ProtectionLevel(Enum):
    """Drawdown protection levels"""
    NORMAL = "normal"  # No drawdown, normal trading
    CAUTION = "caution"  # Minor drawdown (5-10%), reduce position sizes
    WARNING = "warning"  # Moderate drawdown (10-15%), significant reduction
    DANGER = "danger"  # Severe drawdown (15-20%), minimal positions only
    HALT = "halt"  # Critical drawdown (>20%), stop trading


@dataclass
class DrawdownConfig:
    """Configuration for drawdown protection"""
    # Drawdown thresholds (as percentages)
    caution_threshold_pct: float = 5.0  # Start reducing at 5% drawdown
    warning_threshold_pct: float = 10.0  # Significant reduction at 10%
    danger_threshold_pct: float = 15.0  # Minimal trading at 15%
    halt_threshold_pct: float = 20.0  # Stop trading at 20%
    
    # Position size adjustments per level
    caution_position_multiplier: float = 0.75  # 75% of normal size
    warning_position_multiplier: float = 0.50  # 50% of normal size
    danger_position_multiplier: float = 0.25  # 25% of normal size
    halt_position_multiplier: float = 0.0  # No trading
    
    # Recovery settings
    recovery_win_streak_required: int = 3  # Wins needed to step down protection
    recovery_profit_threshold_pct: float = 50.0  # % of drawdown to recover before stepping down
    
    # Protected capital
    enable_capital_floor: bool = True
    protected_capital_pct: float = 0.80  # Never risk last 20% of base capital
    

@dataclass
class DrawdownState:
    """Current drawdown state"""
    peak_capital: float  # All-time high capital
    current_capital: float  # Current capital
    drawdown_amount: float  # Dollar amount of drawdown
    drawdown_pct: float  # Percentage drawdown from peak
    protection_level: ProtectionLevel  # Current protection level
    losing_streak: int  # Current consecutive losses
    winning_streak: int  # Current consecutive wins
    trades_since_peak: int  # Trades since reaching peak
    time_in_drawdown: timedelta  # Time spent in current drawdown
    
    def update(self, current_capital: float):
        """Update drawdown state with new capital"""
        # Update peak if new high
        if current_capital > self.peak_capital:
            self.peak_capital = current_capital
            self.drawdown_amount = 0.0
            self.drawdown_pct = 0.0
            self.trades_since_peak = 0
            return
        
        # Calculate drawdown
        self.current_capital = current_capital
        self.drawdown_amount = self.peak_capital - current_capital
        
        if self.peak_capital > 0:
            self.drawdown_pct = (self.drawdown_amount / self.peak_capital) * 100
        else:
            self.drawdown_pct = 0.0


class DrawdownProtectionSystem:
    """
    Manages capital protection during drawdowns
    
    Responsibilities:
    1. Monitor drawdown levels continuously
    2. Reduce position sizes during losing periods
    3. Implement circuit breakers for severe losses
    4. Manage gradual recovery as performance improves
    5. Protect minimum capital floors
    """
    
    # Data persistence
    DATA_DIR = Path(__file__).parent.parent / "data"
    PROTECTION_FILE = DATA_DIR / "drawdown_protection.json"
    
    def __init__(self, base_capital: float,
                 config: Optional[DrawdownConfig] = None):
        """
        Initialize Drawdown Protection System
        
        Args:
            base_capital: Base capital to protect
            config: Protection configuration (optional)
        """
        self.config = config or DrawdownConfig()
        self.base_capital = base_capital
        
        # Initialize state
        self.state = DrawdownState(
            peak_capital=base_capital,
            current_capital=base_capital,
            drawdown_amount=0.0,
            drawdown_pct=0.0,
            protection_level=ProtectionLevel.NORMAL,
            losing_streak=0,
            winning_streak=0,
            trades_since_peak=0,
            time_in_drawdown=timedelta()
        )
        
        # Tracking
        self.drawdown_start_time: Optional[datetime] = None
        self.last_trade_time: Optional[datetime] = None
        
        # History
        self.protection_changes: List[Dict] = []
        
        # Ensure data directory exists
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        
        # Load existing state
        self._load_state()
        
        logger.info("=" * 70)
        logger.info("🛡️  Drawdown Protection System Initialized")
        logger.info("=" * 70)
        logger.info(f"Base Capital: ${self.base_capital:.2f}")
        logger.info(f"Caution Threshold: {self.config.caution_threshold_pct:.1f}%")
        logger.info(f"Warning Threshold: {self.config.warning_threshold_pct:.1f}%")
        logger.info(f"Danger Threshold: {self.config.danger_threshold_pct:.1f}%")
        logger.info(f"Halt Threshold: {self.config.halt_threshold_pct:.1f}%")
        logger.info("=" * 70)
    
    def _load_state(self) -> bool:
        """Load state from persistent storage"""
        if not self.PROTECTION_FILE.exists():
            return False
        
        try:
            with open(self.PROTECTION_FILE, 'r') as f:
                data = json.load(f)
            
            self.state.peak_capital = data.get('peak_capital', self.base_capital)
            self.state.current_capital = data.get('current_capital', self.base_capital)
            self.state.losing_streak = data.get('losing_streak', 0)
            self.state.winning_streak = data.get('winning_streak', 0)
            self.state.trades_since_peak = data.get('trades_since_peak', 0)
            
            # Recalculate drawdown
            self.state.update(self.state.current_capital)
            self._update_protection_level()
            
            logger.info(f"✅ Loaded protection state from {self.PROTECTION_FILE}")
            return True
        except Exception as e:
            logger.warning(f"Failed to load protection state: {e}")
            return False
    
    def _save_state(self):
        """Save state to persistent storage"""
        try:
            data = {
                'peak_capital': self.state.peak_capital,
                'current_capital': self.state.current_capital,
                'drawdown_amount': self.state.drawdown_amount,
                'drawdown_pct': self.state.drawdown_pct,
                'protection_level': self.state.protection_level.value,
                'losing_streak': self.state.losing_streak,
                'winning_streak': self.state.winning_streak,
                'trades_since_peak': self.state.trades_since_peak,
                'last_updated': datetime.now().isoformat()
            }
            
            with open(self.PROTECTION_FILE, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.debug("💾 Protection state saved")
        except Exception as e:
            logger.error(f"Failed to save protection state: {e}")
    
    def _update_protection_level(self) -> ProtectionLevel:
        """
        Update protection level based on current drawdown
        
        Returns:
            New protection level
        """
        old_level = self.state.protection_level
        
        # Determine new level based on drawdown
        if self.state.drawdown_pct >= self.config.halt_threshold_pct:
            new_level = ProtectionLevel.HALT
        elif self.state.drawdown_pct >= self.config.danger_threshold_pct:
            new_level = ProtectionLevel.DANGER
        elif self.state.drawdown_pct >= self.config.warning_threshold_pct:
            new_level = ProtectionLevel.WARNING
        elif self.state.drawdown_pct >= self.config.caution_threshold_pct:
            new_level = ProtectionLevel.CAUTION
        else:
            new_level = ProtectionLevel.NORMAL
        
        # Check for recovery conditions (can step down if winning)
        if new_level.value != old_level.value and self.state.winning_streak >= self.config.recovery_win_streak_required:
            # Calculate recovery percentage
            recovered_amount = self.state.current_capital - (self.state.peak_capital - self.state.drawdown_amount)
            recovery_pct = (recovered_amount / self.state.drawdown_amount * 100) if self.state.drawdown_amount > 0 else 0
            
            if recovery_pct >= self.config.recovery_profit_threshold_pct:
                # Allow stepping down one level
                levels = [ProtectionLevel.NORMAL, ProtectionLevel.CAUTION, 
                         ProtectionLevel.WARNING, ProtectionLevel.DANGER, ProtectionLevel.HALT]
                old_idx = levels.index(old_level)
                new_idx = levels.index(new_level)
                
                if new_idx > old_idx and old_idx > 0:
                    new_level = levels[old_idx - 1]
                    logger.info(f"✅ Recovery progress: {recovery_pct:.1f}% - stepping down to {new_level.value}")
        
        # Update state
        self.state.protection_level = new_level
        
        # Log change
        if new_level != old_level:
            self._record_protection_change(old_level, new_level)
        
        return new_level
    
    def _record_protection_change(self, old_level: ProtectionLevel, 
                                  new_level: ProtectionLevel):
        """Record a protection level change"""
        change = {
            'timestamp': datetime.now().isoformat(),
            'from_level': old_level.value,
            'to_level': new_level.value,
            'drawdown_pct': self.state.drawdown_pct,
            'capital': self.state.current_capital,
            'losing_streak': self.state.losing_streak,
            'winning_streak': self.state.winning_streak
        }
        
        self.protection_changes.append(change)
        
        # Keep only last 100 changes
        if len(self.protection_changes) > 100:
            self.protection_changes = self.protection_changes[-100:]
        
        # Log the change
        if new_level.value > old_level.value:
            # Escalating protection
            logger.warning("⚠️  PROTECTION ESCALATED")
            logger.warning(f"   {old_level.value.upper()} → {new_level.value.upper()}")
            logger.warning(f"   Drawdown: {self.state.drawdown_pct:.2f}%")
            logger.warning(f"   Losing Streak: {self.state.losing_streak}")
            
            if new_level == ProtectionLevel.HALT:
                logger.error("🛑 TRADING HALTED - CRITICAL DRAWDOWN")
                logger.error(f"   Drawdown: {self.state.drawdown_pct:.2f}%")
                logger.error(f"   Peak: ${self.state.peak_capital:.2f}")
                logger.error(f"   Current: ${self.state.current_capital:.2f}")
                logger.error(f"   Loss: ${self.state.drawdown_amount:.2f}")
        else:
            # De-escalating protection (recovery)
            logger.info("✅ PROTECTION DE-ESCALATED")
            logger.info(f"   {old_level.value.upper()} → {new_level.value.upper()}")
            logger.info(f"   Drawdown: {self.state.drawdown_pct:.2f}%")
            logger.info(f"   Winning Streak: {self.state.winning_streak}")
    
    def record_trade(self, new_capital: float, is_win: bool):
        """
        Record a trade and update protection state
        
        Args:
            new_capital: Capital after trade
            is_win: True if trade was profitable
        """
        # Update streaks
        if is_win:
            self.state.winning_streak += 1
            self.state.losing_streak = 0
        else:
            self.state.losing_streak += 1
            self.state.winning_streak = 0
        
        # Update drawdown state
        self.state.update(new_capital)
        self.state.trades_since_peak += 1
        
        # Update protection level
        self._update_protection_level()
        
        # Update time tracking
        now = datetime.now()
        if self.state.drawdown_pct > 0:
            if self.drawdown_start_time is None:
                self.drawdown_start_time = now
            self.state.time_in_drawdown = now - self.drawdown_start_time
        else:
            self.drawdown_start_time = None
            self.state.time_in_drawdown = timedelta()
        
        self.last_trade_time = now
        
        # Save state
        self._save_state()
        
        # Log status
        self._log_trade_status(is_win)
    
    def _log_trade_status(self, is_win: bool):
        """Log current protection status after a trade"""
        status = "WIN ✅" if is_win else "LOSS ❌"
        
        logger.info(f"🛡️  Protection Status After {status}")
        logger.info(f"   Level: {self.state.protection_level.value.upper()}")
        logger.info(f"   Drawdown: {self.state.drawdown_pct:.2f}%")
        logger.info(f"   Streak: {self.state.losing_streak} losses / {self.state.winning_streak} wins")
        
        if self.state.protection_level != ProtectionLevel.NORMAL:
            multiplier = self.get_position_size_multiplier()
            logger.info(f"   Position Adjustment: {multiplier*100:.0f}% of normal")
    
    def get_position_size_multiplier(self) -> float:
        """
        Get position size multiplier based on protection level
        
        Returns:
            Multiplier to apply to normal position size (0.0 - 1.0)
        """
        if self.state.protection_level == ProtectionLevel.NORMAL:
            return 1.0
        elif self.state.protection_level == ProtectionLevel.CAUTION:
            return self.config.caution_position_multiplier
        elif self.state.protection_level == ProtectionLevel.WARNING:
            return self.config.warning_position_multiplier
        elif self.state.protection_level == ProtectionLevel.DANGER:
            return self.config.danger_position_multiplier
        else:  # HALT
            return self.config.halt_position_multiplier
    
    def can_trade(self) -> Tuple[bool, str]:
        """
        Check if trading is allowed based on protection level
        
        Returns:
            Tuple of (can_trade, reason)
        """
        if self.state.protection_level == ProtectionLevel.HALT:
            return (False, f"Trading halted due to {self.state.drawdown_pct:.2f}% drawdown (>{self.config.halt_threshold_pct:.1f}%)")
        
        # Check capital floor
        if self.config.enable_capital_floor:
            min_capital = self.base_capital * self.config.protected_capital_pct
            if self.state.current_capital <= min_capital:
                return (False, f"Capital floor reached: ${self.state.current_capital:.2f} <= ${min_capital:.2f} (80% of base)")
        
        return (True, "Trading allowed")
    
    def get_adjusted_position_size(self, base_position_size: float) -> float:
        """
        Get position size adjusted for drawdown protection
        
        Args:
            base_position_size: Desired position size before adjustment
            
        Returns:
            Adjusted position size
        """
        multiplier = self.get_position_size_multiplier()
        return base_position_size * multiplier
    
    def get_protection_report(self) -> str:
        """Generate detailed protection report"""
        report = [
            "\n" + "=" * 90,
            "DRAWDOWN PROTECTION REPORT",
            "=" * 90,
            f"Protection Level: {self.state.protection_level.value.upper()}",
            ""
        ]
        
        # Capital status
        report.extend([
            "💰 CAPITAL STATUS",
            "-" * 90,
            f"  Peak Capital:         ${self.state.peak_capital:>12,.2f}",
            f"  Current Capital:      ${self.state.current_capital:>12,.2f}",
            f"  Drawdown Amount:      ${self.state.drawdown_amount:>12,.2f}",
            f"  Drawdown %:           {self.state.drawdown_pct:>12.2f}%",
            ""
        ])
        
        # Streak information
        report.extend([
            "📊 TRADING STREAKS",
            "-" * 90,
            f"  Losing Streak:        {self.state.losing_streak:>12,}",
            f"  Winning Streak:       {self.state.winning_streak:>12,}",
            f"  Trades Since Peak:    {self.state.trades_since_peak:>12,}",
            ""
        ])
        
        # Protection thresholds
        report.extend([
            "⚙️  PROTECTION THRESHOLDS",
            "-" * 90,
            f"  Caution:              {self.config.caution_threshold_pct:>12.1f}% → {self.config.caution_position_multiplier*100:.0f}% position size",
            f"  Warning:              {self.config.warning_threshold_pct:>12.1f}% → {self.config.warning_position_multiplier*100:.0f}% position size",
            f"  Danger:               {self.config.danger_threshold_pct:>12.1f}% → {self.config.danger_position_multiplier*100:.0f}% position size",
            f"  Halt:                 {self.config.halt_threshold_pct:>12.1f}% → Trading stopped",
            ""
        ])
        
        # Current adjustment
        can_trade, reason = self.can_trade()
        multiplier = self.get_position_size_multiplier()
        
        report.extend([
            "🎯 CURRENT ADJUSTMENT",
            "-" * 90,
            f"  Can Trade:            {'YES ✅' if can_trade else 'NO ❌'}",
            f"  Position Multiplier:  {multiplier*100:>12.0f}%",
            f"  Reason:               {reason}",
            ""
        ])
        
        # Recent protection changes
        if self.protection_changes:
            report.extend([
                "📝 RECENT PROTECTION CHANGES",
                "-" * 90
            ])
            for change in self.protection_changes[-5:]:
                timestamp = datetime.fromisoformat(change['timestamp'])
                report.append(
                    f"  {timestamp.strftime('%Y-%m-%d %H:%M:%S')}: "
                    f"{change['from_level'].upper()} → {change['to_level'].upper()} "
                    f"({change['drawdown_pct']:.2f}% drawdown)"
                )
            report.append("")
        
        report.append("=" * 90 + "\n")
        
        return "\n".join(report)
    
    def update_capital(self, new_capital: float):
        """
        Update capital without recording as a trade
        
        Args:
            new_capital: New capital amount
        """
        self.state.update(new_capital)
        self._update_protection_level()
        self._save_state()
    
    def reset_to_peak(self):
        """Reset drawdown state (use after adding capital)"""
        self.state.peak_capital = self.state.current_capital
        self.state.drawdown_amount = 0.0
        self.state.drawdown_pct = 0.0
        self.state.trades_since_peak = 0
        self.drawdown_start_time = None
        self._update_protection_level()
        self._save_state()
        
        logger.info("✅ Drawdown state reset to current capital as new peak")


def get_drawdown_protection(base_capital: float,
                            halt_threshold: float = 20.0) -> DrawdownProtectionSystem:
    """
    Get or create drawdown protection system instance
    
    Args:
        base_capital: Base capital to protect
        halt_threshold: Drawdown % at which to halt trading
        
    Returns:
        DrawdownProtectionSystem instance
    """
    config = DrawdownConfig(halt_threshold_pct=halt_threshold)
    return DrawdownProtectionSystem(base_capital, config)


if __name__ == "__main__":
    # Test/demonstration
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s - %(message)s'
    )
    
    # Create protection system with $1000 base capital
    protection = get_drawdown_protection(1000.0)
    
    print("\nSimulating trades with drawdown...\n")
    
    # Simulate losing streak
    capital = 1000.0
    for i in range(5):
        capital -= 40  # $40 loss each
        protection.record_trade(capital, is_win=False)
    
    print(protection.get_protection_report())
    
    # Simulate recovery
    print("\nSimulating recovery...\n")
    for i in range(3):
        capital += 30  # $30 win each
        protection.record_trade(capital, is_win=True)
    
    print(protection.get_protection_report())
