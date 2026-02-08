"""
CLEANUP METRICS DASHBOARD
=========================
Enhancement 3: Track dust removed, capital reclaimed, and position size trends

This module provides comprehensive metrics tracking for cleanup operations,
useful for monitoring system health and capital efficiency over time.

Author: NIJA Trading Systems
Created: February 8, 2026
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from collections import defaultdict
import threading

logger = logging.getLogger("nija.cleanup_metrics")


@dataclass
class CleanupEvent:
    """Record of a cleanup operation"""
    timestamp: datetime
    symbol: str
    cleanup_type: str  # DUST, CAP_EXCEEDED, UNHEALTHY, STAGNANT
    size_usd: float
    pnl_pct: float
    pnl_usd: float
    age_hours: float
    reason: str
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        data = asdict(self)
        if isinstance(data['timestamp'], datetime):
            data['timestamp'] = data['timestamp'].isoformat()
        return data


@dataclass
class DailyMetrics:
    """Aggregated metrics for a single day"""
    date: str  # YYYY-MM-DD
    dust_positions_removed: int = 0
    dust_capital_reclaimed: float = 0.0
    cap_exceeded_removals: int = 0
    cap_exceeded_capital: float = 0.0
    unhealthy_removals: int = 0
    unhealthy_capital: float = 0.0
    stagnant_removals: int = 0
    stagnant_capital: float = 0.0
    total_removals: int = 0
    total_capital_reclaimed: float = 0.0
    avg_position_size: float = 0.0
    total_pnl_from_cleanup: float = 0.0
    
    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return asdict(self)


class CleanupMetricsTracker:
    """
    Cleanup Metrics Tracker
    
    Tracks:
    - Dust removed per day (count and USD value)
    - Capital reclaimed from cleanup operations
    - Average position size trends
    - Cleanup P&L (wins vs losses from forced exits)
    """
    
    def __init__(self, data_dir: str = "./data"):
        """
        Initialize cleanup metrics tracker
        
        Args:
            data_dir: Directory for metrics data files
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True, parents=True)
        
        # Data files
        self.events_file = self.data_dir / "cleanup_events.jsonl"
        self.daily_metrics_file = self.data_dir / "cleanup_daily_metrics.json"
        self.trends_file = self.data_dir / "cleanup_trends.json"
        
        # In-memory tracking
        self.cleanup_events: List[CleanupEvent] = []
        self.daily_metrics: Dict[str, DailyMetrics] = {}
        
        # Rolling window for position size tracking
        self.position_sizes: List[tuple] = []  # (timestamp, size_usd)
        
        # Thread safety
        self._lock = threading.Lock()
        
        # Load existing data
        self._load_daily_metrics()
        
        logger.info("✅ Cleanup Metrics Tracker initialized")
        logger.info(f"   Data directory: {self.data_dir}")
    
    def _load_daily_metrics(self):
        """Load daily metrics from file"""
        if not self.daily_metrics_file.exists():
            return
        
        try:
            with open(self.daily_metrics_file, 'r') as f:
                data = json.load(f)
                for date_str, metrics_dict in data.items():
                    self.daily_metrics[date_str] = DailyMetrics(**metrics_dict)
            logger.info(f"   Loaded metrics for {len(self.daily_metrics)} days")
        except Exception as e:
            logger.warning(f"Could not load daily metrics: {e}")
    
    def _save_daily_metrics(self):
        """Save daily metrics to file"""
        try:
            data = {
                date_str: metrics.to_dict() 
                for date_str, metrics in self.daily_metrics.items()
            }
            with open(self.daily_metrics_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save daily metrics: {e}")
    
    def record_cleanup(
        self,
        symbol: str,
        cleanup_type: str,
        size_usd: float,
        pnl_pct: float = 0.0,
        age_hours: float = 0.0,
        reason: str = ""
    ):
        """
        Record a cleanup operation
        
        Args:
            symbol: Trading symbol
            cleanup_type: Type of cleanup (DUST, CAP_EXCEEDED, UNHEALTHY, STAGNANT)
            size_usd: Position size in USD
            pnl_pct: P&L percentage at cleanup
            age_hours: Position age in hours
            reason: Human-readable cleanup reason
        """
        with self._lock:
            now = datetime.now()
            date_str = now.strftime("%Y-%m-%d")
            
            # Calculate P&L in USD
            pnl_usd = size_usd * pnl_pct
            
            # Create cleanup event
            event = CleanupEvent(
                timestamp=now,
                symbol=symbol,
                cleanup_type=cleanup_type,
                size_usd=size_usd,
                pnl_pct=pnl_pct,
                pnl_usd=pnl_usd,
                age_hours=age_hours,
                reason=reason
            )
            
            # Add to in-memory list
            self.cleanup_events.append(event)
            
            # Write to events file
            self._write_cleanup_event(event)
            
            # Update daily metrics
            if date_str not in self.daily_metrics:
                self.daily_metrics[date_str] = DailyMetrics(date=date_str)
            
            metrics = self.daily_metrics[date_str]
            
            # Update counts and capital by cleanup type
            if cleanup_type == "DUST":
                metrics.dust_positions_removed += 1
                metrics.dust_capital_reclaimed += size_usd
            elif cleanup_type == "CAP_EXCEEDED":
                metrics.cap_exceeded_removals += 1
                metrics.cap_exceeded_capital += size_usd
            elif cleanup_type == "UNHEALTHY":
                metrics.unhealthy_removals += 1
                metrics.unhealthy_capital += size_usd
            elif cleanup_type == "STAGNANT":
                metrics.stagnant_removals += 1
                metrics.stagnant_capital += size_usd
            
            # Update totals
            metrics.total_removals += 1
            metrics.total_capital_reclaimed += size_usd
            metrics.total_pnl_from_cleanup += pnl_usd
            
            # Save updated metrics
            self._save_daily_metrics()
            
            logger.info(f"📊 CLEANUP METRICS: {cleanup_type} cleanup recorded")
            logger.info(f"   Symbol: {symbol}")
            logger.info(f"   Size: ${size_usd:.2f}")
            logger.info(f"   P&L: {pnl_pct*100:+.2f}% (${pnl_usd:+.2f})")
            logger.info(f"   Today's total removals: {metrics.total_removals}")
    
    def _write_cleanup_event(self, event: CleanupEvent):
        """Write cleanup event to JSONL file"""
        try:
            with open(self.events_file, 'a') as f:
                f.write(json.dumps(event.to_dict()) + '\n')
        except Exception as e:
            logger.error(f"Failed to write cleanup event: {e}")
    
    def track_position_size(self, size_usd: float):
        """
        Track a position size for trend analysis
        
        Args:
            size_usd: Position size in USD
        """
        with self._lock:
            now = datetime.now()
            self.position_sizes.append((now, size_usd))
            
            # Keep only last 30 days
            cutoff = now - timedelta(days=30)
            self.position_sizes = [
                (t, s) for t, s in self.position_sizes if t > cutoff
            ]
            
            # Update today's average
            date_str = now.strftime("%Y-%m-%d")
            if date_str not in self.daily_metrics:
                self.daily_metrics[date_str] = DailyMetrics(date=date_str)
            
            # Calculate today's average
            today_sizes = [s for t, s in self.position_sizes if t.strftime("%Y-%m-%d") == date_str]
            if today_sizes:
                self.daily_metrics[date_str].avg_position_size = sum(today_sizes) / len(today_sizes)
                self._save_daily_metrics()
    
    def get_daily_metrics(self, date: Optional[str] = None) -> Optional[DailyMetrics]:
        """
        Get metrics for a specific date
        
        Args:
            date: Date string (YYYY-MM-DD), or None for today
        
        Returns:
            DailyMetrics or None if no data
        """
        with self._lock:
            if date is None:
                date = datetime.now().strftime("%Y-%m-%d")
            return self.daily_metrics.get(date)
    
    def get_metrics_range(self, start_date: str, end_date: str) -> List[DailyMetrics]:
        """
        Get metrics for a date range
        
        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
        
        Returns:
            List of DailyMetrics
        """
        with self._lock:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
            
            result = []
            current = start
            while current <= end:
                date_str = current.strftime("%Y-%m-%d")
                if date_str in self.daily_metrics:
                    result.append(self.daily_metrics[date_str])
                current += timedelta(days=1)
            
            return result
    
    def get_last_n_days(self, n: int = 7) -> List[DailyMetrics]:
        """
        Get metrics for the last N days
        
        Args:
            n: Number of days
        
        Returns:
            List of DailyMetrics
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=n-1)
        
        return self.get_metrics_range(
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d")
        )
    
    def get_position_size_trend(self, days: int = 30) -> Dict:
        """
        Calculate position size trends
        
        Args:
            days: Number of days to analyze
        
        Returns:
            Dictionary with trend data
        """
        with self._lock:
            cutoff = datetime.now() - timedelta(days=days)
            recent_sizes = [s for t, s in self.position_sizes if t > cutoff]
            
            if not recent_sizes:
                return {
                    'avg_size': 0.0,
                    'min_size': 0.0,
                    'max_size': 0.0,
                    'trend': 'insufficient_data',
                    'data_points': 0
                }
            
            avg_size = sum(recent_sizes) / len(recent_sizes)
            
            # Calculate trend (simple: compare first half to second half)
            mid = len(recent_sizes) // 2
            if mid > 0:
                first_half_avg = sum(recent_sizes[:mid]) / mid
                second_half_avg = sum(recent_sizes[mid:]) / (len(recent_sizes) - mid)
                
                pct_change = ((second_half_avg - first_half_avg) / first_half_avg) if first_half_avg > 0 else 0
                
                if pct_change > 0.1:
                    trend = 'increasing'
                elif pct_change < -0.1:
                    trend = 'decreasing'
                else:
                    trend = 'stable'
            else:
                trend = 'insufficient_data'
                pct_change = 0.0
            
            return {
                'avg_size': avg_size,
                'min_size': min(recent_sizes),
                'max_size': max(recent_sizes),
                'trend': trend,
                'trend_pct_change': pct_change,
                'data_points': len(recent_sizes)
            }
    
    def generate_dashboard_data(self) -> Dict:
        """
        Generate dashboard data with all metrics
        
        Returns:
            Dictionary with dashboard data
        """
        with self._lock:
            today = datetime.now().strftime("%Y-%m-%d")
            today_metrics = self.daily_metrics.get(today, DailyMetrics(date=today))
            
            last_7_days = self.get_last_n_days(7)
            last_30_days = self.get_last_n_days(30)
            
            # Calculate totals for periods
            week_totals = {
                'dust_removed': sum(m.dust_positions_removed for m in last_7_days),
                'capital_reclaimed': sum(m.total_capital_reclaimed for m in last_7_days),
                'total_removals': sum(m.total_removals for m in last_7_days),
                'total_pnl': sum(m.total_pnl_from_cleanup for m in last_7_days)
            }
            
            month_totals = {
                'dust_removed': sum(m.dust_positions_removed for m in last_30_days),
                'capital_reclaimed': sum(m.total_capital_reclaimed for m in last_30_days),
                'total_removals': sum(m.total_removals for m in last_30_days),
                'total_pnl': sum(m.total_pnl_from_cleanup for m in last_30_days)
            }
            
            # Position size trend
            size_trend = self.get_position_size_trend(30)
            
            return {
                'timestamp': datetime.now().isoformat(),
                'today': today_metrics.to_dict(),
                'last_7_days': week_totals,
                'last_30_days': month_totals,
                'position_size_trend': size_trend,
                'recent_events': [
                    event.to_dict() 
                    for event in self.cleanup_events[-10:]  # Last 10 events
                ]
            }
    
    def save_dashboard_data(self):
        """Save dashboard data to file"""
        try:
            data = self.generate_dashboard_data()
            dashboard_file = self.data_dir / "cleanup_dashboard.json"
            with open(dashboard_file, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info(f"✅ Dashboard data saved to {dashboard_file}")
        except Exception as e:
            logger.error(f"Failed to save dashboard data: {e}")
    
    def print_dashboard(self):
        """Print cleanup metrics dashboard to logs"""
        data = self.generate_dashboard_data()
        
        logger.info("\n" + "=" * 70)
        logger.info("CLEANUP METRICS DASHBOARD")
        logger.info("=" * 70)
        
        today = data['today']
        logger.info(f"\n📅 TODAY ({today['date']}):")
        logger.info(f"   Dust Removed: {today['dust_positions_removed']} positions (${today['dust_capital_reclaimed']:.2f})")
        logger.info(f"   Total Removals: {today['total_removals']} (${today['total_capital_reclaimed']:.2f})")
        logger.info(f"   Cleanup P&L: ${today['total_pnl_from_cleanup']:+.2f}")
        logger.info(f"   Avg Position Size: ${today['avg_position_size']:.2f}")
        
        week = data['last_7_days']
        logger.info(f"\n📊 LAST 7 DAYS:")
        logger.info(f"   Dust Removed: {week['dust_removed']} positions")
        logger.info(f"   Capital Reclaimed: ${week['capital_reclaimed']:.2f}")
        logger.info(f"   Total Removals: {week['total_removals']}")
        logger.info(f"   Cleanup P&L: ${week['total_pnl']:+.2f}")
        
        month = data['last_30_days']
        logger.info(f"\n📈 LAST 30 DAYS:")
        logger.info(f"   Dust Removed: {month['dust_removed']} positions")
        logger.info(f"   Capital Reclaimed: ${month['capital_reclaimed']:.2f}")
        logger.info(f"   Total Removals: {month['total_removals']}")
        logger.info(f"   Cleanup P&L: ${month['total_pnl']:+.2f}")
        
        trend = data['position_size_trend']
        logger.info(f"\n📏 POSITION SIZE TREND (30 days):")
        logger.info(f"   Average: ${trend['avg_size']:.2f}")
        logger.info(f"   Range: ${trend['min_size']:.2f} - ${trend['max_size']:.2f}")
        logger.info(f"   Trend: {trend['trend'].upper()} ({trend['trend_pct_change']*100:+.1f}%)")
        logger.info(f"   Data Points: {trend['data_points']}")
        
        logger.info("=" * 70 + "\n")


# Singleton instance
_default_tracker = None


def get_cleanup_metrics_tracker(data_dir: str = "./data") -> CleanupMetricsTracker:
    """
    Get default cleanup metrics tracker instance
    
    Args:
        data_dir: Data directory (used only on first call)
    
    Returns:
        CleanupMetricsTracker instance
    """
    global _default_tracker
    
    if _default_tracker is None:
        _default_tracker = CleanupMetricsTracker(data_dir)
    
    return _default_tracker


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    tracker = CleanupMetricsTracker()
    
    # Simulate some cleanup events
    tracker.record_cleanup(
        symbol="BTC-USD",
        cleanup_type="DUST",
        size_usd=0.85,
        pnl_pct=-0.02,
        age_hours=24.0,
        reason="Dust position ($0.85 < $1.00)"
    )
    
    tracker.record_cleanup(
        symbol="ETH-USD",
        cleanup_type="UNHEALTHY",
        size_usd=45.0,
        pnl_pct=-0.025,
        age_hours=12.0,
        reason="Unhealthy position (score: 25, strong loss, stagnant 8.0h)"
    )
    
    # Track position sizes
    for size in [100.0, 150.0, 75.0, 200.0, 125.0]:
        tracker.track_position_size(size)
    
    # Print dashboard
    tracker.print_dashboard()
    
    # Save dashboard data
    tracker.save_dashboard_data()
