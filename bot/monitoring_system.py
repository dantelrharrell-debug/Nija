"""
NIJA Real-Time Monitoring System with Alerts

Monitors bot health, performance, and triggers alerts for critical events.
- Balance monitoring
- Trade execution tracking
- Error rate monitoring
- Performance metrics
- Alert system (console, file, webhook-ready)

Author: NIJA Trading Systems
Version: 1.0
Date: December 19, 2025
"""

import logging
import time
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum

logger = logging.getLogger(__name__)


class AlertLevel(Enum):
    """Alert severity levels"""
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    EMERGENCY = "EMERGENCY"


class AlertType(Enum):
    """Types of alerts"""
    BALANCE_LOW = "BALANCE_LOW"
    BALANCE_DROP = "BALANCE_DROP"
    NO_TRADES = "NO_TRADES"
    HIGH_ERROR_RATE = "HIGH_ERROR_RATE"
    CONSECUTIVE_LOSSES = "CONSECUTIVE_LOSSES"
    LOW_WIN_RATE = "LOW_WIN_RATE"
    API_ERROR = "API_ERROR"
    BOT_STOPPED = "BOT_STOPPED"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    PROFITABILITY_MILESTONE = "PROFITABILITY_MILESTONE"


@dataclass
class Alert:
    """Alert data structure"""
    timestamp: str
    level: str
    alert_type: str
    message: str
    data: Dict[str, Any]


@dataclass
class PerformanceMetrics:
    """Performance tracking"""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_profit: float = 0.0
    total_loss: float = 0.0
    total_fees: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    consecutive_wins: int = 0
    consecutive_losses: int = 0
    last_trade_time: Optional[str] = None
    
    @property
    def win_rate(self) -> float:
        """Calculate win rate percentage"""
        if self.total_trades == 0:
            return 0.0
        return (self.winning_trades / self.total_trades) * 100
    
    @property
    def profit_factor(self) -> float:
        """Calculate profit factor"""
        if self.total_loss == 0:
            return float('inf') if self.total_profit > 0 else 0.0
        return abs(self.total_profit / self.total_loss)
    
    @property
    def net_profit(self) -> float:
        """Calculate net profit after fees"""
        return self.total_profit - self.total_loss - self.total_fees
    
    @property
    def average_win(self) -> float:
        """Average winning trade"""
        if self.winning_trades == 0:
            return 0.0
        return self.total_profit / self.winning_trades
    
    @property
    def average_loss(self) -> float:
        """Average losing trade"""
        if self.losing_trades == 0:
            return 0.0
        return self.total_loss / self.losing_trades
    
    @property
    def risk_reward_ratio(self) -> float:
        """Calculate risk:reward ratio (avg_win / avg_loss)"""
        avg_loss = self.average_loss
        if avg_loss == 0:
            return float('inf') if self.average_win > 0 else 0.0
        return abs(self.average_win / avg_loss)
    
    @property
    def expectancy(self) -> float:
        """
        Calculate expectancy (expected return per trade)
        Formula: (Win Rate × Avg Win) - (Loss Rate × Avg Loss)
        """
        if self.total_trades == 0:
            return 0.0
        win_rate = self.win_rate / 100.0  # Convert to decimal
        loss_rate = 1.0 - win_rate
        return (win_rate * self.average_win) - (loss_rate * self.average_loss)
    
    @property
    def average_loss(self) -> float:
        """Average losing trade"""
        if self.losing_trades == 0:
            return 0.0
        return self.total_loss / self.losing_trades


