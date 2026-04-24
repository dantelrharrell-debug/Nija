"""
NIJA Scaling Greenlight System
================================

Defines the exact criteria and report format required to unlock position scaling.
Users start with small positions and must "prove" profitability before being
allowed to scale up to larger position sizes.

Greenlight Criteria:
- Profit Proven: YES (all profit proven criteria met)
- Min Net Profit: +$50 (absolute minimum dollar profit)
- Min ROI: +5% (minimum return on initial capital)
- Max Drawdown: <15% (risk management validated)
- Win Rate: ≥45% (trade quality validated)
- Trade Sample: ≥50 trades (statistical significance)
- Time Period: ≥24 hours (multiple market sessions)
- No Risk Violations: 0 kill switch triggers, 0 daily limit hits

Scaling Tiers:
- Tier 0 (Locked): $0 - Cannot trade (failed validation or violations)
- Tier 1 (Micro): $10-50 per trade - Default starting tier
- Tier 2 (Small): $50-100 per trade - Unlocked after greenlight
- Tier 3 (Medium): $100-500 per trade - Unlocked after sustained performance
- Tier 4 (Large): $500-1000 per trade - Unlocked after proven at Tier 3

Author: NIJA Trading Systems
Version: 1.0
Date: February 6, 2026
"""

import logging
from typing import Dict, Optional, List, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum
import json

logger = logging.getLogger("nija.scaling_greenlight")


class ScalingTier(Enum):
    """Position scaling tiers"""
    LOCKED = 0      # Cannot trade
    MICRO = 1       # $10-50 per trade
    SMALL = 2       # $50-100 per trade  
    MEDIUM = 3      # $100-500 per trade
    LARGE = 4       # $500-1000 per trade


class GreenlightStatus(Enum):
    """Greenlight approval status"""
    BLOCKED = "blocked"          # Trading blocked (violations)
    TESTING = "testing"          # Accumulating proof (Tier 1)
    GREENLIT = "greenlit"        # Approved to scale (Tier 2+)
    SCALED = "scaled"            # Already scaled up (Tier 3+)
    SUSPENDED = "suspended"      # Temporarily suspended


@dataclass
class GreenlightCriteria:
    """
    Criteria required to receive greenlight for scaling.
    
    These are the MINIMUM requirements. Users must meet ALL criteria.
    """
    # Profit requirements
    min_net_profit_usd: float = 50.0      # Minimum $50 profit
    min_roi_pct: float = 5.0              # Minimum 5% ROI
    
    # Risk requirements
    max_drawdown_pct: float = 15.0        # Max 15% drawdown
    min_win_rate_pct: float = 45.0        # Min 45% win rate
    
    # Statistical requirements
    min_trades: int = 50                   # Minimum 50 trades
    min_time_hours: float = 24.0          # Minimum 24 hours
    
    # Risk violation requirements
    max_kill_switch_triggers: int = 0      # No kill switch triggers
    max_daily_limit_hits: int = 0          # No daily limit hits
    max_position_rejections_pct: float = 5.0  # Max 5% position rejections
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return asdict(self)
    
    def __str__(self) -> str:
        """Human-readable criteria"""
        return (f"Greenlight Criteria: "
                f"${self.min_net_profit_usd:.0f} profit, "
                f"{self.min_roi_pct}% ROI, "
                f"{self.min_trades} trades, "
                f"{self.min_time_hours}h, "
                f"<{self.max_drawdown_pct}% DD, "
                f"≥{self.min_win_rate_pct}% WR")


