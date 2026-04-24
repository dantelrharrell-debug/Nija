"""
NIJA Automated Performance Tracker

Continuous background monitoring and tracking of trading performance.
Automatically collects metrics at regular intervals and maintains performance history.

Features:
- Background thread for continuous monitoring
- Automatic metric collection every N seconds
- Performance history persistence
- Integration with broker and position manager
- Real-time performance snapshots
- Automatic report generation

Author: NIJA Trading Systems
Version: 1.0
Date: January 30, 2026
"""

import logging
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Callable
from pathlib import Path
import json

try:
    from kpi_tracker import get_kpi_tracker, KPITracker
except ImportError:
    from bot.kpi_tracker import get_kpi_tracker, KPITracker

logger = logging.getLogger(__name__)


class AutomatedPerformanceTracker:
    """
    Automated background performance tracking
    
    Responsibilities:
    - Run continuous monitoring in background thread
    - Collect performance metrics at regular intervals
    - Update KPI tracker with current state
    - Generate periodic performance reports
    - Trigger performance-based events
    """
    
    def __init__(
        self,
        kpi_tracker: Optional[KPITracker] = None,
        update_interval: int = 60,  # seconds
        report_interval: int = 3600,  # 1 hour
        data_dir: str = "./data/performance"
    ):
        """
        Initialize Automated Performance Tracker
        
        Args:
            kpi_tracker: KPI tracker instance (creates new if None)
            update_interval: Seconds between metric updates (default: 60)
            report_interval: Seconds between report generation (default: 3600)
            data_dir: Directory for performance data
        """
        self.kpi_tracker = kpi_tracker or get_kpi_tracker()
        self.update_interval = update_interval
        self.report_interval = report_interval
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # State
        self.running = False
        self.paused = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
        # Callbacks for getting account state
        self.account_value_callback: Optional[Callable[[], float]] = None
        self.cash_balance_callback: Optional[Callable[[], float]] = None
        self.positions_callback: Optional[Callable[[], List[Dict]]] = None
        self.unrealized_pnl_callback: Optional[Callable[[], float]] = None
        self.realized_pnl_callback: Optional[Callable[[], float]] = None
        
        # Performance tracking
        self.last_update_time: Optional[datetime] = None
        self.last_report_time: Optional[datetime] = None
        self.update_count = 0
        self.report_count = 0
        
        logger.info(f"✅ Automated Performance Tracker initialized (update: {update_interval}s, report: {report_interval}s)")
    
    def set_account_callbacks(
        self,
        account_value_fn: Callable[[], float],
        cash_balance_fn: Callable[[], float],
        positions_fn: Callable[[], List[Dict]],
        unrealized_pnl_fn: Optional[Callable[[], float]] = None,
        realized_pnl_fn: Optional[Callable[[], float]] = None
    ):
        """
        Set callback functions for retrieving account state
        
        Args:
            account_value_fn: Function that returns total account value
            cash_balance_fn: Function that returns cash balance
            positions_fn: Function that returns list of positions
            unrealized_pnl_fn: Function that returns unrealized P&L
            realized_pnl_fn: Function that returns total realized P&L
        """
        self.account_value_callback = account_value_fn
        self.cash_balance_callback = cash_balance_fn
        self.positions_callback = positions_fn
        self.unrealized_pnl_callback = unrealized_pnl_fn
        self.realized_pnl_callback = realized_pnl_fn
        
        logger.info("✅ Account state callbacks configured")
    
    def start(self):
        """Start automated performance tracking"""
        with self._lock:
            if self.running:
                logger.warning("Performance tracker already running")
                return
            
            if not self._callbacks_configured():
                logger.error("❌ Cannot start: Account callbacks not configured")
                return
            
            self.running = True
            self.paused = False
            self._thread = threading.Thread(target=self._tracking_loop, daemon=True)
            self._thread.start()
            
            logger.info("🚀 Automated Performance Tracker started")
    
    def stop(self):
        """Stop automated performance tracking"""
        with self._lock:
            if not self.running:
                logger.warning("Performance tracker not running")
                return
            
            self.running = False
            
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=5.0)
            
            logger.info("⏹️ Automated Performance Tracker stopped")
    
    def pause(self):
        """Pause performance tracking (keeps thread alive but skips updates)"""
        self.paused = True
        logger.info("⏸️ Performance tracking paused")
    
    def resume(self):
        """Resume performance tracking after pause"""
        self.paused = False
        logger.info("▶️ Performance tracking resumed")
    
    def _callbacks_configured(self) -> bool:
        """Check if required callbacks are configured"""
        return (
            self.account_value_callback is not None and
            self.cash_balance_callback is not None and
            self.positions_callback is not None
        )
    
    def _tracking_loop(self):
        """Main tracking loop (runs in background thread)"""
        logger.info("Performance tracking loop started")
        
        while self.running:
            try:
                if not self.paused:
                    # Update metrics
                    self._update_metrics()
                    
                    # Generate report if needed
                    if self._should_generate_report():
                        self._generate_report()
                
                # Sleep until next update
                time.sleep(self.update_interval)
                
            except Exception as e:
                logger.error(f"Error in performance tracking loop: {e}", exc_info=True)
                time.sleep(self.update_interval)
        
        logger.info("Performance tracking loop stopped")
    
    def _update_metrics(self):
        """Update performance metrics"""
        try:
            # Get current account state from callbacks
            account_value = self.account_value_callback()
            cash_balance = self.cash_balance_callback()
            positions = self.positions_callback()
            
            unrealized_pnl = 0.0
            if self.unrealized_pnl_callback:
                unrealized_pnl = self.unrealized_pnl_callback()
            
            realized_pnl = 0.0
            if self.realized_pnl_callback:
                realized_pnl = self.realized_pnl_callback()
            
            # Update KPI tracker
            snapshot = self.kpi_tracker.update(
                account_value=account_value,
                cash_balance=cash_balance,
                positions=positions,
                unrealized_pnl=unrealized_pnl,
                realized_pnl_total=realized_pnl
            )
            
            self.last_update_time = datetime.now()
            self.update_count += 1
            
            # Log update (every 10th update to avoid spam)
            if self.update_count % 10 == 0:
                logger.info(
                    f"📊 Performance update #{self.update_count}: "
                    f"Value: ${account_value:,.2f}, "
                    f"Return: {snapshot.total_return_pct:.2f}%, "
                    f"Win Rate: {snapshot.win_rate_pct:.1f}%"
                )
            
        except Exception as e:
            logger.error(f"Error updating metrics: {e}", exc_info=True)
    
    def _should_generate_report(self) -> bool:
        """Check if it's time to generate a report"""
        if self.last_report_time is None:
            return True
        
        time_since_report = (datetime.now() - self.last_report_time).total_seconds()
        return time_since_report >= self.report_interval
    
    def _generate_report(self):
        """Generate performance report"""
        try:
            report_data = self.kpi_tracker.get_kpi_summary()
            
            if report_data.get('status') != 'active':
                logger.warning("No KPI data available for report")
                return
            
            # Save report to file
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_file = self.data_dir / f"performance_report_{timestamp}.json"
            
            with open(report_file, 'w') as f:
                json.dump(report_data, f, indent=2)
            
            self.last_report_time = datetime.now()
            self.report_count += 1
            
            logger.info(f"📄 Performance report #{self.report_count} generated: {report_file}")
            
        except Exception as e:
            logger.error(f"Error generating report: {e}", exc_info=True)
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get tracker status
        
        Returns:
            Dictionary with tracker status information
        """
        return {
            'running': self.running,
            'paused': self.paused,
            'update_interval': self.update_interval,
            'report_interval': self.report_interval,
            'update_count': self.update_count,
            'report_count': self.report_count,
            'last_update': self.last_update_time.isoformat() if self.last_update_time else None,
            'last_report': self.last_report_time.isoformat() if self.last_report_time else None,
            'callbacks_configured': self._callbacks_configured()
        }
    
    def force_update(self):
        """Force immediate metric update (outside normal schedule)"""
        if not self.running:
            logger.warning("Cannot force update: tracker not running")
            return
        
        logger.info("Forcing immediate metric update...")
        self._update_metrics()
    
    def force_report(self):
        """Force immediate report generation (outside normal schedule)"""
        if not self.running:
            logger.warning("Cannot force report: tracker not running")
            return
        
        logger.info("Forcing immediate report generation...")
        self._generate_report()


# Global singleton instance
_performance_tracker: Optional[AutomatedPerformanceTracker] = None


def get_performance_tracker(
    update_interval: int = 60,
    report_interval: int = 3600
) -> AutomatedPerformanceTracker:
    """
    Get or create global automated performance tracker
    
    Args:
        update_interval: Seconds between updates (only used on first creation)
        report_interval: Seconds between reports (only used on first creation)
        
    Returns:
        AutomatedPerformanceTracker instance
    """
    global _performance_tracker
    
    if _performance_tracker is None:
        _performance_tracker = AutomatedPerformanceTracker(
            update_interval=update_interval,
            report_interval=report_interval
        )
    
    return _performance_tracker


def reset_performance_tracker():
    """Reset global performance tracker (use with caution)"""
    global _performance_tracker
    
    if _performance_tracker and _performance_tracker.running:
        _performance_tracker.stop()
    
    _performance_tracker = None
    logger.warning("⚠️ Performance Tracker reset")


# Example usage
if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create tracker
    tracker = get_performance_tracker(update_interval=10, report_interval=60)
    
    # Set up mock callbacks
    def get_account_value():
        return 10500.0  # Example value
    
    def get_cash_balance():
        return 5000.0
    
    def get_positions():
        return [
            {'symbol': 'BTC-USD', 'value': 3000.0},
            {'symbol': 'ETH-USD', 'value': 2500.0}
        ]
    
    tracker.set_account_callbacks(
        account_value_fn=get_account_value,
        cash_balance_fn=get_cash_balance,
        positions_fn=get_positions
    )
    
    # Start tracking
    tracker.start()
    
    # Let it run for a bit
    try:
        logger.info("Tracker running... Press Ctrl+C to stop")
        while True:
            time.sleep(5)
            status = tracker.get_status()
            logger.info(f"Status: {status}")
    except KeyboardInterrupt:
        logger.info("Stopping tracker...")
        tracker.stop()
