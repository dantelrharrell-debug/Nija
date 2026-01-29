"""
Test suite for monitoring system

Tests alerts, metrics tracking, and health checks.
"""

import unittest
import sys
from pathlib import Path
import tempfile
import shutil

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from monitoring_system import (
    MonitoringSystem,
    AlertLevel,
    AlertType,
    PerformanceMetrics
)


class TestPerformanceMetrics(unittest.TestCase):
    """Test performance metrics calculations"""

    def test_win_rate_calculation(self):
        """Test win rate percentage calculation"""
        metrics = PerformanceMetrics()
        metrics.total_trades = 10
        metrics.winning_trades = 6

        self.assertEqual(metrics.win_rate, 60.0, "Win rate should be 60%")

    def test_win_rate_zero_trades(self):
        """Test win rate with no trades"""
        metrics = PerformanceMetrics()
        self.assertEqual(metrics.win_rate, 0.0, "Win rate should be 0% with no trades")

    def test_profit_factor(self):
        """Test profit factor calculation"""
        metrics = PerformanceMetrics()
        metrics.total_profit = 100.0
        metrics.total_loss = 50.0

        self.assertEqual(metrics.profit_factor, 2.0, "Profit factor should be 2.0")

    def test_profit_factor_no_losses(self):
        """Test profit factor with no losses"""
        metrics = PerformanceMetrics()
        metrics.total_profit = 100.0
        metrics.total_loss = 0.0

        self.assertEqual(metrics.profit_factor, float('inf'),
                        "Profit factor should be infinite with no losses")

    def test_net_profit(self):
        """Test net profit calculation"""
        metrics = PerformanceMetrics()
        metrics.total_profit = 100.0
        metrics.total_loss = 30.0
        metrics.total_fees = 10.0

        self.assertEqual(metrics.net_profit, 60.0,
                        "Net profit should be profit - loss - fees")

    def test_average_win(self):
        """Test average win calculation"""
        metrics = PerformanceMetrics()
        metrics.total_profit = 150.0
        metrics.winning_trades = 6

        self.assertEqual(metrics.average_win, 25.0,
                        "Average win should be 25.0")

    def test_average_loss(self):
        """Test average loss calculation"""
        metrics = PerformanceMetrics()
        metrics.total_loss = 120.0
        metrics.losing_trades = 4

        self.assertEqual(metrics.average_loss, 30.0,
                        "Average loss should be 30.0")


class TestMonitoringSystem(unittest.TestCase):
    """Test monitoring system functionality"""

    def setUp(self):
        """Create temporary directory for each test"""
        self.temp_dir = tempfile.mkdtemp()
        self.monitoring = MonitoringSystem(data_dir=self.temp_dir)

    def tearDown(self):
        """Clean up temporary directory"""
        shutil.rmtree(self.temp_dir)

    def test_initialization(self):
        """Test monitoring system initialization"""
        self.assertIsNotNone(self.monitoring)
        self.assertEqual(self.monitoring.metrics.total_trades, 0)
        self.assertEqual(len(self.monitoring.alerts), 0)

    def test_balance_update(self):
        """Test balance tracking"""
        self.monitoring.update_balance(100.0)
        self.assertEqual(self.monitoring.last_balance, 100.0)
        self.assertEqual(self.monitoring.start_balance, 100.0)
        self.assertEqual(self.monitoring.peak_balance, 100.0)

    def test_peak_balance_tracking(self):
        """Test peak balance is tracked correctly"""
        self.monitoring.update_balance(100.0)
        self.monitoring.update_balance(120.0)
        self.monitoring.update_balance(110.0)

        self.assertEqual(self.monitoring.peak_balance, 120.0,
                        "Peak should be 120.0")

    def test_low_balance_alert(self):
        """Test low balance alert is triggered"""
        self.monitoring.update_balance(40.0)  # Below threshold

        # Should have created a low balance alert
        low_balance_alerts = [a for a in self.monitoring.alerts
                             if a.alert_type == AlertType.BALANCE_LOW.value]

        self.assertGreater(len(low_balance_alerts), 0,
                          "Should create low balance alert")

    def test_balance_drop_alert(self):
        """Test balance drop alert"""
        self.monitoring.update_balance(100.0)
        self.monitoring.update_balance(70.0)  # 30% drop

        drop_alerts = [a for a in self.monitoring.alerts
                      if a.alert_type == AlertType.BALANCE_DROP.value]

        self.assertGreater(len(drop_alerts), 0,
                          "Should create balance drop alert")

    def test_record_winning_trade(self):
        """Test recording a winning trade"""
        self.monitoring.record_trade("BTC-USD", profit=2.0, fees=0.5, is_win=True)

        self.assertEqual(self.monitoring.metrics.total_trades, 1)
        self.assertEqual(self.monitoring.metrics.winning_trades, 1)
        self.assertEqual(self.monitoring.metrics.losing_trades, 0)
        self.assertEqual(self.monitoring.metrics.total_profit, 2.0)
        self.assertEqual(self.monitoring.metrics.total_fees, 0.5)
        self.assertEqual(self.monitoring.metrics.consecutive_wins, 1)
        self.assertEqual(self.monitoring.metrics.consecutive_losses, 0)

    def test_record_losing_trade(self):
        """Test recording a losing trade"""
        self.monitoring.record_trade("ETH-USD", profit=-1.0, fees=0.5, is_win=False)

        self.assertEqual(self.monitoring.metrics.total_trades, 1)
        self.assertEqual(self.monitoring.metrics.winning_trades, 0)
        self.assertEqual(self.monitoring.metrics.losing_trades, 1)
        self.assertEqual(self.monitoring.metrics.total_loss, 1.0)
        self.assertEqual(self.monitoring.metrics.consecutive_losses, 1)

    def test_consecutive_losses_alert(self):
        """Test consecutive losses trigger alert"""
        for i in range(5):
            self.monitoring.record_trade(f"SYM{i}", profit=-1.0, fees=0.5, is_win=False)

        loss_alerts = [a for a in self.monitoring.alerts
                      if a.alert_type == AlertType.CONSECUTIVE_LOSSES.value]

        self.assertGreater(len(loss_alerts), 0,
                          "Should create consecutive losses alert")

    def test_api_error_recording(self):
        """Test API error tracking"""
        self.monitoring.record_api_call()
        self.monitoring.record_error("API_ERROR", "Rate limit exceeded")

        self.assertEqual(self.monitoring.error_count, 1)
        self.assertEqual(self.monitoring.api_call_count, 1)

    def test_health_check(self):
        """Test health check returns status"""
        self.monitoring.update_balance(100.0)
        health = self.monitoring.check_health()

        self.assertIn('status', health)
        self.assertIn('balance', health)
        self.assertIn('performance', health)
        self.assertIn('errors', health)

    def test_persistence(self):
        """Test state is saved and loaded"""
        # Record some data
        self.monitoring.record_trade("BTC-USD", profit=2.0, fees=0.5, is_win=True)
        self.monitoring._save_state()

        # Create new instance with same directory
        new_monitoring = MonitoringSystem(data_dir=self.temp_dir)

        # Should load previous state
        self.assertEqual(new_monitoring.metrics.total_trades, 1,
                        "Should load previous trade count")


if __name__ == '__main__':
    unittest.main(verbosity=2)
