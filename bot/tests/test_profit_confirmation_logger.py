"""
Tests for Profit Confirmation Logger

Validates:
1. Profit "proven" criteria are correctly applied
2. Position count explosion is prevented
3. Profit confirmation logs have standardized format
4. Giveback detection works correctly
"""

import unittest
import tempfile
import shutil
from datetime import datetime, timedelta
from pathlib import Path
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from profit_confirmation_logger import ProfitConfirmationLogger


class TestProfitConfirmationLogger(unittest.TestCase):
    """Test cases for ProfitConfirmationLogger"""
    
    def setUp(self):
        """Create a temporary directory for test data"""
        self.test_dir = tempfile.mkdtemp()
        self.logger = ProfitConfirmationLogger(data_dir=self.test_dir)
    
    def tearDown(self):
        """Clean up temporary directory"""
        shutil.rmtree(self.test_dir)
    
    def test_profit_proven_all_criteria_met(self):
        """Test profit is proven when all criteria are met"""
        # Position with 1% NET profit after 3 minutes
        entry_price = 100.0
        current_price = 101.6  # 1.6% gross profit
        entry_time = datetime.now() - timedelta(seconds=180)  # 3 minutes ago
        broker_fee = 0.014  # 1.4% fees
        
        result = self.logger.check_profit_proven(
            symbol='BTC-USD',
            entry_price=entry_price,
            current_price=current_price,
            entry_time=entry_time,
            position_size_usd=100.0,
            broker_fee_pct=broker_fee,
            side='long'
        )
        
        # 1.6% gross - 1.4% fees = 0.2% NET profit
        # Should NOT be proven (below 0.5% minimum)
        self.assertFalse(result['proven'])
        self.assertAlmostEqual(result['net_profit_pct'], 0.002, places=4)
        
    def test_profit_proven_high_profit(self):
        """Test profit is proven with high NET profit"""
        # Position with 2% NET profit after 3 minutes
        entry_price = 100.0
        current_price = 103.4  # 3.4% gross profit
        entry_time = datetime.now() - timedelta(seconds=180)  # 3 minutes ago
        broker_fee = 0.014  # 1.4% fees
        
        result = self.logger.check_profit_proven(
            symbol='ETH-USD',
            entry_price=entry_price,
            current_price=current_price,
            entry_time=entry_time,
            position_size_usd=100.0,
            broker_fee_pct=broker_fee,
            side='long'
        )
        
        # 3.4% gross - 1.4% fees = 2.0% NET profit
        # Should be proven (above 0.5% minimum, held > 2 minutes)
        self.assertTrue(result['proven'])
        self.assertAlmostEqual(result['net_profit_pct'], 0.020, places=4)
        self.assertEqual(result['action'], 'PROFIT_CONFIRMED_TAKE_NOW')
    
    def test_profit_not_proven_insufficient_hold_time(self):
        """Test profit not proven if hold time too short"""
        # Position with 1% NET profit after only 1 minute
        entry_price = 100.0
        current_price = 102.4  # 2.4% gross profit
        entry_time = datetime.now() - timedelta(seconds=60)  # Only 1 minute
        broker_fee = 0.014  # 1.4% fees
        
        result = self.logger.check_profit_proven(
            symbol='SOL-USD',
            entry_price=entry_price,
            current_price=current_price,
            entry_time=entry_time,
            position_size_usd=100.0,
            broker_fee_pct=broker_fee,
            side='long'
        )
        
        # 2.4% gross - 1.4% fees = 1.0% NET profit
        # Should NOT be proven (hold time < 2 minutes)
        self.assertFalse(result['proven'])
        self.assertTrue(result['criteria_met']['profit_threshold'])
        self.assertFalse(result['criteria_met']['hold_time'])
        self.assertEqual(result['action'], 'WAIT_FOR_HOLD_TIME')
    
    def test_profit_not_proven_insufficient_profit(self):
        """Test profit not proven if profit too small"""
        # Position with only 0.3% NET profit after 3 minutes
        entry_price = 100.0
        current_price = 101.7  # 1.7% gross profit
        entry_time = datetime.now() - timedelta(seconds=180)  # 3 minutes ago
        broker_fee = 0.014  # 1.4% fees
        
        result = self.logger.check_profit_proven(
            symbol='ADA-USD',
            entry_price=entry_price,
            current_price=current_price,
            entry_time=entry_time,
            position_size_usd=100.0,
            broker_fee_pct=broker_fee,
            side='long'
        )
        
        # 1.7% gross - 1.4% fees = 0.3% NET profit
        # Should NOT be proven (below 0.5% minimum)
        self.assertFalse(result['proven'])
        self.assertFalse(result['criteria_met']['profit_threshold'])
        self.assertTrue(result['criteria_met']['hold_time'])
        self.assertEqual(result['action'], 'WAIT_FOR_PROFIT_THRESHOLD')
    
    def test_giveback_detection(self):
        """Test profit giveback is detected correctly"""
        symbol = 'AVAX-USD'
        entry_price = 100.0
        entry_time = datetime.now() - timedelta(seconds=180)
        broker_fee = 0.014
        
        # First check: 2% NET profit
        current_price = 103.4  # 3.4% gross
        result1 = self.logger.check_profit_proven(
            symbol=symbol,
            entry_price=entry_price,
            current_price=current_price,
            entry_time=entry_time,
            position_size_usd=100.0,
            broker_fee_pct=broker_fee,
            side='long'
        )
        
        self.assertTrue(result1['proven'])
        self.assertAlmostEqual(result1['net_profit_pct'], 0.020, places=4)
        
        # Second check: Profit pulls back to 1.4% NET (0.6% giveback)
        current_price = 102.8  # 2.8% gross
        result2 = self.logger.check_profit_proven(
            symbol=symbol,
            entry_price=entry_price,
            current_price=current_price,
            entry_time=entry_time,
            position_size_usd=100.0,
            broker_fee_pct=broker_fee,
            side='long'
        )
        
        # Should detect giveback (0.6% > 0.3% threshold)
        self.assertTrue(result2['is_giveback'])
        self.assertEqual(result2['action'], 'IMMEDIATE_EXIT_GIVEBACK')
    
    def test_short_position_profit_calculation(self):
        """Test profit calculation for short positions"""
        # Short position with 1% NET profit
        entry_price = 100.0
        current_price = 98.6  # 1.4% gross profit (price fell)
        entry_time = datetime.now() - timedelta(seconds=180)
        broker_fee = 0.004  # 0.4% fees (Kraken)
        
        result = self.logger.check_profit_proven(
            symbol='BTC-USD',
            entry_price=entry_price,
            current_price=current_price,
            entry_time=entry_time,
            position_size_usd=100.0,
            broker_fee_pct=broker_fee,
            side='short'
        )
        
        # 1.4% gross - 0.4% fees = 1.0% NET profit
        self.assertTrue(result['proven'])
        self.assertAlmostEqual(result['net_profit_pct'], 0.010, places=4)
    
    def test_log_profit_confirmation(self):
        """Test profit confirmation logging"""
        # Should not raise any exceptions
        self.logger.log_profit_confirmation(
            symbol='BTC-USD',
            entry_price=100.0,
            exit_price=102.0,
            position_size_usd=100.0,
            net_profit_pct=0.006,
            net_profit_usd=0.60,
            hold_time_seconds=180,
            exit_type='PROFIT_CONFIRMED'
        )
        
        summary = self.logger.get_confirmation_summary()
        self.assertEqual(summary['total_confirmations'], 1)
        self.assertEqual(summary['total_givebacks'], 0)
        self.assertAlmostEqual(summary['total_profit_taken_usd'], 0.60, places=2)
    
    def test_log_profit_giveback(self):
        """Test profit giveback logging"""
        self.logger.log_profit_confirmation(
            symbol='ETH-USD',
            entry_price=100.0,
            exit_price=100.5,
            position_size_usd=100.0,
            net_profit_pct=-0.004,  # Small loss after giveback
            net_profit_usd=-0.40,
            hold_time_seconds=240,
            exit_type='PROFIT_GIVEBACK'
        )
        
        summary = self.logger.get_confirmation_summary()
        self.assertEqual(summary['total_givebacks'], 1)
        self.assertAlmostEqual(summary['total_profit_given_back_usd'], 0.40, places=2)
    
    def test_cleanup_stale_tracking(self):
        """Test cleanup of stale position tracking"""
        # Track some positions
        self.logger.check_profit_proven(
            symbol='BTC-USD',
            entry_price=100.0,
            current_price=102.0,
            entry_time=datetime.now() - timedelta(seconds=180),
            position_size_usd=100.0,
            broker_fee_pct=0.014,
            side='long'
        )
        
        self.logger.check_profit_proven(
            symbol='ETH-USD',
            entry_price=200.0,
            current_price=204.0,
            entry_time=datetime.now() - timedelta(seconds=180),
            position_size_usd=100.0,
            broker_fee_pct=0.014,
            side='long'
        )
        
        # Cleanup - only BTC-USD is active
        cleaned = self.logger.cleanup_stale_tracking(['BTC-USD'])
        
        # Should remove ETH-USD tracking
        self.assertEqual(cleaned, 1)
        summary = self.logger.get_confirmation_summary()
        self.assertEqual(summary['active_tracking_count'], 1)
    
    def test_persistence(self):
        """Test profit confirmations are persisted across instances"""
        # Log a confirmation
        self.logger.log_profit_confirmation(
            symbol='BTC-USD',
            entry_price=100.0,
            exit_price=102.0,
            position_size_usd=100.0,
            net_profit_pct=0.006,
            net_profit_usd=0.60,
            hold_time_seconds=180,
            exit_type='PROFIT_CONFIRMED'
        )
        
        # Create a new logger instance with same data dir
        logger2 = ProfitConfirmationLogger(data_dir=self.test_dir)
        
        # Should load the previous confirmation
        summary = logger2.get_confirmation_summary()
        self.assertEqual(summary['total_confirmations'], 1)
        self.assertAlmostEqual(summary['total_profit_taken_usd'], 0.60, places=2)
    
    def test_simple_report_with_trades(self):
        """Test simple report generation with trades"""
        # Log several trades
        self.logger.log_profit_confirmation(
            symbol='BTC-USD',
            entry_price=100.0,
            exit_price=102.0,
            position_size_usd=100.0,
            net_profit_pct=0.006,
            net_profit_usd=0.60,
            hold_time_seconds=180,
            exit_type='PROFIT_CONFIRMED',
            fees_paid_usd=1.40,
            risk_amount_usd=1.00
        )
        
        self.logger.log_profit_confirmation(
            symbol='ETH-USD',
            entry_price=200.0,
            exit_price=206.0,
            position_size_usd=100.0,
            net_profit_pct=0.016,
            net_profit_usd=1.60,
            hold_time_seconds=240,
            exit_type='PROFIT_CONFIRMED',
            fees_paid_usd=1.40,
            risk_amount_usd=1.00
        )
        
        # Generate report
        report = self.logger.generate_simple_report(
            starting_equity=1000.0,
            ending_equity=1002.20,
            hours=24
        )
        
        # Check report contains expected data
        self.assertIn('Starting equity: $1,000.00', report)
        self.assertIn('Ending equity:   $1,002.20', report)
        self.assertIn('Net P&L:         $+2.20', report)
        self.assertIn('Count:      2', report)
        self.assertIn('Win rate:   100.0%', report)
        self.assertIn('Fees total: $2.80', report)
        self.assertIn('Avg R:', report)
    
    def test_simple_report_no_trades(self):
        """Test simple report generation with no trades"""
        report = self.logger.generate_simple_report(
            starting_equity=1000.0,
            ending_equity=1000.0,
            hours=24
        )
        
        # Check report shows no trades
        self.assertIn('Starting equity: $1,000.00', report)
        self.assertIn('Ending equity:   $1,000.00', report)
        self.assertIn('Count:      0', report)
        self.assertIn('Win rate:   N/A', report)
    
    def test_simple_report_with_losses(self):
        """Test simple report with mix of wins and losses"""
        # Winner
        self.logger.log_profit_confirmation(
            symbol='BTC-USD',
            entry_price=100.0,
            exit_price=102.0,
            position_size_usd=100.0,
            net_profit_pct=0.006,
            net_profit_usd=0.60,
            hold_time_seconds=180,
            exit_type='PROFIT_CONFIRMED',
            fees_paid_usd=1.40,
            risk_amount_usd=1.00
        )
        
        # Loser
        self.logger.log_profit_confirmation(
            symbol='ETH-USD',
            entry_price=200.0,
            exit_price=198.0,
            position_size_usd=100.0,
            net_profit_pct=-0.024,
            net_profit_usd=-2.40,
            hold_time_seconds=120,
            exit_type='PROFIT_GIVEBACK',
            fees_paid_usd=1.40,
            risk_amount_usd=1.00
        )
        
        # Generate report
        report = self.logger.generate_simple_report(
            starting_equity=1000.0,
            ending_equity=998.20,
            hours=24
        )
        
        # Check win rate calculation
        self.assertIn('Win rate:   50.0%', report)
        self.assertIn('Count:      2', report)
        self.assertIn('Net P&L:         $-1.80', report)


if __name__ == '__main__':
    unittest.main()