@dataclass
class GreenlightReport:
    """
    Complete greenlight report with pass/fail status.
    
    This is the EXACT report required to unlock scaling.
    """
    # Report metadata
    report_id: str
    timestamp: str
    user_id: str
    
    # Overall status
    greenlight_status: str  # GreenlightStatus value
    current_tier: int       # ScalingTier value
    approved_tier: int      # Tier approved for (may be same as current)
    
    # Performance metrics
    net_profit_usd: float
    roi_pct: float
    win_rate_pct: float
    drawdown_pct: float
    trade_count: int
    time_elapsed_hours: float
    
    # Risk metrics
    kill_switch_triggers: int
    daily_limit_hits: int
    position_rejections: int
    position_rejection_pct: float
    
    # Criteria checks (pass/fail for each)
    profit_check: bool
    roi_check: bool
    win_rate_check: bool
    drawdown_check: bool
    trade_count_check: bool
    time_check: bool
    risk_violations_check: bool
    
    # Overall approval
    all_criteria_met: bool
    
    # Next steps
    next_steps: List[str]
    
    # Supporting data
    criteria_used: Dict
    performance_data: Dict
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return asdict(self)
    
    def to_json(self) -> str:
        """Convert to JSON"""
        return json.dumps(self.to_dict(), indent=2)
    
    def to_text_report(self) -> str:
        """Convert to human-readable text report"""
        lines = [
            "=" * 80,
            "NIJA SCALING GREENLIGHT REPORT",
            "=" * 80,
            f"Report ID:  {self.report_id}",
            f"Date:       {self.timestamp}",
            f"User:       {self.user_id}",
            "",
            f"CURRENT STATUS: {self.greenlight_status.upper()}",
            f"Current Tier:   Tier {self.current_tier} ({ScalingTier(self.current_tier).name})",
            f"Approved Tier:  Tier {self.approved_tier} ({ScalingTier(self.approved_tier).name})",
            "",
            "=" * 80,
            "CRITERIA EVALUATION",
            "=" * 80,
            "",
            "Performance Requirements:",
            f"  ✅ Net Profit:     ${self.net_profit_usd:.2f}" if self.profit_check else f"  ❌ Net Profit:     ${self.net_profit_usd:.2f}",
            f"  ✅ ROI:            {self.roi_pct:.2f}%" if self.roi_check else f"  ❌ ROI:            {self.roi_pct:.2f}%",
            f"  ✅ Win Rate:       {self.win_rate_pct:.1f}%" if self.win_rate_check else f"  ❌ Win Rate:       {self.win_rate_pct:.1f}%",
            f"  ✅ Drawdown:       {self.drawdown_pct:.2f}%" if self.drawdown_check else f"  ❌ Drawdown:       {self.drawdown_pct:.2f}%",
            "",
            "Statistical Requirements:",
            f"  ✅ Trade Count:    {self.trade_count} trades" if self.trade_count_check else f"  ❌ Trade Count:    {self.trade_count} trades",
            f"  ✅ Time Period:    {self.time_elapsed_hours:.1f} hours" if self.time_check else f"  ❌ Time Period:    {self.time_elapsed_hours:.1f} hours",
            "",
            "Risk Management:",
            f"  ✅ No Violations:  Clean record" if self.risk_violations_check else f"  ❌ Risk Violations: {self.kill_switch_triggers} kill switch, {self.daily_limit_hits} daily limits",
            f"     - Kill Switch Triggers: {self.kill_switch_triggers}",
            f"     - Daily Limit Hits: {self.daily_limit_hits}",
            f"     - Position Rejections: {self.position_rejections} ({self.position_rejection_pct:.1f}%)",
            "",
            "=" * 80,
            "DECISION",
            "=" * 80,
        ]
        
        if self.all_criteria_met:
            lines.extend([
                "",
                "🎉 GREENLIGHT APPROVED 🎉",
                "",
                f"Congratulations! You have met all criteria for scaling.",
                f"You are approved to scale to Tier {self.approved_tier} ({ScalingTier(self.approved_tier).name}).",
                "",
                "Position Limits:",
            ])
            
            # Show new position limits
            tier = ScalingTier(self.approved_tier)
            if tier == ScalingTier.SMALL:
                lines.append("  New: $50 - $100 per trade")
            elif tier == ScalingTier.MEDIUM:
                lines.append("  New: $100 - $500 per trade")
            elif tier == ScalingTier.LARGE:
                lines.append("  New: $500 - $1,000 per trade")
        else:
            lines.extend([
                "",
                "❌ GREENLIGHT NOT APPROVED",
                "",
                "You have not yet met all criteria for scaling.",
                f"Current tier remains: Tier {self.current_tier} ({ScalingTier(self.current_tier).name})",
            ])
        
        lines.extend([
            "",
            "=" * 80,
            "NEXT STEPS",
            "=" * 80,
        ])
        
        for i, step in enumerate(self.next_steps, 1):
            lines.append(f"{i}. {step}")
        
        lines.append("=" * 80)
        
        return "\n".join(lines)


