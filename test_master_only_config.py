#!/usr/bin/env python3
"""
Test script for MASTER_ONLY configuration
Validates that all configuration settings are working correctly

Usage:
    python3 test_master_only_config.py
"""

import os
import sys

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

def test_whitelist_import():
    """Test that master_only_config can be imported"""
    print("=" * 70)
    print("TEST 1: Import master_only_config module")
    print("=" * 70)
    
    try:
        # Import directly without the bot. prefix since we already added to path
        import master_only_config
        
        # Verify key attributes exist
        required_attrs = [
            'WHITELISTED_ASSETS',
            'is_whitelisted_symbol',
            'get_whitelisted_symbols',
            'A_PLUS_CRITERIA',
            'RISK_PER_TRADE_MIN_PCT',
            'RISK_PER_TRADE_MAX_PCT',
            'MAX_POSITIONS',
            'MIN_TRADE_SIZE_USD',
            'LEVERAGE_ENABLED',
            'GROWTH_PATH',
        ]
        
        for attr in required_attrs:
            if not hasattr(master_only_config, attr):
                print(f"❌ FAILED: Missing attribute: {attr}\n")
                return False
        
        print("✅ PASSED: master_only_config imported successfully\n")
        return True
    except ImportError as e:
        print(f"❌ FAILED: Could not import master_only_config: {e}\n")
        return False
    except Exception as e:
        print(f"❌ FAILED: Unexpected error: {e}\n")
        return False


def test_whitelist_symbols():
    """Test whitelist symbol checking"""
    print("=" * 70)
    print("TEST 2: Whitelist Symbol Checking")
    print("=" * 70)
    
    import master_only_config
    
    print(f"\nWhitelisted assets: {master_only_config.WHITELISTED_ASSETS}")
    
    # Test Coinbase symbols
    print("\n📊 Testing Coinbase symbols:")
    test_cases_coinbase = [
        ("BTC-USD", True),
        ("ETH-USD", True),
        ("SOL-USD", True),
        ("XRP-USD", False),
        ("DOGE-USD", False),
        ("ADA-USD", False),
    ]
    
    all_passed = True
    for symbol, expected in test_cases_coinbase:
        result = master_only_config.is_whitelisted_symbol(symbol, "coinbase")
        status = "✅" if result == expected else "❌"
        print(f"   {status} {symbol}: {result} (expected {expected})")
        if result != expected:
            all_passed = False
    
    # Test Kraken symbols
    print("\n📊 Testing Kraken symbols:")
    test_cases_kraken = [
        ("XXBTZUSD", True),   # BTC on Kraken
        ("XETHZUSD", True),   # ETH on Kraken
        ("SOLUSD", True),     # SOL on Kraken
        ("XRPUSD", False),    # XRP (not whitelisted)
        ("ADAUSD", False),    # ADA (not whitelisted)
    ]
    
    for symbol, expected in test_cases_kraken:
        result = master_only_config.is_whitelisted_symbol(symbol, "kraken")
        status = "✅" if result == expected else "❌"
        print(f"   {status} {symbol}: {result} (expected {expected})")
        if result != expected:
            all_passed = False
    
    if all_passed:
        print("\n✅ PASSED: All whitelist checks correct\n")
    else:
        print("\n❌ FAILED: Some whitelist checks incorrect\n")
    
    return all_passed


