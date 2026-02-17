#!/usr/bin/env python3
"""
Test Kraken Rate Profiles Integration

This test verifies that the Kraken rate profiles are correctly integrated
into the broker_manager module and can be imported and used properly.
"""

import sys
import os

# Add bot directory to path FIRST to avoid bot/__init__.py
# The bot/__init__.py imports many dependencies (coinbase, etc.) which may not be installed
# in the test environment. We only need kraken_rate_profiles.py which has no external deps.
bot_dir = os.path.join(os.path.dirname(__file__), 'bot')
sys.path.insert(0, bot_dir)

def test_imports():
    """Test that all required modules can be imported"""
    print("Testing module imports...")

    try:
        from kraken_rate_profiles import (
            KrakenRateMode,
            KrakenAPICategory,
            get_kraken_rate_profile,
            get_category_for_method,
            calculate_min_interval,
            get_rate_profile_summary
        )
        print("✅ kraken_rate_profiles imports successful")
        return True
    except Exception as e:
        print(f"❌ Failed to import kraken_rate_profiles: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_rate_profile_selection():
    """Test auto-selection of rate profiles based on balance"""
    print("\nTesting rate profile auto-selection...")

    from kraken_rate_profiles import get_kraken_rate_profile, KrakenRateMode

    test_cases = [
        (25.0, KrakenRateMode.MICRO_CAP, "Micro-Cap Rate Profile"),
        (150.0, KrakenRateMode.LOW_CAPITAL, "Low-Capital Rate Profile"),
        (750.0, KrakenRateMode.STANDARD, "Standard Rate Profile"),
        (1500.0, KrakenRateMode.AGGRESSIVE, "Aggressive Rate Profile"),
    ]

    for balance, expected_mode, expected_name in test_cases:
        profile = get_kraken_rate_profile(account_balance=balance)

        if profile['name'] == expected_name:
            print(f"✅ Balance ${balance:.0f} → {profile['name']}")
        else:
            print(f"❌ Balance ${balance:.0f} → Expected {expected_name}, got {profile['name']}")
            return False

    return True


def test_api_categories():
    """Test API category detection for different methods"""
    print("\nTesting API category detection...")

    from kraken_rate_profiles import get_category_for_method, KrakenAPICategory

    test_cases = [
        ('AddOrder', KrakenAPICategory.ENTRY),  # Default for AddOrder
        ('Balance', KrakenAPICategory.MONITORING),
        ('TradeBalance', KrakenAPICategory.MONITORING),
        ('QueryOrders', KrakenAPICategory.QUERY),
        ('OpenOrders', KrakenAPICategory.QUERY),
    ]

    for method, expected_category in test_cases:
        category = get_category_for_method(method)

        if category == expected_category:
            print(f"✅ {method} → {category.value}")
        else:
            print(f"❌ {method} → Expected {expected_category.value}, got {category.value}")
            return False

    return True


def test_min_interval_calculation():
    """Test calculation of minimum intervals for different categories"""
    print("\nTesting minimum interval calculations...")

    from kraken_rate_profiles import (
        calculate_min_interval,
        KrakenAPICategory,
        KrakenRateMode
    )

    # Test MICRO_CAP mode (new)
    entry_interval = calculate_min_interval(KrakenAPICategory.ENTRY, KrakenRateMode.MICRO_CAP)
    monitoring_interval = calculate_min_interval(KrakenAPICategory.MONITORING, KrakenRateMode.MICRO_CAP)

    if entry_interval == 30.0:
        print(f"✅ MICRO_CAP entry interval: {entry_interval}s")
    else:
        print(f"❌ MICRO_CAP entry interval: Expected 30.0s, got {entry_interval}s")
        return False

    if monitoring_interval == 60.0:
        print(f"✅ MICRO_CAP monitoring interval: {monitoring_interval}s")
    else:
        print(f"❌ MICRO_CAP monitoring interval: Expected 60.0s, got {monitoring_interval}s")
        return False

    # Test LOW_CAPITAL mode (updated from 3s to 10s)
    entry_interval = calculate_min_interval(KrakenAPICategory.ENTRY, KrakenRateMode.LOW_CAPITAL)
    monitoring_interval = calculate_min_interval(KrakenAPICategory.MONITORING, KrakenRateMode.LOW_CAPITAL)

    if entry_interval == 10.0:
        print(f"✅ LOW_CAPITAL entry interval: {entry_interval}s")
    else:
        print(f"❌ LOW_CAPITAL entry interval: Expected 10.0s, got {entry_interval}s")
        return False

    if monitoring_interval == 30.0:
        print(f"✅ LOW_CAPITAL monitoring interval: {monitoring_interval}s")
    else:
        print(f"❌ LOW_CAPITAL monitoring interval: Expected 30.0s, got {monitoring_interval}s")
        return False

    # Test STANDARD mode
    entry_interval = calculate_min_interval(KrakenAPICategory.ENTRY, KrakenRateMode.STANDARD)
    monitoring_interval = calculate_min_interval(KrakenAPICategory.MONITORING, KrakenRateMode.STANDARD)

    if entry_interval == 2.0:
        print(f"✅ STANDARD entry interval: {entry_interval}s")
    else:
        print(f"❌ STANDARD entry interval: Expected 2.0s, got {entry_interval}s")
        return False

    if monitoring_interval == 10.0:
        print(f"✅ STANDARD monitoring interval: {monitoring_interval}s")
    else:
        print(f"❌ STANDARD monitoring interval: Expected 10.0s, got {monitoring_interval}s")
        return False

    return True


def test_profile_structure():
    """Test that profiles have all required fields"""
    print("\nTesting profile structure...")

    from kraken_rate_profiles import get_kraken_rate_profile, KrakenRateMode

    required_keys = ['name', 'description', 'entry', 'exit', 'monitoring', 'query', 'budget']
    category_keys = ['min_interval_seconds', 'max_per_minute', 'api_cost_points']
    budget_keys = ['total_points_per_minute', 'reserve_points', 'monitoring_budget_pct', 'query_budget_pct']

    for mode in KrakenRateMode:
        profile = get_kraken_rate_profile(mode=mode)

        # Check top-level keys
        for key in required_keys:
            if key not in profile:
                print(f"❌ {mode.value}: Missing key '{key}'")
                return False

        # Check category keys
        for category in ['entry', 'exit', 'monitoring', 'query']:
            for key in category_keys:
                if key not in profile[category]:
                    print(f"❌ {mode.value}.{category}: Missing key '{key}'")
                    return False

        # Check budget keys
        for key in budget_keys:
            if key not in profile['budget']:
                print(f"❌ {mode.value}.budget: Missing key '{key}'")
                return False

        print(f"✅ {mode.value} profile structure valid")

    return True


def main():
    """Run all tests"""
    print("="*80)
    print("KRAKEN RATE PROFILES INTEGRATION TESTS")
    print("="*80)

    all_passed = True

    # Run tests
    tests = [
        test_imports,
        test_rate_profile_selection,
        test_api_categories,
        test_min_interval_calculation,
        test_profile_structure,
    ]

    for test in tests:
        if not test():
            all_passed = False
            print(f"\n❌ Test failed: {test.__name__}")
        else:
            print(f"\n✅ Test passed: {test.__name__}")

    print("\n" + "="*80)
    if all_passed:
        print("✅ ALL TESTS PASSED")
        print("="*80)
        return 0
    else:
        print("❌ SOME TESTS FAILED")
        print("="*80)
        return 1


if __name__ == "__main__":
    sys.exit(main())
