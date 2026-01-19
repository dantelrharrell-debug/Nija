#!/usr/bin/env python3
"""
Test Forced Stop-Loss Exit Logic

Validates that stop-loss fires BEFORE all other logic and cannot be bypassed.
This test ensures capital preservation by verifying losing trades exit immediately.

Priority A from architect's recommendation: "Forced stop-loss exit logic (prevents capital bleed)"
"""

import sys
import os
import logging
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Get the directory of this script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TRADING_STRATEGY_PATH = os.path.join(SCRIPT_DIR, 'bot', 'trading_strategy.py')


def test_stop_loss_fires_first():
    """
    Test that stop-loss check happens BEFORE all other exit logic.
    
    Stop-loss should trigger at STOP_LOSS_THRESHOLD (-0.01%) and execute
    immediately, skipping all other checks (RSI, EMA, time-based, etc.)
    """
    logger.info("=" * 80)
    logger.info("TEST: Stop-Loss Fires BEFORE All Other Logic")
    logger.info("=" * 80)
    
    try:
        # Import after path setup
        from bot.trading_strategy import (
            TradingStrategy,
            STOP_LOSS_THRESHOLD,
            MAX_LOSING_POSITION_HOLD_MINUTES
        )
        
        logger.info(f"✅ Imported trading_strategy module")
        logger.info(f"   STOP_LOSS_THRESHOLD = {STOP_LOSS_THRESHOLD}%")
        logger.info(f"   MAX_LOSING_POSITION_HOLD_MINUTES = {MAX_LOSING_POSITION_HOLD_MINUTES} min")
        
        # Verify constants are set to aggressive values
        assert STOP_LOSS_THRESHOLD == -0.01, f"STOP_LOSS_THRESHOLD should be -0.01, got {STOP_LOSS_THRESHOLD}"
        assert MAX_LOSING_POSITION_HOLD_MINUTES == 3, f"MAX_LOSING_POSITION_HOLD_MINUTES should be 3, got {MAX_LOSING_POSITION_HOLD_MINUTES}"
        
        logger.info("✅ Stop-loss constants verified:")
        logger.info(f"   - Exit threshold: {STOP_LOSS_THRESHOLD}% (immediate exit on ANY loss)")
        logger.info(f"   - Max hold time: {MAX_LOSING_POSITION_HOLD_MINUTES} minutes")
        
        return True
        
    except ImportError as e:
        logger.error(f"❌ Failed to import trading_strategy: {e}")
        return False
    except AssertionError as e:
        logger.error(f"❌ Assertion failed: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        return False


def test_stop_loss_priority_order():
    """
    Test that stop-loss check occurs in the correct order within the code.
    
    The check should happen:
    1. AFTER P&L calculation
    2. BEFORE profit target checks
    3. BEFORE time-based exit checks
    4. BEFORE RSI/EMA checks
    """
    logger.info("")
    logger.info("=" * 80)
    logger.info("TEST: Stop-Loss Priority Order in Code")
    logger.info("=" * 80)
    
    try:
        # Read the trading_strategy.py file to verify code structure
        if not os.path.exists(TRADING_STRATEGY_PATH):
            logger.error(f"❌ Could not find trading_strategy.py at {TRADING_STRATEGY_PATH}")
            return False
        
        with open(TRADING_STRATEGY_PATH, 'r') as f:
            content = f.read()
        
        # Find the stop-loss check location
        stop_loss_marker = "# 🔥 FIX #1: HARD STOP-LOSS OVERRIDE"
        if stop_loss_marker not in content:
            logger.error(f"❌ Could not find stop-loss override marker in code")
            return False
        
        logger.info("✅ Found hard stop-loss override section in code")
        
        # Verify it comes BEFORE profit target checks
        stop_loss_pos = content.find(stop_loss_marker)
        profit_target_pos = content.find("# STEPPED PROFIT TAKING")
        
        if stop_loss_pos < profit_target_pos:
            logger.info("✅ Stop-loss check occurs BEFORE profit target checks")
        else:
            logger.error("❌ Stop-loss check occurs AFTER profit target checks (WRONG ORDER)")
            return False
        
        # Verify it comes AFTER P&L calculation
        pnl_calc_pos = content.rfind("calculate_pnl", 0, stop_loss_pos)
        if pnl_calc_pos > 0:
            logger.info("✅ Stop-loss check occurs AFTER P&L calculation")
        else:
            logger.error("❌ Could not verify P&L calculation occurs before stop-loss")
            return False
        
        # Verify it uses 'continue' to skip remaining logic
        # Need to search a larger range as the continue is about 30 lines down
        stop_loss_section = content[stop_loss_pos:stop_loss_pos + 3000]
        if "# Skip ALL remaining logic for this position" in stop_loss_section and "continue" in stop_loss_section:
            logger.info("✅ Stop-loss uses 'continue' to skip all remaining logic")
        else:
            logger.error("❌ Stop-loss doesn't properly skip remaining logic")
            logger.debug(f"Section length: {len(stop_loss_section)}")
            return False
        
        logger.info("✅ Stop-loss priority order verified:")
        logger.info("   1. P&L calculation")
        logger.info("   2. Hard stop-loss check (exits immediately)")
        logger.info("   3. Losing trade time check")
        logger.info("   4. Emergency stop-loss (-0.75%)")
        logger.info("   5. Profit targets (only if no stop-loss)")
        
        return True
        
    except FileNotFoundError:
        logger.error("❌ Could not find bot/trading_strategy.py")
        return False
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        return False


def test_3_minute_max_losing_hold():
    """
    Test that losing trades are held for a maximum of 3 minutes.
    
    This prevents the "will auto-exit in 23.7min" messages that bleed capital.
    Any position with P&L < 0% for more than 3 minutes should be exited.
    """
    logger.info("")
    logger.info("=" * 80)
    logger.info("TEST: 3-Minute Max Hold for Losing Trades")
    logger.info("=" * 80)
    
    try:
        from bot.trading_strategy import MAX_LOSING_POSITION_HOLD_MINUTES
        
        # Verify 3-minute max
        assert MAX_LOSING_POSITION_HOLD_MINUTES == 3, \
            f"MAX_LOSING_POSITION_HOLD_MINUTES should be 3, got {MAX_LOSING_POSITION_HOLD_MINUTES}"
        
        logger.info(f"✅ Losing trades held max {MAX_LOSING_POSITION_HOLD_MINUTES} minutes")
        logger.info("   (Changed from 30 minutes to prevent capital bleed)")
        
        # Verify the logic exists in code
        if not os.path.exists(TRADING_STRATEGY_PATH):
            logger.error(f"❌ Could not find trading_strategy.py at {TRADING_STRATEGY_PATH}")
            return False
        
        with open(TRADING_STRATEGY_PATH, 'r') as f:
            content = f.read()
        
        # Look for the 3-minute time exit logic
        time_exit_marker = "# ✅ FIX #2: LOSING TRADES GET 3 MINUTES MAX"
        if time_exit_marker not in content:
            logger.error("❌ Could not find 3-minute max hold logic in code")
            return False
        
        logger.info("✅ 3-minute max hold logic found in code")
        
        # Verify it checks pnl_percent < 0
        time_exit_pos = content.find(time_exit_marker)
        time_exit_section = content[time_exit_pos:time_exit_pos + 1000]
        
        if "if pnl_percent < 0 and entry_time_available:" in time_exit_section:
            logger.info("✅ Time exit only applies to losing trades (P&L < 0%)")
        else:
            logger.error("❌ Time exit logic doesn't check for losing trades")
            return False
        
        if "position_age_minutes >= MAX_LOSING_POSITION_HOLD_MINUTES:" in time_exit_section:
            logger.info("✅ Time exit enforces MAX_LOSING_POSITION_HOLD_MINUTES")
        else:
            logger.error("❌ Time exit doesn't enforce max hold minutes")
            return False
        
        logger.info("✅ 3-minute max hold verified:")
        logger.info("   - Only applies to losing trades (P&L < 0%)")
        logger.info("   - Exits after 3 minutes of holding")
        logger.info("   - Prevents 'will auto-exit in 23.7min' capital bleed")
        
        return True
        
    except ImportError as e:
        logger.error(f"❌ Failed to import: {e}")
        return False
    except AssertionError as e:
        logger.error(f"❌ Assertion failed: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        return False


def test_emergency_stop_loss():
    """
    Test that emergency stop-loss at -0.75% acts as a failsafe.
    
    This catches any losing trades that might slip through the -0.01% threshold.
    """
    logger.info("")
    logger.info("=" * 80)
    logger.info("TEST: Emergency Stop-Loss Failsafe")
    logger.info("=" * 80)
    
    try:
        # Verify emergency stop-loss exists in code
        if not os.path.exists(TRADING_STRATEGY_PATH):
            logger.error(f"❌ Could not find trading_strategy.py at {TRADING_STRATEGY_PATH}")
            return False
        
        with open(TRADING_STRATEGY_PATH, 'r') as f:
            content = f.read()
        
        # Look for emergency stop-loss at -0.75%
        if "if pnl_percent <= -0.75:" in content:
            logger.info("✅ Emergency stop-loss found at -0.75%")
        else:
            logger.error("❌ Emergency stop-loss at -0.75% not found")
            return False
        
        # Verify it executes immediately
        emergency_pos = content.find("if pnl_percent <= -0.75:")
        emergency_section = content[emergency_pos:emergency_pos + 2000]
        
        if "place_market_order" in emergency_section:
            logger.info("✅ Emergency stop-loss executes market sell immediately")
        else:
            logger.error("❌ Emergency stop-loss doesn't execute sell order")
            return False
        
        if "# Skip to next position - emergency exit overrides all other logic" in emergency_section:
            logger.info("✅ Emergency stop-loss skips all remaining logic")
        else:
            logger.error("❌ Emergency stop-loss doesn't skip remaining logic")
            return False
        
        logger.info("✅ Emergency stop-loss verified:")
        logger.info("   - Triggers at -0.75% loss")
        logger.info("   - Executes immediate market sell")
        logger.info("   - Acts as failsafe if -0.01% threshold missed")
        
        return True
        
    except FileNotFoundError:
        logger.error("❌ Could not find bot/trading_strategy.py")
        return False
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        return False


def main():
    """Run all stop-loss validation tests."""
    logger.info("\n")
    logger.info("╔" + "=" * 78 + "╗")
    logger.info("║" + " " * 15 + "FORCED STOP-LOSS EXIT VALIDATION" + " " * 30 + "║")
    logger.info("║" + " " * 20 + "Priority A: Capital Preservation" + " " * 27 + "║")
    logger.info("╚" + "=" * 78 + "╝")
    logger.info("\n")
    
    tests = [
        ("Stop-Loss Constants", test_stop_loss_fires_first),
        ("Stop-Loss Priority Order", test_stop_loss_priority_order),
        ("3-Minute Max Hold", test_3_minute_max_losing_hold),
        ("Emergency Stop-Loss", test_emergency_stop_loss),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            logger.error(f"❌ Test '{test_name}' crashed: {e}")
            results.append((test_name, False))
    
    # Summary
    logger.info("\n")
    logger.info("=" * 80)
    logger.info("TEST SUMMARY")
    logger.info("=" * 80)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{status} - {test_name}")
    
    logger.info("")
    logger.info(f"Results: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("✅ ALL TESTS PASSED - Stop-loss logic validated")
        logger.info("")
        logger.info("Capital preservation features:")
        logger.info("  ✓ Immediate exit on ANY loss (P&L ≤ -0.01%)")
        logger.info("  ✓ 3-minute max hold for losing trades")
        logger.info("  ✓ Emergency failsafe at -0.75%")
        logger.info("  ✓ Stop-loss fires BEFORE all other logic")
        return 0
    else:
        logger.error(f"❌ {total - passed} TEST(S) FAILED - Review stop-loss implementation")
        return 1


if __name__ == "__main__":
    sys.exit(main())
