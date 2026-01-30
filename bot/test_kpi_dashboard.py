"""
Test suite for KPI Dashboard components

Tests KPI tracking, automated performance tracking, and risk alarms
"""

import unittest
import time
from datetime import datetime
from pathlib import Path
import shutil

# Import components to test
import sys
sys.path.insert(0, str(Path(__file__).parent))

from kpi_tracker import KPITracker, KPISnapshot
from automated_performance_tracker import AutomatedPerformanceTracker
from risk_alarm_system import RiskAlarmSystem, RiskThresholds, RiskAlarmType


class TestKPITracker(unittest.TestCase):
    """Test KPI Tracker functionality"""
    
    def setUp(self):
        """Set up test fixture"""
        self.test_dir = Path("./test_data_kpi")
        self.test_dir.mkdir(exist_ok=True)
        
        self.tracker = KPITracker(
            initial_capital=10000.0,
            data_dir=str(self.test_dir)
        )
    
    def tearDown(self):
        """Clean up test data"""
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
    
    def test_initialization(self):
        """Test tracker initialization"""
        self.assertEqual(self.tracker.initial_capital, 10000.0)
        self.assertEqual(self.tracker.current_capital, 10000.0)
        self.assertIsNotNone(self.tracker.kpi_history)
    
    def test_record_trade(self):
        """Test recording trades"""
        self.tracker.record_trade(
            symbol='BTC-USD',
            entry_price=50000,
            exit_price=51000,
            quantity=0.1,
            side='long',
            pnl=100.0,
            entry_time=datetime.now(),
            exit_time=datetime.now(),
            fees=1.0
        )
        
        self.assertEqual(len(self.tracker.trade_history), 1)
        trade = self.tracker.trade_history[0]
        self.assertEqual(trade['symbol'], 'BTC-USD')
        self.assertEqual(trade['pnl'], 100.0)
    
    def test_kpi_update(self):
        """Test KPI update"""
        snapshot = self.tracker.update(
            account_value=10500.0,
            cash_balance=8000.0,
            positions=[{'symbol': 'BTC-USD', 'value': 2500.0}],
            unrealized_pnl=500.0,
            realized_pnl_total=500.0
        )
        
        self.assertIsInstance(snapshot, KPISnapshot)
        self.assertEqual(snapshot.account_value, 10500.0)
        self.assertGreater(snapshot.total_return_pct, 0)
    
    def test_kpi_calculations(self):
        """Test KPI calculations with multiple trades"""
        # Record winning trade
        self.tracker.record_trade(
            symbol='BTC-USD',
            entry_price=50000,
            exit_price=51000,
            quantity=0.1,
            side='long',
            pnl=95.0,
            entry_time=datetime.now(),
            exit_time=datetime.now(),
            fees=5.0
        )
        
        # Record losing trade
        self.tracker.record_trade(
            symbol='ETH-USD',
            entry_price=3000,
            exit_price=2950,
            quantity=1.0,
            side='long',
            pnl=-53.0,
            entry_time=datetime.now(),
            exit_time=datetime.now(),
            fees=3.0
        )
        
        # Update KPIs
        snapshot = self.tracker.update(
            account_value=10042.0,
            cash_balance=10042.0,
            positions=[],
            unrealized_pnl=0.0,
            realized_pnl_total=42.0
        )
        
        # Verify calculations
        self.assertEqual(snapshot.total_trades, 2)
        self.assertEqual(snapshot.winning_trades, 1)
        self.assertEqual(snapshot.losing_trades, 1)
        self.assertEqual(snapshot.win_rate_pct, 50.0)
        self.assertGreater(snapshot.total_return_pct, 0)
    
    def test_state_persistence(self):
        """Test saving and loading state"""
        # Record some trades
        self.tracker.record_trade(
            symbol='BTC-USD',
            entry_price=50000,
            exit_price=51000,
            quantity=0.1,
            side='long',
            pnl=100.0,
            entry_time=datetime.now(),
            exit_time=datetime.now()
        )
        
        # Save state
        self.tracker._save_state()
        
        # Create new tracker (should load state)
        new_tracker = KPITracker(
            initial_capital=10000.0,
            data_dir=str(self.test_dir)
        )
        
        # Verify loaded state
        self.assertEqual(len(new_tracker.trade_history), 1)


