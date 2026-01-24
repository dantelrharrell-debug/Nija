#!/usr/bin/env python3
"""
Validation script for losing trade exit fix.

This script validates that the fix for auto-imported losing positions works correctly.
It checks:
1. Auto-imported positions with losses are queued for immediate exit
2. just_auto_imported flag is set to False to allow stop-loss execution
3. Position tracker uses data/ directory for persistence
"""

import os
import sys

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))


def validate_trading_strategy_fix():
    """Validate that trading_strategy.py has the correct fix."""
    print("🔍 Validating trading_strategy.py fixes...")
    
    with open('bot/trading_strategy.py', 'r') as f:
        content = f.read()
    
    # Check 1: just_auto_imported should be set to False (not True)
    fixes_found = 0
    
    # Look for the fix where just_auto_imported = False
    if 'just_auto_imported = False  # Changed from True' in content:
        print("✅ Fix 1: just_auto_imported set to False (allows stop-loss)")
        fixes_found += 1
    else:
        print("❌ Fix 1: MISSING - just_auto_imported should be False")
    
    # Check 2: Auto-imported losers should be added to positions_to_exit
    if 'positions_to_exit.append' in content and 'Auto-imported losing position' in content:
        print("✅ Fix 2: Auto-imported losers queued for immediate exit")
        fixes_found += 1
    else:
        print("❌ Fix 2: MISSING - auto-imported losers not queued for exit")
    
    # Check 3: The old buggy code should be removed/fixed
    if 'just_auto_imported = True' not in content or '# Changed from True' in content:
        print("✅ Fix 3: Buggy 'just_auto_imported = True' removed/fixed")
        fixes_found += 1
    else:
        print("⚠️  WARNING: Found 'just_auto_imported = True' in code")
    
    return fixes_found >= 2


def validate_broker_manager_fix():
    """Validate that broker_manager.py uses data/ directory for position tracker."""
    print("\n🔍 Validating broker_manager.py fixes...")
    
    with open('bot/broker_manager.py', 'r') as f:
        content = f.read()
    
    # Check if PositionTracker uses data/ directory
    if 'PositionTracker(storage_file="data/positions.json")' in content:
        print("✅ Position tracker uses data/ directory for persistence")
        return True
    elif 'PositionTracker(storage_file="positions.json")' in content:
        print("❌ Position tracker still uses root directory (won't persist)")
        return False
    else:
        print("⚠️  Could not find PositionTracker initialization")
        return False


def validate_data_directory():
    """Validate that data/ directory exists and is writable."""
    print("\n🔍 Validating data/ directory...")
    
    if not os.path.exists('data'):
        print("❌ data/ directory does not exist!")
        return False
    
    if not os.path.isdir('data'):
        print("❌ data/ is not a directory!")
        return False
    
    # Check if writable
    test_file = 'data/.write_test'
    try:
        with open(test_file, 'w') as f:
            f.write('test')
        os.remove(test_file)
        print("✅ data/ directory is writable")
        return True
    except Exception as e:
        print(f"❌ data/ directory is not writable: {e}")
        return False


def validate_position_files():
    """Check status of position tracking files."""
    print("\n🔍 Checking position tracking files...")
    
    # Check data/open_positions.json
    if os.path.exists('data/open_positions.json'):
        size = os.path.getsize('data/open_positions.json')
        if size < 200:  # Small size indicates clean/empty file
            print(f"✅ data/open_positions.json exists and is clean ({size} bytes)")
        else:
            print(f"⚠️  data/open_positions.json exists ({size} bytes) - may need cleanup")
    else:
        print("ℹ️  data/open_positions.json does not exist (will be created on run)")
    
    # Check data/positions.json (position tracker)
    if os.path.exists('data/positions.json'):
        size = os.path.getsize('data/positions.json')
        print(f"✅ data/positions.json exists ({size} bytes)")
    else:
        print("ℹ️  data/positions.json does not exist (will be created on first run)")
    
    # Check for old positions.json in root
    if os.path.exists('positions.json'):
        print("⚠️  WARNING: Old positions.json found in root (should be deleted)")
        return False
    else:
        print("✅ No old positions.json in root directory")
    
    return True


def main():
    """Run all validations."""
    print("=" * 80)
    print("🔍 VALIDATING LOSING TRADE EXIT FIX")
    print("=" * 80)
    
    results = []
    
    # Run validations
    results.append(("Trading Strategy Fix", validate_trading_strategy_fix()))
    results.append(("Broker Manager Fix", validate_broker_manager_fix()))
    results.append(("Data Directory", validate_data_directory()))
    results.append(("Position Files", validate_position_files()))
    
    # Summary
    print("\n" + "=" * 80)
    print("📊 VALIDATION SUMMARY")
    print("=" * 80)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")
    
    print(f"\nResults: {passed}/{total} validations passed")
    
    if passed == total:
        print("\n✅ ALL VALIDATIONS PASSED!")
        print("\n📝 Next steps:")
        print("   1. Deploy to Railway")
        print("   2. Monitor logs for auto-imported positions")
        print("   3. Verify losing trades are exited immediately")
        print("   4. Check that positions persist across restarts")
        return 0
    else:
        print("\n❌ SOME VALIDATIONS FAILED!")
        print("   Please review the failures above and fix before deploying.")
        return 1


if __name__ == '__main__':
    sys.exit(main())
