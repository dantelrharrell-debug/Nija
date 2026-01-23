#!/usr/bin/env python3
"""
Test Copy Trading Requirements Validation

This script tests the copy trading requirements validation logic
to ensure all requirements are properly checked.
"""

import sys
import os

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from copy_trading_requirements import (
    MasterRequirements,
    UserRequirements,
    check_master_requirements,
    check_user_requirements
)

def test_master_requirements():
    """Test master requirements validation"""
    print("=" * 70)
    print("TEST 1: Master Requirements")
    print("=" * 70)
    
    # Test 1: All requirements met
    print("\n✅ Test 1.1: All requirements met")
    reqs = MasterRequirements(
        pro_mode=True,
        live_trading=True,
        master_broker_kraken=True,
        master_connected=True
    )
    assert reqs.all_met() == True
    assert len(reqs.get_unmet_requirements()) == 0
    print("   PASS: All requirements recognized as met")
    
    # Test 2: PRO_MODE missing
    print("\n❌ Test 1.2: PRO_MODE=false")
    reqs = MasterRequirements(
        pro_mode=False,
        live_trading=True,
        master_broker_kraken=True,
        master_connected=True
    )
    assert reqs.all_met() == False
    unmet = reqs.get_unmet_requirements()
    assert "MASTER PRO_MODE=true" in unmet
    print(f"   PASS: Correctly identified missing requirement: {unmet}")
    
    # Test 3: LIVE_TRADING missing
    print("\n❌ Test 1.3: LIVE_TRADING=false")
    reqs = MasterRequirements(
        pro_mode=True,
        live_trading=False,
        master_broker_kraken=True,
        master_connected=True
    )
    assert reqs.all_met() == False
    unmet = reqs.get_unmet_requirements()
    assert "LIVE_TRADING=true" in unmet
    print(f"   PASS: Correctly identified missing requirement: {unmet}")
    
    # Test 4: Kraken not configured
    print("\n❌ Test 1.4: Kraken not configured")
    reqs = MasterRequirements(
        pro_mode=True,
        live_trading=True,
        master_broker_kraken=False,
        master_connected=False
    )
    assert reqs.all_met() == False
    unmet = reqs.get_unmet_requirements()
    assert "MASTER_BROKER=KRAKEN" in unmet
    assert "MASTER_CONNECTED=true" in unmet
    print(f"   PASS: Correctly identified missing requirements: {unmet}")
    
    # Test 5: Multiple missing
    print("\n❌ Test 1.5: Multiple requirements missing")
    reqs = MasterRequirements(
        pro_mode=False,
        live_trading=False,
        master_broker_kraken=False,
        master_connected=False
    )
    assert reqs.all_met() == False
    unmet = reqs.get_unmet_requirements()
    assert len(unmet) == 4
    print(f"   PASS: Correctly identified all 4 missing requirements: {unmet}")


def test_user_requirements():
    """Test user requirements validation"""
    print("\n" + "=" * 70)
    print("TEST 2: User Requirements")
    print("=" * 70)
    
    # Test 1: All requirements met (SAVER tier)
    print("\n✅ Test 2.1: All requirements met (SAVER tier, $150)")
    reqs = UserRequirements(
        user_id="test_user",
        pro_mode=True,
        copy_trading_enabled=True,
        standalone=False,
        tier_sufficient=True,
        initial_capital_sufficient=True
    )
    assert reqs.all_met() == True
    assert len(reqs.get_unmet_requirements()) == 0
    print("   PASS: All requirements recognized as met")
    
    # Test 2: PRO_MODE missing
    print("\n❌ Test 2.2: PRO_MODE=false")
    reqs = UserRequirements(
        user_id="test_user",
        pro_mode=False,
        copy_trading_enabled=True,
        standalone=False,
        tier_sufficient=True,
        initial_capital_sufficient=True
    )
    assert reqs.all_met() == False
    unmet = reqs.get_unmet_requirements()
    assert any("PRO_MODE=true" in req for req in unmet)
    print(f"   PASS: Correctly identified missing requirement: {unmet}")
    
    # Test 3: Copy trading disabled
    print("\n❌ Test 2.3: COPY_TRADING=false")
    reqs = UserRequirements(
        user_id="test_user",
        pro_mode=True,
        copy_trading_enabled=False,
        standalone=False,
        tier_sufficient=True,
        initial_capital_sufficient=True
    )
    assert reqs.all_met() == False
    unmet = reqs.get_unmet_requirements()
    assert any("COPY_TRADING=true" in req for req in unmet)
    print(f"   PASS: Correctly identified missing requirement: {unmet}")
    
    # Test 4: Standalone mode
    print("\n❌ Test 2.4: STANDALONE=true")
    reqs = UserRequirements(
        user_id="test_user",
        pro_mode=True,
        copy_trading_enabled=True,
        standalone=True,  # This should fail
        tier_sufficient=True,
        initial_capital_sufficient=True
    )
    assert reqs.all_met() == False
    unmet = reqs.get_unmet_requirements()
    assert any("STANDALONE=false" in req for req in unmet)
    print(f"   PASS: Correctly identified missing requirement: {unmet}")
    
    # Test 5: Insufficient balance (below STARTER)
    print("\n❌ Test 2.5: Balance below STARTER tier ($40)")
    reqs = UserRequirements(
        user_id="test_user",
        pro_mode=True,
        copy_trading_enabled=True,
        standalone=False,
        tier_sufficient=False,  # Below $50
        initial_capital_sufficient=False
    )
    assert reqs.all_met() == False
    unmet = reqs.get_unmet_requirements()
    assert any("TIER >= STARTER" in req for req in unmet)
    print(f"   PASS: Correctly identified missing requirement: {unmet}")
    
    # Test 6: STARTER tier ($75) - should pass
    print("\n✅ Test 2.6: STARTER tier ($75) - INITIAL_CAPITAL requirement waived")
    reqs = UserRequirements(
        user_id="test_user",
        pro_mode=True,
        copy_trading_enabled=True,
        standalone=False,
        tier_sufficient=True,  # >= $50
        initial_capital_sufficient=True  # Waived for STARTER
    )
    assert reqs.all_met() == True
    print("   PASS: STARTER tier user can copy trade without $100 requirement")


