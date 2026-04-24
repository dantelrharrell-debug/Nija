"""
NIJA Graduation System - Paper to Live Trading Progression

Institutional-grade user advancement system with regulatory compliance,
safety controls, and graduated access management.

Version: 1.0
Last Updated: January 31, 2026
"""

from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
import logging

logger = logging.getLogger(__name__)


class TradingLevel(Enum):
    """User trading access levels"""
    PAPER = 1
    LIMITED_LIVE = 2
    FULL_LIVE = 3


class GraduationStatus(Enum):
    """Status of graduation application"""
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    UNDER_REVIEW = "under_review"


class DowngradeReason(Enum):
    """Reasons for level downgrade"""
    PERFORMANCE = "performance"
    COMPLIANCE = "compliance"
    RISK_VIOLATION = "risk_violation"
    USER_REQUEST = "user_request"
    LARGE_LOSS = "large_loss"
    REPEATED_VIOLATIONS = "repeated_violations"


@dataclass
class LevelLimits:
    """Trading limits for each level"""
    max_account_value: float
    max_position_size: float
    max_open_positions: int
    daily_loss_limit: Optional[float]
    weekly_loss_limit: Optional[float]
    daily_trade_limit: int
    allowed_markets: List[str]
    leverage_allowed: bool
    max_leverage: float
    forced_stop_loss: bool = True
    
    def to_dict(self) -> Dict:
        return {
            "max_account_value": self.max_account_value,
            "max_position_size": self.max_position_size,
            "max_open_positions": self.max_open_positions,
            "daily_loss_limit": self.daily_loss_limit,
            "weekly_loss_limit": self.weekly_loss_limit,
            "daily_trade_limit": self.daily_trade_limit,
            "allowed_markets": self.allowed_markets,
            "leverage_allowed": self.leverage_allowed,
            "max_leverage": self.max_leverage,
            "forced_stop_loss": self.forced_stop_loss
        }


@dataclass
class GraduationRecord:
    """Record of user graduation attempt"""
    user_id: str
    from_level: TradingLevel
    to_level: TradingLevel
    timestamp: datetime = field(default_factory=datetime.now)
    
    # Performance snapshot
    performance_snapshot: Dict = field(default_factory=dict)
    
    # Assessment results
    knowledge_test_score: Optional[float] = None
    suitability_assessment: Dict = field(default_factory=dict)
    risk_education_completed: bool = False
    
    # Approval
    status: GraduationStatus = GraduationStatus.PENDING
    approval_timestamp: Optional[datetime] = None
    approved_by: Optional[str] = None
    denial_reason: Optional[str] = None
    
    # Compliance
    kyc_level: str = "none"  # "none", "basic", "enhanced"
    kyc_verified_at: Optional[datetime] = None
    video_verification: bool = False
    compliance_notes: str = ""
    
    def to_dict(self) -> Dict:
        return {
            "user_id": self.user_id,
            "from_level": self.from_level.name,
            "to_level": self.to_level.name,
            "timestamp": self.timestamp.isoformat(),
            "performance_snapshot": self.performance_snapshot,
            "knowledge_test_score": self.knowledge_test_score,
            "suitability_assessment": self.suitability_assessment,
            "risk_education_completed": self.risk_education_completed,
            "status": self.status.value,
            "approval_timestamp": self.approval_timestamp.isoformat() if self.approval_timestamp else None,
            "approved_by": self.approved_by,
            "denial_reason": self.denial_reason,
            "kyc_level": self.kyc_level,
            "kyc_verified_at": self.kyc_verified_at.isoformat() if self.kyc_verified_at else None,
            "video_verification": self.video_verification,
            "compliance_notes": self.compliance_notes
        }


@dataclass
class DowngradeRecord:
    """Record of user level downgrade"""
    user_id: str
    from_level: TradingLevel
    to_level: TradingLevel
    timestamp: datetime = field(default_factory=datetime.now)
    
    # Reason
    reason: DowngradeReason = DowngradeReason.PERFORMANCE
    trigger: str = ""
    
    # Automatic vs Manual
    automatic: bool = True
    triggered_by_system: Optional[str] = None
    manual_override_by: Optional[str] = None
    
    # Impact
    duration_seconds: Optional[int] = None  # Time until can reapply
    limits_reduced: Dict = field(default_factory=dict)
    
    # User notification
    user_notified: bool = False
    notification_sent_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict:
        return {
            "user_id": self.user_id,
            "from_level": self.from_level.name,
            "to_level": self.to_level.name,
            "timestamp": self.timestamp.isoformat(),
            "reason": self.reason.value,
            "trigger": self.trigger,
            "automatic": self.automatic,
            "triggered_by_system": self.triggered_by_system,
            "manual_override_by": self.manual_override_by,
            "duration_seconds": self.duration_seconds,
            "limits_reduced": self.limits_reduced,
            "user_notified": self.user_notified,
            "notification_sent_at": self.notification_sent_at.isoformat() if self.notification_sent_at else None
        }


