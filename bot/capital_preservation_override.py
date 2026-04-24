"""
NIJA Capital Preservation Override Layer
=========================================

The ultimate safety layer that overrides all other trading systems when
capital is at risk. This is the "emergency brake" for the entire system.

Priority Hierarchy:
1. Capital preservation (THIS LAYER) - Highest priority
2. Drawdown protection
3. Risk management
4. Position sizing
5. Trading signals - Lowest priority

Triggers:
- Catastrophic drawdown (>25%)
- Rapid capital loss (>10% in 24 hours)
- System-wide failures
- Regulatory/compliance issues
- Manual emergency stop

When triggered, this layer:
- Immediately halts all new trades
- Optionally closes existing positions
- Locks capital at preservation floor
- Requires manual reset to resume trading
- Logs all actions for audit

Philosophy:
"Preservation of capital is paramount. A trading system that loses all
capital is worthless. This layer exists to prevent that scenario."

Author: NIJA Trading Systems
Version: 1.0
Date: February 18, 2026
"""

import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import json
from pathlib import Path

logger = logging.getLogger("nija.capital_preservation")


class PreservationMode(Enum):
    """Capital preservation modes"""
    NORMAL = "normal"  # Normal trading operations
    MONITORING = "monitoring"  # Watching for issues
    WARNING = "warning"  # Concerning conditions detected
    PRESERVATION = "preservation"  # Preservation mode active
    LOCKDOWN = "lockdown"  # Complete lockdown, no trading


class TriggerType(Enum):
    """Types of preservation triggers"""
    DRAWDOWN_CATASTROPHIC = "drawdown_catastrophic"
    DRAWDOWN_RAPID = "drawdown_rapid"
    CAPITAL_FLOOR = "capital_floor"
    LOSS_VELOCITY = "loss_velocity"
    SYSTEM_FAILURE = "system_failure"
    MANUAL = "manual"
    COMPLIANCE = "compliance"


@dataclass
class PreservationConfig:
    """Configuration for capital preservation"""
    # Capital floors
    catastrophic_drawdown_pct: float = 25.0  # Trigger at 25% drawdown
    rapid_loss_pct: float = 10.0  # Trigger at 10% loss in timeframe
    rapid_loss_timeframe_hours: float = 24.0  # Timeframe for rapid loss
    absolute_capital_floor_pct: float = 0.85  # Never go below 85% of base
    
    # Loss velocity
    max_loss_per_hour: float = 2.0  # Max 2% loss per hour
    max_loss_per_day: float = 10.0  # Max 10% loss per day
    
    # Position handling
    close_positions_on_trigger: bool = False  # Close positions when triggered
    allow_position_closes_only: bool = True  # Allow closing existing positions
    
    # Recovery requirements
    require_manual_reset: bool = True  # Require manual intervention
    min_review_period_hours: float = 24.0  # Minimum review period before reset
    
    # Notifications
    send_emergency_notifications: bool = True
    notification_channels: List[str] = field(default_factory=lambda: ["email", "sms", "slack"])


@dataclass
class PreservationTrigger:
    """Record of a preservation trigger event"""
    timestamp: str
    trigger_type: TriggerType
    mode_before: PreservationMode
    mode_after: PreservationMode
    capital: float
    peak_capital: float
    drawdown_pct: float
    reason: str
    metadata: Dict = field(default_factory=dict)


@dataclass
class PreservationState:
    """Current preservation system state"""
    mode: PreservationMode = PreservationMode.NORMAL
    triggered: bool = False
    trigger_time: Optional[datetime] = None
    trigger_reason: str = ""
    trigger_type: Optional[TriggerType] = None
    
    # Capital tracking
    base_capital: float = 0.0
    current_capital: float = 0.0
    peak_capital: float = 0.0
    preservation_floor: float = 0.0
    
    # Loss velocity tracking
    losses_last_hour: List[float] = field(default_factory=list)
    losses_last_day: List[float] = field(default_factory=list)
    
    # Status
    can_trade: bool = True
    can_close_positions: bool = True
    requires_manual_reset: bool = False
    last_check_time: Optional[datetime] = None