class MonitoringSystem:
    """
    Real-time monitoring and alerting system for NIJA bot
    
    Features:
    - Balance tracking
    - Performance metrics
    - Alert generation
    - Health checks
    - Automated notifications
    """
    
    def __init__(self, data_dir: str = "/tmp/nija_monitoring"):
        """Initialize monitoring system"""
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.alerts_file = self.data_dir / "alerts.json"
        self.metrics_file = self.data_dir / "metrics.json"
        self.health_file = self.data_dir / "health_status.json"
        
        # Alert thresholds
        self.min_balance_threshold = 50.0  # Alert if balance < $50
        self.balance_drop_threshold = 0.20  # Alert if 20% balance drop
        self.no_trade_threshold_minutes = 60  # Alert if no trades for 60 min
        self.max_error_rate = 0.30  # Alert if >30% errors
        self.min_win_rate = 40.0  # Alert if win rate <40%
        self.max_consecutive_losses = 4  # Alert after 4 losses
        
        # Tracking
        self.alerts: List[Alert] = []
        self.metrics = PerformanceMetrics()
        self.last_balance = 0.0
        self.peak_balance = 0.0
        self.start_balance = 0.0
        self.start_time = datetime.now()
        self.last_health_check = datetime.now()
        self.error_count = 0
        self.api_call_count = 0
        
        # Load existing data
        self._load_state()
        
        logger.info("🔍 Monitoring system initialized")
    
    def _load_state(self):
        """Load monitoring state from disk"""
        try:
            if self.metrics_file.exists():
                with open(self.metrics_file, 'r') as f:
                    data = json.load(f)
                    self.metrics = PerformanceMetrics(**data)
                    logger.info(f"📊 Loaded metrics: {self.metrics.total_trades} trades")
        except Exception as e:
            logger.warning(f"Could not load metrics: {e}")
    
    def _save_state(self):
        """Save monitoring state to disk"""
        try:
            with open(self.metrics_file, 'w') as f:
                json.dump(asdict(self.metrics), f, indent=2)
        except Exception as e:
            logger.error(f"Could not save metrics: {e}")
    
    def update_balance(self, current_balance: float):
        """Update balance and check for alerts"""
        if self.start_balance == 0.0:
            self.start_balance = current_balance
            self.peak_balance = current_balance
        
        # Track peak
        if current_balance > self.peak_balance:
            self.peak_balance = current_balance
            self._create_alert(
                AlertLevel.INFO,
                AlertType.PROFITABILITY_MILESTONE,
                f"🎉 New peak balance: ${current_balance:.2f}",
                {"balance": current_balance, "gain_from_start": current_balance - self.start_balance}
            )
        
        # Check for low balance
        if current_balance < self.min_balance_threshold:
            self._create_alert(
                AlertLevel.CRITICAL,
                AlertType.BALANCE_LOW,
                f"⚠️ Balance critically low: ${current_balance:.2f} (threshold: ${self.min_balance_threshold})",
                {"balance": current_balance, "threshold": self.min_balance_threshold}
            )
        
        # Check for significant drop
        if self.last_balance > 0:
            drop_pct = (self.last_balance - current_balance) / self.last_balance
            if drop_pct >= self.balance_drop_threshold:
                self._create_alert(
                    AlertLevel.WARNING,
                    AlertType.BALANCE_DROP,
                    f"📉 Balance dropped {drop_pct*100:.1f}% from ${self.last_balance:.2f} to ${current_balance:.2f}",
                    {"previous": self.last_balance, "current": current_balance, "drop_pct": drop_pct}
                )
        
        self.last_balance = current_balance
    
    def record_trade(self, symbol: str, profit: float, fees: float, is_win: bool):
        """Record a trade and update metrics"""
        self.metrics.total_trades += 1
        self.metrics.total_fees += fees
        self.metrics.last_trade_time = datetime.now().isoformat()
        
        if is_win:
            self.metrics.winning_trades += 1
            self.metrics.total_profit += profit
            self.metrics.consecutive_wins += 1
            self.metrics.consecutive_losses = 0
            
            if profit > self.metrics.largest_win:
                self.metrics.largest_win = profit
                self._create_alert(
                    AlertLevel.INFO,
                    AlertType.PROFITABILITY_MILESTONE,
                    f"🏆 New largest win: ${profit:.2f} on {symbol}",
                    {"symbol": symbol, "profit": profit}
                )
        else:
            self.metrics.losing_trades += 1
            self.metrics.total_loss += abs(profit)
            self.metrics.consecutive_losses += 1
            self.metrics.consecutive_wins = 0
            
            if abs(profit) > self.metrics.largest_loss:
                self.metrics.largest_loss = abs(profit)
            
            # Alert on consecutive losses
            if self.metrics.consecutive_losses >= self.max_consecutive_losses:
                self._create_alert(
                    AlertLevel.WARNING,
                    AlertType.CONSECUTIVE_LOSSES,
                    f"⚠️ {self.metrics.consecutive_losses} consecutive losses",
                    {"consecutive_losses": self.metrics.consecutive_losses}
                )
        
        # Check win rate
        if self.metrics.total_trades >= 10:  # After 10 trades
            if self.metrics.win_rate < self.min_win_rate:
                self._create_alert(
                    AlertLevel.WARNING,
                    AlertType.LOW_WIN_RATE,
                    f"📊 Win rate low: {self.metrics.win_rate:.1f}% (threshold: {self.min_win_rate}%)",
                    {"win_rate": self.metrics.win_rate, "trades": self.metrics.total_trades}
                )
        
        self._save_state()
        logger.info(f"📈 Trade recorded: {symbol} {'WIN' if is_win else 'LOSS'} ${profit:.2f}")
    
    def record_error(self, error_type: str, error_message: str):
        """Record an error"""
        self.error_count += 1
        
        # Check error rate
        if self.api_call_count > 0:
            error_rate = self.error_count / self.api_call_count
            if error_rate >= self.max_error_rate:
                self._create_alert(
                    AlertLevel.CRITICAL,
                    AlertType.HIGH_ERROR_RATE,
                    f"🚨 High error rate: {error_rate*100:.1f}% ({self.error_count}/{self.api_call_count})",
                    {"error_rate": error_rate, "errors": self.error_count, "calls": self.api_call_count}
                )
        
        # Special handling for API errors
        if "API" in error_type.upper() or "RATE" in error_type.upper():
            self._create_alert(
                AlertLevel.WARNING,
                AlertType.API_ERROR,
                f"⚠️ API Error: {error_message}",
                {"error_type": error_type, "message": error_message}
            )
    
    def record_api_call(self):
        """Record an API call"""
        self.api_call_count += 1
    
    def check_health(self) -> Dict[str, Any]:
        """Perform health check and return status"""
        now = datetime.now()
        uptime = (now - self.start_time).total_seconds()
        
        health_status = {
            "timestamp": now.isoformat(),
            "status": "healthy",
            "uptime_seconds": uptime,
            "balance": {
                "current": self.last_balance,
                "start": self.start_balance,
                "peak": self.peak_balance,
                "change_pct": ((self.last_balance - self.start_balance) / self.start_balance * 100) if self.start_balance > 0 else 0
            },
            "performance": {
                "total_trades": self.metrics.total_trades,
                "win_rate": self.metrics.win_rate,
                "profit_factor": self.metrics.profit_factor,
                "net_profit": self.metrics.net_profit,
                "consecutive_wins": self.metrics.consecutive_wins,
                "consecutive_losses": self.metrics.consecutive_losses
            },
            "errors": {
                "total": self.error_count,
                "rate": (self.error_count / self.api_call_count * 100) if self.api_call_count > 0 else 0
            }
        }
        
        # Check if no recent trades
        if self.metrics.last_trade_time:
            last_trade = datetime.fromisoformat(self.metrics.last_trade_time)
            minutes_since_trade = (now - last_trade).total_seconds() / 60
            
            if minutes_since_trade > self.no_trade_threshold_minutes:
                health_status["status"] = "warning"
                self._create_alert(
                    AlertLevel.WARNING,
                    AlertType.NO_TRADES,
                    f"⏰ No trades for {minutes_since_trade:.0f} minutes",
                    {"minutes": minutes_since_trade}
                )
        
        # Save health status
        try:
            with open(self.health_file, 'w') as f:
                json.dump(health_status, f, indent=2)
        except Exception as e:
            logger.error(f"Could not save health status: {e}")
        
        self.last_health_check = now
        return health_status
    
    def _create_alert(self, level: AlertLevel, alert_type: AlertType, message: str, data: Dict[str, Any]):
        """Create and log an alert"""
        alert = Alert(
            timestamp=datetime.now().isoformat(),
            level=level.value,
            alert_type=alert_type.value,
            message=message,
            data=data
        )
        
        self.alerts.append(alert)
        
        # Log based on severity
        if level == AlertLevel.CRITICAL or level == AlertLevel.EMERGENCY:
            logger.error(f"🚨 {message}")
        elif level == AlertLevel.WARNING:
            logger.warning(f"⚠️ {message}")
        else:
            logger.info(f"ℹ️ {message}")
        
        # Save alerts
        try:
            # Keep last 100 alerts
            recent_alerts = self.alerts[-100:]
            with open(self.alerts_file, 'w') as f:
                json.dump([asdict(a) for a in recent_alerts], f, indent=2)
        except Exception as e:
            logger.error(f"Could not save alerts: {e}")
    
    def get_summary(self) -> str:
        """Get a text summary of current status"""
        uptime = (datetime.now() - self.start_time).total_seconds() / 3600  # hours
        
        summary = f"""
╔══════════════════════════════════════════════════════════════════╗
║              NIJA BOT MONITORING SUMMARY                         ║
╚══════════════════════════════════════════════════════════════════╝

⏱️  UPTIME: {uptime:.1f} hours

💰 BALANCE:
   Current:  ${self.last_balance:.2f}
   Start:    ${self.start_balance:.2f}
   Peak:     ${self.peak_balance:.2f}
   Change:   ${self.last_balance - self.start_balance:+.2f} ({((self.last_balance - self.start_balance) / self.start_balance * 100) if self.start_balance > 0 else 0:+.1f}%)

📊 PERFORMANCE:
   Total Trades:        {self.metrics.total_trades}
   Wins / Losses:       {self.metrics.winning_trades} / {self.metrics.losing_trades}
   Win Rate:            {self.metrics.win_rate:.1f}%
   Profit Factor:       {self.metrics.profit_factor:.2f}
   
   Gross Profit:        ${self.metrics.total_profit:.2f}
   Gross Loss:          ${self.metrics.total_loss:.2f}
   Total Fees:          ${self.metrics.total_fees:.2f}
   Net Profit:          ${self.metrics.net_profit:+.2f}
   
   Largest Win:         ${self.metrics.largest_win:.2f}
   Largest Loss:        ${self.metrics.largest_loss:.2f}
   Average Win:         ${self.metrics.average_win:.2f}
   Average Loss:        ${self.metrics.average_loss:.2f}
   
   Consecutive Wins:    {self.metrics.consecutive_wins}
   Consecutive Losses:  {self.metrics.consecutive_losses}

🔧 SYSTEM:
   API Calls:           {self.api_call_count}
   Errors:              {self.error_count}
   Error Rate:          {(self.error_count / self.api_call_count * 100) if self.api_call_count > 0 else 0:.1f}%

🚨 RECENT ALERTS: {len(self.alerts[-5:])}
"""
        
        # Add recent alerts
        for alert in self.alerts[-5:]:
            summary += f"   [{alert.level}] {alert.message}\n"
        
        summary += "\n" + "═" * 70
        
        return summary


# Global monitoring instance
monitoring = MonitoringSystem()


if __name__ == "__main__":
    # Test the monitoring system
    logging.basicConfig(level=logging.INFO)
    
    print("Testing Monitoring System...")
    
    # Simulate some activity
    monitoring.update_balance(57.70)
    monitoring.record_api_call()
    
    # Simulate trades
    monitoring.record_trade("BTC-USD", profit=1.50, fees=0.36, is_win=True)
    monitoring.record_api_call()
    
    monitoring.record_trade("ETH-USD", profit=-0.92, fees=0.36, is_win=False)
    monitoring.record_api_call()
    
    monitoring.record_trade("SOL-USD", profit=2.30, fees=0.36, is_win=True)
    monitoring.record_api_call()
    
    monitoring.update_balance(60.08)
    
    # Health check
    health = monitoring.check_health()
    
    # Print summary
    print(monitoring.get_summary())
    
    print(f"\n✅ Monitoring system test complete!")
    print(f"📁 Data saved to: {monitoring.data_dir}")