class GraduationSystem:
    """
    Manages user progression through trading levels with institutional-grade
    safety controls and regulatory compliance.
    """
    
    # Level 1: Paper Trading (Education Phase)
    LEVEL_1_LIMITS = LevelLimits(
        max_account_value=10000.0,  # Virtual money
        max_position_size=2000.0,
        max_open_positions=10,
        daily_loss_limit=None,  # No limits in paper
        weekly_loss_limit=None,
        daily_trade_limit=100,
        allowed_markets=["ALL"],
        leverage_allowed=False,
        max_leverage=1.0,
        forced_stop_loss=False  # Optional in paper
    )
    
    # Level 2: Limited Live Trading (Validation Phase)
    LEVEL_2_LIMITS = LevelLimits(
        max_account_value=5000.0,
        max_position_size=500.0,
        max_open_positions=3,
        daily_loss_limit=250.0,
        weekly_loss_limit=500.0,
        daily_trade_limit=10,
        allowed_markets=["BTC-USD", "ETH-USD", "major_crypto_top20"],
        leverage_allowed=False,
        max_leverage=1.0,
        forced_stop_loss=True  # Mandatory
    )
    
    # Level 3: Full Live Trading (Progressive unlocking)
    LEVEL_3_INITIAL_LIMITS = LevelLimits(
        max_account_value=50000.0,
        max_position_size=10000.0,
        max_open_positions=10,
        daily_loss_limit=2500.0,
        weekly_loss_limit=None,
        daily_trade_limit=50,
        allowed_markets=["ALL"],
        leverage_allowed=True,
        max_leverage=1.5,
        forced_stop_loss=True
    )
    
    # Cooling-off periods (in seconds)
    LEVEL_2_COOLOFF = 7 * 24 * 3600  # 7 days after KYC
    LEVEL_3_COOLOFF = 14 * 24 * 3600  # 14 days after application
    LARGE_LOSS_COOLOFF = 3 * 24 * 3600  # 3 days after 20%+ loss
    STREAK_LOSS_COOLOFF = 24 * 3600  # 24 hours after 5 consecutive losses
    KILL_SWITCH_COOLOFF = 7 * 24 * 3600  # 7 days after manual halt
    
    def __init__(self, database_connection=None):
        """
        Initialize graduation system.
        
        Args:
            database_connection: Database connection for storing records
        """
        self.db = database_connection
        self.graduation_records: List[GraduationRecord] = []
        self.downgrade_records: List[DowngradeRecord] = []
    
    def check_level1_graduation_eligibility(
        self, 
        user_id: str,
        performance_data: Dict
    ) -> Tuple[bool, str, Dict]:
        """
        Check if user meets Level 1 → Level 2 graduation criteria.
        
        Args:
            user_id: User identifier
            performance_data: Dictionary of performance metrics
            
        Returns:
            Tuple of (eligible, reason, missing_criteria)
        """
        logger.info(f"Checking Level 1 graduation eligibility for user {user_id}")
        
        criteria = {
            "win_rate": performance_data.get("win_rate", 0) >= 0.52,
            "sharpe_ratio": performance_data.get("sharpe_ratio", 0) >= 1.0,
            "max_drawdown": performance_data.get("max_drawdown", 1.0) <= 0.15,
            "total_trades": performance_data.get("total_trades", 0) >= 50,
            "profit_factor": performance_data.get("profit_factor", 0) >= 1.3,
            "risk_reward_ratio": performance_data.get("avg_rr", 0) >= 1.5,
            "knowledge_test": performance_data.get("knowledge_test_score", 0) >= 0.80,
            "risk_education": performance_data.get("risk_education_completed", False),
            "trading_days": performance_data.get("trading_days", 0) >= 30
        }
        
        all_met = all(criteria.values())
        
        if all_met:
            logger.info(f"User {user_id} meets all Level 1 graduation criteria")
            return True, "All criteria met - eligible for Level 2", {}
        else:
            missing = {k: v for k, v in criteria.items() if not v}
            reason = f"Missing {len(missing)} criteria: {', '.join(missing.keys())}"
            logger.info(f"User {user_id} not eligible: {reason}")
            return False, reason, missing
    
    def check_level2_graduation_eligibility(
        self,
        user_id: str,
        performance_data: Dict
    ) -> Tuple[bool, str, Dict]:
        """
        Check if user meets Level 2 → Level 3 graduation criteria.
        
        Args:
            user_id: User identifier
            performance_data: Dictionary of performance metrics
            
        Returns:
            Tuple of (eligible, reason, missing_criteria)
        """
        logger.info(f"Checking Level 2 graduation eligibility for user {user_id}")
        
        criteria = {
            "profitable_months": performance_data.get("consecutive_profitable_months", 0) >= 3,
            "win_rate": performance_data.get("win_rate_90d", 0) >= 0.55,
            "max_drawdown": performance_data.get("max_drawdown_90d", 1.0) <= 0.12,
            "total_trades": performance_data.get("total_real_trades", 0) >= 100,
            "no_violations_60d": performance_data.get("violations_last_60d", 1) == 0,
            "no_circuit_breakers_30d": performance_data.get("circuit_breakers_last_30d", 1) == 0,
            "sharpe_ratio_90d": performance_data.get("sharpe_ratio_90d", 0) >= 1.2,
            "advanced_test": performance_data.get("advanced_test_score", 0) >= 0.85,
            "risk_essay": performance_data.get("risk_essay_submitted", False),
            "trading_days": performance_data.get("level2_trading_days", 0) >= 90
        }
        
        all_met = all(criteria.values())
        
        if all_met:
            logger.info(f"User {user_id} meets all Level 2 graduation criteria")
            return True, "All criteria met - eligible for Level 3", {}
        else:
            missing = {k: v for k, v in criteria.items() if not v}
            reason = f"Missing {len(missing)} criteria: {', '.join(missing.keys())}"
            logger.info(f"User {user_id} not eligible: {reason}")
            return False, reason, missing
    
    def apply_circuit_breaker(
        self,
        user_id: str,
        level: TradingLevel,
        trigger: str,
        duration_hours: int
    ) -> bool:
        """
        Apply circuit breaker to halt user trading.
        
        Args:
            user_id: User identifier
            level: Current trading level
            trigger: Reason for circuit breaker
            duration_hours: Hours to halt trading
            
        Returns:
            True if applied successfully
        """
        logger.warning(
            f"Circuit breaker triggered for user {user_id} at {level.name}: "
            f"{trigger} (duration: {duration_hours} hours)"
        )
        
        # Implementation would halt trading in user's account
        # For now, just log
        
        # Store circuit breaker event
        event = {
            "user_id": user_id,
            "level": level.name,
            "trigger": trigger,
            "duration_hours": duration_hours,
            "timestamp": datetime.now().isoformat(),
            "halt_until": (datetime.now() + timedelta(hours=duration_hours)).isoformat()
        }
        
        # Notify user
        self._notify_user_circuit_breaker(user_id, trigger, duration_hours)
        
        return True
    
    def check_level2_circuit_breakers(
        self,
        user_id: str,
        account_data: Dict
    ) -> Optional[str]:
        """
        Check Level 2 circuit breaker conditions.
        
        Args:
            user_id: User identifier
            account_data: Current account state
            
        Returns:
            Circuit breaker trigger reason if should halt, None otherwise
        """
        # 3 consecutive losses
        if account_data.get("consecutive_losses", 0) >= 3:
            self.apply_circuit_breaker(
                user_id, 
                TradingLevel.LIMITED_LIVE,
                "3 consecutive losses",
                24
            )
            return "consecutive_losses"
        
        # 10% drawdown in 24 hours
        if account_data.get("drawdown_24h_pct", 0) >= 0.10:
            self.apply_circuit_breaker(
                user_id,
                TradingLevel.LIMITED_LIVE,
                "10% drawdown in 24 hours",
                48
            )
            return "rapid_drawdown"
        
        # Daily loss limit
        if account_data.get("daily_loss", 0) >= 250:
            self.apply_circuit_breaker(
                user_id,
                TradingLevel.LIMITED_LIVE,
                "Daily loss limit: $250",
                24
            )
            return "daily_loss_limit"
        
        # Weekly loss limit
        if account_data.get("weekly_loss", 0) >= 500:
            self.apply_circuit_breaker(
                user_id,
                TradingLevel.LIMITED_LIVE,
                "Weekly loss limit: $500",
                168  # 7 days
            )
            return "weekly_loss_limit"
        
        return None
    
    def check_level3_circuit_breakers(
        self,
        user_id: str,
        account_data: Dict
    ) -> Optional[str]:
        """
        Check Level 3 circuit breaker conditions.
        
        Args:
            user_id: User identifier
            account_data: Current account state
            
        Returns:
            Circuit breaker trigger reason if should halt, None otherwise
        """
        # 25% monthly loss - severe, triggers downgrade
        if account_data.get("monthly_loss_pct", 0) >= 0.25:
            self.downgrade_user(
                user_id,
                TradingLevel.FULL_LIVE,
                TradingLevel.LIMITED_LIVE,
                DowngradeReason.LARGE_LOSS,
                "25% monthly loss - automatic downgrade to Level 2",
                duration_days=90
            )
            return "severe_monthly_loss"
        
        # 15% monthly loss - reduce limits
        if account_data.get("monthly_loss_pct", 0) >= 0.15:
            self.apply_circuit_breaker(
                user_id,
                TradingLevel.FULL_LIVE,
                "15% monthly loss - limits reduced by 50%",
                720  # 30 days
            )
            # Also reduce limits by 50%
            return "monthly_loss_threshold"
        
        # Rapid 5% loss in 1 hour
        if account_data.get("hourly_loss_pct", 0) >= 0.05:
            self.apply_circuit_breaker(
                user_id,
                TradingLevel.FULL_LIVE,
                "5% loss in 1 hour - rapid loss protection",
                1
            )
            return "rapid_hourly_loss"
        
        return None
    
    def progressive_limit_unlock(
        self,
        user_id: str,
        level: TradingLevel,
        months_trading: int,
        performance_metrics: Dict
    ) -> LevelLimits:
        """
        Calculate progressive limits based on experience and performance.
        
        Args:
            user_id: User identifier
            level: Current trading level
            months_trading: Months of profitable trading at current level
            performance_metrics: Recent performance data
            
        Returns:
            LevelLimits object with calculated limits
        """
        if level != TradingLevel.FULL_LIVE:
            # Only Level 3 has progressive unlocking
            if level == TradingLevel.LIMITED_LIVE:
                return self.LEVEL_2_LIMITS
            else:
                return self.LEVEL_1_LIMITS
        
        # Level 3 progressive unlocking based on months trading
        if months_trading < 3:
            # Initial 3 months
            logger.info(f"User {user_id}: Level 3 initial limits (0-3 months)")
            return LevelLimits(
                max_account_value=50000.0,
                max_position_size=10000.0,
                max_open_positions=10,
                daily_loss_limit=2500.0,
                weekly_loss_limit=None,
                daily_trade_limit=50,
                allowed_markets=["ALL"],
                leverage_allowed=True,
                max_leverage=1.5,
                forced_stop_loss=True
            )
        elif months_trading < 6:
            # 3-6 months
            logger.info(f"User {user_id}: Level 3 expanded limits (3-6 months)")
            return LevelLimits(
                max_account_value=250000.0,
                max_position_size=50000.0,
                max_open_positions=20,
                daily_loss_limit=12500.0,
                weekly_loss_limit=None,
                daily_trade_limit=100,
                allowed_markets=["ALL"],
                leverage_allowed=True,
                max_leverage=2.0,
                forced_stop_loss=True
            )
        elif months_trading < 12:
            # 6-12 months
            logger.info(f"User {user_id}: Level 3 high limits (6-12 months)")
            return LevelLimits(
                max_account_value=1000000.0,
                max_position_size=200000.0,
                max_open_positions=50,
                daily_loss_limit=50000.0,
                weekly_loss_limit=None,
                daily_trade_limit=200,
                allowed_markets=["ALL"],
                leverage_allowed=True,
                max_leverage=3.0,
                forced_stop_loss=True
            )
        else:
            # 12+ months - Institutional tier
            logger.info(f"User {user_id}: Level 3 institutional limits (12+ months)")
            return LevelLimits(
                max_account_value=float('inf'),  # Negotiated
                max_position_size=float('inf'),  # Based on account size
                max_open_positions=100,
                daily_loss_limit=None,  # Custom risk management
                weekly_loss_limit=None,
                daily_trade_limit=500,
                allowed_markets=["ALL"],
                leverage_allowed=True,
                max_leverage=5.0,
                forced_stop_loss=True
            )
    
    def create_graduation_record(
        self,
        user_id: str,
        from_level: TradingLevel,
        to_level: TradingLevel,
        performance_snapshot: Dict,
        kyc_level: str = "none"
    ) -> GraduationRecord:
        """
        Create a graduation record for user.
        
        Args:
            user_id: User identifier
            from_level: Current level
            to_level: Target level
            performance_snapshot: Performance data at time of application
            kyc_level: KYC verification level
            
        Returns:
            GraduationRecord object
        """
        record = GraduationRecord(
            user_id=user_id,
            from_level=from_level,
            to_level=to_level,
            performance_snapshot=performance_snapshot,
            kyc_level=kyc_level,
            status=GraduationStatus.PENDING
        )
        
        self.graduation_records.append(record)
        logger.info(
            f"Created graduation record: {user_id} {from_level.name} → {to_level.name}"
        )
        
        return record
    
    def downgrade_user(
        self,
        user_id: str,
        from_level: TradingLevel,
        to_level: TradingLevel,
        reason: DowngradeReason,
        trigger: str,
        duration_days: int = 90
    ) -> DowngradeRecord:
        """
        Downgrade user to lower trading level.
        
        Args:
            user_id: User identifier
            from_level: Current level
            to_level: New (lower) level
            reason: Reason for downgrade
            trigger: Specific trigger description
            duration_days: Days before can reapply
            
        Returns:
            DowngradeRecord object
        """
        record = DowngradeRecord(
            user_id=user_id,
            from_level=from_level,
            to_level=to_level,
            reason=reason,
            trigger=trigger,
            automatic=True,
            triggered_by_system="circuit_breaker",
            duration_seconds=duration_days * 24 * 3600
        )
        
        self.downgrade_records.append(record)
        
        logger.warning(
            f"User {user_id} downgraded: {from_level.name} → {to_level.name} "
            f"due to {reason.value} ({trigger})"
        )
        
        # Notify user
        self._notify_user_downgrade(user_id, from_level, to_level, trigger, duration_days)
        
        return record
    
    def _notify_user_circuit_breaker(
        self,
        user_id: str,
        trigger: str,
        duration_hours: int
    ):
        """Send notification to user about circuit breaker."""
        # Implementation would send email/SMS/push notification
        logger.info(
            f"Notification sent to {user_id}: Circuit breaker triggered - {trigger} "
            f"(trading halted for {duration_hours} hours)"
        )
    
    def _notify_user_downgrade(
        self,
        user_id: str,
        from_level: TradingLevel,
        to_level: TradingLevel,
        trigger: str,
        duration_days: int
    ):
        """Send notification to user about level downgrade."""
        # Implementation would send email/SMS/push notification
        logger.info(
            f"Notification sent to {user_id}: Downgraded from {from_level.name} "
            f"to {to_level.name} - {trigger} (review period: {duration_days} days)"
        )
    
    def get_user_limits(
        self,
        user_id: str,
        level: TradingLevel,
        months_at_level: int = 0
    ) -> LevelLimits:
        """
        Get current limits for user based on level and experience.
        
        Args:
            user_id: User identifier
            level: Current trading level
            months_at_level: Months at current level (for progressive unlocking)
            
        Returns:
            LevelLimits object
        """
        return self.progressive_limit_unlock(
            user_id,
            level,
            months_at_level,
            {}  # Performance metrics would be passed here
        )


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Initialize system
    graduation_system = GraduationSystem()
    
    # Example: Check Level 1 graduation eligibility
    user_id = "user_123"
    performance = {
        "win_rate": 0.583,
        "sharpe_ratio": 1.42,
        "max_drawdown": 0.087,
        "total_trades": 127,
        "profit_factor": 1.67,
        "avg_rr": 1.83,
        "knowledge_test_score": 0.92,
        "risk_education_completed": True,
        "trading_days": 47
    }
    
    eligible, reason, missing = graduation_system.check_level1_graduation_eligibility(
        user_id, performance
    )
    
    print(f"\nLevel 1 Graduation Check:")
    print(f"Eligible: {eligible}")
    print(f"Reason: {reason}")
    if missing:
        print(f"Missing criteria: {missing}")
    
    # Example: Get user limits
    level_2_limits = graduation_system.get_user_limits(
        user_id,
        TradingLevel.LIMITED_LIVE,
        months_at_level=0
    )
    
    print(f"\nLevel 2 Limits:")
    print(f"Max account value: ${level_2_limits.max_account_value:,.0f}")
    print(f"Max position size: ${level_2_limits.max_position_size:,.0f}")
    print(f"Max open positions: {level_2_limits.max_open_positions}")
    print(f"Daily loss limit: ${level_2_limits.daily_loss_limit:,.0f}")
    
    # Example: Progressive unlocking at Level 3
    for months in [0, 3, 6, 12]:
        limits = graduation_system.get_user_limits(
            user_id,
            TradingLevel.FULL_LIVE,
            months_at_level=months
        )
        print(f"\nLevel 3 after {months} months:")
        print(f"  Max account: ${limits.max_account_value:,.0f}")
        print(f"  Max position: ${limits.max_position_size:,.0f}")
        print(f"  Max leverage: {limits.max_leverage}x")