class CapitalPreservationOverride:
    """
    Ultimate capital protection layer.
    
    This is the highest priority safety system. When triggered, it overrides
    all other systems to protect capital.
    
    Responsibilities:
    1. Monitor for catastrophic conditions
    2. Trigger preservation mode when necessary
    3. Halt trading operations
    4. Manage position closures
    5. Enforce capital floors
    6. Require manual intervention for reset
    7. Maintain audit trail
    """
    
    # Data persistence
    DATA_DIR = Path(__file__).parent.parent / "data"
    STATE_FILE = DATA_DIR / "capital_preservation.json"
    TRIGGERS_FILE = DATA_DIR / "preservation_triggers.json"
    
    def __init__(
        self,
        base_capital: float,
        config: Optional[PreservationConfig] = None
    ):
        """
        Initialize Capital Preservation Override Layer.
        
        Args:
            base_capital: Base capital to protect
            config: Optional configuration
        """
        self.config = config or PreservationConfig()
        
        # Initialize state
        self.state = PreservationState(
            base_capital=base_capital,
            current_capital=base_capital,
            peak_capital=base_capital,
            preservation_floor=base_capital * self.config.absolute_capital_floor_pct
        )
        
        # Trigger history
        self.triggers: List[PreservationTrigger] = []
        
        # Ensure data directory exists
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        
        # Load existing state
        self._load_state()
        
        logger.critical("=" * 80)
        logger.critical("🛡️  CAPITAL PRESERVATION OVERRIDE LAYER INITIALIZED")
        logger.critical("=" * 80)
        logger.critical(f"Base Capital: ${base_capital:,.2f}")
        logger.critical(f"Preservation Floor: ${self.state.preservation_floor:,.2f}")
        logger.critical(f"Catastrophic DD Trigger: {self.config.catastrophic_drawdown_pct}%")
        logger.critical(f"Rapid Loss Trigger: {self.config.rapid_loss_pct}% in {self.config.rapid_loss_timeframe_hours}h")
        logger.critical(f"Manual Reset Required: {self.config.require_manual_reset}")
        logger.critical("=" * 80)
    
    def _load_state(self):
        """Load state from persistent storage"""
        if self.STATE_FILE.exists():
            try:
                with open(self.STATE_FILE, 'r') as f:
                    data = json.load(f)
                
                self.state.mode = PreservationMode(data.get('mode', 'normal'))
                self.state.triggered = data.get('triggered', False)
                self.state.current_capital = data.get('current_capital', self.state.base_capital)
                self.state.peak_capital = data.get('peak_capital', self.state.base_capital)
                self.state.can_trade = data.get('can_trade', True)
                self.state.requires_manual_reset = data.get('requires_manual_reset', False)
                
                if data.get('trigger_time'):
                    self.state.trigger_time = datetime.fromisoformat(data['trigger_time'])
                
                logger.info(f"✅ Loaded preservation state: Mode={self.state.mode.value}")
            except Exception as e:
                logger.error(f"Failed to load preservation state: {e}")
        
        # Load triggers
        if self.TRIGGERS_FILE.exists():
            try:
                with open(self.TRIGGERS_FILE, 'r') as f:
                    trigger_data = json.load(f)
                    self.triggers = [
                        PreservationTrigger(**t) for t in trigger_data
                    ]
                logger.info(f"✅ Loaded {len(self.triggers)} preservation triggers")
            except Exception as e:
                logger.error(f"Failed to load preservation triggers: {e}")
    
    def _save_state(self):
        """Save state to persistent storage"""
        try:
            data = {
                'mode': self.state.mode.value,
                'triggered': self.state.triggered,
                'trigger_time': self.state.trigger_time.isoformat() if self.state.trigger_time else None,
                'trigger_reason': self.state.trigger_reason,
                'trigger_type': self.state.trigger_type.value if self.state.trigger_type else None,
                'base_capital': self.state.base_capital,
                'current_capital': self.state.current_capital,
                'peak_capital': self.state.peak_capital,
                'preservation_floor': self.state.preservation_floor,
                'can_trade': self.state.can_trade,
                'can_close_positions': self.state.can_close_positions,
                'requires_manual_reset': self.state.requires_manual_reset,
                'last_updated': datetime.now().isoformat()
            }
            
            with open(self.STATE_FILE, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.debug("💾 Preservation state saved")
        except Exception as e:
            logger.error(f"Failed to save preservation state: {e}")
    
    def _save_triggers(self):
        """Save trigger history"""
        try:
            trigger_data = [
                {
                    'timestamp': t.timestamp,
                    'trigger_type': t.trigger_type.value,
                    'mode_before': t.mode_before.value,
                    'mode_after': t.mode_after.value,
                    'capital': t.capital,
                    'peak_capital': t.peak_capital,
                    'drawdown_pct': t.drawdown_pct,
                    'reason': t.reason,
                    'metadata': t.metadata
                }
                for t in self.triggers
            ]
            
            with open(self.TRIGGERS_FILE, 'w') as f:
                json.dump(trigger_data, f, indent=2)
            
            logger.debug("💾 Preservation triggers saved")
        except Exception as e:
            logger.error(f"Failed to save preservation triggers: {e}")
    
    def check_preservation_triggers(
        self,
        current_capital: float,
        recent_loss: Optional[float] = None
    ) -> Tuple[bool, Optional[TriggerType], str]:
        """
        Check all preservation triggers.
        
        Args:
            current_capital: Current capital amount
            recent_loss: Recent loss amount (optional)
            
        Returns:
            Tuple of (triggered, trigger_type, reason)
        """
        # Update capital
        self.state.current_capital = current_capital
        self.state.last_check_time = datetime.now()
        
        # Update peak
        if current_capital > self.state.peak_capital:
            self.state.peak_capital = current_capital
        
        # Calculate drawdown
        drawdown_pct = 0.0
        if self.state.peak_capital > 0:
            drawdown_pct = ((self.state.peak_capital - current_capital) / 
                           self.state.peak_capital * 100)
        
        # Track recent loss
        if recent_loss is not None and recent_loss > 0:
            now = datetime.now()
            self.state.losses_last_hour.append({
                'timestamp': now,
                'loss': recent_loss
            })
            self.state.losses_last_day.append({
                'timestamp': now,
                'loss': recent_loss
            })
            
            # Clean old losses
            cutoff_hour = now - timedelta(hours=1)
            cutoff_day = now - timedelta(hours=24)
            self.state.losses_last_hour = [
                l for l in self.state.losses_last_hour
                if l['timestamp'] >= cutoff_hour
            ]
            self.state.losses_last_day = [
                l for l in self.state.losses_last_day
                if l['timestamp'] >= cutoff_day
            ]
        
        # Check triggers (in order of severity)
        
        # 1. Capital floor breach
        if current_capital <= self.state.preservation_floor:
            return (
                True,
                TriggerType.CAPITAL_FLOOR,
                f"Capital ${current_capital:,.2f} at/below preservation floor ${self.state.preservation_floor:,.2f}"
            )
        
        # 2. Catastrophic drawdown
        if drawdown_pct >= self.config.catastrophic_drawdown_pct:
            return (
                True,
                TriggerType.DRAWDOWN_CATASTROPHIC,
                f"Catastrophic drawdown: {drawdown_pct:.2f}% (trigger: {self.config.catastrophic_drawdown_pct}%)"
            )
        
        # 3. Rapid loss in timeframe
        loss_in_timeframe = sum(l['loss'] for l in self.state.losses_last_day)
        loss_pct = (loss_in_timeframe / self.state.peak_capital * 100) if self.state.peak_capital > 0 else 0
        
        if loss_pct >= self.config.rapid_loss_pct:
            return (
                True,
                TriggerType.DRAWDOWN_RAPID,
                f"Rapid loss: {loss_pct:.2f}% in {self.config.rapid_loss_timeframe_hours}h (trigger: {self.config.rapid_loss_pct}%)"
            )
        
        # 4. Loss velocity
        hourly_loss = sum(l['loss'] for l in self.state.losses_last_hour)
        hourly_loss_pct = (hourly_loss / self.state.peak_capital * 100) if self.state.peak_capital > 0 else 0
        
        if hourly_loss_pct >= self.config.max_loss_per_hour:
            return (
                True,
                TriggerType.LOSS_VELOCITY,
                f"Loss velocity: {hourly_loss_pct:.2f}%/hour (trigger: {self.config.max_loss_per_hour}%)"
            )
        
        return (False, None, "No preservation triggers")
    
    def trigger_preservation(
        self,
        trigger_type: TriggerType,
        reason: str,
        mode: PreservationMode = PreservationMode.PRESERVATION,
        metadata: Optional[Dict] = None
    ):
        """
        Trigger preservation mode.
        
        Args:
            trigger_type: Type of trigger
            reason: Reason for trigger
            mode: Preservation mode to enter
            metadata: Additional metadata
        """
        old_mode = self.state.mode
        
        # Update state
        self.state.triggered = True
        self.state.trigger_time = datetime.now()
        self.state.trigger_reason = reason
        self.state.trigger_type = trigger_type
        self.state.mode = mode
        self.state.can_trade = False
        self.state.can_close_positions = self.config.allow_position_closes_only
        self.state.requires_manual_reset = self.config.require_manual_reset
        
        # Calculate drawdown
        drawdown_pct = 0.0
        if self.state.peak_capital > 0:
            drawdown_pct = ((self.state.peak_capital - self.state.current_capital) / 
                           self.state.peak_capital * 100)
        
        # Record trigger
        trigger = PreservationTrigger(
            timestamp=datetime.now().isoformat(),
            trigger_type=trigger_type,
            mode_before=old_mode,
            mode_after=mode,
            capital=self.state.current_capital,
            peak_capital=self.state.peak_capital,
            drawdown_pct=drawdown_pct,
            reason=reason,
            metadata=metadata or {}
        )
        
        self.triggers.append(trigger)
        
        # Save state
        self._save_state()
        self._save_triggers()
        
        # Log critical alert
        logger.critical("🚨" * 40)
        logger.critical("CAPITAL PRESERVATION MODE TRIGGERED")
        logger.critical("🚨" * 40)
        logger.critical(f"Trigger Type: {trigger_type.value.upper()}")
        logger.critical(f"Mode: {old_mode.value.upper()} → {mode.value.upper()}")
        logger.critical(f"Reason: {reason}")
        logger.critical(f"Capital: ${self.state.current_capital:,.2f}")
        logger.critical(f"Peak: ${self.state.peak_capital:,.2f}")
        logger.critical(f"Drawdown: {drawdown_pct:.2f}%")
        logger.critical(f"Trading: {'DISABLED' if not self.state.can_trade else 'ENABLED'}")
        logger.critical(f"Manual Reset: {'REQUIRED' if self.state.requires_manual_reset else 'NOT REQUIRED'}")
        logger.critical("🚨" * 40)
        
        # Send notifications
        if self.config.send_emergency_notifications:
            self._send_notifications(trigger)
    
    def _send_notifications(self, trigger: PreservationTrigger):
        """Send emergency notifications"""
        # TODO: Implement actual notification sending
        logger.critical(f"📧 Emergency notifications sent via: {', '.join(self.config.notification_channels)}")
    
    def can_trade(self) -> Tuple[bool, str]:
        """
        Check if trading is allowed.
        
        Returns:
            Tuple of (allowed, reason)
        """
        if not self.state.can_trade:
            return (
                False,
                f"Capital preservation mode active: {self.state.mode.value} - {self.state.trigger_reason}"
            )
        
        return (True, "Trading allowed")
    
    def can_open_position(self) -> Tuple[bool, str]:
        """Check if new positions can be opened"""
        return self.can_trade()
    
    def can_close_position(self) -> Tuple[bool, str]:
        """Check if positions can be closed"""
        if not self.state.can_close_positions:
            return (False, "Position closing disabled in preservation mode")
        return (True, "Position closing allowed")
    
    def manual_reset(self, reset_by: str, notes: str = "") -> bool:
        """
        Manually reset preservation mode.
        
        Args:
            reset_by: Who is resetting (username/system)
            notes: Notes about the reset
            
        Returns:
            True if reset successful
        """
        if not self.state.triggered:
            logger.warning("No active preservation trigger to reset")
            return False
        
        # Check minimum review period
        if self.state.trigger_time:
            elapsed = datetime.now() - self.state.trigger_time
            min_period = timedelta(hours=self.config.min_review_period_hours)
            
            if elapsed < min_period:
                remaining = min_period - elapsed
                logger.warning(
                    f"Cannot reset yet - minimum review period not met. "
                    f"Remaining: {remaining.total_seconds()/3600:.1f} hours"
                )
                return False
        
        # Reset state
        old_mode = self.state.mode
        self.state.triggered = False
        self.state.mode = PreservationMode.NORMAL
        self.state.can_trade = True
        self.state.can_close_positions = True
        self.state.requires_manual_reset = False
        self.state.trigger_type = None
        
        # Save state
        self._save_state()
        
        # Log reset
        logger.warning("=" * 80)
        logger.warning("CAPITAL PRESERVATION MODE RESET")
        logger.warning("=" * 80)
        logger.warning(f"Reset By: {reset_by}")
        logger.warning(f"Previous Mode: {old_mode.value.upper()}")
        logger.warning(f"Notes: {notes}")
        logger.warning(f"Capital: ${self.state.current_capital:,.2f}")
        logger.warning("=" * 80)
        
        return True
    
    def update_capital(self, new_capital: float):
        """Update capital and check triggers"""
        triggered, trigger_type, reason = self.check_preservation_triggers(new_capital)
        
        if triggered and not self.state.triggered:
            self.trigger_preservation(trigger_type, reason)
    
    def get_status_report(self) -> str:
        """Generate status report"""
        drawdown_pct = 0.0
        if self.state.peak_capital > 0:
            drawdown_pct = ((self.state.peak_capital - self.state.current_capital) / 
                           self.state.peak_capital * 100)
        
        lines = [
            "\n" + "=" * 80,
            "CAPITAL PRESERVATION OVERRIDE STATUS",
            "=" * 80,
            f"Mode: {self.state.mode.value.upper()}",
            f"Triggered: {'YES ⚠️' if self.state.triggered else 'NO ✅'}",
            "",
            "💰 CAPITAL",
            "-" * 80,
            f"  Current:              ${self.state.current_capital:>15,.2f}",
            f"  Peak:                 ${self.state.peak_capital:>15,.2f}",
            f"  Base:                 ${self.state.base_capital:>15,.2f}",
            f"  Preservation Floor:   ${self.state.preservation_floor:>15,.2f}",
            f"  Drawdown:             {drawdown_pct:>15.2f}%",
            "",
            "🚦 PERMISSIONS",
            "-" * 80,
            f"  Can Trade:            {'YES ✅' if self.state.can_trade else 'NO ❌'}",
            f"  Can Close Positions:  {'YES ✅' if self.state.can_close_positions else 'NO ❌'}",
            f"  Manual Reset Needed:  {'YES ⚠️' if self.state.requires_manual_reset else 'NO'}",
            ""
        ]
        
        if self.state.triggered:
            lines.extend([
                "⚠️  TRIGGER DETAILS",
                "-" * 80,
                f"  Trigger Type:         {self.state.trigger_type.value if self.state.trigger_type else 'N/A'}",
                f"  Trigger Time:         {self.state.trigger_time.strftime('%Y-%m-%d %H:%M:%S') if self.state.trigger_time else 'N/A'}",
                f"  Reason:               {self.state.trigger_reason}",
                ""
            ])
        
        if self.triggers:
            lines.extend([
                "📝 RECENT TRIGGERS",
                "-" * 80
            ])
            for trigger in self.triggers[-5:]:
                lines.append(
                    f"  {trigger.timestamp}: {trigger.trigger_type.value} - {trigger.reason}"
                )
            lines.append("")
        
        lines.append("=" * 80 + "\n")
        
        return "\n".join(lines)


def create_preservation_override(
    base_capital: float,
    config: Optional[PreservationConfig] = None
) -> CapitalPreservationOverride:
    """
    Factory function to create capital preservation override.
    
    Args:
        base_capital: Base capital to protect
        config: Optional configuration
        
    Returns:
        CapitalPreservationOverride instance
    """
    return CapitalPreservationOverride(base_capital, config)


if __name__ == "__main__":
    # Test/demonstration
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s - %(message)s'
    )
    
    # Create preservation system
    preservation = create_preservation_override(10_000.0)
    print(preservation.get_status_report())
    
    # Simulate catastrophic loss
    print("\n🔥 Simulating catastrophic loss...")
    preservation.update_capital(7_000.0)  # 30% loss
    
    print(preservation.get_status_report())
    
    # Try to trade
    can_trade, reason = preservation.can_trade()
    print(f"\nCan trade? {can_trade}")
    print(f"Reason: {reason}")
