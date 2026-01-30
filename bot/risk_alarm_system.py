"""
NIJA Risk Alarm System

Proactive risk monitoring and alerting system.
Triggers alarms when risk thresholds are breached.

Risk Monitors:
- Drawdown limits (max drawdown exceeded)
- Daily loss limits
- Position size limits
- Total exposure limits
- Consecutive loss streaks
- Win rate degradation
- Volatility spikes
- Account balance thresholds

Notification Channels:
- Console logging
- File logging
- Webhook ready (easily extendable)
- Email ready (easily extendable)

Author: NIJA Trading Systems
Version: 1.0
Date: January 30, 2026
"""

import logging
import json
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Callable, Set
from pathlib import Path
from dataclasses import dataclass, asdict
from enum import Enum

try:
    from kpi_tracker import get_kpi_tracker, KPITracker, KPISnapshot
except ImportError:
    from bot.kpi_tracker import get_kpi_tracker, KPITracker, KPISnapshot

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    """Risk alarm severity levels"""
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    EMERGENCY = "EMERGENCY"


class RiskAlarmType(Enum):
    """Types of risk alarms"""
    MAX_DRAWDOWN_EXCEEDED = "MAX_DRAWDOWN_EXCEEDED"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    CONSECUTIVE_LOSSES = "CONSECUTIVE_LOSSES"
    LOW_WIN_RATE = "LOW_WIN_RATE"
    POSITION_SIZE_EXCEEDED = "POSITION_SIZE_EXCEEDED"
    TOTAL_EXPOSURE_EXCEEDED = "TOTAL_EXPOSURE_EXCEEDED"
    ACCOUNT_BALANCE_LOW = "ACCOUNT_BALANCE_LOW"
    VOLATILITY_SPIKE = "VOLATILITY_SPIKE"
    SHARPE_DEGRADATION = "SHARPE_DEGRADATION"
    PROFIT_FACTOR_LOW = "PROFIT_FACTOR_LOW"
    NO_TRADES_PERIOD = "NO_TRADES_PERIOD"
    API_ERROR_RATE_HIGH = "API_ERROR_RATE_HIGH"


@dataclass
class RiskAlarm:
    """Risk alarm data structure"""
    alarm_id: str
    timestamp: str
    level: str
    alarm_type: str
    message: str
    current_value: float
    threshold_value: float
    recommended_action: str
    metadata: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)


class RiskThresholds:
    """Configuration for risk thresholds"""
    
    def __init__(self):
        # Drawdown thresholds
        self.max_drawdown_pct = 20.0  # Maximum acceptable drawdown
        self.warning_drawdown_pct = 15.0  # Warning threshold
        
        # Loss limits
        self.daily_loss_limit_pct = 5.0  # Max daily loss as % of account
        self.consecutive_losses_limit = 5  # Max consecutive losses
        
        # Win rate thresholds
        self.min_win_rate_pct = 50.0  # Minimum acceptable win rate
        self.warning_win_rate_pct = 55.0  # Warning threshold
        
        # Position limits
        self.max_position_size_pct = 10.0  # Max single position as % of account
        self.max_total_exposure_pct = 80.0  # Max total exposure
        
        # Account balance
        self.min_account_balance = 100.0  # Minimum account balance
        self.warning_account_balance = 500.0  # Warning threshold
        
        # Performance metrics
        self.min_sharpe_ratio = 0.5  # Minimum acceptable Sharpe
        self.min_profit_factor = 1.0  # Minimum profit factor
        
        # Trading activity
        self.max_hours_no_trades = 48  # Max hours without trades (for active bot)
        
        # Volatility
        self.max_daily_volatility_pct = 10.0  # Max acceptable daily volatility


