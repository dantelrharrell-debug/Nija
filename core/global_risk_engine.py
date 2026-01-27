"""
NIJA Global Risk Engine

Centralized risk management system that aggregates risk across all accounts,
monitors portfolio-level exposure, and enforces global risk limits.

Features:
- Multi-account risk aggregation
- Portfolio-level exposure monitoring
- Global position limit enforcement
- Risk event logging and alerts
- Real-time risk metrics calculation
- Drawdown monitoring
- Correlation-aware risk assessment

Author: NIJA Trading Systems
Version: 1.0
Date: January 27, 2026
"""

import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
import threading
from collections import defaultdict

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    """Risk severity levels"""
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    EMERGENCY = "EMERGENCY"


class RiskEventType(Enum):
    """Types of risk events"""
    EXPOSURE_LIMIT_BREACH = "EXPOSURE_LIMIT_BREACH"
    DRAWDOWN_LIMIT_BREACH = "DRAWDOWN_LIMIT_BREACH"
    POSITION_LIMIT_BREACH = "POSITION_LIMIT_BREACH"
    DAILY_LOSS_LIMIT_BREACH = "DAILY_LOSS_LIMIT_BREACH"
    CORRELATION_RISK_HIGH = "CORRELATION_RISK_HIGH"
    ACCOUNT_BALANCE_LOW = "ACCOUNT_BALANCE_LOW"
    VOLATILITY_SPIKE = "VOLATILITY_SPIKE"
    LIQUIDITY_ISSUE = "LIQUIDITY_ISSUE"


