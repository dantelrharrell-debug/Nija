"""
Copy-Trade Health Scoring System
=================================

Evaluates the overall health and performance of copy trading operations.
Provides actionable metrics and scores to optimize copy trading effectiveness.

Health Dimensions:
- Copy Success Rate
- Slippage Impact  
- Follower Engagement
- PnL Consistency
- System Reliability

Author: NIJA Trading Systems
Date: January 30, 2026
"""

import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta

logger = logging.getLogger('nija.copy_health')


@dataclass
class CopyTradeHealthScore:
    """Overall copy trade health score and metrics."""
    
    # Overall health score (0-100)
    overall_score: float
    health_grade: str  # 'A', 'B', 'C', 'D', 'F'
    
    # Individual dimension scores (0-100)
    copy_success_score: float
    slippage_score: float
    engagement_score: float
    pnl_consistency_score: float
    reliability_score: float
    
    # Underlying metrics
    total_signals_emitted: int
    successful_copies: int
    failed_copies: int
    avg_slippage_pct: float
    active_followers: int
    total_followers: int
    avg_follower_pnl_pct: float
    pnl_std_dev: float
    uptime_pct: float
    
    # Recommendations
    recommendations: List[str]
    warnings: List[str]
    
    # Timestamp
    timestamp: float
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return asdict(self)