class RiskAlarmSystem:
    """
    Proactive risk monitoring and alarm system
    
    Responsibilities:
    - Monitor KPIs against risk thresholds
    - Trigger alarms when thresholds breached
    - Log and persist alarms
    - Provide alarm history
    - Support multiple notification channels
    """
    
    def __init__(
        self,
        kpi_tracker: Optional[KPITracker] = None,
        thresholds: Optional[RiskThresholds] = None,
        data_dir: str = "./data/risk_alarms"
    ):
        """
        Initialize Risk Alarm System
        
        Args:
            kpi_tracker: KPI tracker to monitor
            thresholds: Risk threshold configuration
            data_dir: Directory for alarm data
        """
        self.kpi_tracker = kpi_tracker or get_kpi_tracker()
        self.thresholds = thresholds or RiskThresholds()
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Active alarms (keyed by alarm type)
        self.active_alarms: Dict[RiskAlarmType, RiskAlarm] = {}
        
        # Alarm history
        self.alarm_history: List[RiskAlarm] = []
        
        # Notification callbacks
        self.notification_callbacks: List[Callable[[RiskAlarm], None]] = []
        
        # Thread safety
        self._lock = threading.Lock()
        
        # Suppression (avoid spam)
        self.alarm_cooldown_minutes = 15  # Don't re-trigger same alarm for N minutes
        self.last_alarm_times: Dict[RiskAlarmType, datetime] = {}
        
        # Load previous state
        self._load_state()
        
        logger.info("✅ Risk Alarm System initialized")
    
    def check_all_risks(self, kpi_snapshot: Optional[KPISnapshot] = None):
        """
        Check all risk conditions and trigger alarms as needed
        
        Args:
            kpi_snapshot: KPI snapshot to check (uses latest if None)
        """
        if kpi_snapshot is None:
            kpi_snapshot = self.kpi_tracker.get_current_kpis()
        
        if kpi_snapshot is None:
            logger.warning("No KPI data available for risk checking")
            return
        
        # Check each risk condition
        self._check_drawdown(kpi_snapshot)
        self._check_daily_loss(kpi_snapshot)
        self._check_consecutive_losses(kpi_snapshot)
        self._check_win_rate(kpi_snapshot)
        self._check_position_exposure(kpi_snapshot)
        self._check_account_balance(kpi_snapshot)
        self._check_sharpe_ratio(kpi_snapshot)
        self._check_profit_factor(kpi_snapshot)
    
    def _check_drawdown(self, kpi: KPISnapshot):
        """Check drawdown thresholds"""
        current_dd = kpi.max_drawdown_pct
        
        if current_dd >= self.thresholds.max_drawdown_pct:
            self._trigger_alarm(
                alarm_type=RiskAlarmType.MAX_DRAWDOWN_EXCEEDED,
                level=RiskLevel.EMERGENCY,
                message=f"Maximum drawdown exceeded: {current_dd:.2f}%",
                current_value=current_dd,
                threshold_value=self.thresholds.max_drawdown_pct,
                recommended_action="STOP TRADING IMMEDIATELY - Review strategy and reduce position sizes",
                metadata={'account_value': kpi.account_value}
            )
        elif current_dd >= self.thresholds.warning_drawdown_pct:
            self._trigger_alarm(
                alarm_type=RiskAlarmType.MAX_DRAWDOWN_EXCEEDED,
                level=RiskLevel.WARNING,
                message=f"Drawdown approaching limit: {current_dd:.2f}%",
                current_value=current_dd,
                threshold_value=self.thresholds.warning_drawdown_pct,
                recommended_action="Reduce position sizes and review strategy performance",
                metadata={'account_value': kpi.account_value}
            )
        else:
            # Clear alarm if it exists
            self._clear_alarm(RiskAlarmType.MAX_DRAWDOWN_EXCEEDED)
    
    def _check_daily_loss(self, kpi: KPISnapshot):
        """Check daily loss limits"""
        daily_return = kpi.daily_return_pct
        
        if daily_return < -self.thresholds.daily_loss_limit_pct:
            self._trigger_alarm(
                alarm_type=RiskAlarmType.DAILY_LOSS_LIMIT,
                level=RiskLevel.CRITICAL,
                message=f"Daily loss limit exceeded: {daily_return:.2f}%",
                current_value=abs(daily_return),
                threshold_value=self.thresholds.daily_loss_limit_pct,
                recommended_action="STOP TRADING for today - Daily loss limit reached",
                metadata={'account_value': kpi.account_value}
            )
        else:
            self._clear_alarm(RiskAlarmType.DAILY_LOSS_LIMIT)
    
    def _check_consecutive_losses(self, kpi: KPISnapshot):
        """Check consecutive loss streak"""
        # Note: This would need actual streak tracking in KPI tracker
        # For now, using a simple heuristic
        if kpi.losing_trades > kpi.winning_trades and kpi.total_trades > 10:
            recent_loss_rate = kpi.losing_trades / kpi.total_trades
            
            if recent_loss_rate > 0.7:  # 70% loss rate
                self._trigger_alarm(
                    alarm_type=RiskAlarmType.CONSECUTIVE_LOSSES,
                    level=RiskLevel.CRITICAL,
                    message=f"High loss rate detected: {recent_loss_rate*100:.1f}%",
                    current_value=recent_loss_rate * 100,
                    threshold_value=70.0,
                    recommended_action="Review strategy - High loss rate indicates problem",
                    metadata={'win_rate': kpi.win_rate_pct}
                )
    
    def _check_win_rate(self, kpi: KPISnapshot):
        """Check win rate thresholds"""
        if kpi.total_trades < 10:
            return  # Not enough data
        
        win_rate = kpi.win_rate_pct
        
        if win_rate < self.thresholds.min_win_rate_pct:
            self._trigger_alarm(
                alarm_type=RiskAlarmType.LOW_WIN_RATE,
                level=RiskLevel.CRITICAL,
                message=f"Win rate below minimum: {win_rate:.2f}%",
                current_value=win_rate,
                threshold_value=self.thresholds.min_win_rate_pct,
                recommended_action="Strategy not performing - Consider pausing and reviewing",
                metadata={'total_trades': kpi.total_trades}
            )
        elif win_rate < self.thresholds.warning_win_rate_pct:
            self._trigger_alarm(
                alarm_type=RiskAlarmType.LOW_WIN_RATE,
                level=RiskLevel.WARNING,
                message=f"Win rate below target: {win_rate:.2f}%",
                current_value=win_rate,
                threshold_value=self.thresholds.warning_win_rate_pct,
                recommended_action="Monitor closely - Win rate trending down",
                metadata={'total_trades': kpi.total_trades}
            )
        else:
            self._clear_alarm(RiskAlarmType.LOW_WIN_RATE)
    
    def _check_position_exposure(self, kpi: KPISnapshot):
        """Check position size and exposure limits"""
        exposure = kpi.total_exposure_pct
        
        if exposure > self.thresholds.max_total_exposure_pct:
            self._trigger_alarm(
                alarm_type=RiskAlarmType.TOTAL_EXPOSURE_EXCEEDED,
                level=RiskLevel.WARNING,
                message=f"Total exposure too high: {exposure:.2f}%",
                current_value=exposure,
                threshold_value=self.thresholds.max_total_exposure_pct,
                recommended_action="Reduce position sizes or close some positions",
                metadata={'active_positions': kpi.active_positions}
            )
        else:
            self._clear_alarm(RiskAlarmType.TOTAL_EXPOSURE_EXCEEDED)
    
    def _check_account_balance(self, kpi: KPISnapshot):
        """Check account balance thresholds"""
        balance = kpi.account_value
        
        if balance < self.thresholds.min_account_balance:
            self._trigger_alarm(
                alarm_type=RiskAlarmType.ACCOUNT_BALANCE_LOW,
                level=RiskLevel.EMERGENCY,
                message=f"Account balance critically low: ${balance:,.2f}",
                current_value=balance,
                threshold_value=self.thresholds.min_account_balance,
                recommended_action="STOP TRADING - Add funds or risk total loss",
                metadata={'cash_balance': kpi.cash_balance}
            )
        elif balance < self.thresholds.warning_account_balance:
            self._trigger_alarm(
                alarm_type=RiskAlarmType.ACCOUNT_BALANCE_LOW,
                level=RiskLevel.WARNING,
                message=f"Account balance low: ${balance:,.2f}",
                current_value=balance,
                threshold_value=self.thresholds.warning_account_balance,
                recommended_action="Consider reducing position sizes or adding funds",
                metadata={'cash_balance': kpi.cash_balance}
            )
        else:
            self._clear_alarm(RiskAlarmType.ACCOUNT_BALANCE_LOW)
    
    def _check_sharpe_ratio(self, kpi: KPISnapshot):
        """Check Sharpe ratio degradation"""
        if kpi.total_trades < 20:
            return  # Not enough data
        
        sharpe = kpi.sharpe_ratio
        
        if sharpe < self.thresholds.min_sharpe_ratio:
            self._trigger_alarm(
                alarm_type=RiskAlarmType.SHARPE_DEGRADATION,
                level=RiskLevel.WARNING,
                message=f"Sharpe ratio too low: {sharpe:.2f}",
                current_value=sharpe,
                threshold_value=self.thresholds.min_sharpe_ratio,
                recommended_action="Risk-adjusted returns poor - Review strategy",
                metadata={'sortino_ratio': kpi.sortino_ratio}
            )
        else:
            self._clear_alarm(RiskAlarmType.SHARPE_DEGRADATION)
    
    def _check_profit_factor(self, kpi: KPISnapshot):
        """Check profit factor"""
        if kpi.total_trades < 10:
            return
        
        pf = kpi.profit_factor
        
        if pf < self.thresholds.min_profit_factor:
            self._trigger_alarm(
                alarm_type=RiskAlarmType.PROFIT_FACTOR_LOW,
                level=RiskLevel.CRITICAL,
                message=f"Profit factor below 1.0: {pf:.2f}",
                current_value=pf,
                threshold_value=self.thresholds.min_profit_factor,
                recommended_action="Strategy losing money - STOP and review",
                metadata={'avg_win': kpi.avg_win, 'avg_loss': kpi.avg_loss}
            )
        else:
            self._clear_alarm(RiskAlarmType.PROFIT_FACTOR_LOW)
    
    def _trigger_alarm(
        self,
        alarm_type: RiskAlarmType,
        level: RiskLevel,
        message: str,
        current_value: float,
        threshold_value: float,
        recommended_action: str,
        metadata: Dict[str, Any]
    ):
        """Trigger a risk alarm"""
        with self._lock:
            # Check cooldown to avoid spam
            if not self._should_trigger(alarm_type):
                return
            
            # Create alarm
            alarm = RiskAlarm(
                alarm_id=f"{alarm_type.value}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                timestamp=datetime.now().isoformat(),
                level=level.value,
                alarm_type=alarm_type.value,
                message=message,
                current_value=current_value,
                threshold_value=threshold_value,
                recommended_action=recommended_action,
                metadata=metadata
            )
            
            # Store as active alarm
            self.active_alarms[alarm_type] = alarm
            
            # Add to history
            self.alarm_history.append(alarm)
            
            # Update last alarm time
            self.last_alarm_times[alarm_type] = datetime.now()
            
            # Log alarm
            log_func = {
                RiskLevel.INFO: logger.info,
                RiskLevel.WARNING: logger.warning,
                RiskLevel.CRITICAL: logger.error,
                RiskLevel.EMERGENCY: logger.critical
            }.get(level, logger.warning)
            
            log_func(f"🚨 RISK ALARM [{level.value}]: {message}")
            
            # Send notifications
            self._send_notifications(alarm)
            
            # Persist
            self._save_alarm(alarm)
    
    def _clear_alarm(self, alarm_type: RiskAlarmType):
        """Clear an active alarm"""
        with self._lock:
            if alarm_type in self.active_alarms:
                del self.active_alarms[alarm_type]
                logger.info(f"✅ Risk alarm cleared: {alarm_type.value}")
    
    def _should_trigger(self, alarm_type: RiskAlarmType) -> bool:
        """Check if alarm should trigger (cooldown check)"""
        if alarm_type not in self.last_alarm_times:
            return True
        
        last_time = self.last_alarm_times[alarm_type]
        time_since = (datetime.now() - last_time).total_seconds() / 60
        
        return time_since >= self.alarm_cooldown_minutes
    
    def _send_notifications(self, alarm: RiskAlarm):
        """Send alarm through notification channels"""
        for callback in self.notification_callbacks:
            try:
                callback(alarm)
            except Exception as e:
                logger.error(f"Error in notification callback: {e}")
    
    def add_notification_callback(self, callback: Callable[[RiskAlarm], None]):
        """Add a notification callback"""
        self.notification_callbacks.append(callback)
        logger.info(f"✅ Notification callback added: {callback.__name__}")
    
    def get_active_alarms(self) -> List[RiskAlarm]:
        """Get all active alarms"""
        with self._lock:
            return list(self.active_alarms.values())
    
    def get_alarm_history(self, hours: int = 24) -> List[RiskAlarm]:
        """Get alarm history for specified period"""
        with self._lock:
            cutoff_time = datetime.now() - timedelta(hours=hours)
            
            return [
                alarm for alarm in self.alarm_history
                if datetime.fromisoformat(alarm.timestamp) >= cutoff_time
            ]
    
    def _save_alarm(self, alarm: RiskAlarm):
        """Save alarm to file"""
        try:
            # Save to daily log file
            date_str = datetime.now().strftime("%Y%m%d")
            log_file = self.data_dir / f"alarms_{date_str}.jsonl"
            
            with open(log_file, 'a') as f:
                f.write(json.dumps(alarm.to_dict()) + '\n')
            
        except Exception as e:
            logger.error(f"Error saving alarm: {e}")
    
    def _save_state(self):
        """Save alarm system state"""
        try:
            state_file = self.data_dir / "alarm_state.json"
            
            state = {
                'active_alarms': {k.value: v.to_dict() for k, v in self.active_alarms.items()},
                'last_updated': datetime.now().isoformat()
            }
            
            with open(state_file, 'w') as f:
                json.dump(state, f, indent=2)
            
        except Exception as e:
            logger.error(f"Error saving alarm state: {e}")
    
    def _load_state(self):
        """Load alarm system state"""
        try:
            state_file = self.data_dir / "alarm_state.json"
            
            if not state_file.exists():
                return
            
            with open(state_file, 'r') as f:
                state = json.load(f)
            
            # Restore active alarms
            for type_str, alarm_dict in state.get('active_alarms', {}).items():
                alarm_type = RiskAlarmType(type_str)
                alarm = RiskAlarm(**alarm_dict)
                self.active_alarms[alarm_type] = alarm
            
            logger.info(f"✅ Loaded {len(self.active_alarms)} active alarms")
            
        except Exception as e:
            logger.error(f"Error loading alarm state: {e}")


# Global singleton
_risk_alarm_system: Optional[RiskAlarmSystem] = None


def get_risk_alarm_system() -> RiskAlarmSystem:
    """Get or create global risk alarm system"""
    global _risk_alarm_system
    
    if _risk_alarm_system is None:
        _risk_alarm_system = RiskAlarmSystem()
    
    return _risk_alarm_system


def reset_risk_alarm_system():
    """Reset global risk alarm system"""
    global _risk_alarm_system
    _risk_alarm_system = None
    logger.warning("⚠️ Risk Alarm System reset")
