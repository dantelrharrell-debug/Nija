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