class TestAutomatedPerformanceTracker(unittest.TestCase):
    """Test Automated Performance Tracker"""
    
    def setUp(self):
        """Set up test fixture"""
        self.test_dir = Path("./test_data_perf")
        self.test_dir.mkdir(exist_ok=True)
        
        self.kpi_tracker = KPITracker(
            initial_capital=10000.0,
            data_dir=str(self.test_dir / "kpi")
        )
        
        self.tracker = AutomatedPerformanceTracker(
            kpi_tracker=self.kpi_tracker,
            update_interval=1,  # 1 second for testing
            report_interval=5,
            data_dir=str(self.test_dir / "performance")
        )
        
        # Set up callbacks
        self.account_value = 10000.0
        self.tracker.set_account_callbacks(
            account_value_fn=lambda: self.account_value,
            cash_balance_fn=lambda: self.account_value,
            positions_fn=lambda: []
        )
    
    def tearDown(self):
        """Clean up"""
        if self.tracker.running:
            self.tracker.stop()
        
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
    
    def test_start_stop(self):
        """Test starting and stopping tracker"""
        self.assertFalse(self.tracker.running)
        
        self.tracker.start()
        self.assertTrue(self.tracker.running)
        
        time.sleep(0.1)  # Let it run briefly
        
        self.tracker.stop()
        self.assertFalse(self.tracker.running)
    
    def test_pause_resume(self):
        """Test pause and resume"""
        self.tracker.start()
        
        self.assertFalse(self.tracker.paused)
        
        self.tracker.pause()
        self.assertTrue(self.tracker.paused)
        
        self.tracker.resume()
        self.assertFalse(self.tracker.paused)
        
        self.tracker.stop()
    
    def test_automated_updates(self):
        """Test automated updates"""
        self.tracker.start()
        
        # Wait for a few updates
        time.sleep(3)
        
        status = self.tracker.get_status()
        self.assertGreater(status['update_count'], 0)
        
        self.tracker.stop()


class TestRiskAlarmSystem(unittest.TestCase):
    """Test Risk Alarm System"""
    
    def setUp(self):
        """Set up test fixture"""
        self.test_dir = Path("./test_data_alarms")
        self.test_dir.mkdir(exist_ok=True)
        
        self.kpi_tracker = KPITracker(
            initial_capital=10000.0,
            data_dir=str(self.test_dir / "kpi")
        )
        
        self.thresholds = RiskThresholds()
        self.alarm_system = RiskAlarmSystem(
            kpi_tracker=self.kpi_tracker,
            thresholds=self.thresholds,
            data_dir=str(self.test_dir / "alarms")
        )
        
        # Shorter cooldown for testing
        self.alarm_system.alarm_cooldown_minutes = 0.01
    
    def tearDown(self):
        """Clean up"""
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
    
    def test_drawdown_alarm(self):
        """Test drawdown alarm triggering"""
        # Create a snapshot with high drawdown
        snapshot = self.kpi_tracker.update(
            account_value=8000.0,  # 20% drawdown
            cash_balance=8000.0,
            positions=[],
            unrealized_pnl=0.0,
            realized_pnl_total=-2000.0
        )
        
        # Check risks
        self.alarm_system.check_all_risks(snapshot)
        
        # Should have drawdown alarm
        active_alarms = self.alarm_system.get_active_alarms()
        self.assertGreater(len(active_alarms), 0)
        
        # Check alarm type
        alarm_types = [a.alarm_type for a in active_alarms]
        self.assertIn(RiskAlarmType.MAX_DRAWDOWN_EXCEEDED.value, alarm_types)
    
    def test_win_rate_alarm(self):
        """Test win rate alarm"""
        # Record mostly losing trades
        for i in range(10):
            self.kpi_tracker.record_trade(
                symbol='BTC-USD',
                entry_price=50000,
                exit_price=49000 if i < 8 else 51000,  # 80% losses
                quantity=0.1,
                side='long',
                pnl=-100.0 if i < 8 else 100.0,
                entry_time=datetime.now(),
                exit_time=datetime.now()
            )
        
        # Update KPIs
        snapshot = self.kpi_tracker.update(
            account_value=9200.0,
            cash_balance=9200.0,
            positions=[]
        )
        
        # Check risks
        self.alarm_system.check_all_risks(snapshot)
        
        # Should have win rate alarm
        active_alarms = self.alarm_system.get_active_alarms()
        alarm_types = [a.alarm_type for a in active_alarms]
        self.assertIn(RiskAlarmType.LOW_WIN_RATE.value, alarm_types)
    
    def test_notification_callback(self):
        """Test notification callbacks"""
        notifications_received = []
        
        def callback(alarm):
            notifications_received.append(alarm)
        
        self.alarm_system.add_notification_callback(callback)
        
        # Trigger an alarm
        snapshot = self.kpi_tracker.update(
            account_value=8000.0,
            cash_balance=8000.0,
            positions=[]
        )
        
        self.alarm_system.check_all_risks(snapshot)
        
        # Should have received notification
        self.assertGreater(len(notifications_received), 0)


def run_tests():
    """Run all tests"""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestKPITracker))
    suite.addTests(loader.loadTestsFromTestCase(TestAutomatedPerformanceTracker))
    suite.addTests(loader.loadTestsFromTestCase(TestRiskAlarmSystem))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == '__main__':
    import logging
    logging.basicConfig(level=logging.WARNING)  # Suppress info logs during tests
    
    success = run_tests()
    exit(0 if success else 1)
