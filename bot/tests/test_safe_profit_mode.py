#!/usr/bin/env python3
"""
Tests for the Safe Profit Mode feature.

Verifies:
1. SafeProfitModeManager activates when daily target is reached.
2. SafeProfitModeManager activates when the lock-fraction threshold is crossed.
3. New-day reset correctly deactivates the mode.
4. NIJAApexStrategyV71 blocks new entries when safe profit mode is active.
5. NIJAApexStrategyV71 updates safe profit mode after a successful exit.
"""

import sys
import os

_BOT_DIR   = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_BOT_DIR)
for _p in (_BOT_DIR, _REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import threading
from unittest.mock import MagicMock, patch
import pandas as pd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_manager(target_pct=1.0, lock_fraction=0.50):
    """Return a new SafeProfitModeManager with state file patched to /tmp."""
    from safe_profit_mode import SafeProfitModeManager
    mgr = SafeProfitModeManager.__new__(SafeProfitModeManager)
    mgr._lock                  = threading.Lock()
    mgr.target_pct_threshold   = target_pct
    mgr.lock_fraction_threshold = lock_fraction
    from pathlib import Path
    mgr.DATA_DIR   = Path("/tmp/nija_test_spm")
    mgr.STATE_FILE = mgr.DATA_DIR / "safe_profit_mode_state.json"
    mgr.DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Initialise runtime fields without loading stale state
    from datetime import date
    mgr._today             = str(date.today())
    mgr._daily_profit_usd  = 0.0
    mgr._daily_target_usd  = 0.0
    mgr._locked_profit_usd = 0.0
    from safe_profit_mode import SafeMode
    mgr._mode              = SafeMode.INACTIVE
    mgr._activated_at      = None
    mgr._trades_blocked    = 0
    return mgr


def _make_df(close_prices):
    """Create a minimal OHLCV DataFrame the strategy can work with."""
    n = len(close_prices)
    return pd.DataFrame({
        'open':   close_prices,
        'high':   [p * 1.002 for p in close_prices],
        'low':    [p * 0.998 for p in close_prices],
        'close':  close_prices,
        'volume': [1_000_000] * n,
    })


def _build_strategy():
    """Instantiate NIJAApexStrategyV71 with optional modules disabled."""
    from nija_apex_strategy_v71 import NIJAApexStrategyV71
    cfg = {
        'use_enhanced_scoring':    False,
        'use_regime_detection':    False,
        'enable_stepped_exits':    True,
        'stepped_exits': {
            0.025: 0.15,
            0.030: 0.25,
            0.040: 0.35,
            0.065: 0.50,
        },
        'use_ai_intelligence_hub': False,
        'enable_profit_stack':     True,
        'enable_safe_profit_mode': True,
        'daily_profit_target_pct': 0.01,  # 1 % of balance
    }
    return NIJAApexStrategyV71(broker_client=None, config=cfg)


# ---------------------------------------------------------------------------
# Unit tests for SafeProfitModeManager
# ---------------------------------------------------------------------------

def test_inactive_by_default():
    """Mode starts INACTIVE; entries should not be blocked."""
    mgr = _fresh_manager()
    assert not mgr.should_block_entry(), "Mode should be INACTIVE at start"
    assert not mgr.is_active()
    print("✅ Mode is INACTIVE by default")


def test_activates_on_target_reached():
    """Mode activates when daily profit ≥ target (100% of target)."""
    mgr = _fresh_manager(target_pct=1.0)
    just_activated = mgr.update(
        daily_profit_usd=200.0,
        daily_target_usd=200.0,
        locked_profit_usd=0.0,
    )
    assert just_activated, "Should have just activated"
    assert mgr.should_block_entry(), "Entries should be blocked after target reached"
    print("✅ Activates when daily target is reached")


def test_activates_on_lock_fraction():
    """Mode activates when locked fraction ≥ threshold (50%)."""
    mgr = _fresh_manager(lock_fraction=0.50)
    just_activated = mgr.update(
        daily_profit_usd=100.0,
        daily_target_usd=500.0,   # target not reached
        locked_profit_usd=50.0,   # exactly 50% locked
    )
    assert just_activated, "Should have just activated (50% locked)"
    assert mgr.should_block_entry()
    print("✅ Activates when lock fraction threshold is crossed")


def test_not_activated_below_thresholds():
    """Mode stays INACTIVE when neither threshold is crossed."""
    mgr = _fresh_manager(target_pct=1.0, lock_fraction=0.50)
    just_activated = mgr.update(
        daily_profit_usd=80.0,
        daily_target_usd=200.0,    # 40% of target — not enough
        locked_profit_usd=30.0,    # 37.5% locked — not enough
    )
    assert not just_activated
    assert not mgr.should_block_entry()
    print("✅ Stays INACTIVE below thresholds")


def test_does_not_reactivate_once_active():
    """Calling update() again while already ACTIVE returns False (no double-fire)."""
    mgr = _fresh_manager()
    mgr.update(daily_profit_usd=200.0, daily_target_usd=200.0, locked_profit_usd=0.0)
    assert mgr.is_active()
    again = mgr.update(daily_profit_usd=250.0, daily_target_usd=200.0, locked_profit_usd=0.0)
    assert not again, "Should return False when already active"
    print("✅ Does not double-fire activation")


def test_no_profit_does_not_activate():
    """Mode should not activate when daily profit is zero or negative."""
    mgr = _fresh_manager()
    mgr.update(daily_profit_usd=0.0, daily_target_usd=200.0, locked_profit_usd=0.0)
    assert not mgr.is_active()
    mgr.update(daily_profit_usd=-50.0, daily_target_usd=200.0, locked_profit_usd=0.0)
    assert not mgr.is_active()
    print("✅ Does not activate on zero/negative profit")


def test_get_state_fields():
    """get_state() returns a SafeProfitState with all expected fields."""
    mgr = _fresh_manager()
    mgr.update(daily_profit_usd=150.0, daily_target_usd=200.0, locked_profit_usd=60.0)
    s = mgr.get_state()
    assert s.daily_profit_usd  == 150.0
    assert s.daily_target_usd  == 200.0
    assert s.locked_profit_usd == 60.0
    assert abs(s.lock_fraction - 0.40) < 1e-6, f"Expected 0.40, got {s.lock_fraction}"
    print(f"✅ get_state() fields correct (lock_fraction={s.lock_fraction:.2f})")


def test_block_reason_contains_amounts():
    """get_block_reason() should mention dollar amounts."""
    mgr = _fresh_manager()
    mgr.update(daily_profit_usd=200.0, daily_target_usd=200.0, locked_profit_usd=0.0)
    reason = mgr.get_block_reason()
    assert "$" in reason, "Block reason should contain '$'"
    assert "Safe Profit Mode" in reason
    print(f"✅ Block reason: {reason[:80]}…")


def test_record_blocked_attempt_increments():
    """record_blocked_attempt() increments the trades_blocked counter."""
    mgr = _fresh_manager()
    mgr.update(daily_profit_usd=200.0, daily_target_usd=200.0, locked_profit_usd=0.0)
    mgr.record_blocked_attempt()
    mgr.record_blocked_attempt()
    assert mgr.get_state().trades_blocked == 2
    print("✅ Blocked-attempt counter increments correctly")


def test_get_report_runs_without_error():
    """get_report() should return a non-empty string."""
    mgr = _fresh_manager()
    mgr.update(daily_profit_usd=120.0, daily_target_usd=200.0, locked_profit_usd=70.0)
    report = mgr.get_report()
    assert isinstance(report, str) and len(report) > 0
    assert "SAFE PROFIT MODE" in report.upper()
    print("✅ get_report() returns a valid report")


# ---------------------------------------------------------------------------
# Integration tests with NIJAApexStrategyV71
# ---------------------------------------------------------------------------

def test_strategy_has_safe_profit_mode_attribute():
    """Strategy should expose the safe_profit_mode attribute."""
    strategy = _build_strategy()
    assert hasattr(strategy, 'safe_profit_mode'), "Missing safe_profit_mode attribute"
    print(f"✅ safe_profit_mode attribute present (type={type(strategy.safe_profit_mode).__name__})")


def test_strategy_blocks_entry_when_safe_mode_active():
    """
    analyze_market() should return action='hold' with a safe-profit-mode reason
    when the safe profit mode is active.
    """
    strategy = _build_strategy()
    if strategy.safe_profit_mode is None:
        print("⚠️  Safe profit mode not available – skipping")
        return

    # Replace with a fresh manager to avoid singleton state pollution
    strategy.safe_profit_mode = _fresh_manager()

    # Force activate the safe profit mode
    strategy.safe_profit_mode.update(
        daily_profit_usd=200.0,
        daily_target_usd=100.0,   # profit > target → activate
        locked_profit_usd=0.0,
    )
    assert strategy.safe_profit_mode.is_active()

    # No existing position
    strategy.execution_engine.get_position = MagicMock(return_value=None)

    prices = [100.0 + i * 0.05 for i in range(200)]
    df = _make_df(prices)

    result = strategy.analyze_market(df, 'BTC-USD', account_balance=10_000.0)
    assert result['action'] == 'hold', f"Expected 'hold', got '{result['action']}'"
    assert 'safe profit' in result['reason'].lower() or 'locked' in result['reason'].lower(), \
        f"Reason should mention safe profit, got: {result['reason']}"
    print(f"✅ Entry blocked when safe profit mode active: {result['reason'][:80]}")


def test_strategy_allows_entry_when_safe_mode_inactive():
    """
    When safe profit mode is INACTIVE, analyze_market() should NOT block for
    that reason (other filters may still apply).
    """
    strategy = _build_strategy()
    if strategy.safe_profit_mode is None:
        print("⚠️  Safe profit mode not available – skipping")
        return

    # Replace with a fresh manager to avoid singleton state pollution
    strategy.safe_profit_mode = _fresh_manager()

    # Ensure mode is inactive (fresh state)
    assert not strategy.safe_profit_mode.is_active()

    # No existing position; mock get_position to return None
    strategy.execution_engine.get_position = MagicMock(return_value=None)

    prices = [100.0 + i * 0.05 for i in range(200)]
    df = _make_df(prices)

    result = strategy.analyze_market(df, 'ETH-USD', account_balance=10_000.0)
    # Result may be 'hold' for market-filter reasons, but NOT because of safe profit mode
    if result['action'] == 'hold':
        reason = result.get('reason', '')
        assert 'safe profit' not in reason.lower(), \
            f"Should not block for safe profit mode when inactive, got: {reason}"
    print(f"✅ Safe profit mode does not interfere when inactive (result={result['action']})")


def test_update_safe_profit_mode_after_exit():
    """
    execute_action('exit') should call _update_safe_profit_mode and potentially
    activate safe profit mode when the accumulated P&L crosses the target.
    """
    strategy = _build_strategy()
    if strategy.safe_profit_mode is None:
        print("⚠️  Safe profit mode not available – skipping")
        return

    # Replace with a fresh manager to avoid singleton state pollution
    strategy.safe_profit_mode = _fresh_manager()

    # Set a tiny daily target so the first trade triggers activation
    strategy._last_daily_target_usd = 10.0   # $10 target
    strategy._daily_pnl_usd = 0.0

    strategy.execution_engine.execute_exit = MagicMock(return_value=True)

    action_data = {
        'action': 'exit',
        'position': {
            'entry_price': 100.0,
            'position_size': 500.0,
            'side': 'long',
        },
        'current_price': 105.0,   # +5 % → large profit
        'reason': 'Test exit',
    }

    result = strategy.execute_action(action_data, 'BTC-USD')
    assert result is True

    # Daily P&L should be positive
    assert strategy._daily_pnl_usd > 0, \
        f"Daily P&L should be > 0 after profitable exit, got {strategy._daily_pnl_usd}"

    # Safe profit mode should be active (profit well exceeds $10 target)
    assert strategy.safe_profit_mode.is_active(), \
        "Safe profit mode should be ACTIVE after P&L exceeds daily target"
    print(f"✅ Safe profit mode activated after exit (daily_pnl=${strategy._daily_pnl_usd:.2f})")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    print("=" * 70)
    print("SAFE PROFIT MODE TESTS")
    print("=" * 70)

    tests = [
        test_inactive_by_default,
        test_activates_on_target_reached,
        test_activates_on_lock_fraction,
        test_not_activated_below_thresholds,
        test_does_not_reactivate_once_active,
        test_no_profit_does_not_activate,
        test_get_state_fields,
        test_block_reason_contains_amounts,
        test_record_blocked_attempt_increments,
        test_get_report_runs_without_error,
        test_strategy_has_safe_profit_mode_attribute,
        test_strategy_blocks_entry_when_safe_mode_active,
        test_strategy_allows_entry_when_safe_mode_inactive,
        test_update_safe_profit_mode_after_exit,
    ]

    passed = 0
    failed = 0
    for t in tests:
        print(f"\n▶ {t.__name__}")
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"  ❌ FAILED: {e}")
            failed += 1
        except Exception as e:
            import traceback
            print(f"  ❌ ERROR: {e}")
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 70)
    if failed == 0:
        print(f"✅ ALL {passed} TESTS PASSED")
    else:
        print(f"❌ {failed} FAILED / {passed} PASSED")
    print("=" * 70)

    sys.exit(0 if failed == 0 else 1)
