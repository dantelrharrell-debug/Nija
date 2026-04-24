"""
NIJA Automated Performance Tracking Service

Automated service that continuously tracks trading performance,
calculates KPIs, monitors risk conditions, and triggers alarms.

Features:
- Continuous performance monitoring
- Automated KPI calculations
- Risk alarm monitoring
- Scheduled reporting
- Historical data persistence
- Integration with KPI tracker and risk alarms

Author: NIJA Trading Systems
Version: 1.0
Date: January 30, 2026
"""

import time
import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Callable
from pathlib import Path
import json

try:
    from kpi_tracker import get_kpi_tracker, KPITracker
    from risk_alarm_system import get_risk_alarm_system, RiskAlarmSystem
except ImportError:
    from bot.kpi_tracker import get_kpi_tracker, KPITracker
    from bot.risk_alarm_system import get_risk_alarm_system, RiskAlarmSystem

logger = logging.getLogger(__name__)


class PerformanceTrackingService:
    """
    Automated performance tracking service.
    
    Runs in background and:
    - Collects performance metrics
    - Calculates KPIs on schedule
    - Monitors risk conditions
    - Triggers alarms when needed
    - Generates periodic reports
    """
    
    def __init__(self, 
                 initial_capital: float = 1000.0,
                 update_interval_seconds: int = 300,  # 5 minutes
                 kpi_calculation_interval_seconds: int = 3600,  # 1 hour
                 alarm_check_interval_seconds: int = 60):  # 1 minute
        """
        Initialize performance tracking service.
        
        Args:
            initial_capital: Starting capital
            update_interval_seconds: How often to collect metrics
            kpi_calculation_interval_seconds: How often to calculate full KPIs
            alarm_check_interval_seconds: How often to check alarms
        """
        self.initial_capital = initial_capital
        self.update_interval = update_interval_seconds
        self.kpi_interval = kpi_calculation_interval_seconds
        self.alarm_interval = alarm_check_interval_seconds
        
        # Initialize components
        self.kpi_tracker = get_kpi_tracker(initial_capital=initial_capital)
        self.alarm_system = get_risk_alarm_system()
        
        # Service state
        self.running = False
        self.thread: Optional[threading.Thread] = None
        
        # Callbacks for data collection
        self.balance_provider: Optional[Callable] = None
        self.equity_provider: Optional[Callable] = None
        
        # Tracking
        self.last_update = datetime.now()
        self.last_kpi_calculation = datetime.now()
        self.last_alarm_check = datetime.now()
        
        # Statistics
        self.updates_count = 0
        self.kpi_calculations_count = 0
        self.alarm_checks_count = 0
        
        logger.info("✅ Performance Tracking Service initialized")
    
    def set_balance_provider(self, provider: Callable[[], float]):
        """
        Set callback to get current balance.
        
        Args:
            provider: Function that returns current balance
        """
        self.balance_provider = provider
    
    def set_equity_provider(self, provider: Callable[[], float]):
        """
        Set callback to get current equity.
        
        Args:
            provider: Function that returns current equity
        """
        self.equity_provider = provider
    
    def record_trade(self, symbol: str, strategy: str, profit: float, fees: float,
                    is_win: bool, entry_price: float, exit_price: float, position_size: float):
        """
        Record a trade (pass-through to KPI tracker).
        
        Args:
            symbol: Trading symbol
            strategy: Strategy name
            profit: Profit/loss amount
            fees: Trading fees
            is_win: Whether trade was profitable
            entry_price: Entry price
            exit_price: Exit price
            position_size: Position size
        """
        self.kpi_tracker.record_trade(
            symbol, strategy, profit, fees, is_win, 
            entry_price, exit_price, position_size
        )
    
    def start(self):
        """Start the performance tracking service"""
        if self.running:
            logger.warning("Service already running")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        logger.info("🚀 Performance Tracking Service started")
    
    def stop(self):
        """Stop the performance tracking service"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5.0)
        logger.info("⏹️ Performance Tracking Service stopped")
    
    def _run_loop(self):
        """Main service loop"""
        logger.info("📊 Performance tracking loop started")
        
        while self.running:
            try:
                now = datetime.now()
                
                # Update metrics
                if (now - self.last_update).total_seconds() >= self.update_interval:
                    self._update_metrics()
                    self.last_update = now
                
                # Calculate KPIs
                if (now - self.last_kpi_calculation).total_seconds() >= self.kpi_interval:
                    self._calculate_kpis()
                    self.last_kpi_calculation = now
                
                # Check alarms
                if (now - self.last_alarm_check).total_seconds() >= self.alarm_interval:
                    self._check_alarms()
                    self.last_alarm_check = now
                
                # Sleep to avoid busy waiting
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"Error in performance tracking loop: {e}", exc_info=True)
                time.sleep(10)  # Wait before retrying
    
    def _update_metrics(self):
        """Update performance metrics"""
        try:
            # Get current balance and equity
            balance = self.balance_provider() if self.balance_provider else 0.0
            equity = self.equity_provider() if self.equity_provider else 0.0
            
            # Update KPI tracker
            self.kpi_tracker.update_balance(balance, equity)
            
            self.updates_count += 1
            logger.debug(f"📊 Metrics updated: Balance=${balance:.2f}, Equity=${equity:.2f}")
            
        except Exception as e:
            logger.error(f"Error updating metrics: {e}")
    
    def _calculate_kpis(self):
        """Calculate full KPIs"""
        try:
            # Get current balance and equity
            balance = self.balance_provider() if self.balance_provider else 0.0
            equity = self.equity_provider() if self.equity_provider else 0.0
            
            # Calculate KPIs
            kpis = self.kpi_tracker.calculate_kpis(balance, equity)
            
            self.kpi_calculations_count += 1
            logger.info(f"📈 KPIs calculated: Win Rate={kpis.win_rate:.1f}%, "
                       f"Profit Factor={kpis.profit_factor:.2f}, "
                       f"ROI={kpis.roi_percentage:.2f}%")
            
        except Exception as e:
            logger.error(f"Error calculating KPIs: {e}")
    
    def _check_alarms(self):
        """Check risk alarms"""
        try:
            # Get current KPIs
            kpi_summary = self.kpi_tracker.get_kpi_summary()
            
            if 'error' not in kpi_summary:
                # Check balance alarms
                self.alarm_system.check_balance_alarms(
                    kpi_summary['account_balance'],
                    self.kpi_tracker.peak_balance
                )
                
                # Check drawdown alarms
                self.alarm_system.check_drawdown_alarms(
                    kpi_summary['current_drawdown'],
                    kpi_summary['max_drawdown']
                )
                
                # Check performance alarms
                self.alarm_system.check_performance_alarms(
                    kpi_summary['win_rate'],
                    kpi_summary['profit_factor']
                )
            
            self.alarm_checks_count += 1
            
            # Log active alarms
            active_alarms = self.alarm_system.get_active_alarms()
            if active_alarms:
                logger.warning(f"⚠️ {len(active_alarms)} active alarms")
            
        except Exception as e:
            logger.error(f"Error checking alarms: {e}")
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get service status.
        
        Returns:
            Dictionary with service status
        """
        return {
            'running': self.running,
            'uptime_seconds': (datetime.now() - self.last_update).total_seconds(),
            'updates_count': self.updates_count,
            'kpi_calculations_count': self.kpi_calculations_count,
            'alarm_checks_count': self.alarm_checks_count,
            'last_update': self.last_update.isoformat(),
            'last_kpi_calculation': self.last_kpi_calculation.isoformat(),
            'last_alarm_check': self.last_alarm_check.isoformat(),
            'intervals': {
                'update': self.update_interval,
                'kpi_calculation': self.kpi_interval,
                'alarm_check': self.alarm_interval
            }
        }
    
    def get_current_summary(self) -> Dict[str, Any]:
        """
        Get current performance summary.
        
        Returns:
            Dictionary with KPIs, alarms, and service status
        """
        kpi_summary = self.kpi_tracker.get_kpi_summary()
        alarm_summary = self.alarm_system.get_alarm_summary()
        service_status = self.get_status()
        
        return {
            'timestamp': datetime.now().isoformat(),
            'service': service_status,
            'kpis': kpi_summary,
            'alarms': alarm_summary
        }
    
    def export_report(self, output_dir: str = "/tmp/nija_reports") -> str:
        """
        Export comprehensive performance report.
        
        Args:
            output_dir: Directory to save report
            
        Returns:
            Path to exported report
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"performance_report_{timestamp}.json"
        filepath = output_path / filename
        
        # Generate comprehensive report
        report = {
            'report_date': datetime.now().isoformat(),
            'service_status': self.get_status(),
            'kpis': self.kpi_tracker.get_kpi_summary(),
            'kpi_trends': self.kpi_tracker.get_kpi_trends(days=30),
            'alarm_summary': self.alarm_system.get_alarm_summary(),
            'active_alarms': [
                {
                    'severity': a.severity,
                    'category': a.category,
                    'name': a.name,
                    'message': a.message,
                    'timestamp': a.timestamp
                }
                for a in self.alarm_system.get_active_alarms()
            ],
            'trade_count': len(self.kpi_tracker.trade_history),
            'strategy_performance': dict(self.kpi_tracker.strategy_performance)
        }
        
        with open(filepath, 'w') as f:
            json.dump(report, f, indent=2)
        
        logger.info(f"📄 Performance report exported to {filepath}")
        return str(filepath)


# Global service instance
_tracking_service: Optional[PerformanceTrackingService] = None


def get_tracking_service(initial_capital: float = 1000.0, 
                         reset: bool = False) -> PerformanceTrackingService:
    """
    Get or create the global performance tracking service instance.
    
    Args:
        initial_capital: Initial capital (only used on first creation)
        reset: Force reset and create new instance
        
    Returns:
        PerformanceTrackingService instance
    """
    global _tracking_service
    
    if _tracking_service is None or reset:
        _tracking_service = PerformanceTrackingService(initial_capital=initial_capital)
    
    return _tracking_service


if __name__ == "__main__":
    # Test the performance tracking service
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("Testing Performance Tracking Service...")
    
    # Create service
    service = get_tracking_service(initial_capital=1000.0)
    
    # Set up simple providers for testing
    test_balance = 1000.0
    
    def get_balance():
        return test_balance
    
    def get_equity():
        return test_balance
    
    service.set_balance_provider(get_balance)
    service.set_equity_provider(get_equity)
    
    # Record some test trades
    service.record_trade("BTC-USD", "APEX_V71", 50.0, 1.0, True, 45000, 46000, 0.1)
    test_balance += 49.0
    
    service.record_trade("ETH-USD", "DUAL_RSI", -25.0, 1.0, False, 3000, 2950, 1.0)
    test_balance -= 26.0
    
    service.record_trade("SOL-USD", "APEX_V71", 75.0, 1.0, True, 120, 125, 10.0)
    test_balance += 74.0
    
    # Start service
    service.start()
    
    print("\n✅ Service started - running for 30 seconds...")
    print("Watch the logs for automated updates...\n")
    
    # Run for 30 seconds
    time.sleep(30)
    
    # Get status
    print("\n--- Service Status ---")
    status = service.get_status()
    print(json.dumps(status, indent=2))
    
    # Get summary
    print("\n--- Performance Summary ---")
    summary = service.get_current_summary()
    print(f"Total Trades: {summary['kpis']['total_trades']}")
    print(f"Win Rate: {summary['kpis']['win_rate']:.1f}%")
    print(f"ROI: {summary['kpis']['roi_percentage']:.2f}%")
    print(f"Active Alarms: {summary['alarms']['total_active']}")
    
    # Export report
    print("\n--- Exporting Report ---")
    report_path = service.export_report()
    print(f"Report saved to: {report_path}")
    
    # Stop service
    service.stop()
    
    print("\n✅ Performance tracking service test complete!")
