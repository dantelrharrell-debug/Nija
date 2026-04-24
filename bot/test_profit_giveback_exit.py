#!/usr/bin/env python3
"""
Test profit giveback exit functionality
Ensures positions exit when giving back >0.5% of peak profit

Example: Peak 3% → Drops to 2.5% → Auto-exit to lock in 2.5%
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd
import numpy as np
from nija_trailing_system import NIJATrailingSystem


def create_sample_dataframe(current_price, num_rows=100):
    """Create a sample DataFrame for testing with realistic EMA"""
    # Create a price series that builds up to current_price
    # This ensures EMA-21 is below current price for long positions
    base_price = current_price * 0.95  # Start 5% below current
    data = {
        'close': [base_price + (current_price - base_price) * (i / num_rows) for i in range(num_rows)],
        'volume': [1000000] * num_rows,
    }
    df = pd.DataFrame(data)
    df['high'] = df['close'] * 1.005
    df['low'] = df['close'] * 0.995
    return df


def test_exit_on_half_percent_giveback():
    """Test that position exits when giving back >0.5% from peak"""
    print("Testing 0.5% giveback exit trigger...")

    system = NIJATrailingSystem()
    entry_price = 100.0

    # Open a long position
    position = system.open_position(
        position_id='test_long',
        side='long',
        entry_price=entry_price,
        size=1000.0,
        volatility=0.004
    )

    # Simulate price going up to +3% profit (peak)
    peak_price = entry_price * 1.03  # +3.0%
    df = create_sample_dataframe(peak_price)
    action, size, reason = system.manage_position(
        'test_long',
        current_price=peak_price,
        df=df,
        rsi=50,
        vwap=peak_price
    )
    print(f"   At peak (+3.0%): action={action}, reason={reason}")
    assert action == 'hold' or action == 'partial_close', "Should hold or take partial profit at peak"

    # Verify peak was tracked
    position = system.positions['test_long']
    assert 'peak_profit_pct' in position, "Peak profit should be tracked"
    print(f"   Peak profit tracked: {position['peak_profit_pct']:.2f}%")

    # Simulate price dropping to +2.4% (0.6% giveback from peak - should exit)
    exit_price = entry_price * 1.024  # +2.4%
    df = create_sample_dataframe(exit_price)
    action, size, reason = system.manage_position(
        'test_long',
        current_price=exit_price,
        df=df,
        rsi=50,
        vwap=exit_price
    )
    print(f"   At +2.4% (0.6% giveback): action={action}, reason={reason}")
    assert action == 'close_all', f"Should exit when giveback >0.5%, got action={action}"
    assert "Giveback" in reason, f"Reason should mention giveback, got: {reason}"
    print(f"✅ Exit triggered correctly at 0.6% giveback")


def test_no_exit_on_small_giveback():
    """Test that position does NOT exit when giveback is <=0.5%"""
    print("\nTesting no exit on <=0.5% giveback...")

    system = NIJATrailingSystem()
    entry_price = 100.0

    # Open a long position
    position = system.open_position(
        position_id='test_long2',
        side='long',
        entry_price=entry_price,
        size=1000.0,
        volatility=0.004
    )

    # Simulate price going up to +3% profit (peak)
    peak_price = entry_price * 1.03  # +3.0%
    df = create_sample_dataframe(peak_price)
    action, size, reason = system.manage_position(
        'test_long2',
        current_price=peak_price,
        df=df,
        rsi=50,
        vwap=peak_price
    )
    print(f"   At peak (+3.0%): action={action}")

    # Simulate price dropping to +2.6% (0.4% giveback - should NOT exit)
    no_exit_price = entry_price * 1.026  # +2.6%
    df = create_sample_dataframe(no_exit_price)
    action, size, reason = system.manage_position(
        'test_long2',
        current_price=no_exit_price,
        df=df,
        rsi=50,
        vwap=no_exit_price
    )
    print(f"   At +2.6% (0.4% giveback): action={action}, reason={reason}")
    assert action in ['hold', 'partial_close'], f"Should hold when giveback <=0.5%, got action={action}"
    print(f"✅ Position held correctly at 0.4% giveback")


def test_exact_half_percent_giveback():
    """Test that position exits at exactly 0.5% giveback (stop-loss triggers)"""
    print("\nTesting exact 0.5% giveback...")

    system = NIJATrailingSystem()
    entry_price = 100.0

    # Open a long position
    position = system.open_position(
        position_id='test_long3',
        side='long',
        entry_price=entry_price,
        size=1000.0,
        volatility=0.004
    )

    # Simulate price going up to +2% profit (peak)
    peak_price = entry_price * 1.02  # +2.0%
    df = create_sample_dataframe(peak_price)
    action, size, reason = system.manage_position(
        'test_long3',
        current_price=peak_price,
        df=df,
        rsi=50,
        vwap=peak_price
    )
    print(f"   At peak (+2.0%): action={action}")

    # Simulate price dropping to +1.51% (0.49% giveback - should NOT exit via giveback check)
    safe_price = entry_price * 1.0151  # +1.51%
    df = create_sample_dataframe(safe_price)
    action, size, reason = system.manage_position(
        'test_long3',
        current_price=safe_price,
        df=df,
        rsi=50,
        vwap=safe_price
    )
    print(f"   At +1.51% (0.49% giveback): action={action}, reason={reason}")
    # At 0.49%, should not exit via giveback
    assert action in ['hold', 'partial_close'], f"Should hold at 0.49% giveback, got action={action}"
    print(f"✅ Position held correctly at 0.49% giveback")

    # Now drop to +1.49% (0.51% giveback - should exit via giveback check)
    exit_price = entry_price * 1.0149  # +1.49% (0.51% giveback)
    df = create_sample_dataframe(exit_price)
    action, size, reason = system.manage_position(
        'test_long3',
        current_price=exit_price,
        df=df,
        rsi=50,
        vwap=exit_price
    )
    print(f"   At +1.49% (0.51% giveback): action={action}, reason={reason}")
    assert action == 'close_all', f"Should exit when giveback >0.5%, got action={action}"
    assert "Giveback" in reason or "Stop-loss" in reason, f"Should mention giveback or stop-loss, got: {reason}"
    print(f"✅ Exit triggered correctly at 0.51% giveback")


def test_short_position_giveback():
    """Test giveback logic works for short positions"""
    print("\nTesting short position giveback...")

    system = NIJATrailingSystem()
    entry_price = 100.0

    # Open a short position
    position = system.open_position(
        position_id='test_short',
        side='short',
        entry_price=entry_price,
        size=1000.0,
        volatility=0.004
    )

    # Simulate price going down to +3% profit (peak for short)
    peak_price = entry_price * 0.97  # -3% price = +3% profit on short
    df = create_sample_dataframe(peak_price)
    action, size, reason = system.manage_position(
        'test_short',
        current_price=peak_price,
        df=df,
        rsi=50,
        vwap=peak_price
    )
    print(f"   At peak (+3.0% profit on short): action={action}")

    # Simulate price rising to +2.4% profit (0.6% giveback - should exit)
    exit_price = entry_price * 0.976  # -2.4% price = +2.4% profit on short
    df = create_sample_dataframe(exit_price)
    action, size, reason = system.manage_position(
        'test_short',
        current_price=exit_price,
        df=df,
        rsi=50,
        vwap=exit_price
    )
    print(f"   At +2.4% profit (0.6% giveback): action={action}, reason={reason}")
    assert action == 'close_all', f"Should exit when giveback >0.5%, got action={action}"
    print(f"✅ Short position exit triggered correctly at 0.6% giveback")


def test_peak_updates_correctly():
    """Test that peak profit updates as position improves"""
    print("\nTesting peak profit updates...")

    system = NIJATrailingSystem()
    entry_price = 100.0

    # Open a long position
    position = system.open_position(
        position_id='test_peak',
        side='long',
        entry_price=entry_price,
        size=1000.0,
        volatility=0.004
    )

    # First peak at +1%
    price1 = entry_price * 1.01
    df1 = create_sample_dataframe(price1)
    system.manage_position('test_peak', price1, df1, 50, price1)
    assert abs(system.positions['test_peak']['peak_profit_pct'] - 1.0) < 0.01, "Peak should be ~1%"
    print(f"   Peak at +1.0%: {system.positions['test_peak']['peak_profit_pct']:.2f}%")

    # New peak at +2%
    price2 = entry_price * 1.02
    df2 = create_sample_dataframe(price2)
    system.manage_position('test_peak', price2, df2, 50, price2)
    assert abs(system.positions['test_peak']['peak_profit_pct'] - 2.0) < 0.01, "Peak should update to ~2%"
    print(f"   Peak updated to +2.0%: {system.positions['test_peak']['peak_profit_pct']:.2f}%")

    # New peak at +3%
    price3 = entry_price * 1.03
    df3 = create_sample_dataframe(price3)
    system.manage_position('test_peak', price3, df3, 50, price3)
    assert abs(system.positions['test_peak']['peak_profit_pct'] - 3.0) < 0.01, "Peak should update to ~3%"
    print(f"   Peak updated to +3.0%: {system.positions['test_peak']['peak_profit_pct']:.2f}%")

    # Price drops but peak should stay at 3%
    price4 = entry_price * 1.025
    df4 = create_sample_dataframe(price4)
    system.manage_position('test_peak', price4, df4, 50, price4)
    assert abs(system.positions['test_peak']['peak_profit_pct'] - 3.0) < 0.01, "Peak should remain at ~3%"
    print(f"   Peak remains at +3.0% when price drops: {system.positions['test_peak']['peak_profit_pct']:.2f}%")

    print(f"✅ Peak profit tracking works correctly")


if __name__ == '__main__':
    print("=" * 70)
    print("TESTING PROFIT GIVEBACK EXIT LOGIC")
    print("Requirement: Exit if price gives back >0.5% of peak profit")
    print("=" * 70)

    try:
        test_exit_on_half_percent_giveback()
        test_no_exit_on_small_giveback()
        test_exact_half_percent_giveback()
        test_short_position_giveback()
        test_peak_updates_correctly()

        print("\n" + "=" * 70)
        print("✅ ALL TESTS PASSED")
        print("=" * 70)

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
