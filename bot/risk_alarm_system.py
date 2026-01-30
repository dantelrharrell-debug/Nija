"""
NIJA Risk Alarm System

Comprehensive risk monitoring and alarm system for NIJA trading bot.
Monitors risk conditions and triggers alarms when thresholds are breached.

Features:
- Real-time risk monitoring
- Configurable alarm thresholds
- Multiple alarm severity levels
- Alarm notification system
- Historical alarm logging
- Integration with existing monitoring
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

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, asdict
from enum import Enum

logger = logging.getLogger(__name__)


class AlarmSeverity(Enum):
    """Alarm severity levels"""
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


class AlarmCategory(Enum):
    """Alarm categories"""
    BALANCE = "BALANCE"
    DRAWDOWN = "DRAWDOWN"
    POSITION = "POSITION"
    TRADE_PERFORMANCE = "TRADE_PERFORMANCE"
    VOLATILITY = "VOLATILITY"
    SYSTEM = "SYSTEM"
    API = "API"
    STRATEGY = "STRATEGY"


@dataclass
class AlarmThreshold:
    """Alarm threshold configuration"""
    name: str
    category: str
    severity: str
    threshold_value: float
    comparison: str  # 'gt', 'lt', 'gte', 'lte', 'eq'
    enabled: bool = True
    description: str = ""


@dataclass
class Alarm:
    """Alarm event"""
    alarm_id: str
    timestamp: str
    severity: str
    category: str
    name: str
    message: str
    current_value: float
    threshold_value: float
    metadata: Dict[str, Any]
    acknowledged: bool = False
    acknowledged_at: Optional[str] = None
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
    Comprehensive risk alarm system.
    
    Monitors risk conditions and triggers alarms when:
    - Balance drops below threshold
    - Drawdown exceeds limit
    - Position size too large
    - Win rate drops too low
    - Consecutive losses exceed limit
    - Volatility spikes
    - API errors occur
    - System health degrades
    """
    
    def __init__(self, data_dir: str = "/tmp/nija_alarms"):
        """
        Initialize risk alarm system.
        
        Args:
            data_dir: Directory to store alarm data
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.alarms_file = self.data_dir / "alarms.json"
        self.config_file = self.data_dir / "alarm_config.json"
        
        # Alarm storage
        self.active_alarms: List[Alarm] = []
        self.alarm_history: List[Alarm] = []
        self.thresholds: Dict[str, AlarmThreshold] = {}
        
        # Alarm callbacks
        self.alarm_callbacks: List[Callable] = []
        
        # Initialize default thresholds
        self._initialize_default_thresholds()
        
        # Load existing data
        self._load_data()
        
        logger.info("✅ Risk Alarm System initialized")
    
    def _initialize_default_thresholds(self):
        """Initialize default alarm thresholds"""
        defaults = [
            # Balance alarms
            AlarmThreshold(
                name="critical_balance",
                category=AlarmCategory.BALANCE.value,
                severity=AlarmSeverity.CRITICAL.value,
                threshold_value=50.0,
                comparison='lt',
                description="Balance below $50"
            ),
            AlarmThreshold(
                name="low_balance",
                category=AlarmCategory.BALANCE.value,
                severity=AlarmSeverity.WARNING.value,
                threshold_value=100.0,
                comparison='lt',
                description="Balance below $100"
            ),
            
            # Drawdown alarms
            AlarmThreshold(
                name="max_drawdown",
                category=AlarmCategory.DRAWDOWN.value,
                severity=AlarmSeverity.CRITICAL.value,
                threshold_value=20.0,
                comparison='gt',
                description="Drawdown exceeds 20%"
            ),
            AlarmThreshold(
                name="high_drawdown",
                category=AlarmCategory.DRAWDOWN.value,
                severity=AlarmSeverity.WARNING.value,
                threshold_value=10.0,
                comparison='gt',
                description="Drawdown exceeds 10%"
            ),
            
            # Performance alarms
            AlarmThreshold(
                name="low_win_rate",
                category=AlarmCategory.TRADE_PERFORMANCE.value,
                severity=AlarmSeverity.WARNING.value,
                threshold_value=40.0,
                comparison='lt',
                description="Win rate below 40%"
            ),
            AlarmThreshold(
                name="critical_win_rate",
                category=AlarmCategory.TRADE_PERFORMANCE.value,
                severity=AlarmSeverity.CRITICAL.value,
                threshold_value=30.0,
                comparison='lt',
                description="Win rate below 30%"
            ),
            AlarmThreshold(
                name="low_profit_factor",
                category=AlarmCategory.TRADE_PERFORMANCE.value,
                severity=AlarmSeverity.WARNING.value,
                threshold_value=1.0,
                comparison='lt',
                description="Profit factor below 1.0"
            ),
            
            # Position alarms
            AlarmThreshold(
                name="excessive_position",
                category=AlarmCategory.POSITION.value,
                severity=AlarmSeverity.WARNING.value,
                threshold_value=10.0,
                comparison='gt',
                description="Position size exceeds 10% of balance"
            ),
            AlarmThreshold(
                name="total_exposure_high",
                category=AlarmCategory.POSITION.value,
                severity=AlarmSeverity.WARNING.value,
                threshold_value=80.0,
                comparison='gt',
                description="Total exposure exceeds 80%"
            ),
            
            # Volatility alarms
            AlarmThreshold(
                name="volatility_spike",
                category=AlarmCategory.VOLATILITY.value,
                severity=AlarmSeverity.WARNING.value,
                threshold_value=50.0,
                comparison='gt',
                description="Volatility spike detected"
            ),
        ]
        
        for threshold in defaults:
            self.thresholds[threshold.name] = threshold
    
    def _load_data(self):
        """Load alarm data from disk"""
        try:
            if self.alarms_file.exists():
                with open(self.alarms_file, 'r') as f:
                    data = json.load(f)
                    self.active_alarms = [Alarm(**a) for a in data.get('active_alarms', [])]
                    self.alarm_history = [Alarm(**a) for a in data.get('alarm_history', [])]
                    logger.info(f"📊 Loaded {len(self.alarm_history)} historical alarms")
            
            if self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    data = json.load(f)
                    for name, threshold_data in data.items():
                        self.thresholds[name] = AlarmThreshold(**threshold_data)
        except Exception as e:
            logger.warning(f"Could not load alarm data: {e}")
    
    def _save_data(self):
        """Save alarm data to disk"""
        try:
            # Save alarms
            alarm_data = {
                'active_alarms': [asdict(a) for a in self.active_alarms],
                'alarm_history': [asdict(a) for a in self.alarm_history[-1000:]],  # Keep last 1000
                'last_updated': datetime.now().isoformat()
            }
            with open(self.alarms_file, 'w') as f:
                json.dump(alarm_data, f, indent=2)
            
            # Save config
            config_data = {name: asdict(t) for name, t in self.thresholds.items()}
            with open(self.config_file, 'w') as f:
                json.dump(config_data, f, indent=2)
        except Exception as e:
            logger.error(f"Could not save alarm data: {e}")
    
    def add_threshold(self, threshold: AlarmThreshold):
        """
        Add or update an alarm threshold.
        
        Args:
            threshold: AlarmThreshold configuration
        """
        self.thresholds[threshold.name] = threshold
        self._save_data()
        logger.info(f"✅ Threshold added: {threshold.name}")
    
    def check_threshold(self, name: str, current_value: float, metadata: Dict = None) -> Optional[Alarm]:
        """
        Check if a threshold is breached.
        
        Args:
            name: Threshold name
            current_value: Current value to check
            metadata: Additional alarm metadata
            
        Returns:
            Alarm if threshold breached, None otherwise
        """
        if name not in self.thresholds:
            return None
        
        threshold = self.thresholds[name]
        
        if not threshold.enabled:
            return None
        
        # Check threshold
        breached = False
        if threshold.comparison == 'gt':
            breached = current_value > threshold.threshold_value
        elif threshold.comparison == 'lt':
            breached = current_value < threshold.threshold_value
        elif threshold.comparison == 'gte':
            breached = current_value >= threshold.threshold_value
        elif threshold.comparison == 'lte':
            breached = current_value <= threshold.threshold_value
        elif threshold.comparison == 'eq':
            breached = current_value == threshold.threshold_value
        
        if breached:
            return self._create_alarm(
                name=threshold.name,
                severity=threshold.severity,
                category=threshold.category,
                message=threshold.description,
                current_value=current_value,
                threshold_value=threshold.threshold_value,
                metadata=metadata or {}
            )
        
        return None
    
    def _create_alarm(self, name: str, severity: str, category: str, message: str,
                      current_value: float, threshold_value: float, metadata: Dict) -> Alarm:
        """Create and register an alarm"""
        alarm_id = f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        alarm = Alarm(
            alarm_id=alarm_id,
            timestamp=datetime.now().isoformat(),
            severity=severity,
            category=category,
            name=name,
            message=message,
            current_value=current_value,
            threshold_value=threshold_value,
            metadata=metadata
        )
        
        self.active_alarms.append(alarm)
        self.alarm_history.append(alarm)
        
        # Trigger callbacks
        for callback in self.alarm_callbacks:
            try:
                callback(alarm)
            except Exception as e:
                logger.error(f"Error in alarm callback: {e}")
        
        # Log based on severity
        if severity == AlarmSeverity.EMERGENCY.value:
            logger.critical(f"🚨 EMERGENCY: {message} (Current: {current_value}, Threshold: {threshold_value})")
        elif severity == AlarmSeverity.CRITICAL.value:
            logger.error(f"🔴 CRITICAL: {message} (Current: {current_value}, Threshold: {threshold_value})")
        elif severity == AlarmSeverity.WARNING.value:
            logger.warning(f"⚠️ WARNING: {message} (Current: {current_value}, Threshold: {threshold_value})")
        else:
            logger.info(f"ℹ️ INFO: {message} (Current: {current_value}, Threshold: {threshold_value})")
        
        self._save_data()
        return alarm
    
    def acknowledge_alarm(self, alarm_id: str):
        """
        Acknowledge an alarm.
        
        Args:
            alarm_id: Alarm ID to acknowledge
        """
        for alarm in self.active_alarms:
            if alarm.alarm_id == alarm_id:
                alarm.acknowledged = True
                alarm.acknowledged_at = datetime.now().isoformat()
                logger.info(f"✅ Alarm acknowledged: {alarm_id}")
                break
        
        self._save_data()
    
    def clear_alarm(self, alarm_id: str):
        """
        Clear an active alarm.
        
        Args:
            alarm_id: Alarm ID to clear
        """
        self.active_alarms = [a for a in self.active_alarms if a.alarm_id != alarm_id]
        self._save_data()
        logger.info(f"✅ Alarm cleared: {alarm_id}")
    
    def clear_all_acknowledged(self):
        """Clear all acknowledged alarms"""
        before_count = len(self.active_alarms)
        self.active_alarms = [a for a in self.active_alarms if not a.acknowledged]
        cleared_count = before_count - len(self.active_alarms)
        self._save_data()
        logger.info(f"✅ Cleared {cleared_count} acknowledged alarms")
    
    def register_callback(self, callback: Callable):
        """
        Register a callback to be called when alarms are triggered.
        
        Args:
            callback: Function that accepts an Alarm object
        """
        self.alarm_callbacks.append(callback)
    
    def get_active_alarms(self, severity: str = None, category: str = None) -> List[Alarm]:
        """
        Get active alarms.
        
        Args:
            severity: Filter by severity (optional)
            category: Filter by category (optional)
            
        Returns:
            List of active alarms
        """
        alarms = self.active_alarms
        
        if severity:
            alarms = [a for a in alarms if a.severity == severity]
        
        if category:
            alarms = [a for a in alarms if a.category == category]
        
        return alarms
    
    def get_alarm_summary(self) -> Dict[str, Any]:
        """
        Get alarm summary.
        
        Returns:
            Dictionary with alarm statistics
        """
        active_by_severity = {}
        for severity in AlarmSeverity:
            count = len([a for a in self.active_alarms if a.severity == severity.value])
            active_by_severity[severity.value] = count
        
        active_by_category = {}
        for category in AlarmCategory:
            count = len([a for a in self.active_alarms if a.category == category.value])
            active_by_category[category.value] = count
        
        return {
            'total_active': len(self.active_alarms),
            'total_acknowledged': len([a for a in self.active_alarms if a.acknowledged]),
            'active_by_severity': active_by_severity,
            'active_by_category': active_by_category,
            'total_historical': len(self.alarm_history),
            'last_alarm': self.alarm_history[-1].timestamp if self.alarm_history else None
        }
    
    def check_balance_alarms(self, current_balance: float, peak_balance: float):
        """
        Check balance-related alarms.
        
        Args:
            current_balance: Current account balance
            peak_balance: Peak balance achieved
        """
        self.check_threshold('critical_balance', current_balance)
        self.check_threshold('low_balance', current_balance)
        
        # Check for significant balance drop
        if peak_balance > 0:
            drop_pct = (peak_balance - current_balance) / peak_balance * 100
            if drop_pct >= 20:
                self._create_alarm(
                    name="balance_drop",
                    severity=AlarmSeverity.WARNING.value,
                    category=AlarmCategory.BALANCE.value,
                    message=f"Balance dropped {drop_pct:.1f}% from peak",
                    current_value=current_balance,
                    threshold_value=peak_balance,
                    metadata={'drop_pct': drop_pct}
                )
    
    def check_drawdown_alarms(self, current_drawdown: float, max_drawdown: float):
        """
        Check drawdown-related alarms.
        
        Args:
            current_drawdown: Current drawdown percentage
            max_drawdown: Maximum drawdown percentage
        """
        self.check_threshold('high_drawdown', current_drawdown)
        self.check_threshold('max_drawdown', current_drawdown)
    
    def check_performance_alarms(self, win_rate: float, profit_factor: float):
        """
        Check performance-related alarms.
        
        Args:
            win_rate: Current win rate percentage
            profit_factor: Current profit factor
        """
        self.check_threshold('low_win_rate', win_rate)
        self.check_threshold('critical_win_rate', win_rate)
        self.check_threshold('low_profit_factor', profit_factor)
    
    def check_position_alarms(self, position_size_pct: float, total_exposure_pct: float):
        """
        Check position-related alarms.
        
        Args:
            position_size_pct: Position size as percentage of balance
            total_exposure_pct: Total exposure as percentage of balance
        """
        self.check_threshold('excessive_position', position_size_pct)
        self.check_threshold('total_exposure_high', total_exposure_pct)


# Global risk alarm system instance
_risk_alarm_system: Optional[RiskAlarmSystem] = None


def get_risk_alarm_system(reset: bool = False) -> RiskAlarmSystem:
    """
    Get or create the global risk alarm system instance.
    
    Args:
        reset: Force reset and create new instance
        
    Returns:
        RiskAlarmSystem instance
    """
    global _risk_alarm_system
    
    if _risk_alarm_system is None or reset:
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


if __name__ == "__main__":
    # Test the risk alarm system
    logging.basicConfig(level=logging.INFO)
    
    print("Testing Risk Alarm System...")
    
    alarm_system = get_risk_alarm_system()
    
    # Test balance alarms
    print("\n--- Testing Balance Alarms ---")
    alarm_system.check_balance_alarms(45.0, 100.0)
    
    # Test drawdown alarms
    print("\n--- Testing Drawdown Alarms ---")
    alarm_system.check_drawdown_alarms(15.0, 15.0)
    
    # Test performance alarms
    print("\n--- Testing Performance Alarms ---")
    alarm_system.check_performance_alarms(35.0, 0.8)
    
    # Get summary
    print("\n--- Alarm Summary ---")
    summary = alarm_system.get_alarm_summary()
    print(json.dumps(summary, indent=2))
    
    # Get active alarms
    print("\n--- Active Alarms ---")
    active = alarm_system.get_active_alarms()
    for alarm in active:
        print(f"[{alarm.severity}] {alarm.name}: {alarm.message}")
    
    print(f"\n✅ Risk alarm system test complete!")
    print(f"📁 Data saved to: {alarm_system.data_dir}")
def reset_risk_alarm_system():
    """Reset global risk alarm system"""
    global _risk_alarm_system
    _risk_alarm_system = None
    logger.warning("⚠️ Risk Alarm System reset")
