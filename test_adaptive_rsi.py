#!/usr/bin/env python3
"""
Test Adaptive RSI Ranges (MAX ALPHA UPGRADE)

This test validates that the adaptive RSI system correctly adjusts entry ranges
based on market regime and trend strength.

Tests:
1. Regime-based RSI range selection
2. ADX-based fine-tuning
3. Range validation (no overlap, minimum widths)
4. Fallback to static ranges
"""

import sys
import os

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

def test_regime_rsi_ranges():
    """Test that each regime has correct RSI ranges"""
    print("=" * 70)
    print("TEST 1: Regime-Based RSI Range Selection")
    print("=" * 70)

    try:
        from market_regime_detector import RegimeDetector, MarketRegime

        detector = RegimeDetector()

        # Test TRENDING regime (tight ranges for high conviction)
        print("\n📊 Test: TRENDING Regime (ADX ≥ 25)")
        ranges = detector.get_adaptive_rsi_ranges(MarketRegime.TRENDING)

        print(f"   Long: RSI {ranges['long_min']:.0f}-{ranges['long_max']:.0f}")
        print(f"   Short: RSI {ranges['short_min']:.0f}-{ranges['short_max']:.0f}")
        print(f"   Neutral Zone: {ranges['long_max']:.0f}-{ranges['short_min']:.0f}")

        # Validate trending ranges
        assert ranges['long_min'] == 25, f"Trending long_min should be 25, got {ranges['long_min']}"
        assert ranges['long_max'] == 45, f"Trending long_max should be 45, got {ranges['long_max']}"
        assert ranges['short_min'] == 55, f"Trending short_min should be 55, got {ranges['short_min']}"
        assert ranges['short_max'] == 75, f"Trending short_max should be 75, got {ranges['short_max']}"
        print("   ✅ TRENDING ranges correct (25-45 long, 55-75 short)")

        # Test RANGING regime (wider ranges for more opportunities)
        print("\n📊 Test: RANGING Regime (ADX < 20, low volatility)")
        ranges = detector.get_adaptive_rsi_ranges(MarketRegime.RANGING)

        print(f"   Long: RSI {ranges['long_min']:.0f}-{ranges['long_max']:.0f}")
        print(f"   Short: RSI {ranges['short_min']:.0f}-{ranges['short_max']:.0f}")
        print(f"   Neutral Zone: {ranges['long_max']:.0f}-{ranges['short_min']:.0f}")

        # Validate ranging ranges
        assert ranges['long_min'] == 20, f"Ranging long_min should be 20, got {ranges['long_min']}"
        assert ranges['long_max'] == 50, f"Ranging long_max should be 50, got {ranges['long_max']}"
        assert ranges['short_min'] == 50, f"Ranging short_min should be 50, got {ranges['short_min']}"
        assert ranges['short_max'] == 80, f"Ranging short_max should be 80, got {ranges['short_max']}"
        print("   ✅ RANGING ranges correct (20-50 long, 50-80 short)")

        # Test VOLATILE regime (conservative ranges to avoid whipsaws)
        print("\n📊 Test: VOLATILE Regime (ADX 20-25, high ATR)")
        ranges = detector.get_adaptive_rsi_ranges(MarketRegime.VOLATILE)

        print(f"   Long: RSI {ranges['long_min']:.0f}-{ranges['long_max']:.0f}")
        print(f"   Short: RSI {ranges['short_min']:.0f}-{ranges['short_max']:.0f}")
        print(f"   Neutral Zone: {ranges['long_max']:.0f}-{ranges['short_min']:.0f}")

        # Validate volatile ranges
        assert ranges['long_min'] == 30, f"Volatile long_min should be 30, got {ranges['long_min']}"
        assert ranges['long_max'] == 40, f"Volatile long_max should be 40, got {ranges['long_max']}"
        assert ranges['short_min'] == 60, f"Volatile short_min should be 60, got {ranges['short_min']}"
        assert ranges['short_max'] == 70, f"Volatile short_max should be 70, got {ranges['short_max']}"
        print("   ✅ VOLATILE ranges correct (30-40 long, 60-70 short)")

        return True

    except ImportError as e:
        print(f"⚠️  Could not import regime detector: {e}")
        return None