def test_integration():
    """Test integration with environment variables"""
    print("\n" + "=" * 70)
    print("TEST 3: Environment Variable Integration")
    print("=" * 70)
    
    # Save original env vars
    original_pro_mode = os.getenv('PRO_MODE')
    original_live_trading = os.getenv('LIVE_TRADING')
    original_copy_mode = os.getenv('COPY_TRADING_MODE')
    
    # Test 1: Set valid environment
    print("\n✅ Test 3.1: Valid environment variables")
    os.environ['PRO_MODE'] = 'true'
    os.environ['LIVE_TRADING'] = '1'
    os.environ['COPY_TRADING_MODE'] = 'MASTER_FOLLOW'
    
    # Test check_user_requirements with valid env
    user_reqs = check_user_requirements(
        user_id="test_user",
        user_balance=150.0,  # SAVER tier
        user_broker=None,
        copy_from_master=True
    )
    assert user_reqs.pro_mode == True
    assert user_reqs.copy_trading_enabled == True
    assert user_reqs.standalone == False
    assert user_reqs.tier_sufficient == True
    assert user_reqs.initial_capital_sufficient == True
    print("   PASS: Environment variables correctly parsed")
    
    # Test 2: Invalid environment
    print("\n❌ Test 3.2: Invalid environment variables")
    os.environ['PRO_MODE'] = 'false'
    os.environ['COPY_TRADING_MODE'] = 'INDEPENDENT'
    
    user_reqs = check_user_requirements(
        user_id="test_user",
        user_balance=150.0,
        user_broker=None,
        copy_from_master=True
    )
    assert user_reqs.pro_mode == False
    assert user_reqs.copy_trading_enabled == False
    assert user_reqs.standalone == True  # INDEPENDENT mode = standalone
    print("   PASS: Invalid environment correctly detected")
    
    # Restore original env vars
    if original_pro_mode is not None:
        os.environ['PRO_MODE'] = original_pro_mode
    elif 'PRO_MODE' in os.environ:
        del os.environ['PRO_MODE']
    
    if original_live_trading is not None:
        os.environ['LIVE_TRADING'] = original_live_trading
    elif 'LIVE_TRADING' in os.environ:
        del os.environ['LIVE_TRADING']
    
    if original_copy_mode is not None:
        os.environ['COPY_TRADING_MODE'] = original_copy_mode
    elif 'COPY_TRADING_MODE' in os.environ:
        del os.environ['COPY_TRADING_MODE']


def main():
    """Run all tests"""
    print("\n🧪 COPY TRADING REQUIREMENTS VALIDATION TEST SUITE")
    print("=" * 70)
    
    try:
        test_master_requirements()
        test_user_requirements()
        test_integration()
        
        print("\n" + "=" * 70)
        print("✅ ALL TESTS PASSED")
        print("=" * 70)
        print("\nCopy trading requirements validation is working correctly!")
        return 0
    
    except AssertionError as e:
        print("\n" + "=" * 70)
        print("❌ TEST FAILED")
        print("=" * 70)
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    except Exception as e:
        print("\n" + "=" * 70)
        print("❌ UNEXPECTED ERROR")
        print("=" * 70)
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
