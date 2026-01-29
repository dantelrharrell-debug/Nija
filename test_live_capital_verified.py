#!/usr/bin/env python3
"""
Test script to verify LIVE_CAPITAL_VERIFIED is properly enabled.
This test checks that the safety control system recognizes the setting.
"""

import os
import sys

# Load .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("✅ .env file loaded")
except ImportError:
    print("⚠️  dotenv not available, using environment variables directly")

# Add bot directory to path (using absolute path for reliability)
bot_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot')
if bot_dir not in sys.path:
    sys.path.insert(0, bot_dir)

def test_environment_variable():
    """Test that LIVE_CAPITAL_VERIFIED is set in environment."""
    print("\n" + "="*80)
    print("TEST 1: Environment Variable Check")
    print("="*80)

    verified_str = os.getenv('LIVE_CAPITAL_VERIFIED', 'false').lower().strip()
    print(f"LIVE_CAPITAL_VERIFIED environment variable: '{verified_str}'")

    verified = verified_str in ['true', '1', 'yes', 'enabled']

    if verified:
        print("✅ LIVE_CAPITAL_VERIFIED is set to TRUE")
        print("   Trading should be ENABLED")
        return True
    else:
        print("❌ LIVE_CAPITAL_VERIFIED is set to FALSE or not set")
        print("   Trading is DISABLED")
        return False

def test_controls_module():
    """Test that the controls module recognizes the setting."""
    print("\n" + "="*80)
    print("TEST 2: Controls Module Check")
    print("="*80)

    try:
        # Import the controls module
        from controls import get_hard_controls

        # Get the hard controls instance
        controls = get_hard_controls()

        print(f"Controls initialized: {controls is not None}")
        print(f"live_capital_verified property: {controls.live_capital_verified}")

        if controls.live_capital_verified:
            print("✅ Controls module recognizes LIVE_CAPITAL_VERIFIED=true")
            print("   Trading is ENABLED at the controls level")
            return True
        else:
            print("❌ Controls module does not recognize LIVE_CAPITAL_VERIFIED")
            print("   Trading is DISABLED at the controls level")
            return False

    except Exception as e:
        print(f"❌ Error testing controls module: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_can_trade():
    """Test that can_trade() returns True for a test user."""
    print("\n" + "="*80)
    print("TEST 3: Can Trade Check")
    print("="*80)

    try:
        from controls import get_hard_controls

        controls = get_hard_controls()
        # Use a representative test user ID (matching typical user_id format in the system)
        test_user_id = os.getenv("TEST_USER_ID", "master")

        can_trade, error_msg = controls.can_trade(test_user_id)

        print(f"can_trade() result: {can_trade}")
        if error_msg:
            print(f"Error message: {error_msg}")

        if can_trade:
            print("✅ User CAN trade - no blocking conditions")
            print("   All safety checks passed")
            return True
        else:
            print("❌ User CANNOT trade")
            print(f"   Blocking reason: {error_msg}")
            return False

    except Exception as e:
        print(f"❌ Error testing can_trade: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests."""
    print("\n" + "#"*80)
    print("# LIVE_CAPITAL_VERIFIED Configuration Test")
    print("#"*80)

    results = []

    # Run tests
    results.append(("Environment Variable", test_environment_variable()))
    results.append(("Controls Module", test_controls_module()))
    results.append(("Can Trade", test_can_trade()))

    # Print summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)

    all_passed = True
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} - {test_name}")
        if not passed:
            all_passed = False

    print("="*80)

    if all_passed:
        print("\n🎉 ALL TESTS PASSED!")
        print("   NIJA should now be able to execute trades")
        print("   The LIVE_CAPITAL_VERIFIED setting is properly configured")
        return 0
    else:
        print("\n⚠️  SOME TESTS FAILED")
        print("   Please check the error messages above")
        print("   Trading may still be blocked")
        return 1

if __name__ == "__main__":
    sys.exit(main())