def test_adx_fine_tuning():
    """Test that ADX fine-tunes RSI ranges in trending markets"""
    print("\n" + "=" * 70)
    print("TEST 2: ADX-Based Fine-Tuning")
    print("=" * 70)

    try:
        from market_regime_detector import RegimeDetector, MarketRegime

        detector = RegimeDetector()

        # Test base trending ranges (no ADX)
        print("\n📊 Test: TRENDING without ADX fine-tuning")
        ranges_base = detector.get_adaptive_rsi_ranges(MarketRegime.TRENDING)
        print(f"   Long: RSI {ranges_base['long_min']:.0f}-{ranges_base['long_max']:.0f}")
        print(f"   Short: RSI {ranges_base['short_min']:.0f}-{ranges_base['short_max']:.0f}")

        # Test with strong trend (ADX 30-35)
        print("\n📊 Test: TRENDING with strong trend (ADX 32)")
        ranges_strong = detector.get_adaptive_rsi_ranges(MarketRegime.TRENDING, adx=32)
        print(f"   Long: RSI {ranges_strong['long_min']:.0f}-{ranges_strong['long_max']:.0f}")
        print(f"   Short: RSI {ranges_strong['short_min']:.0f}-{ranges_strong['short_max']:.0f}")

        # Should be slightly tighter
        assert ranges_strong['long_max'] < ranges_base['long_max'], "Strong trend should tighten long_max"
        assert ranges_strong['short_min'] > ranges_base['short_min'], "Strong trend should tighten short_min"
        print(f"   ✅ Strong trend tightened ranges (ADX 32)")

        # Test with very strong trend (ADX ≥ 35)
        print("\n📊 Test: TRENDING with very strong trend (ADX 40)")
        ranges_very_strong = detector.get_adaptive_rsi_ranges(MarketRegime.TRENDING, adx=40)
        print(f"   Long: RSI {ranges_very_strong['long_min']:.0f}-{ranges_very_strong['long_max']:.0f}")
        print(f"   Short: RSI {ranges_very_strong['short_min']:.0f}-{ranges_very_strong['short_max']:.0f}")

        # Should be even tighter
        assert ranges_very_strong['long_max'] <= ranges_strong['long_max'], "Very strong trend should be tighter or equal"
        assert ranges_very_strong['short_min'] >= ranges_strong['short_min'], "Very strong trend should be tighter or equal"
        print(f"   ✅ Very strong trend tightened ranges even more (ADX 40)")

        # Test with weak trend (ADX < 30, no adjustment)
        print("\n📊 Test: TRENDING with weak trend (ADX 26)")
        ranges_weak = detector.get_adaptive_rsi_ranges(MarketRegime.TRENDING, adx=26)
        print(f"   Long: RSI {ranges_weak['long_min']:.0f}-{ranges_weak['long_max']:.0f}")
        print(f"   Short: RSI {ranges_weak['short_min']:.0f}-{ranges_weak['short_max']:.0f}")

        # Should match base (no adjustment for ADX < 30)
        assert ranges_weak['long_max'] == ranges_base['long_max'], "Weak trend should not adjust"
        assert ranges_weak['short_min'] == ranges_base['short_min'], "Weak trend should not adjust"
        print(f"   ✅ Weak trend kept base ranges (ADX 26, no adjustment)")

        return True

    except ImportError as e:
        print(f"⚠️  Could not import regime detector: {e}")
        return None


def test_range_validation():
    """Test that RSI ranges are always valid (no overlap, minimum widths)"""
    print("\n" + "=" * 70)
    print("TEST 3: Range Validation (No Overlap, Minimum Widths)")
    print("=" * 70)

    try:
        from market_regime_detector import RegimeDetector, MarketRegime

        detector = RegimeDetector()

        test_cases = [
            (MarketRegime.TRENDING, None, "TRENDING (base)"),
            (MarketRegime.TRENDING, 35, "TRENDING (ADX 35)"),
            (MarketRegime.RANGING, None, "RANGING"),
            (MarketRegime.VOLATILE, None, "VOLATILE"),
        ]

        all_valid = True

        for regime, adx, description in test_cases:
            print(f"\n📊 Test: {description}")
            ranges = detector.get_adaptive_rsi_ranges(regime, adx)

            long_width = ranges['long_max'] - ranges['long_min']
            short_width = ranges['short_max'] - ranges['short_min']
            neutral_gap = ranges['short_min'] - ranges['long_max']

            print(f"   Long width: {long_width:.0f} points")
            print(f"   Short width: {short_width:.0f} points")
            print(f"   Neutral gap: {neutral_gap:.0f} points")

            # Validate minimum widths
            if long_width < 10:
                print(f"   ❌ Long range too narrow ({long_width:.0f} < 10)")
                all_valid = False
            else:
                print(f"   ✅ Long range has minimum width (≥10)")

            if short_width < 10:
                print(f"   ❌ Short range too narrow ({short_width:.0f} < 10)")
                all_valid = False
            else:
                print(f"   ✅ Short range has minimum width (≥10)")

            # Validate no overlap (minimum 5-point gap)
            if neutral_gap < 5:
                print(f"   ❌ Ranges overlap or gap too small ({neutral_gap:.0f} < 5)")
                all_valid = False
            else:
                print(f"   ✅ Neutral zone exists (≥5 point gap)")

            # Validate bounds
            if ranges['long_min'] < 0 or ranges['short_max'] > 100:
                print(f"   ❌ RSI values out of 0-100 range")
                all_valid = False
            else:
                print(f"   ✅ RSI values within 0-100 range")

        return all_valid

    except ImportError as e:
        print(f"⚠️  Could not import regime detector: {e}")
        return None


