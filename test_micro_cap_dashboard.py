"""
Test NIJA MICRO_CAP Production Readiness Dashboard

Tests the dashboard API and integration with bot components.

Author: NIJA Trading Systems
Version: 1.0
Date: February 17, 2026
"""

import unittest
from unittest.mock import Mock, patch
import json


class TestMicroCapDashboardAPI(unittest.TestCase):
    """Test cases for MICRO_CAP Dashboard API"""
    
    def setUp(self):
        """Set up test fixtures"""
        from micro_cap_dashboard_api import MicroCapDashboardAPI
        self.api = MicroCapDashboardAPI()
    
    def test_get_balances(self):
        """Test balance retrieval"""
        balances = self.api.get_balances()
        
        # Should return a dictionary with required keys
        self.assertIn('cash', balances)
        self.assertIn('equity', balances)
        self.assertIn('available', balances)
        self.assertIn('reserved', balances)
        
        # All values should be numeric
        self.assertIsInstance(balances['cash'], (int, float))
        self.assertIsInstance(balances['equity'], (int, float))
        self.assertIsInstance(balances['available'], (int, float))
        self.assertIsInstance(balances['reserved'], (int, float))
        
        # Available should not be negative
        self.assertGreaterEqual(balances['available'], 0.0)
        
        print(f"✅ Balances test passed: {balances}")
    
    def test_get_held_capital(self):
        """Test held capital retrieval"""
        held_capital = self.api.get_held_capital()
        
        # Should return a dictionary with required keys
        self.assertIn('value', held_capital)
        self.assertIn('count', held_capital)
        self.assertIn('unrealized_pnl', held_capital)
        self.assertIn('exposure_pct', held_capital)
        
        # Count should be non-negative integer
        self.assertGreaterEqual(held_capital['count'], 0)
        
        # Exposure should be percentage
        self.assertGreaterEqual(held_capital['exposure_pct'], 0.0)
        self.assertLessEqual(held_capital['exposure_pct'], 100.0)
        
        print(f"✅ Held capital test passed: {held_capital}")
    
    def test_get_expectancy(self):
        """Test expectancy metrics retrieval"""
        expectancy = self.api.get_expectancy()
        
        # Should return a dictionary with required keys
        self.assertIn('win_rate', expectancy)
        self.assertIn('profit_factor', expectancy)
        self.assertIn('avg_win', expectancy)
        self.assertIn('avg_loss', expectancy)
        
        # Win rate should be 0-100
        self.assertGreaterEqual(expectancy['win_rate'], 0.0)
        self.assertLessEqual(expectancy['win_rate'], 100.0)
        
        # Profit factor should be non-negative
        self.assertGreaterEqual(expectancy['profit_factor'], 0.0)
        
        print(f"✅ Expectancy test passed: {expectancy}")
    
    def test_get_drawdown(self):
        """Test drawdown metrics retrieval"""
        drawdown = self.api.get_drawdown()
        
        # Should return a dictionary with required keys
        self.assertIn('current', drawdown)
        self.assertIn('max', drawdown)
        self.assertIn('peak_balance', drawdown)
        
        # Drawdowns should be negative or zero
        self.assertLessEqual(drawdown['current'], 0.0)
        self.assertLessEqual(drawdown['max'], 0.0)
        
        # Peak balance should be positive
        self.assertGreater(drawdown['peak_balance'], 0.0)
        
        print(f"✅ Drawdown test passed: {drawdown}")
    
    def test_get_open_orders(self):
        """Test open orders retrieval"""
        orders = self.api.get_open_orders()
        
        # Should return a list
        self.assertIsInstance(orders, list)
        
        # Each order should have required fields
        for order in orders:
            self.assertIn('symbol', order)
            self.assertIn('side', order)
            self.assertIn('size', order)
            self.assertIn('entry_price', order)
            self.assertIn('current_price', order)
            self.assertIn('pnl', order)
            self.assertIn('pnl_pct', order)
        
        print(f"✅ Open orders test passed: {len(orders)} orders")
    
    def test_get_trades_info(self):
        """Test trades info retrieval"""
        trades = self.api.get_trades_info()
        
        # Should return a dictionary with required keys
        self.assertIn('total_trades', trades)
        self.assertIn('winning_trades', trades)
        self.assertIn('losing_trades', trades)
        
        # All should be non-negative integers
        self.assertGreaterEqual(trades['total_trades'], 0)
        self.assertGreaterEqual(trades['winning_trades'], 0)
        self.assertGreaterEqual(trades['losing_trades'], 0)
        
        # Winning + losing should not exceed total
        self.assertLessEqual(
            trades['winning_trades'] + trades['losing_trades'],
            trades['total_trades']
        )
        
        print(f"✅ Trades info test passed: {trades}")
    
    def test_get_compliance_alerts(self):
        """Test compliance alerts generation"""
        alerts = self.api.get_compliance_alerts()
        
        # Should return a list
        self.assertIsInstance(alerts, list)
        
        # Each alert should have severity and message
        for alert in alerts:
            self.assertIn('severity', alert)
            self.assertIn('message', alert)
            self.assertIn(alert['severity'], ['success', 'warning', 'error'])
        
        print(f"✅ Compliance alerts test passed: {len(alerts)} alerts")
    
    def test_get_dashboard_data(self):
        """Test complete dashboard data retrieval"""
        data = self.api.get_dashboard_data()
        
        # Should return a dictionary with all sections
        self.assertIn('timestamp', data)
        self.assertIn('balances', data)
        self.assertIn('held_capital', data)
        self.assertIn('open_orders', data)
        self.assertIn('expectancy', data)
        self.assertIn('drawdown', data)
        self.assertIn('trades', data)
        self.assertIn('compliance_alerts', data)
        
        print(f"✅ Complete dashboard data test passed")


