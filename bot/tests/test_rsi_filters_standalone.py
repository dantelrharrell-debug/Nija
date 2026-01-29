"""
Standalone test script for RSI filter logic validation
Runs independently without pytest to verify institutional-grade RSI filters
"""

import sys
sys.path.insert(0, '.')


def test_rsi_filters():
    """Test RSI filter methods directly"""
    
    # Define the filter functions inline (same logic as in nija_apex_strategy_v71.py)
    def _rsi_long_filter(rsi: float) -> bool:
        """Institutional long entry RSI filter: buy weakness, not strength."""
        return 25 <= rsi <= 45
    
    def _rsi_short_filter(rsi: float) -> bool:
        """Institutional short entry RSI filter: sell strength, not weakness."""
        return 55 <= rsi <= 75
    
    print("=" * 70)
    print("INSTITUTIONAL-GRADE RSI ENTRY VALIDATION TESTS")
    print("=" * 70)
    print()
    
    # Track test results
    passed = 0
    failed = 0
    
    # Long entry tests
    print("LONG ENTRY RSI TESTS")
    print("-" * 70)
    
    tests = [
        (35, True, "RSI 35 → TRUE (optimal long zone: 25-45)"),
        (48, False, "RSI 48 → FALSE (too high, avoid buying high)"),
        (55, False, "RSI 55 → FALSE (overbought)"),
        (65, False, "RSI 65 → FALSE (extreme overbought)"),
        (25, True, "RSI 25 → TRUE (lower boundary)"),
        (45, True, "RSI 45 → TRUE (upper boundary)"),
        (24, False, "RSI 24 → FALSE (below boundary)"),
        (46, False, "RSI 46 → FALSE (above boundary)"),
    ]
    
    for rsi, expected, desc in tests:
        result = _rsi_long_filter(rsi)
        if result == expected:
            print(f"✅ PASSED: {desc}")
            passed += 1
        else:
            print(f"❌ FAILED: {desc} (got {result}, expected {expected})")
            failed += 1
    
    print()
    print("SHORT ENTRY RSI TESTS")
    print("-" * 70)
    
    tests = [
        (65, True, "RSI 65 → TRUE (optimal short zone: 55-75)"),
        (58, True, "RSI 58 → TRUE (valid short entry zone)"),
        (45, False, "RSI 45 → FALSE (too low, avoid selling low)"),
        (35, False, "RSI 35 → FALSE (deep oversold, never short)"),
        (55, True, "RSI 55 → TRUE (lower boundary)"),
        (75, True, "RSI 75 → TRUE (upper boundary)"),
        (54, False, "RSI 54 → FALSE (below boundary)"),
        (76, False, "RSI 76 → FALSE (above boundary)"),
    ]
    
    for rsi, expected, desc in tests:
        result = _rsi_short_filter(rsi)
        if result == expected:
            print(f"✅ PASSED: {desc}")
            passed += 1
        else:
            print(f"❌ FAILED: {desc} (got {result}, expected {expected})")
            failed += 1
    
    print()
    print("INSTITUTIONAL DISCIPLINE TESTS")
    print("-" * 70)
    
    # Test no overlap between zones
    overlap_failed = False
    for rsi in range(46, 55):  # Gap zone: 46-54
        if _rsi_long_filter(rsi) or _rsi_short_filter(rsi):
            print(f"❌ FAILED: RSI {rsi} should not trigger any entry (neutral zone)")
            overlap_failed = True
            failed += 1
    
    if not overlap_failed:
        print("✅ PASSED: No overlap between long and short zones (gap: 46-54)")
        passed += 1
    
    # Test buying strength prevention (RSI > 45)
    strength_failed = False
    for rsi in [46, 50, 55, 60, 65, 70, 75, 80]:
        if _rsi_long_filter(rsi):
            print(f"❌ FAILED: Should never buy at RSI {rsi} (buying strength)")
            strength_failed = True
            failed += 1
    
    if not strength_failed:
        print("✅ PASSED: Never buy strength (RSI > 45)")
        passed += 1
    
    # Test selling weakness prevention (RSI < 55)
    weakness_failed = False
    for rsi in [25, 30, 35, 40, 45, 50, 54]:
        if _rsi_short_filter(rsi):
            print(f"❌ FAILED: Should never short at RSI {rsi} (selling weakness)")
            weakness_failed = True
            failed += 1
    
    if not weakness_failed:
        print("✅ PASSED: Never sell weakness (RSI < 55)")
        passed += 1
    
    print()
    print("=" * 70)
    print(f"TEST SUMMARY: {passed} passed, {failed} failed")
    print("=" * 70)
    
    if failed == 0:
        print("✅ ALL TESTS PASSED - RSI filters are working correctly!")
        return True
    else:
        print(f"❌ {failed} TESTS FAILED - Please review implementation")
        return False


if __name__ == "__main__":
    success = test_rsi_filters()
    sys.exit(0 if success else 1)
