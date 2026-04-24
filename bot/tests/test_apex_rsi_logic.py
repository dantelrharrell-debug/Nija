"""
✅ Institutional-Grade RSI Entry Validation Tests

These tests permanently prevent regression into buy-high / sell-low logic.

Purpose:
- Ensure long entries only occur in oversold zones (RSI 25-45)
- Ensure short entries only occur in overbought zones (RSI 55-75)
- Prevent buying strength (RSI > 45)
- Prevent selling weakness (RSI < 55)

Author: NIJA Trading Systems
Date: January 2026
"""

import pytest
import sys
sys.path.insert(0, '.')

from bot.nija_apex_strategy_v71 import NIJAApexStrategyV71


@pytest.fixture
def strategy():
    """Initialize strategy instance for testing"""
    return NIJAApexStrategyV71()


# ============================
# LONG ENTRY RSI TESTS
# ============================

def test_long_entry_rsi_35_true(strategy):
    """RSI 35 → TRUE (optimal long zone: 25-45)"""
    assert strategy._rsi_long_filter(35) is True


def test_long_entry_rsi_48_false(strategy):
    """RSI 48 → FALSE (too high, avoid buying high)"""
    assert strategy._rsi_long_filter(48) is False


def test_long_entry_rsi_55_false(strategy):
    """RSI 55 → FALSE (overbought)"""
    assert strategy._rsi_long_filter(55) is False


def test_long_entry_rsi_65_false(strategy):
    """RSI 65 → FALSE (extreme overbought)"""
    assert strategy._rsi_long_filter(65) is False


# ============================
# SHORT ENTRY RSI TESTS
# ============================

def test_short_entry_rsi_65_true(strategy):
    """RSI 65 → TRUE (optimal short zone: 55-75)"""
    assert strategy._rsi_short_filter(65) is True


def test_short_entry_rsi_58_true(strategy):
    """RSI 58 → TRUE (valid short entry zone)"""
    assert strategy._rsi_short_filter(58) is True


def test_short_entry_rsi_45_false(strategy):
    """RSI 45 → FALSE (too low, avoid selling low)"""
    assert strategy._rsi_short_filter(45) is False


def test_short_entry_rsi_35_false(strategy):
    """RSI 35 → FALSE (deep oversold, never short)"""
    assert strategy._rsi_short_filter(35) is False


# ============================
# BOUNDARY CONDITION TESTS
# ============================

def test_long_entry_rsi_25_boundary_true(strategy):
    """RSI 25 → TRUE (lower boundary of long zone)"""
    assert strategy._rsi_long_filter(25) is True


def test_long_entry_rsi_45_boundary_true(strategy):
    """RSI 45 → TRUE (upper boundary of long zone)"""
    assert strategy._rsi_long_filter(45) is True


def test_long_entry_rsi_24_boundary_false(strategy):
    """RSI 24 → FALSE (just below lower boundary)"""
    assert strategy._rsi_long_filter(24) is False


def test_long_entry_rsi_46_boundary_false(strategy):
    """RSI 46 → FALSE (just above upper boundary)"""
    assert strategy._rsi_long_filter(46) is False


def test_short_entry_rsi_55_boundary_true(strategy):
    """RSI 55 → TRUE (lower boundary of short zone)"""
    assert strategy._rsi_short_filter(55) is True


def test_short_entry_rsi_75_boundary_true(strategy):
    """RSI 75 → TRUE (upper boundary of short zone)"""
    assert strategy._rsi_short_filter(75) is True


def test_short_entry_rsi_54_boundary_false(strategy):
    """RSI 54 → FALSE (just below lower boundary)"""
    assert strategy._rsi_short_filter(54) is False


def test_short_entry_rsi_76_boundary_false(strategy):
    """RSI 76 → FALSE (just above upper boundary)"""
    assert strategy._rsi_short_filter(76) is False


# ============================
# EXTREME CONDITION TESTS
# ============================

def test_long_entry_rsi_0_extreme_false(strategy):
    """RSI 0 → FALSE (extreme oversold, too risky)"""
    assert strategy._rsi_long_filter(0) is False


def test_long_entry_rsi_100_extreme_false(strategy):
    """RSI 100 → FALSE (extreme overbought)"""
    assert strategy._rsi_long_filter(100) is False


def test_short_entry_rsi_0_extreme_false(strategy):
    """RSI 0 → FALSE (extreme oversold)"""
    assert strategy._rsi_short_filter(0) is False


def test_short_entry_rsi_100_extreme_false(strategy):
    """RSI 100 → FALSE (extreme overbought, too risky)"""
    assert strategy._rsi_short_filter(100) is False


# ============================
# INPUT VALIDATION TESTS
# ============================

def test_long_entry_rsi_negative_invalid(strategy):
    """RSI -10 → FALSE (invalid negative value)"""
    assert strategy._rsi_long_filter(-10) is False


def test_short_entry_rsi_negative_invalid(strategy):
    """RSI -10 → FALSE (invalid negative value)"""
    assert strategy._rsi_short_filter(-10) is False


def test_long_entry_rsi_over_100_invalid(strategy):
    """RSI 150 → FALSE (invalid value > 100)"""
    assert strategy._rsi_long_filter(150) is False


def test_short_entry_rsi_over_100_invalid(strategy):
    """RSI 150 → FALSE (invalid value > 100)"""
    assert strategy._rsi_short_filter(150) is False


def test_long_entry_rsi_nan_invalid(strategy):
    """RSI NaN → FALSE (invalid value)"""
    import numpy as np
    assert strategy._rsi_long_filter(np.nan) is False


def test_short_entry_rsi_nan_invalid(strategy):
    """RSI NaN → FALSE (invalid value)"""
    import numpy as np
    assert strategy._rsi_short_filter(np.nan) is False


def test_long_entry_rsi_inf_invalid(strategy):
    """RSI infinity → FALSE (invalid value)"""
    import numpy as np
    assert strategy._rsi_long_filter(np.inf) is False


def test_short_entry_rsi_inf_invalid(strategy):
    """RSI infinity → FALSE (invalid value)"""
    import numpy as np
    assert strategy._rsi_short_filter(np.inf) is False


# ============================
# INTEGRATION VERIFICATION
# ============================

def test_no_overlap_between_long_and_short_zones(strategy):
    """Verify long and short zones don't overlap (prevents conflicting signals)"""
    # Long zone: 25-45
    # Short zone: 55-75
    # Gap: 46-54 (neutral zone)

    # Test the gap zone - should reject both long and short
    for rsi in [46, 47, 48, 49, 50, 51, 52, 53, 54]:
        assert strategy._rsi_long_filter(rsi) is False, f"RSI {rsi} should not trigger long entry"
        assert strategy._rsi_short_filter(rsi) is False, f"RSI {rsi} should not trigger short entry"


def test_institutional_discipline_enforcement(strategy):
    """
    Verify institutional trading discipline:
    - Never buy strength (RSI > 45)
    - Never sell weakness (RSI < 55)
    """
    # Test buying strength prevention
    strength_zone = [46, 50, 55, 60, 65, 70, 75, 80, 85, 90]
    for rsi in strength_zone:
        assert strategy._rsi_long_filter(rsi) is False, f"Should never buy at RSI {rsi} (buying strength)"

    # Test selling weakness prevention
    weakness_zone = [25, 30, 35, 40, 45, 50, 54]
    for rsi in weakness_zone:
        assert strategy._rsi_short_filter(rsi) is False, f"Should never short at RSI {rsi} (selling weakness)"