@dataclass
class RiskEvent:
    """Risk event data structure"""
    timestamp: datetime
    event_type: RiskEventType
    risk_level: RiskLevel
    account_id: Optional[str]
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/storage"""
        return {
            'timestamp': self.timestamp.isoformat(),
            'event_type': self.event_type.value,
            'risk_level': self.risk_level.value,
            'account_id': self.account_id,
            'message': self.message,
            'details': self.details
        }


@dataclass
class AccountRiskMetrics:
    """Risk metrics for a single account"""
    account_id: str
    total_exposure: float = 0.0
    position_count: int = 0
    unrealized_pnl: float = 0.0
    daily_pnl: float = 0.0
    peak_balance: float = 0.0
    current_balance: float = 0.0
    drawdown_pct: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    largest_position_size: float = 0.0
    average_position_size: float = 0.0
    last_updated: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        data = asdict(self)
        data['last_updated'] = self.last_updated.isoformat()
        return data


@dataclass
class PortfolioRiskMetrics:
    """Aggregated risk metrics across all accounts"""
    total_accounts: int = 0
    total_exposure: float = 0.0
    total_positions: int = 0
    total_unrealized_pnl: float = 0.0
    total_daily_pnl: float = 0.0
    total_balance: float = 0.0
    portfolio_drawdown_pct: float = 0.0
    concentration_risk: float = 0.0
    correlation_risk: float = 0.0
    accounts_at_risk: List[str] = field(default_factory=list)
    last_updated: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        data = asdict(self)
        data['last_updated'] = self.last_updated.isoformat()
        return data


class GlobalRiskEngine:
    """
    Centralized risk management engine for the entire NIJA platform.
    
    Monitors and enforces risk limits across all trading accounts,
    provides real-time risk metrics, and generates alerts for risk events.
    """
    
    def __init__(self,
                 max_portfolio_exposure_pct: float = 0.80,
                 max_daily_loss_pct: float = 0.05,
                 max_drawdown_pct: float = 0.20,
                 max_total_positions: int = 50,
                 max_positions_per_account: int = 10,
                 correlation_threshold: float = 0.7):
        """
        Initialize Global Risk Engine
        
        Args:
            max_portfolio_exposure_pct: Maximum portfolio exposure (0.80 = 80%)
            max_daily_loss_pct: Maximum daily loss percentage (0.05 = 5%)
            max_drawdown_pct: Maximum drawdown percentage (0.20 = 20%)
            max_total_positions: Maximum total positions across all accounts
            max_positions_per_account: Maximum positions per individual account
            correlation_threshold: Correlation threshold for risk alerts
        """
        self.max_portfolio_exposure_pct = max_portfolio_exposure_pct
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.max_total_positions = max_total_positions
        self.max_positions_per_account = max_positions_per_account
        self.correlation_threshold = correlation_threshold
        
        # Thread-safe data structures
        self._lock = threading.Lock()
        self._account_metrics: Dict[str, AccountRiskMetrics] = {}
        self._portfolio_metrics: PortfolioRiskMetrics = PortfolioRiskMetrics()
        self._risk_events: List[RiskEvent] = []
        self._alert_callbacks: List[callable] = []
        
        # Daily tracking
        self._daily_start_balance: Dict[str, float] = {}
        self._daily_reset_date = datetime.now().date()
        
        logger.info("✅ Global Risk Engine initialized")
        logger.info(f"Portfolio exposure limit: {self.max_portfolio_exposure_pct*100:.1f}%")
        logger.info(f"Daily loss limit: {self.max_daily_loss_pct*100:.1f}%")
        logger.info(f"Max drawdown: {self.max_drawdown_pct*100:.1f}%")
        logger.info(f"Max total positions: {self.max_total_positions}")
    
    def register_alert_callback(self, callback: callable) -> None:
        """
        Register a callback function for risk alerts
        
        Args:
            callback: Function to call when risk event occurs
        """
        with self._lock:
            self._alert_callbacks.append(callback)
            logger.info(f"Registered risk alert callback: {callback.__name__}")
    
    def update_account_metrics(self, account_id: str, metrics: Dict[str, Any]) -> None:
        """
        Update risk metrics for a specific account
        
        Args:
            account_id: Account identifier
            metrics: Dictionary with account metrics
        """
        with self._lock:
            # Create or update account metrics
            if account_id not in self._account_metrics:
                self._account_metrics[account_id] = AccountRiskMetrics(account_id=account_id)
            
            account = self._account_metrics[account_id]
            
            # Update metrics from provided data
            if 'total_exposure' in metrics:
                account.total_exposure = float(metrics['total_exposure'])
            if 'position_count' in metrics:
                account.position_count = int(metrics['position_count'])
            if 'unrealized_pnl' in metrics:
                account.unrealized_pnl = float(metrics['unrealized_pnl'])
            if 'current_balance' in metrics:
                account.current_balance = float(metrics['current_balance'])
                # Update peak balance
                if account.current_balance > account.peak_balance:
                    account.peak_balance = account.current_balance
            if 'win_rate' in metrics:
                account.win_rate = float(metrics['win_rate'])
            if 'profit_factor' in metrics:
                account.profit_factor = float(metrics['profit_factor'])
            
            # Initialize daily tracking if new day
            self._reset_daily_if_needed()
            if account_id not in self._daily_start_balance:
                self._daily_start_balance[account_id] = account.current_balance
            
            # Calculate daily PnL
            start_balance = self._daily_start_balance[account_id]
            if start_balance > 0:
                account.daily_pnl = account.current_balance - start_balance
            
            # Calculate drawdown
            if account.peak_balance > 0:
                account.drawdown_pct = ((account.peak_balance - account.current_balance) / 
                                       account.peak_balance * 100)
            
            # Calculate position sizes
            if account.position_count > 0 and 'positions' in metrics:
                positions = metrics['positions']
                if positions:
                    sizes = [abs(p.get('size', 0) * p.get('current_price', 0)) 
                            for p in positions]
                    account.largest_position_size = max(sizes) if sizes else 0.0
                    account.average_position_size = sum(sizes) / len(sizes) if sizes else 0.0
            
            account.last_updated = datetime.now()
            
            # Check account-level risk limits
            self._check_account_risk_limits(account_id)
    
    def _reset_daily_if_needed(self) -> None:
        """Reset daily tracking at start of new day"""
        current_date = datetime.now().date()
        if current_date > self._daily_reset_date:
            logger.info(f"Resetting daily tracking for new day: {current_date}")
            self._daily_start_balance.clear()
            self._daily_reset_date = current_date
    
    def _check_account_risk_limits(self, account_id: str) -> None:
        """
        Check risk limits for a specific account
        
        Args:
            account_id: Account to check
        """
        account = self._account_metrics.get(account_id)
        if not account:
            return
        
        # Check position count limit
        if account.position_count > self.max_positions_per_account:
            self._create_risk_event(
                event_type=RiskEventType.POSITION_LIMIT_BREACH,
                risk_level=RiskLevel.HIGH,
                account_id=account_id,
                message=f"Position limit exceeded: {account.position_count}/{self.max_positions_per_account}",
                details={'position_count': account.position_count}
            )
        
        # Check daily loss limit
        if account.current_balance > 0:
            daily_loss_pct = abs(account.daily_pnl / account.current_balance * 100)
            if account.daily_pnl < 0 and daily_loss_pct > self.max_daily_loss_pct * 100:
                self._create_risk_event(
                    event_type=RiskEventType.DAILY_LOSS_LIMIT_BREACH,
                    risk_level=RiskLevel.CRITICAL,
                    account_id=account_id,
                    message=f"Daily loss limit exceeded: {daily_loss_pct:.2f}%",
                    details={
                        'daily_pnl': account.daily_pnl,
                        'daily_loss_pct': daily_loss_pct
                    }
                )
        
        # Check drawdown limit
        if account.drawdown_pct > self.max_drawdown_pct * 100:
            self._create_risk_event(
                event_type=RiskEventType.DRAWDOWN_LIMIT_BREACH,
                risk_level=RiskLevel.CRITICAL,
                account_id=account_id,
                message=f"Drawdown limit exceeded: {account.drawdown_pct:.2f}%",
                details={'drawdown_pct': account.drawdown_pct}
            )
        
        # Check account balance
        if account.current_balance < 10.0:  # Minimum viable balance
            self._create_risk_event(
                event_type=RiskEventType.ACCOUNT_BALANCE_LOW,
                risk_level=RiskLevel.HIGH,
                account_id=account_id,
                message=f"Account balance critically low: ${account.current_balance:.2f}",
                details={'current_balance': account.current_balance}
            )
    
    def calculate_portfolio_metrics(self) -> PortfolioRiskMetrics:
        """
        Calculate aggregated portfolio risk metrics
        
        Returns:
            PortfolioRiskMetrics object
        """
        with self._lock:
            metrics = PortfolioRiskMetrics()
            
            if not self._account_metrics:
                return metrics
            
            # Aggregate metrics
            metrics.total_accounts = len(self._account_metrics)
            metrics.total_exposure = sum(a.total_exposure for a in self._account_metrics.values())
            metrics.total_positions = sum(a.position_count for a in self._account_metrics.values())
            metrics.total_unrealized_pnl = sum(a.unrealized_pnl for a in self._account_metrics.values())
            metrics.total_daily_pnl = sum(a.daily_pnl for a in self._account_metrics.values())
            metrics.total_balance = sum(a.current_balance for a in self._account_metrics.values())
            
            # Calculate portfolio drawdown
            total_peak = sum(a.peak_balance for a in self._account_metrics.values())
            if total_peak > 0:
                metrics.portfolio_drawdown_pct = ((total_peak - metrics.total_balance) / 
                                                  total_peak * 100)
            
            # Calculate concentration risk (max account exposure / total exposure)
            if metrics.total_exposure > 0:
                max_account_exposure = max((a.total_exposure for a in self._account_metrics.values()), 
                                          default=0)
                metrics.concentration_risk = max_account_exposure / metrics.total_exposure
            
            # Identify accounts at risk
            metrics.accounts_at_risk = [
                account_id for account_id, account in self._account_metrics.items()
                if account.drawdown_pct > 10.0 or account.daily_pnl < -50.0
            ]
            
            metrics.last_updated = datetime.now()
            self._portfolio_metrics = metrics
            
            # Check portfolio-level limits
            self._check_portfolio_risk_limits()
            
            return metrics
    
    def _check_portfolio_risk_limits(self) -> None:
        """Check portfolio-level risk limits"""
        metrics = self._portfolio_metrics
        
        # Check total position limit
        if metrics.total_positions > self.max_total_positions:
            self._create_risk_event(
                event_type=RiskEventType.POSITION_LIMIT_BREACH,
                risk_level=RiskLevel.HIGH,
                account_id=None,
                message=f"Portfolio position limit exceeded: {metrics.total_positions}/{self.max_total_positions}",
                details={'total_positions': metrics.total_positions}
            )
        
        # Check portfolio exposure
        if metrics.total_balance > 0:
            exposure_pct = metrics.total_exposure / metrics.total_balance
            if exposure_pct > self.max_portfolio_exposure_pct:
                self._create_risk_event(
                    event_type=RiskEventType.EXPOSURE_LIMIT_BREACH,
                    risk_level=RiskLevel.HIGH,
                    account_id=None,
                    message=f"Portfolio exposure limit exceeded: {exposure_pct*100:.1f}%",
                    details={'exposure_pct': exposure_pct * 100}
                )
        
        # Check portfolio drawdown
        if metrics.portfolio_drawdown_pct > self.max_drawdown_pct * 100:
            self._create_risk_event(
                event_type=RiskEventType.DRAWDOWN_LIMIT_BREACH,
                risk_level=RiskLevel.CRITICAL,
                account_id=None,
                message=f"Portfolio drawdown limit exceeded: {metrics.portfolio_drawdown_pct:.2f}%",
                details={'drawdown_pct': metrics.portfolio_drawdown_pct}
            )
        
        # Check concentration risk
        if metrics.concentration_risk > 0.5:  # 50% concentration threshold
            self._create_risk_event(
                event_type=RiskEventType.CORRELATION_RISK_HIGH,
                risk_level=RiskLevel.MODERATE,
                account_id=None,
                message=f"High concentration risk: {metrics.concentration_risk*100:.1f}%",
                details={'concentration_risk': metrics.concentration_risk}
            )
    
    def _create_risk_event(self, event_type: RiskEventType, risk_level: RiskLevel,
                          account_id: Optional[str], message: str, 
                          details: Dict[str, Any]) -> None:
        """
        Create and log a risk event
        
        Args:
            event_type: Type of risk event
            risk_level: Severity level
            account_id: Account ID (None for portfolio-level)
            message: Event message
            details: Additional details
        """
        event = RiskEvent(
            timestamp=datetime.now(),
            event_type=event_type,
            risk_level=risk_level,
            account_id=account_id,
            message=message,
            details=details
        )
        
        # Add to event log
        self._risk_events.append(event)
        
        # Keep only last 1000 events
        if len(self._risk_events) > 1000:
            self._risk_events = self._risk_events[-1000:]
        
        # Log the event
        log_level = logging.WARNING if risk_level in [RiskLevel.HIGH, RiskLevel.CRITICAL] else logging.INFO
        logger.log(log_level, f"[{risk_level.value}] {message}")
        
        # Notify callbacks
        for callback in self._alert_callbacks:
            try:
                callback(event)
            except Exception as e:
                logger.error(f"Error in risk alert callback: {e}")
    
    def get_account_metrics(self, account_id: str) -> Optional[AccountRiskMetrics]:
        """
        Get risk metrics for a specific account
        
        Args:
            account_id: Account identifier
            
        Returns:
            AccountRiskMetrics or None if not found
        """
        with self._lock:
            return self._account_metrics.get(account_id)
    
    def get_portfolio_metrics(self) -> PortfolioRiskMetrics:
        """
        Get current portfolio risk metrics
        
        Returns:
            PortfolioRiskMetrics object
        """
        with self._lock:
            return self._portfolio_metrics
    
    def get_risk_events(self, 
                       account_id: Optional[str] = None,
                       event_type: Optional[RiskEventType] = None,
                       risk_level: Optional[RiskLevel] = None,
                       hours: int = 24) -> List[RiskEvent]:
        """
        Get recent risk events with optional filtering
        
        Args:
            account_id: Filter by account (None = all accounts)
            event_type: Filter by event type (None = all types)
            risk_level: Filter by risk level (None = all levels)
            hours: Number of hours to look back
            
        Returns:
            List of matching risk events
        """
        with self._lock:
            cutoff_time = datetime.now() - timedelta(hours=hours)
            
            events = [
                e for e in self._risk_events
                if e.timestamp >= cutoff_time
                and (account_id is None or e.account_id == account_id)
                and (event_type is None or e.event_type == event_type)
                and (risk_level is None or e.risk_level == risk_level)
            ]
            
            return sorted(events, key=lambda x: x.timestamp, reverse=True)
    
    def can_open_position(self, account_id: str, position_size: float) -> Tuple[bool, str]:
        """
        Check if a new position can be opened based on risk limits
        
        Args:
            account_id: Account identifier
            position_size: Size of new position in USD
            
        Returns:
            Tuple of (allowed: bool, reason: str)
        """
        with self._lock:
            # Check portfolio-level limits
            if self._portfolio_metrics.total_positions >= self.max_total_positions:
                return False, f"Portfolio position limit reached ({self.max_total_positions})"
            
            # Check account-level limits
            account = self._account_metrics.get(account_id)
            if account:
                if account.position_count >= self.max_positions_per_account:
                    return False, f"Account position limit reached ({self.max_positions_per_account})"
                
                # Check if account is in critical drawdown
                if account.drawdown_pct > self.max_drawdown_pct * 100:
                    return False, f"Account in critical drawdown ({account.drawdown_pct:.1f}%)"
                
                # Check daily loss limit
                if account.current_balance > 0:
                    daily_loss_pct = abs(account.daily_pnl / account.current_balance * 100)
                    if account.daily_pnl < 0 and daily_loss_pct > self.max_daily_loss_pct * 100:
                        return False, f"Daily loss limit exceeded ({daily_loss_pct:.1f}%)"
            
            return True, "Position allowed"
    
    def get_status_summary(self) -> Dict[str, Any]:
        """
        Get comprehensive status summary
        
        Returns:
            Dictionary with complete status information
        """
        # Calculate latest portfolio metrics (this acquires its own lock)
        portfolio = self.calculate_portfolio_metrics()
        
        # Get recent critical events (this acquires its own lock)
        critical_events = self.get_risk_events(
            risk_level=RiskLevel.CRITICAL,
            hours=24
        )
        
        # Get recent events (this acquires its own lock)
        recent_events = self.get_risk_events(hours=1)
        
        with self._lock:
            return {
                'portfolio_metrics': portfolio.to_dict(),
                'account_count': len(self._account_metrics),
                'accounts': {
                    acc_id: metrics.to_dict() 
                    for acc_id, metrics in self._account_metrics.items()
                },
                'critical_events_24h': len(critical_events),
                'recent_events': [e.to_dict() for e in recent_events],
                'risk_limits': {
                    'max_portfolio_exposure_pct': self.max_portfolio_exposure_pct * 100,
                    'max_daily_loss_pct': self.max_daily_loss_pct * 100,
                    'max_drawdown_pct': self.max_drawdown_pct * 100,
                    'max_total_positions': self.max_total_positions,
                    'max_positions_per_account': self.max_positions_per_account
                },
                'timestamp': datetime.now().isoformat()
            }


# Global singleton instance
_global_risk_engine: Optional[GlobalRiskEngine] = None
_engine_lock = threading.Lock()


def get_global_risk_engine(**kwargs) -> GlobalRiskEngine:
    """
    Get or create global risk engine singleton
    
    Args:
        **kwargs: Configuration options for risk engine
        
    Returns:
        GlobalRiskEngine instance
    """
    global _global_risk_engine
    
    with _engine_lock:
        if _global_risk_engine is None:
            _global_risk_engine = GlobalRiskEngine(**kwargs)
            logger.info("Created new Global Risk Engine instance")
        return _global_risk_engine


def reset_global_risk_engine() -> None:
    """Reset global risk engine (for testing)"""
    global _global_risk_engine
    with _engine_lock:
        _global_risk_engine = None
        logger.info("Global Risk Engine reset")