class ScalingGreenlightSystem:
    """
    Manages scaling approval and tier progression.
    
    Determines when users are ready to scale position sizes based on
    proven performance and risk management.
    """
    
    def __init__(self, criteria: Optional[GreenlightCriteria] = None):
        """
        Initialize scaling greenlight system.
        
        Args:
            criteria: Custom criteria (uses defaults if None)
        """
        self.criteria = criteria or GreenlightCriteria()
        self._report_counter = 0
        
        logger.info("✅ Scaling Greenlight System initialized")
        logger.info(f"   {self.criteria}")
    
    def generate_greenlight_report(
        self,
        user_id: str,
        current_tier: ScalingTier,
        performance_metrics: Dict,
        risk_metrics: Dict
    ) -> GreenlightReport:
        """
        Generate greenlight report for a user.
        
        Args:
            user_id: User identifier
            current_tier: Current scaling tier
            performance_metrics: Performance data from profit proven tracker
            risk_metrics: Risk violation data from hard controls
        
        Returns:
            Complete greenlight report
        """
        # Generate report ID
        self._report_counter += 1
        report_id = f"GLR-{datetime.now().strftime('%Y%m%d%H%M%S')}-{self._report_counter:04d}"
        
        # Extract metrics
        net_profit = performance_metrics.get('net_profit_usd', 0.0)
        roi_pct = performance_metrics.get('net_profit_pct', 0.0)
        win_rate = performance_metrics.get('win_rate_pct', 0.0)
        drawdown = performance_metrics.get('drawdown_pct', 0.0)
        trade_count = performance_metrics.get('trade_count', 0)
        time_hours = performance_metrics.get('time_elapsed_hours', 0.0)
        
        kill_switch_triggers = risk_metrics.get('kill_switch_triggers', 0)
        daily_limit_hits = risk_metrics.get('daily_limit_hits', 0)
        position_rejections = risk_metrics.get('position_rejections', 0)
        total_validations = risk_metrics.get('total_validations', 0)
        rejection_pct = (position_rejections / total_validations * 100) if total_validations > 0 else 0.0
        
        # Evaluate criteria
        profit_check = net_profit >= self.criteria.min_net_profit_usd
        roi_check = roi_pct >= self.criteria.min_roi_pct
        win_rate_check = win_rate >= self.criteria.min_win_rate_pct
        drawdown_check = drawdown <= self.criteria.max_drawdown_pct
        trade_count_check = trade_count >= self.criteria.min_trades
        time_check = time_hours >= self.criteria.min_time_hours
        risk_violations_check = (
            kill_switch_triggers <= self.criteria.max_kill_switch_triggers and
            daily_limit_hits <= self.criteria.max_daily_limit_hits and
            rejection_pct <= self.criteria.max_position_rejections_pct
        )
        
        # Overall approval
        all_criteria_met = all([
            profit_check,
            roi_check,
            win_rate_check,
            drawdown_check,
            trade_count_check,
            time_check,
            risk_violations_check
        ])
        
        # Determine status and approved tier
        if not risk_violations_check:
            status = GreenlightStatus.BLOCKED
            approved_tier = ScalingTier.LOCKED
        elif all_criteria_met:
            if current_tier == ScalingTier.MICRO:
                status = GreenlightStatus.GREENLIT
                approved_tier = ScalingTier.SMALL
            elif current_tier == ScalingTier.SMALL:
                status = GreenlightStatus.SCALED
                approved_tier = ScalingTier.MEDIUM
            else:
                status = GreenlightStatus.SCALED
                approved_tier = current_tier
        else:
            status = GreenlightStatus.TESTING
            approved_tier = current_tier
        
        # Generate next steps
        next_steps = self._generate_next_steps(
            all_criteria_met=all_criteria_met,
            profit_check=profit_check,
            roi_check=roi_check,
            win_rate_check=win_rate_check,
            drawdown_check=drawdown_check,
            trade_count_check=trade_count_check,
            time_check=time_check,
            risk_violations_check=risk_violations_check,
            current_tier=current_tier,
            approved_tier=approved_tier,
            net_profit=net_profit,
            roi_pct=roi_pct,
            trade_count=trade_count,
            time_hours=time_hours
        )
        
        # Create report
        report = GreenlightReport(
            report_id=report_id,
            timestamp=datetime.now().isoformat() + 'Z',
            user_id=user_id,
            greenlight_status=status.value,
            current_tier=current_tier.value,
            approved_tier=approved_tier.value,
            net_profit_usd=net_profit,
            roi_pct=roi_pct,
            win_rate_pct=win_rate,
            drawdown_pct=drawdown,
            trade_count=trade_count,
            time_elapsed_hours=time_hours,
            kill_switch_triggers=kill_switch_triggers,
            daily_limit_hits=daily_limit_hits,
            position_rejections=position_rejections,
            position_rejection_pct=rejection_pct,
            profit_check=profit_check,
            roi_check=roi_check,
            win_rate_check=win_rate_check,
            drawdown_check=drawdown_check,
            trade_count_check=trade_count_check,
            time_check=time_check,
            risk_violations_check=risk_violations_check,
            all_criteria_met=all_criteria_met,
            next_steps=next_steps,
            criteria_used=self.criteria.to_dict(),
            performance_data=performance_metrics,
        )
        
        return report
    
    def _generate_next_steps(
        self,
        all_criteria_met: bool,
        profit_check: bool,
        roi_check: bool,
        win_rate_check: bool,
        drawdown_check: bool,
        trade_count_check: bool,
        time_check: bool,
        risk_violations_check: bool,
        current_tier: ScalingTier,
        approved_tier: ScalingTier,
        net_profit: float,
        roi_pct: float,
        trade_count: int,
        time_hours: float
    ) -> List[str]:
        """Generate actionable next steps based on current status"""
        steps = []
        
        if all_criteria_met:
            if approved_tier.value > current_tier.value:
                steps.append(f"✅ You are approved to scale to Tier {approved_tier.value} ({approved_tier.name})")
                steps.append("Contact support or update your account settings to activate new tier")
                steps.append("Continue trading consistently to maintain tier status")
            else:
                steps.append("✅ You have met all criteria for your current tier")
                steps.append("Continue trading to build track record for next tier")
                steps.append(f"Target: Sustain performance for {self.criteria.min_time_hours * 2}h at current tier")
        else:
            steps.append("Continue testing with current position sizes")
            
            # Specific improvements needed
            if not profit_check:
                needed = self.criteria.min_net_profit_usd - net_profit
                steps.append(f"📈 Profit Target: Earn ${needed:.2f} more to reach ${self.criteria.min_net_profit_usd:.0f}")
            
            if not roi_check:
                needed = self.criteria.min_roi_pct - roi_pct
                steps.append(f"📈 ROI Target: Increase ROI by {needed:.2f}% to reach {self.criteria.min_roi_pct}%")
            
            if not win_rate_check:
                steps.append(f"📈 Win Rate: Improve win rate to ≥{self.criteria.min_win_rate_pct}%")
            
            if not drawdown_check:
                steps.append(f"⚠️  Drawdown: Reduce drawdown to ≤{self.criteria.max_drawdown_pct}%")
            
            if not trade_count_check:
                needed = self.criteria.min_trades - trade_count
                steps.append(f"📊 Trade Count: Complete {needed} more trades to reach {self.criteria.min_trades}")
            
            if not time_check:
                needed = self.criteria.min_time_hours - time_hours
                steps.append(f"⏱️  Time: Continue trading for {needed:.1f} more hours")
            
            if not risk_violations_check:
                steps.append("🚨 Risk Violations: Resolve violations before scaling approval")
                steps.append("Contact support to review risk violations")
        
        return steps
    
    def get_tier_limits(self, tier: ScalingTier) -> Dict[str, float]:
        """
        Get position size limits for a tier.
        
        Args:
            tier: Scaling tier
        
        Returns:
            Dict with min and max position sizes
        """
        limits = {
            ScalingTier.LOCKED: {'min': 0.0, 'max': 0.0},
            ScalingTier.MICRO: {'min': 10.0, 'max': 50.0},
            ScalingTier.SMALL: {'min': 50.0, 'max': 100.0},
            ScalingTier.MEDIUM: {'min': 100.0, 'max': 500.0},
            ScalingTier.LARGE: {'min': 500.0, 'max': 1000.0},
        }
        
        return limits.get(tier, {'min': 0.0, 'max': 0.0})


# Global greenlight system instance
_global_greenlight_system: Optional[ScalingGreenlightSystem] = None


def get_greenlight_system(
    criteria: Optional[GreenlightCriteria] = None
) -> ScalingGreenlightSystem:
    """
    Get or create global greenlight system.
    
    Args:
        criteria: Custom criteria (only used on first creation)
    
    Returns:
        Global greenlight system instance
    """
    global _global_greenlight_system
    
    if _global_greenlight_system is None:
        _global_greenlight_system = ScalingGreenlightSystem(criteria)
    
    return _global_greenlight_system


__all__ = [
    'ScalingTier',
    'GreenlightStatus',
    'GreenlightCriteria',
    'GreenlightReport',
    'ScalingGreenlightSystem',
    'get_greenlight_system',
]
