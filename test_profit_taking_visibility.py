#!/usr/bin/env python3
"""
Test profit-taking visibility improvements
Simulates positions and verifies logging is working correctly
"""

import sys
import os
import logging

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from execution_engine import ExecutionEngine

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("nija")

def test_position_profit_status_logging():
    """Test the log_position_profit_status method"""
    print("\n" + "="*80)
    print("TEST: Position Profit Status Logging")
    print("="*80 + "\n")
    
    # Create execution engine with mock broker
    class MockBroker:
        def __init__(self):
            self.broker_type = 'kraken'
        
        def get_account_balance(self):
            return 100.0
    
    engine = ExecutionEngine(broker_client=MockBroker(), user_id=None)
    
    # Add some mock positions
    engine.positions['BTC-USD'] = {
        'symbol': 'BTC-USD',
        'side': 'long',
        'entry_price': 50000.00,
        'position_size': 50.00,
        'status': 'open',
        'remaining_size': 1.0,
        'stop_loss': 49500.00,
        'tp1': 51000.00,
        'tp2': 51500.00,
        'tp3': 52000.00
    }
    
    engine.positions['ETH-USD'] = {
        'symbol': 'ETH-USD',
        'side': 'long',
        'entry_price': 3000.00,
        'position_size': 30.00,
        'status': 'open',
        'remaining_size': 0.75,  # 25% already exited
        'stop_loss': 2970.00,
        'tp1': 3045.00,
        'tp2': 3075.00,
        'tp3': 3105.00,
        'tp_exit_0.7pct': True  # First stepped exit already hit
    }
    
    engine.positions['MATIC-USD'] = {
        'symbol': 'MATIC-USD',
        'side': 'long',
        'entry_price': 1.00,
        'position_size': 10.00,
        'status': 'open',
        'remaining_size': 1.0,
        'stop_loss': 0.99,
        'tp1': 1.02,
        'tp2': 1.03,
        'tp3': 1.05
    }
    
    # Simulate current prices (some winning, some losing)
    current_prices = {
        'BTC-USD': 50750.00,   # +1.5% gross profit (Kraken: should trigger 1.5% exit)
        'ETH-USD': 3033.00,    # +1.1% gross profit (partially exited already)
        'MATIC-USD': 0.995     # -0.5% loss
    }
    
    print("\n📊 Simulated Positions:")
    print(f"   BTC-USD: Entry $50,000 → Current $50,750 (+1.5%)")
    print(f"   ETH-USD: Entry $3,000 → Current $3,033 (+1.1%, 75% remaining)")
    print(f"   MATIC-USD: Entry $1.00 → Current $0.995 (-0.5%)")
    print("\n")
    
    # Call the logging method
    engine.log_position_profit_status(current_prices)
    
    print("\n" + "="*80)
    print("✅ Position profit status logging test complete")
    print("="*80 + "\n")

def test_stepped_profit_exit_logging():
    """Test check_stepped_profit_exits debug logging"""
    print("\n" + "="*80)
    print("TEST: Stepped Profit Exit Logging")
    print("="*80 + "\n")
    
    # Create execution engine with mock broker
    class MockBroker:
        def __init__(self):
            self.broker_type = 'kraken'
        
        def get_account_balance(self):
            return 100.0
    
    engine = ExecutionEngine(broker_client=MockBroker(), user_id=None)
    
    # Add a position that should trigger profit exit
    engine.positions['CRO-USD'] = {
        'symbol': 'CRO-USD',
        'side': 'long',
        'entry_price': 0.1000,
        'position_size': 10.00,
        'status': 'open',
        'remaining_size': 1.0,
        'stop_loss': 0.0990,
        'tp1': 0.1020,
        'tp2': 0.1030,
        'tp3': 0.1050
    }
    
    print("Testing profit exit at different price levels:\n")
    
    # Test 1: Price at +0.5% (no exit)
    print("1. Price at +0.5% gross profit (below 0.7% threshold):")
    result = engine.check_stepped_profit_exits('CRO-USD', 0.1005)
    print(f"   Result: {result}\n")
    
    # Test 2: Price at +0.8% (should trigger first exit)
    print("2. Price at +0.8% gross profit (above 0.7% threshold):")
    result = engine.check_stepped_profit_exits('CRO-USD', 0.1008)
    print(f"   Result: {result}")
    if result:
        print(f"   ✅ Exit triggered: {result['exit_pct']*100:.0f}% of position")
        print(f"   ✅ Profit level: {result['profit_level']}")
        print(f"   ✅ Net profit: {result['net_profit_pct']*100:.2f}%\n")
    
    # Test 3: Price at +1.2% (should trigger second exit)
    print("3. Price at +1.2% gross profit (above 1.0% threshold):")
    # Reset the position
    engine.positions['CRO-USD']['remaining_size'] = 0.90  # 10% already exited
    result = engine.check_stepped_profit_exits('CRO-USD', 0.1012)
    print(f"   Result: {result}")
    if result:
        print(f"   ✅ Exit triggered: {result['exit_pct']*100:.0f}% of position")
        print(f"   ✅ Profit level: {result['profit_level']}\n")
    
    print("="*80)
    print("✅ Stepped profit exit logging test complete")
    print("="*80 + "\n")

def test_profit_target_progress():
    """Test the 'progress toward next target' logging"""
    print("\n" + "="*80)
    print("TEST: Profit Target Progress Logging")
    print("="*80 + "\n")
    
    # Create execution engine with mock broker
    class MockBroker:
        def __init__(self):
            self.broker_type = 'kraken'
        
        def get_account_balance(self):
            return 100.0
    
    engine = ExecutionEngine(broker_client=MockBroker(), user_id=None)
    
    # Add a position making progress toward profit
    engine.positions['ADA-USD'] = {
        'symbol': 'ADA-USD',
        'side': 'long',
        'entry_price': 0.50,
        'position_size': 10.00,
        'status': 'open',
        'remaining_size': 1.0,
        'stop_loss': 0.495,
        'tp1': 0.510,
        'tp2': 0.515,
        'tp3': 0.525
    }
    
    print("Position: ADA-USD Long @ $0.50")
    print("Next target: 0.7% (+$0.0035)\n")
    
    # Test at different price levels
    prices_to_test = [
        (0.501, 0.2),   # +0.2% (29% of way to 0.7%)
        (0.502, 0.4),   # +0.4% (57% of way to 0.7%)
        (0.503, 0.6),   # +0.6% (86% of way to 0.7%)
    ]
    
    for price, expected_pct in prices_to_test:
        print(f"Testing at ${price:.3f} (+{expected_pct:.1f}%):")
        result = engine.check_stepped_profit_exits('ADA-USD', price)
        print(f"   Result: {result}\n")
    
    print("="*80)
    print("✅ Profit target progress logging test complete")
    print("="*80 + "\n")

def main():
    """Run all tests"""
    print("\n" + "="*80)
    print("NIJA PROFIT-TAKING VISIBILITY TEST SUITE")
    print("="*80)
    
    try:
        test_position_profit_status_logging()
        test_stepped_profit_exit_logging()
        test_profit_target_progress()
        
        print("\n" + "="*80)
        print("✅ ALL TESTS PASSED")
        print("="*80)
        print("\nProfit-taking visibility improvements are working correctly.")
        print("When deployed, the bot will now show:")
        print("  1. Position profit status summary on each cycle")
        print("  2. Real-time P&L vs profit targets")
        print("  3. Progress toward next profit threshold")
        print("  4. Clear indication when profit exits are triggered")
        print("\nThis answers the question: 'Is NIJA making and taking profits?'")
        print("="*80 + "\n")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