class TestDashboardFlaskApp(unittest.TestCase):
    """Test cases for Flask application endpoints"""
    
    def setUp(self):
        """Set up test Flask client"""
        from micro_cap_dashboard_api import create_app
        self.app = create_app()
        self.client = self.app.test_client()
    
    def test_health_endpoint(self):
        """Test health check endpoint"""
        response = self.client.get('/health')
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.data)
        self.assertIn('status', data)
        self.assertEqual(data['status'], 'healthy')
        
        print(f"✅ Health endpoint test passed")
    
    def test_dashboard_data_endpoint(self):
        """Test main dashboard data endpoint"""
        response = self.client.get('/api/v1/dashboard/micro-cap')
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.data)
        self.assertIn('balances', data)
        self.assertIn('held_capital', data)
        self.assertIn('expectancy', data)
        
        print(f"✅ Dashboard data endpoint test passed")
    
    def test_balances_endpoint(self):
        """Test balances-only endpoint"""
        response = self.client.get('/api/v1/dashboard/micro-cap/balances')
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.data)
        self.assertIn('cash', data)
        self.assertIn('equity', data)
        
        print(f"✅ Balances endpoint test passed")
    
    def test_expectancy_endpoint(self):
        """Test expectancy-only endpoint"""
        response = self.client.get('/api/v1/dashboard/micro-cap/expectancy')
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.data)
        self.assertIn('win_rate', data)
        self.assertIn('profit_factor', data)
        
        print(f"✅ Expectancy endpoint test passed")
    
    def test_drawdown_endpoint(self):
        """Test drawdown-only endpoint"""
        response = self.client.get('/api/v1/dashboard/micro-cap/drawdown')
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.data)
        self.assertIn('current', data)
        self.assertIn('max', data)
        
        print(f"✅ Drawdown endpoint test passed")
    
    def test_compliance_endpoint(self):
        """Test compliance alerts endpoint"""
        response = self.client.get('/api/v1/dashboard/micro-cap/compliance')
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.data)
        self.assertIsInstance(data, list)
        
        print(f"✅ Compliance endpoint test passed")


def run_tests():
    """Run all tests"""
    print("\n" + "="*70)
    print("🧪 NIJA MICRO_CAP Dashboard Tests")
    print("="*70 + "\n")
    
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add test cases
    suite.addTests(loader.loadTestsFromTestCase(TestMicroCapDashboardAPI))
    suite.addTests(loader.loadTestsFromTestCase(TestDashboardFlaskApp))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    print("\n" + "="*70)
    if result.wasSuccessful():
        print("✅ All tests passed!")
    else:
        print("❌ Some tests failed")
    print("="*70 + "\n")
    
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    exit(0 if success else 1)