def test_strategy_integration():
    """Test that strategy correctly uses adaptive RSI ranges"""
    print("\n" + "=" * 70)
    print("TEST 4: Strategy Integration")
    print("=" * 70)

    print("\n📊 Test: Check that v71 and v72 have adaptive RSI enabled")

    # This is more of a code structure test
    # In practice, the strategies would be tested with actual market data

    try:
        # Check v71
        with open('bot/nija_apex_strategy_v71.py', 'r') as f:
            v71_content = f.read()

        has_adaptive = 'get_adaptive_rsi_ranges' in v71_content
        has_fallback = 'Fallback to institutional grade' in v71_content

        if has_adaptive and has_fallback:
            print("   ✅ V71: Adaptive RSI integrated with fallback")
        else:
            print(f"   ❌ V71: Missing adaptive RSI ({has_adaptive}) or fallback ({has_fallback})")
            return False

        # Check v72
        with open('bot/nija_apex_strategy_v72_upgrade.py', 'r') as f:
            v72_content = f.read()

        has_adaptive = 'get_adaptive_rsi_ranges' in v72_content
        has_fallback = 'Fallback to institutional grade' in v72_content
        has_update_regime = 'update_regime' in v72_content

        if has_adaptive and has_fallback and has_update_regime:
            print("   ✅ V72: Adaptive RSI integrated with fallback and regime updates")
        else:
            print(f"   ❌ V72: Missing components (adaptive:{has_adaptive}, fallback:{has_fallback}, update:{has_update_regime})")
            return False

        return True

    except Exception as e:
        print(f"⚠️  Could not check strategy files: {e}")
        return None


def main():
    """Run all tests"""
    print("\n" + "=" * 70)
    print("ADAPTIVE RSI TEST SUITE (MAX ALPHA UPGRADE)")
    print("=" * 70)
    print("Testing adaptive RSI range functionality...")
    print()

    results = []

    # Run tests
    results.append(("Regime RSI Ranges", test_regime_rsi_ranges()))
    results.append(("ADX Fine-Tuning", test_adx_fine_tuning()))
    results.append(("Range Validation", test_range_validation()))
    results.append(("Strategy Integration", test_strategy_integration()))

    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    passed = 0
    failed = 0
    skipped = 0

    for test_name, result in results:
        if result is True:
            print(f"✅ {test_name}: PASSED")
            passed += 1
        elif result is False:
            print(f"❌ {test_name}: FAILED")
            failed += 1
        else:
            print(f"⚠️  {test_name}: SKIPPED")
            skipped += 1

    print("\n" + "=" * 70)
    print(f"Total: {passed} passed, {failed} failed, {skipped} skipped")
    print("=" * 70)

    if failed > 0:
        print("\n🚨 SOME TESTS FAILED!")
        print("Adaptive RSI has issues that need to be fixed.")
        return 1
    elif passed == len(results):
        print("\n✅ ALL TESTS PASSED")
        print("Adaptive RSI is working correctly!")
        print("\n📈 BENEFITS:")
        print("• TRENDING: Tight ranges (25-45 long, 55-75 short) for high conviction")
        print("• RANGING: Wide ranges (20-50 long, 50-80 short) for more opportunities")
        print("• VOLATILE: Conservative ranges (30-40 long, 60-70 short) to avoid whipsaws")
        print("• ADX Fine-Tuning: Even tighter in very strong trends")
        return 0
    else:
        print("\n⚠️  SOME TESTS SKIPPED")
        print("Could not fully validate adaptive RSI.")
        return 2


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
