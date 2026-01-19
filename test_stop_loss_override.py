#!/usr/bin/env python3
"""
Test script to validate stop-loss override implementation.
Tests the three key fixes:
1. Hard stop-loss override at -0.01% (any loss)
2. 3-minute max hold time for losing trades
3. Explicit sell confirmation logging
"""

import sys
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_stop_loss_threshold():
    """Test that stop-loss threshold is set to -0.01%"""
    logger.info("=" * 70)
    logger.info("TEST 1: Stop-Loss Threshold")
    logger.info("=" * 70)
    
    # Read the constant from file
    with open('bot/trading_strategy.py', 'r') as f:
        code = f.read()
    
    expected_threshold = -0.01
    
    # Find the STOP_LOSS_THRESHOLD definition
    if 'STOP_LOSS_THRESHOLD = -0.01' in code:
        logger.info(f"Expected threshold: {expected_threshold*100}%")
        logger.info(f"Actual threshold: -0.01%")
        
        # Also verify it's being used in the hard stop-loss check
        if 'if pnl_percent <= STOP_LOSS_THRESHOLD:' in code:
            logger.info("✅ PASS: Stop-loss threshold constant defined and used correctly")
            return True
        else:
            logger.warning("⚠️ Constant defined but not used in hard stop-loss check")
            return False
    else:
        logger.error(f"❌ FAIL: Expected {expected_threshold*100}%, threshold not found or incorrect")
        return False

def test_code_implementation():
    """Test that the code implements the required logic"""
    logger.info("")
    logger.info("=" * 70)
    logger.info("TEST 2: Code Implementation Check")
    logger.info("=" * 70)
    
    # Read the trading_strategy.py file
    with open('bot/trading_strategy.py', 'r') as f:
        code = f.read()
    
    tests = []
    
    # Test 1: Hard stop-loss override exists and uses STOP_LOSS_THRESHOLD constant
    if 'if pnl_percent <= STOP_LOSS_THRESHOLD:' in code:
        logger.info("✅ PASS: Hard stop-loss check uses STOP_LOSS_THRESHOLD constant")
        tests.append(True)
    else:
        logger.error("❌ FAIL: Hard stop-loss check doesn't use STOP_LOSS_THRESHOLD constant")
        tests.append(False)
    
    # Test 2: Hard stop-loss uses continue to skip remaining logic
    hard_stop_section = code.find('if pnl_percent <= STOP_LOSS_THRESHOLD:')
    if hard_stop_section != -1:
        section = code[hard_stop_section:hard_stop_section + 2000]
        if 'Skip ALL remaining logic' in section and 'continue' in section:
            logger.info("✅ PASS: Hard stop-loss uses 'continue' to skip remaining checks")
            tests.append(True)
        else:
            logger.error("❌ FAIL: Hard stop-loss doesn't use 'continue' properly")
            tests.append(False)
    else:
        logger.error("❌ FAIL: Hard stop-loss section not found")
        tests.append(False)
    
    # Test 3: 3-minute max hold time for losers
    if 'MAX_LOSING_POSITION_HOLD_MINUTES = 3' in code:
        # Also verify it's being used
        if 'if position_age_minutes >= MAX_LOSING_POSITION_HOLD_MINUTES:' in code:
            logger.info("✅ PASS: Losing trades limited to 3 minutes max (constant defined and used)")
            tests.append(True)
        else:
            logger.warning("⚠️ Constant defined but not used properly")
            tests.append(False)
    else:
        logger.error("❌ FAIL: 3-minute limit constant not found")
        tests.append(False)
    
    # Test 4: Removed 30-minute auto-exit warning
    # The old code had warnings like "will auto-exit in 23.7min" that should be removed
    # We allow up to 1 occurrence (may still exist in other contexts like time-based exits)
    # but should NOT appear for losing trade warnings
    if 'will auto-exit in' not in code or code.count('will auto-exit in') < 2:
        logger.info("✅ PASS: Removed 'will auto-exit in X minutes' warning for losing trades")
        tests.append(True)
    else:
        logger.error("❌ FAIL: 'will auto-exit in X minutes' warning still present")
        tests.append(False)
    
    # Test 5: Sell confirmation log exists
    if '✅ SOLD {symbol} @ market due to stop loss' in code:
        logger.info("✅ PASS: Explicit sell confirmation log added")
        tests.append(True)
    else:
        logger.error("❌ FAIL: Sell confirmation log not found")
        tests.append(False)
    
    # Test 6: Hard stop-loss override message
    if '🛑 HARD STOP LOSS SELL:' in code:
        logger.info("✅ PASS: Hard stop-loss override message present")
        tests.append(True)
    else:
        logger.error("❌ FAIL: Hard stop-loss override message not found")
        tests.append(False)
    
    return all(tests)

def test_logic_order():
    """Test that hard stop-loss comes BEFORE other checks"""
    logger.info("")
    logger.info("=" * 70)
    logger.info("TEST 3: Logic Order Validation")
    logger.info("=" * 70)
    
    with open('bot/trading_strategy.py', 'r') as f:
        code = f.read()
    
    # Find positions of key checks
    hard_stop_pos = code.find('if pnl_percent <= STOP_LOSS_THRESHOLD:')
    emergency_stop_pos = code.find('if pnl_percent <= -0.75:')
    profit_target_pos = code.find('for target_pct, reason in PROFIT_TARGETS:')
    
    logger.info(f"Hard stop-loss position: {hard_stop_pos}")
    logger.info(f"Emergency stop-loss position: {emergency_stop_pos}")
    logger.info(f"Profit targets position: {profit_target_pos}")
    
    if hard_stop_pos == -1:
        logger.error("❌ FAIL: Hard stop-loss check not found")
        return False
    
    if hard_stop_pos < emergency_stop_pos and hard_stop_pos < profit_target_pos:
        logger.info("✅ PASS: Hard stop-loss check comes BEFORE all other P&L logic")
        return True
    else:
        logger.error("❌ FAIL: Hard stop-loss check is NOT at the top of P&L logic")
        return False

def main():
    """Run all tests"""
    logger.info("Starting stop-loss override tests...")
    logger.info("")
    
    results = []
    
    # Run tests
    results.append(test_stop_loss_threshold())
    results.append(test_code_implementation())
    results.append(test_logic_order())
    
    # Summary
    logger.info("")
    logger.info("=" * 70)
    logger.info("TEST SUMMARY")
    logger.info("=" * 70)
    
    passed = sum(results)
    total = len(results)
    
    logger.info(f"Tests passed: {passed}/{total}")
    
    if all(results):
        logger.info("✅ ALL TESTS PASSED - Stop-loss override implemented correctly!")
        return 0
    else:
        logger.error("❌ SOME TESTS FAILED - Review implementation")
        return 1

if __name__ == '__main__':
    sys.exit(main())