def test_risk_config():
    """Test risk configuration values"""
    print("=" * 70)
    print("TEST 3: Risk Configuration Values")
    print("=" * 70)
    
    import master_only_config
    from master_only_config import (
        RISK_PER_TRADE_MIN_PCT,
        RISK_PER_TRADE_MAX_PCT,
        DEFAULT_RISK_PER_TRADE_PCT,
        MAX_DAILY_LOSS_PCT,
        MAX_TOTAL_EXPOSURE_PCT,
    )
    
    print(f"\n💼 Risk Settings:")
    print(f"   Risk per trade: {RISK_PER_TRADE_MIN_PCT}% - {RISK_PER_TRADE_MAX_PCT}%")
    print(f"   Default risk: {DEFAULT_RISK_PER_TRADE_PCT}%")
    print(f"   Max daily loss: {MAX_DAILY_LOSS_PCT}%")
    print(f"   Max total exposure: {MAX_TOTAL_EXPOSURE_PCT}%")
    
    # Validate ranges
    all_passed = True
    
    if RISK_PER_TRADE_MIN_PCT != 3.0:
        print(f"   ❌ Min risk should be 3.0%, got {RISK_PER_TRADE_MIN_PCT}%")
        all_passed = False
    else:
        print(f"   ✅ Min risk: {RISK_PER_TRADE_MIN_PCT}%")
    
    if RISK_PER_TRADE_MAX_PCT != 5.0:
        print(f"   ❌ Max risk should be 5.0%, got {RISK_PER_TRADE_MAX_PCT}%")
        all_passed = False
    else:
        print(f"   ✅ Max risk: {RISK_PER_TRADE_MAX_PCT}%")
    
    if DEFAULT_RISK_PER_TRADE_PCT != 4.0:
        print(f"   ❌ Default risk should be 4.0%, got {DEFAULT_RISK_PER_TRADE_PCT}%")
        all_passed = False
    else:
        print(f"   ✅ Default risk: {DEFAULT_RISK_PER_TRADE_PCT}%")
    
    if all_passed:
        print("\n✅ PASSED: Risk configuration correct\n")
    else:
        print("\n❌ FAILED: Risk configuration incorrect\n")
    
    return all_passed


def test_position_config():
    """Test position management configuration"""
    print("=" * 70)
    print("TEST 4: Position Management Configuration")
    print("=" * 70)
    
    import master_only_config
    from master_only_config import (
        MAX_POSITIONS,
        MIN_TRADE_SIZE_USD,
        LEVERAGE_ENABLED,
    )
    
    print(f"\n📊 Position Settings:")
    print(f"   Max positions: {MAX_POSITIONS}")
    print(f"   Min trade size: ${MIN_TRADE_SIZE_USD}")
    print(f"   Leverage enabled: {LEVERAGE_ENABLED}")
    
    all_passed = True
    
    if MAX_POSITIONS != 2:
        print(f"   ❌ Max positions should be 2, got {MAX_POSITIONS}")
        all_passed = False
    else:
        print(f"   ✅ Max positions: {MAX_POSITIONS}")
    
    if MIN_TRADE_SIZE_USD != 5.00:
        print(f"   ❌ Min trade size should be $5.00, got ${MIN_TRADE_SIZE_USD}")
        all_passed = False
    else:
        print(f"   ✅ Min trade size: ${MIN_TRADE_SIZE_USD}")
    
    if LEVERAGE_ENABLED != False:
        print(f"   ❌ Leverage should be disabled, got {LEVERAGE_ENABLED}")
        all_passed = False
    else:
        print(f"   ✅ Leverage disabled")
    
    if all_passed:
        print("\n✅ PASSED: Position configuration correct\n")
    else:
        print("\n❌ FAILED: Position configuration incorrect\n")
    
    return all_passed


def test_growth_path():
    """Test growth path configuration"""
    print("=" * 70)
    print("TEST 5: Growth Path Configuration")
    print("=" * 70)
    
    import master_only_config
    from master_only_config import GROWTH_PATH, get_next_milestone
    
    print(f"\n📈 Growth Path:")
    for key, value in GROWTH_PATH.items():
        print(f"   {key}: ${value}")
    
    # Test milestone calculation
    print("\n🎯 Milestone Tests:")
    
    test_balances = [74, 90, 100, 125, 150, 200, 250, 400, 500, 600]
    all_passed = True
    
    for balance in test_balances:
        milestone = get_next_milestone(balance)
        if milestone:
            print(f"   ${balance:>3} → Next: ${milestone['target']} "
                  f"(need ${milestone['profit_needed']:.2f}, "
                  f"+{milestone['percent_gain']:.1f}%)")
        else:
            print(f"   ${balance:>3} → 🎉 Reached final milestone!")
    
    # Verify starting point
    if GROWTH_PATH['start'] != 74:
        print(f"\n   ❌ Starting point should be $74, got ${GROWTH_PATH['start']}")
        all_passed = False
    
    # Verify final milestone
    if GROWTH_PATH['milestone_4'] != 500:
        print(f"\n   ❌ Final milestone should be $500, got ${GROWTH_PATH['milestone_4']}")
        all_passed = False
    
    if all_passed:
        print("\n✅ PASSED: Growth path configuration correct\n")
    else:
        print("\n❌ FAILED: Growth path configuration incorrect\n")
    
    return all_passed


