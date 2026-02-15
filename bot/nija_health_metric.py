"""
NIJA HEALTH METRIC
==================
Requirement D: One golden metric

Logs health status every cycle:

📊 NIJA HEALTH METRIC
Starting Balance (24h): $61.20
Current Balance: $63.38
Net Change: +$2.18
Status: POSITIVE

If red (negative) → reduce trading aggression
If green (positive) → maintain or increase aggression
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass
import json
import os

logger = logging.getLogger(__name__)


@dataclass
class HealthSnapshot:
    """Single health metric snapshot"""
    timestamp: datetime
    starting_balance: float
    current_balance: float
    net_change: float
    status: str  # "POSITIVE", "NEGATIVE", or "FLAT"
    period_hours: int


class NIJAHealthMetric:
    """
    The ONE metric that matters: Is NIJA making or losing money?
    
    This is the truth that determines if NIJA can claim profitability.
    If this metric is red (negative), NIJA must reduce aggression.
    
    GUARDRAIL 2: Hard drawdown circuit breaker
    If 24h net PnL <= -3% → new entries paused, exits only
    """
    
    # Aggression level thresholds (class-level constants)
    SEVERE_LOSS_PCT = 10.0  # > 10% loss
    SEVERE_LOSS_AGGRESSION = 0.3
    
    SIGNIFICANT_LOSS_PCT = 5.0  # > 5% loss
    SIGNIFICANT_LOSS_AGGRESSION = 0.5
    
    MODERATE_LOSS_PCT = 2.0  # > 2% loss
    MODERATE_LOSS_AGGRESSION = 0.7
    
    MINOR_LOSS_AGGRESSION = 0.85  # < 2% loss
    
    STRONG_PROFIT_PCT = 5.0  # > 5% gain
    STRONG_PROFIT_AGGRESSION = 1.0
    
    GOOD_PROFIT_PCT = 2.0  # > 2% gain
    GOOD_PROFIT_AGGRESSION = 0.95
    
    SMALL_PROFIT_AGGRESSION = 0.9  # < 2% gain
    
    FLAT_AGGRESSION = 0.75  # No change
    
    # GUARDRAIL 2: Circuit breaker threshold
    CIRCUIT_BREAKER_PCT = 3.0  # -3% in 24h triggers circuit breaker
    
    def __init__(self, 
                 storage_path: str = "/tmp/nija_health_metric.json",
                 lookback_hours: int = 24,
                 circuit_breaker_enabled: bool = True):
        """
        Args:
            storage_path: Where to persist health records
            lookback_hours: How far back to compare (default: 24 hours)
            circuit_breaker_enabled: Enable hard drawdown circuit breaker
        """
        self.storage_path = storage_path
        self.lookback_hours = lookback_hours
        self.history: List[HealthSnapshot] = []
        self._load_history()
        
        # Trading aggression level (affected by health)
        self.current_aggression_level = 1.0  # 0.0 to 1.0 (1.0 = normal)
        
        # GUARDRAIL 2: Circuit breaker state
        self.circuit_breaker_enabled = circuit_breaker_enabled
        self.circuit_breaker_active = False
        self.circuit_breaker_trigger_time = None
        
        logger.info(f"📊 NIJAHealthMetric initialized (lookback: {lookback_hours}h)")
        if circuit_breaker_enabled:
            logger.info(f"🧯 Circuit breaker enabled: -{self.CIRCUIT_BREAKER_PCT}% triggers pause")
    
    def _load_history(self):
        """Load historical health snapshots"""
        try:
            with open(self.storage_path, 'r') as f:
                data = json.load(f)
                for record in data:
                    self.history.append(HealthSnapshot(
                        timestamp=datetime.fromisoformat(record['timestamp']),
                        starting_balance=record['starting_balance'],
                        current_balance=record['current_balance'],
                        net_change=record['net_change'],
                        status=record['status'],
                        period_hours=record['period_hours']
                    ))
            logger.info(f"   Loaded {len(self.history)} historical health snapshots")
        except FileNotFoundError:
            logger.info("   No historical health data (starting fresh)")
        except Exception as e:
            logger.warning(f"   Error loading health history: {e}")
    
    def _save_history(self):
        """Persist health history"""
        try:
            data = [
                {
                    'timestamp': snapshot.timestamp.isoformat(),
                    'starting_balance': snapshot.starting_balance,
                    'current_balance': snapshot.current_balance,
                    'net_change': snapshot.net_change,
                    'status': snapshot.status,
                    'period_hours': snapshot.period_hours
                }
                for snapshot in self.history
            ]
            with open(self.storage_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving health history: {e}")
    
    def record_health_check(self, 
                           starting_balance: float,
                           current_balance: float,
                           period_hours: Optional[int] = None) -> HealthSnapshot:
        """
        Record a health check
        
        Args:
            starting_balance: Balance at start of period
            current_balance: Current balance
            period_hours: Period length (default: self.lookback_hours)
        
        Returns:
            HealthSnapshot with the current health status
        """
        if period_hours is None:
            period_hours = self.lookback_hours
        
        net_change = current_balance - starting_balance
        
        # Determine status
        if net_change > 0:
            status = "POSITIVE"
        elif net_change < 0:
            status = "NEGATIVE"
        else:
            status = "FLAT"
        
        snapshot = HealthSnapshot(
            timestamp=datetime.now(),
            starting_balance=starting_balance,
            current_balance=current_balance,
            net_change=net_change,
            status=status,
            period_hours=period_hours
        )
        
        # Add to history
        self.history.append(snapshot)
        
        # Keep only last 30 days of history
        cutoff = datetime.now() - timedelta(days=30)
        self.history = [s for s in self.history if s.timestamp > cutoff]
        
        self._save_history()
        
        # Update aggression level based on health
        self._update_aggression_level(snapshot)
        
        # Log the metric
        self._log_health_metric(snapshot)
        
        return snapshot
    
    def _update_aggression_level(self, snapshot: HealthSnapshot):
        """
        Update trading aggression based on health
        
        If losing money → reduce aggression
        If making money → maintain or increase aggression
        
        GUARDRAIL 2: Circuit breaker activation
        If 24h loss >= 3% → PAUSE new entries (exits only)
        """
        if snapshot.status == "NEGATIVE":
            # Calculate how much we're losing
            loss_pct = abs(snapshot.net_change / snapshot.starting_balance * 100) if snapshot.starting_balance > 0 else 0
            
            # GUARDRAIL 2: Check circuit breaker
            if self.circuit_breaker_enabled and loss_pct >= self.CIRCUIT_BREAKER_PCT:
                if not self.circuit_breaker_active:
                    self.circuit_breaker_active = True
                    self.circuit_breaker_trigger_time = datetime.now()
                    logger.error("")
                    logger.error("=" * 60)
                    logger.error("🧯 CIRCUIT BREAKER ACTIVATED")
                    logger.error("=" * 60)
                    logger.error(f"24h Loss: -{loss_pct:.2f}% (threshold: -{self.CIRCUIT_BREAKER_PCT}%)")
                    logger.error(f"NEW ENTRIES PAUSED - EXITS ONLY")
                    logger.error(f"Triggered at: {self.circuit_breaker_trigger_time}")
                    logger.error("This protects capital during bad market regimes")
                    logger.error("=" * 60)
                    logger.error("")
                else:
                    logger.warning(f"🧯 Circuit breaker still active (loss: -{loss_pct:.2f}%)")
            
            if loss_pct > self.SEVERE_LOSS_PCT:
                self.current_aggression_level = self.SEVERE_LOSS_AGGRESSION
                logger.warning(f"⚠️  SEVERE LOSSES: Reducing aggression to {self.current_aggression_level*100:.0f}%")
            elif loss_pct > self.SIGNIFICANT_LOSS_PCT:
                self.current_aggression_level = self.SIGNIFICANT_LOSS_AGGRESSION
                logger.warning(f"⚠️  SIGNIFICANT LOSSES: Reducing aggression to {self.current_aggression_level*100:.0f}%")
            elif loss_pct > self.MODERATE_LOSS_PCT:
                self.current_aggression_level = self.MODERATE_LOSS_AGGRESSION
                logger.warning(f"⚠️  LOSSES DETECTED: Reducing aggression to {self.current_aggression_level*100:.0f}%")
            else:
                self.current_aggression_level = self.MINOR_LOSS_AGGRESSION
                logger.info(f"⚠️  Minor losses: Slight aggression reduction to {self.current_aggression_level*100:.0f}%")
        
        elif snapshot.status == "POSITIVE":
            # Making money → can be more aggressive
            profit_pct = (snapshot.net_change / snapshot.starting_balance * 100) if snapshot.starting_balance > 0 else 0
            
            # GUARDRAIL 2: Reset circuit breaker on profitability
            if self.circuit_breaker_active:
                self.circuit_breaker_active = False
                logger.info("")
                logger.info("=" * 60)
                logger.info("✅ CIRCUIT BREAKER RESET")
                logger.info("=" * 60)
                logger.info(f"24h Profit: +{profit_pct:.2f}%")
                logger.info(f"NEW ENTRIES RESUMED")
                logger.info("=" * 60)
                logger.info("")
            
            if profit_pct > self.STRONG_PROFIT_PCT:
                self.current_aggression_level = self.STRONG_PROFIT_AGGRESSION
                logger.info(f"✅ STRONG PROFITS: Maximum aggression {self.current_aggression_level*100:.0f}%")
            elif profit_pct > self.GOOD_PROFIT_PCT:
                self.current_aggression_level = self.GOOD_PROFIT_AGGRESSION
                logger.info(f"✅ GOOD PROFITS: High aggression {self.current_aggression_level*100:.0f}%")
            else:
                self.current_aggression_level = self.SMALL_PROFIT_AGGRESSION
                logger.info(f"✅ PROFITS: Normal aggression {self.current_aggression_level*100:.0f}%")
        
        else:  # FLAT
            self.current_aggression_level = self.FLAT_AGGRESSION
            logger.info(f"⚠️  FLAT PERFORMANCE: Cautious aggression {self.current_aggression_level*100:.0f}%")
    
    def _log_health_metric(self, snapshot: HealthSnapshot):
        """
        Log the golden health metric in the standard format
        """
        logger.info("")
        logger.info("=" * 60)
        logger.info("📊 NIJA HEALTH METRIC")
        logger.info("=" * 60)
        logger.info(f"Starting Balance ({snapshot.period_hours}h): ${snapshot.starting_balance:.2f}")
        logger.info(f"Current Balance: ${snapshot.current_balance:.2f}")
        
        if snapshot.net_change >= 0:
            logger.info(f"Net Change: +${snapshot.net_change:.2f}")
        else:
            logger.info(f"Net Change: -${abs(snapshot.net_change):.2f}")
        
        logger.info(f"Status: {snapshot.status}")
        logger.info(f"Aggression Level: {self.current_aggression_level*100:.0f}%")
        # GUARDRAIL 2: Show circuit breaker status
        if self.circuit_breaker_active:
            logger.info(f"🧯 CIRCUIT BREAKER: ACTIVE (new entries PAUSED)")
        logger.info("=" * 60)
        logger.info("")
    
    def get_current_health(self) -> Optional[HealthSnapshot]:
        """Get the most recent health snapshot"""
        if self.history:
            return self.history[-1]
        return None
    
    def get_aggression_multiplier(self) -> float:
        """
        Get the current aggression multiplier
        
        This should be applied to:
        - Position sizes (multiply by this)
        - Maximum positions (multiply by this)
        - Entry thresholds (more conservative if lower)
        
        Returns:
            Float from 0.0 to 1.0 (1.0 = full aggression, 0.3 = very conservative)
        """
        return self.current_aggression_level
    
    def should_reduce_aggression(self) -> bool:
        """Check if we should reduce trading aggression"""
        return self.current_aggression_level < 1.0
    
    def should_pause_trading(self) -> bool:
        """Check if losses are severe enough to pause trading"""
        return self.current_aggression_level < 0.4
    
    def is_circuit_breaker_active(self) -> bool:
        """
        GUARDRAIL 2: Check if circuit breaker is active
        
        Returns:
            True if new entries should be paused (exits only)
        """
        return self.circuit_breaker_active
    
    def should_allow_new_entry(self) -> tuple[bool, str]:
        """
        GUARDRAIL 2: Check if new entries are allowed
        
        Returns:
            (allowed: bool, reason: str)
        """
        if self.circuit_breaker_active:
            return False, "Circuit breaker active: 24h loss >= 3%, NEW ENTRIES PAUSED"
        return True, "OK"
    
    def get_health_summary(self, days: int = 7) -> Dict:
        """
        Get health summary for the last N days
        
        Returns metrics about overall health trend
        """
        end_time = datetime.now()
        start_time = end_time - timedelta(days=days)
        
        recent_snapshots = [
            s for s in self.history
            if s.timestamp >= start_time
        ]
        
        if not recent_snapshots:
            return {
                'period_days': days,
                'snapshots': 0,
                'positive_checks': 0,
                'negative_checks': 0,
                'avg_change': 0.0,
                'total_change': 0.0,
                'trend': 'UNKNOWN',
                'health_score': 0
            }
        
        positive = sum(1 for s in recent_snapshots if s.status == "POSITIVE")
        negative = sum(1 for s in recent_snapshots if s.status == "NEGATIVE")
        total_change = sum(s.net_change for s in recent_snapshots)
        avg_change = total_change / len(recent_snapshots)
        
        # Determine trend
        if positive > negative and total_change > 0:
            trend = "IMPROVING"
        elif negative > positive and total_change < 0:
            trend = "DECLINING"
        else:
            trend = "MIXED"
        
        # Health score (0-100)
        health_score = 50  # Baseline
        if total_change > 0:
            health_score += min(30, total_change * 5)  # Up to +30 for profits
        else:
            health_score += max(-30, total_change * 5)  # Up to -30 for losses
        
        if positive > negative:
            health_score += 20
        elif negative > positive:
            health_score -= 20
        
        health_score = max(0, min(100, health_score))
        
        return {
            'period_days': days,
            'snapshots': len(recent_snapshots),
            'positive_checks': positive,
            'negative_checks': negative,
            'avg_change': avg_change,
            'total_change': total_change,
            'trend': trend,
            'health_score': health_score,
            'current_aggression': self.current_aggression_level
        }
    
    def print_health_report(self):
        """Print a comprehensive health report"""
        print("\n" + "="*60)
        print("📊 NIJA HEALTH REPORT")
        print("="*60)
        
        current = self.get_current_health()
        if current:
            print(f"\nCurrent Status:")
            print(f"  Starting Balance ({current.period_hours}h): ${current.starting_balance:.2f}")
            print(f"  Current Balance: ${current.current_balance:.2f}")
            if current.net_change >= 0:
                print(f"  Net Change: +${current.net_change:.2f}")
            else:
                print(f"  Net Change: -${abs(current.net_change):.2f}")
            print(f"  Status: {current.status}")
            print(f"  Aggression Level: {self.current_aggression_level*100:.0f}%")
        
        summary = self.get_health_summary(7)
        print(f"\n7-Day Summary:")
        print(f"  Health Checks: {summary['snapshots']}")
        print(f"  Positive: {summary['positive_checks']}")
        print(f"  Negative: {summary['negative_checks']}")
        print(f"  Total Change: ${summary['total_change']:.2f}")
        print(f"  Trend: {summary['trend']}")
        print(f"  Health Score: {summary['health_score']}/100")
        print("="*60)


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Initialize health metric
    health = NIJAHealthMetric(lookback_hours=24)
    
    # Simulate health checks
    print("\n📊 Simulating health checks...")
    
    # Day 1: Made money
    health.record_health_check(
        starting_balance=61.20,
        current_balance=63.38
    )
    
    # Day 2: Lost money (should reduce aggression)
    health.record_health_check(
        starting_balance=63.38,
        current_balance=62.15
    )
    
    # Day 3: Made money again
    health.record_health_check(
        starting_balance=62.15,
        current_balance=64.50
    )
    
    # Print report
    health.print_health_report()
    
    # Check aggression
    print(f"\n🎯 Current Aggression Multiplier: {health.get_aggression_multiplier():.2f}")
    print(f"   Should reduce aggression? {health.should_reduce_aggression()}")
    print(f"   Should pause trading? {health.should_pause_trading()}")
