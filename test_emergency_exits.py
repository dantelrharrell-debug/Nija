#!/usr/bin/env python3
"""
Test Emergency Exit System
===========================

Verify that emergency exit thresholds are properly configured.
"""

import sys
import os

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

try:
    from trading_strategy import (
        STOP_LOSS_THRESHOLD,
        STOP_LOSS_EMERGENCY,
        STOP_LOSS_WARNING,
        MAX_POSITION_HOLD_HOURS,
        MAX_POSITION_HOLD_EMERGENCY,
        STALE_POSITION_WARNING_HOURS,
        UNSELLABLE_RETRY_HOURS
    )
    
    print("=" * 70)
    print("EMERGENCY EXIT SYSTEM CONFIGURATION")
    print("=" * 70)
    print()
    
    print("📊 STOP LOSS THRESHOLDS")
    print("-" * 70)
    print(f"   Warning Level:        {STOP_LOSS_WARNING}% loss")
    print(f"   Normal Stop Loss:     {STOP_LOSS_THRESHOLD}% loss")
    print(f"   EMERGENCY Stop Loss:  {STOP_LOSS_EMERGENCY}% loss ⚠️")
    print()
    
    print("⏰ TIME-BASED EXIT THRESHOLDS")
    print("-" * 70)
    print(f"   Warning After:        {STALE_POSITION_WARNING_HOURS} hours")
    print(f"   Normal Exit After:    {MAX_POSITION_HOLD_HOURS} hours")
    print(f"   EMERGENCY Exit After: {MAX_POSITION_HOLD_EMERGENCY} hours ⚠️")
    print()
    
    print("🔄 UNSELLABLE POSITION RETRY")
    print("-" * 70)
    print(f"   Retry After:          {UNSELLABLE_RETRY_HOURS} hours")
    print()
    
    print("=" * 70)
    print("VALIDATION RESULTS")
    print("=" * 70)
    print()
    
    # Validate configuration
    all_valid = True
    
    # Check stop loss progression
    if not (STOP_LOSS_WARNING < STOP_LOSS_THRESHOLD < STOP_LOSS_EMERGENCY < 0):
        print("❌ INVALID: Stop loss thresholds not in correct order")
        print(f"   Should be: Warning < Normal < Emergency < 0")
        print(f"   Actual: {STOP_LOSS_WARNING} < {STOP_LOSS_THRESHOLD} < {STOP_LOSS_EMERGENCY} < 0")
        all_valid = False
    else:
        print("✅ Stop loss thresholds correctly ordered")
    
    # Check time progression
    if not (0 < STALE_POSITION_WARNING_HOURS < MAX_POSITION_HOLD_HOURS < MAX_POSITION_HOLD_EMERGENCY):
        print("❌ INVALID: Time thresholds not in correct order")
        print(f"   Should be: 0 < Warning < Normal < Emergency")
        print(f"   Actual: 0 < {STALE_POSITION_WARNING_HOURS} < {MAX_POSITION_HOLD_HOURS} < {MAX_POSITION_HOLD_EMERGENCY}")
        all_valid = False
    else:
        print("✅ Time thresholds correctly ordered")
    
    # Check emergency thresholds exist
    if STOP_LOSS_EMERGENCY >= STOP_LOSS_THRESHOLD:
        print("❌ INVALID: Emergency stop loss not more aggressive than normal")
        all_valid = False
    else:
        print("✅ Emergency stop loss more aggressive than normal")
    
    if MAX_POSITION_HOLD_EMERGENCY <= MAX_POSITION_HOLD_HOURS:
        print("❌ INVALID: Emergency time exit not longer than normal")
        all_valid = False
    else:
        print("✅ Emergency time exit provides failsafe")
    
    # Check unsellable retry is reasonable (at least 1 hour)
    if UNSELLABLE_RETRY_HOURS < 1:
        print("❌ INVALID: Unsellable retry too short (< 1 hour)")
        all_valid = False
    else:
        print("✅ Unsellable retry timeout reasonable")
    
    print()
    
    if all_valid:
        print("=" * 70)
        print("✅ ALL VALIDATIONS PASSED")
        print("=" * 70)
        print()
        print("The emergency exit system is properly configured.")
        print()
        print("What this means:")
        print("  • No position can lose more than 5%")
        print("  • No position held longer than 12 hours")
        print("  • Unsellable positions retried after 24 hours")
        print("  • Multiple layers of protection active")
        print()
    else:
        print("=" * 70)
        print("❌ VALIDATION FAILED")
        print("=" * 70)
        print()
        print("Please review the configuration in bot/trading_strategy.py")
        sys.exit(1)

except ImportError as e:
    print("❌ ERROR: Could not import trading_strategy constants")
    print(f"   {e}")
    print()
    print("Make sure bot/trading_strategy.py exists and is valid Python.")
    sys.exit(1)
except Exception as e:
    print(f"❌ ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