def test_a_plus_criteria():
    """Test A+ setup criteria configuration"""
    print("=" * 70)
    print("TEST 6: A+ Setup Criteria Configuration")
    print("=" * 70)
    
    import master_only_config
    from master_only_config import A_PLUS_CRITERIA, MIN_ENTRY_SCORE
    
    print(f"\n⭐ A+ Setup Criteria:")
    print(f"   Min entry score: {MIN_ENTRY_SCORE}/10")
    print(f"\n   Technical Requirements:")
    for key, value in A_PLUS_CRITERIA.items():
        print(f"      • {key}: {value}")
    
    all_passed = True
    
    if MIN_ENTRY_SCORE != 8:
        print(f"\n   ❌ Min entry score should be 8, got {MIN_ENTRY_SCORE}")
        all_passed = False
    else:
        print(f"\n   ✅ Min entry score: {MIN_ENTRY_SCORE}/10")
    
    if all_passed:
        print("\n✅ PASSED: A+ criteria configuration correct\n")
    else:
        print("\n❌ FAILED: A+ criteria configuration incorrect\n")
    
    return all_passed


def test_env_config():
    """Test environment variable generation"""
    print("=" * 70)
    print("TEST 7: Environment Variable Generation")
    print("=" * 70)
    
    import master_only_config
    from master_only_config import get_env_config
    
    env_config = get_env_config()
    
    print(f"\n🔧 Generated Environment Variables:")
    for key, value in env_config.items():
        print(f"   {key}={value}")
    
    expected = {
        'COPY_TRADING_MODE': 'INDEPENDENT',
        'PRO_MODE': 'true',
        'MAX_CONCURRENT_POSITIONS': '2',
        'MIN_CASH_TO_BUY': '5.0',
        'LEVERAGE_ENABLED': 'false',
    }
    
    all_passed = True
    for key, expected_value in expected.items():
        if env_config.get(key) != expected_value:
            print(f"   ❌ {key} should be '{expected_value}', got '{env_config.get(key)}'")
            all_passed = False
    
    if all_passed:
        print("\n✅ PASSED: Environment config correct\n")
    else:
        print("\n❌ FAILED: Environment config incorrect\n")
    
    return all_passed


def main():
    """Run all tests"""
    print("\n")
    print("=" * 70)
    print("MASTER_ONLY CONFIGURATION TEST SUITE")
    print("=" * 70)
    print("\n")
    
    results = []
    
    # Run all tests
    results.append(("Import Module", test_whitelist_import()))
    
    if results[0][1]:  # Only continue if import succeeded
        results.append(("Whitelist Symbols", test_whitelist_symbols()))
        results.append(("Risk Configuration", test_risk_config()))
        results.append(("Position Configuration", test_position_config()))
        results.append(("Growth Path", test_growth_path()))
        results.append(("A+ Criteria", test_a_plus_criteria()))
        results.append(("Environment Config", test_env_config()))
    
    # Print summary
    print("=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{status}: {test_name}")
    
    print("\n" + "=" * 70)
    print(f"Results: {passed}/{total} tests passed")
    print("=" * 70)
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED! MASTER_ONLY configuration is working correctly.\n")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Please review the output above.\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