class CopyTradeHealthScoring:
    """
    Calculates health scores for copy trading operations.
    
    Analyzes multiple dimensions of copy trading performance and provides
    an overall health score with actionable recommendations.
    """
    
    def __init__(self):
        """Initialize health scoring system."""
        logger.info("=" * 70)
        logger.info("🏥 COPY TRADE HEALTH SCORING INITIALIZED")
        logger.info("=" * 70)
    
    def calculate_health_score(
        self,
        total_signals: int,
        successful_copies: int,
        failed_copies: int,
        avg_slippage_pct: float,
        active_followers: int,
        total_followers: int,
        follower_pnl_data: List[float],
        uptime_pct: float
    ) -> CopyTradeHealthScore:
        """
        Calculate comprehensive health score.
        
        Args:
            total_signals: Total signals emitted by master
            successful_copies: Number of successful copy trades
            failed_copies: Number of failed copy trades
            avg_slippage_pct: Average slippage percentage
            active_followers: Number of actively trading followers
            total_followers: Total number of configured followers
            follower_pnl_data: List of follower PnL percentages
            uptime_pct: System uptime percentage
        
        Returns:
            CopyTradeHealthScore object
        """
        # Calculate individual dimension scores
        copy_success_score = self._calculate_copy_success_score(
            total_signals, successful_copies, failed_copies
        )
        
        slippage_score = self._calculate_slippage_score(avg_slippage_pct)
        
        engagement_score = self._calculate_engagement_score(
            active_followers, total_followers
        )
        
        pnl_consistency_score = self._calculate_pnl_consistency_score(
            follower_pnl_data
        )
        
        reliability_score = self._calculate_reliability_score(uptime_pct)
        
        # Calculate overall score (weighted average)
        overall_score = (
            copy_success_score * 0.30 +  # 30% weight
            slippage_score * 0.20 +       # 20% weight
            engagement_score * 0.20 +     # 20% weight
            pnl_consistency_score * 0.20 + # 20% weight
            reliability_score * 0.10       # 10% weight
        )
        
        # Determine health grade
        health_grade = self._get_health_grade(overall_score)
        
        # Calculate metrics
        avg_follower_pnl_pct = sum(follower_pnl_data) / len(follower_pnl_data) if follower_pnl_data else 0.0
        pnl_std_dev = self._calculate_std_dev(follower_pnl_data) if follower_pnl_data else 0.0
        
        # Generate recommendations and warnings
        recommendations, warnings = self._generate_recommendations(
            copy_success_score, slippage_score, engagement_score,
            pnl_consistency_score, reliability_score, overall_score
        )
        
        return CopyTradeHealthScore(
            overall_score=overall_score,
            health_grade=health_grade,
            copy_success_score=copy_success_score,
            slippage_score=slippage_score,
            engagement_score=engagement_score,
            pnl_consistency_score=pnl_consistency_score,
            reliability_score=reliability_score,
            total_signals_emitted=total_signals,
            successful_copies=successful_copies,
            failed_copies=failed_copies,
            avg_slippage_pct=avg_slippage_pct,
            active_followers=active_followers,
            total_followers=total_followers,
            avg_follower_pnl_pct=avg_follower_pnl_pct,
            pnl_std_dev=pnl_std_dev,
            uptime_pct=uptime_pct,
            recommendations=recommendations,
            warnings=warnings,
            timestamp=datetime.now().timestamp()
        )
    
    def _calculate_copy_success_score(
        self, total_signals: int, successful: int, failed: int
    ) -> float:
        """Calculate copy success rate score (0-100)."""
        if total_signals == 0:
            return 100.0  # No signals = perfect score (no failures)
        
        success_rate = (successful / (successful + failed)) * 100 if (successful + failed) > 0 else 100.0
        
        # Score based on success rate
        if success_rate >= 95:
            return 100.0
        elif success_rate >= 90:
            return 90.0
        elif success_rate >= 80:
            return 75.0
        elif success_rate >= 70:
            return 60.0
        elif success_rate >= 50:
            return 40.0
        else:
            return 20.0
    
    def _calculate_slippage_score(self, avg_slippage_pct: float) -> float:
        """Calculate slippage impact score (0-100)."""
        # Lower slippage = better score
        if avg_slippage_pct <= 0.5:
            return 100.0
        elif avg_slippage_pct <= 1.0:
            return 90.0
        elif avg_slippage_pct <= 1.5:
            return 75.0
        elif avg_slippage_pct <= 2.0:
            return 60.0
        elif avg_slippage_pct <= 3.0:
            return 40.0
        else:
            return 20.0
    
    def _calculate_engagement_score(
        self, active_followers: int, total_followers: int
    ) -> float:
        """Calculate follower engagement score (0-100)."""
        if total_followers == 0:
            return 50.0  # Neutral score when no followers configured
        
        engagement_rate = (active_followers / total_followers) * 100
        
        if engagement_rate >= 80:
            return 100.0
        elif engagement_rate >= 60:
            return 85.0
        elif engagement_rate >= 40:
            return 65.0
        elif engagement_rate >= 20:
            return 45.0
        else:
            return 25.0
    
    def _calculate_pnl_consistency_score(self, follower_pnl_data: List[float]) -> float:
        """Calculate PnL consistency score (0-100)."""
        if not follower_pnl_data or len(follower_pnl_data) < 2:
            return 75.0  # Neutral score for insufficient data
        
        std_dev = self._calculate_std_dev(follower_pnl_data)
        
        # Lower std dev = more consistent = better score
        if std_dev <= 5.0:
            return 100.0
        elif std_dev <= 10.0:
            return 85.0
        elif std_dev <= 15.0:
            return 70.0
        elif std_dev <= 20.0:
            return 55.0
        elif std_dev <= 30.0:
            return 40.0
        else:
            return 25.0
    
    def _calculate_reliability_score(self, uptime_pct: float) -> float:
        """Calculate system reliability score (0-100)."""
        if uptime_pct >= 99.0:
            return 100.0
        elif uptime_pct >= 95.0:
            return 90.0
        elif uptime_pct >= 90.0:
            return 75.0
        elif uptime_pct >= 80.0:
            return 60.0
        elif uptime_pct >= 70.0:
            return 40.0
        else:
            return 20.0
    
    def _get_health_grade(self, score: float) -> str:
        """Convert numerical score to letter grade."""
        if score >= 90:
            return 'A'
        elif score >= 80:
            return 'B'
        elif score >= 70:
            return 'C'
        elif score >= 60:
            return 'D'
        else:
            return 'F'
    
    def _calculate_std_dev(self, data: List[float]) -> float:
        """Calculate standard deviation."""
        if not data or len(data) < 2:
            return 0.0
        
        mean = sum(data) / len(data)
        variance = sum((x - mean) ** 2 for x in data) / len(data)
        return variance ** 0.5
    
    def _generate_recommendations(
        self,
        copy_success: float,
        slippage: float,
        engagement: float,
        pnl_consistency: float,
        reliability: float,
        overall: float
    ) -> tuple[List[str], List[str]]:
        """Generate actionable recommendations and warnings."""
        recommendations = []
        warnings = []
        
        # Copy success recommendations
        if copy_success < 70:
            warnings.append("⚠️  Low copy success rate - investigate follower requirements and broker connectivity")
            recommendations.append("Review follower account configurations and ensure adequate balance")
        elif copy_success < 90:
            recommendations.append("Consider adjusting follower balance buffers to reduce failures")
        
        # Slippage recommendations
        if slippage < 60:
            warnings.append("⚠️  High slippage detected - followers experiencing significant price deterioration")
            recommendations.append("Reduce max_slippage_pct threshold or improve signal emission speed")
        elif slippage < 80:
            recommendations.append("Monitor slippage trends - consider tightening slippage limits")
        
        # Engagement recommendations
        if engagement < 50:
            warnings.append("⚠️  Low follower engagement - many configured followers not actively trading")
            recommendations.append("Review inactive follower accounts and verify they meet copy trading requirements")
        elif engagement < 70:
            recommendations.append("Some followers inactive - check account balances and API connections")
        
        # PnL consistency recommendations
        if pnl_consistency < 60:
            warnings.append("⚠️  High PnL variance across followers - inconsistent performance")
            recommendations.append("Investigate why some followers underperforming - check slippage and sizing")
        elif pnl_consistency < 80:
            recommendations.append("Monitor follower PnL distribution for early detection of issues")
        
        # Reliability recommendations
        if reliability < 70:
            warnings.append("⚠️  Low system uptime - affecting copy trade reliability")
            recommendations.append("Improve infrastructure stability and monitor for connection issues")
        elif reliability < 90:
            recommendations.append("Minor uptime issues detected - review system logs")
        
        # Overall health recommendations
        if overall >= 90:
            recommendations.append("✅ Excellent copy trading health - maintain current practices")
        elif overall >= 80:
            recommendations.append("Good copy trading health - minor optimizations recommended")
        elif overall >= 70:
            recommendations.append("Moderate health - address identified issues to improve performance")
        else:
            warnings.append("⚠️  Poor copy trading health - immediate action required")
            recommendations.append("🔧 Priority: Address all warnings above to restore healthy operations")
        
        return recommendations, warnings
    
    def print_health_report(self, score: CopyTradeHealthScore):
        """Print formatted health report."""
        print("\n" + "=" * 70)
        print(f"🏥 COPY TRADE HEALTH REPORT")
        print("=" * 70)
        print(f"   Overall Score: {score.overall_score:.1f}/100")
        print(f"   Health Grade: {score.health_grade}")
        print()
        print(f"   📊 DIMENSION SCORES:")
        print(f"      Copy Success Rate: {score.copy_success_score:.1f}/100")
        print(f"      Slippage Control: {score.slippage_score:.1f}/100")
        print(f"      Follower Engagement: {score.engagement_score:.1f}/100")
        print(f"      PnL Consistency: {score.pnl_consistency_score:.1f}/100")
        print(f"      System Reliability: {score.reliability_score:.1f}/100")
        print()
        print(f"   📈 KEY METRICS:")
        print(f"      Signals Emitted: {score.total_signals_emitted}")
        print(f"      Successful Copies: {score.successful_copies}")
        print(f"      Failed Copies: {score.failed_copies}")
        print(f"      Avg Slippage: {score.avg_slippage_pct:.2f}%")
        print(f"      Active Followers: {score.active_followers}/{score.total_followers}")
        print(f"      Avg Follower PnL: {score.avg_follower_pnl_pct:+.2f}%")
        print(f"      PnL Std Dev: {score.pnl_std_dev:.2f}%")
        print(f"      System Uptime: {score.uptime_pct:.1f}%")
        
        if score.warnings:
            print()
            print(f"   ⚠️  WARNINGS:")
            for warning in score.warnings:
                print(f"      {warning}")
        
        if score.recommendations:
            print()
            print(f"   💡 RECOMMENDATIONS:")
            for rec in score.recommendations:
                print(f"      {rec}")
        
        print("=" * 70)


# Global instance
_copy_health_scoring = None


def get_copy_health_scoring() -> CopyTradeHealthScoring:
    """Get global copy health scoring instance."""
    global _copy_health_scoring
    if _copy_health_scoring is None:
        _copy_health_scoring = CopyTradeHealthScoring()
    return _copy_health_scoring
