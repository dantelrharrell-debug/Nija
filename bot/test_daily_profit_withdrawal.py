#!/usr/bin/env python3
"""
Tests for the NIJA Daily Profit Withdrawal Lock.

Covers:
1. No withdrawal below threshold.
2. Withdrawal triggered when daily profit exceeds threshold.
3. Ratchet prevents double-counting same profits.
4. Multiple profits accumulate correctly.
5. Loss records are ignored (not subtracted from daily profit).
6. End-of-day sweep triggers a final withdrawal then resets daily counters.
7. DailyWithdrawalConfig validation rejects bad parameters.
8. ProfitLockSystem wires DailyProfitWithdrawalEngine and records profits.
9. force_withdrawal manually triggers payout when eligible.
10. get_daily_summary returns accurate fields.
"""

import sys
import os
import threading
import tempfile
from pathlib import Path

_BOT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_BOT_DIR)
for _p in (_BOT_DIR, _REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from daily_profit_withdrawal import (
    DailyWithdrawalConfig,
    DailyProfitWithdrawalEngine,
    get_daily_profit_withdrawal_engine,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _engine(
    min_daily_profit_usd: float = 100.0,
    withdrawal_fraction: float = 0.30,
    min_withdrawal_usd: float = 5.0,
    end_of_day_sweep: bool = True,
) -> DailyProfitWithdrawalEngine:
    """Create a fresh isolated engine instance for each test (no shared disk state)."""
    cfg = DailyWithdrawalConfig(
        min_daily_profit_usd=min_daily_profit_usd,
        withdrawal_fraction=withdrawal_fraction,
        min_withdrawal_usd=min_withdrawal_usd,
        end_of_day_sweep=end_of_day_sweep,
    )
    # Each test gets its own temp directory so state files don't cross-contaminate.
    tmpdir = Path(tempfile.mkdtemp())
    return DailyProfitWithdrawalEngine(config=cfg, data_dir=tmpdir)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_no_withdrawal_below_threshold():
    """No withdrawal when daily profit is below min_daily_profit_usd."""
    engine = _engine(min_daily_profit_usd=100.0)
    engine.record_profit("BTC-USD", pnl_usd=80.0)

    summary = engine.get_daily_summary()
    assert summary["daily_profit_usd"] == 80.0
    assert summary["daily_withdrawn_usd"] == 0.0
    assert summary["withdrawals_today_count"] == 0
    print("✅ No withdrawal below threshold")


def test_withdrawal_triggered_above_threshold():
    """A withdrawal is made once profits exceed the threshold."""
    engine = _engine(min_daily_profit_usd=100.0, withdrawal_fraction=0.30)
    engine.record_profit("BTC-USD", pnl_usd=150.0)

    # Withdrawable base = 150 - 100 = 50; withdrawal = 50 * 0.30 = 15
    summary = engine.get_daily_summary()
    assert summary["daily_profit_usd"] == 150.0
    expected_withdrawal = (150.0 - 100.0) * 0.30
    assert abs(summary["daily_withdrawn_usd"] - expected_withdrawal) < 0.01
    assert summary["withdrawals_today_count"] == 1
    print(f"✅ Withdrawal triggered: ${summary['daily_withdrawn_usd']:.2f} (expected ${expected_withdrawal:.2f})")


def test_ratchet_no_double_withdraw():
    """The ratchet ensures already-withdrawn profits are never double-counted."""
    engine = _engine(min_daily_profit_usd=100.0, withdrawal_fraction=0.30, min_withdrawal_usd=1.0)

    # First profit: triggers first withdrawal
    engine.record_profit("BTC-USD", pnl_usd=150.0)
    first_withdrawn = engine.get_daily_summary()["daily_withdrawn_usd"]

    # Second profit that stays below the next ratchet step (still $150 cumulative)
    # Calling record_profit with 0 additional should not trigger another withdrawal
    engine.record_profit("ETH-USD", pnl_usd=0.0)  # zero — ignored
    second_withdrawn = engine.get_daily_summary()["daily_withdrawn_usd"]
    assert second_withdrawn == first_withdrawn, (
        f"No additional withdrawal expected; got ${second_withdrawn:.2f} (was ${first_withdrawn:.2f})"
    )
    print("✅ Ratchet prevents double-counting")


def test_ratchet_grows_with_additional_profits():
    """Each new winning trade increases the daily profit and may trigger incremental withdrawals."""
    engine = _engine(min_daily_profit_usd=100.0, withdrawal_fraction=0.30, min_withdrawal_usd=1.0)

    # Round 1: $150 total → withdraw 30% × $50 = $15
    engine.record_profit("BTC-USD", pnl_usd=150.0)
    withdrawn_1 = engine.get_daily_summary()["daily_withdrawn_usd"]
    assert abs(withdrawn_1 - 15.0) < 0.01, f"Expected ~$15, got ${withdrawn_1:.2f}"

    # Round 2: add $50 → $200 total → gross = 30% × $100 = $30; ratchet = $30 - $15 = $15 more
    engine.record_profit("ETH-USD", pnl_usd=50.0)
    withdrawn_2 = engine.get_daily_summary()["daily_withdrawn_usd"]
    assert abs(withdrawn_2 - 30.0) < 0.01, f"Expected ~$30, got ${withdrawn_2:.2f}"

    print(f"✅ Ratchet grows with profits: ${withdrawn_1:.2f} → ${withdrawn_2:.2f}")


def test_losses_ignored():
    """Negative P&L should not affect daily profit or trigger withdrawals."""
    engine = _engine(min_daily_profit_usd=100.0)
    engine.record_profit("BTC-USD", pnl_usd=200.0)  # profit above threshold
    withdrawn_before = engine.get_daily_summary()["daily_withdrawn_usd"]

    engine.record_profit("ETH-USD", pnl_usd=-50.0)  # loss — should be ignored

    summary = engine.get_daily_summary()
    assert summary["daily_profit_usd"] == 200.0, "Daily profit should not decrease on a loss"
    assert summary["daily_withdrawn_usd"] == withdrawn_before, (
        "Withdrawal should not change after a loss record"
    )
    print("✅ Losses are ignored by daily profit counter")


def test_end_of_day_sweep():
    """EOD sweep should extract remaining eligible profits and then roll over."""
    engine = _engine(
        min_daily_profit_usd=100.0,
        withdrawal_fraction=0.30,
        min_withdrawal_usd=1.0,
        end_of_day_sweep=True,
    )
    # Add profit that would generate a partial intraday withdrawal
    engine.record_profit("BTC-USD", pnl_usd=160.0)
    withdrawn_intraday = engine.get_daily_summary()["daily_withdrawn_usd"]

    # Run EOD sweep — any remaining eligible profit above threshold is extracted
    rec = engine.run_end_of_day_sweep()

    summary = engine.get_daily_summary()
    # After rollover, daily counters should be reset
    assert summary["daily_profit_usd"] == 0.0, "Daily profit should reset after EOD sweep"
    assert summary["daily_withdrawn_usd"] == 0.0, "Daily withdrawn should reset after EOD sweep"
    # History should contain yesterday's entry
    history = engine.get_daily_history(n=5)
    assert len(history) >= 1, "EOD sweep should save the day to history"
    print(
        f"✅ EOD sweep executed; intraday=${withdrawn_intraday:.2f}; "
        f"history entries={len(history)}"
    )


def test_end_of_day_sweep_disabled():
    """With end_of_day_sweep=False, run_end_of_day_sweep should still rollover but not extract."""
    engine = _engine(
        min_daily_profit_usd=100.0,
        withdrawal_fraction=0.30,
        min_withdrawal_usd=1.0,
        end_of_day_sweep=False,
    )
    engine.record_profit("BTC-USD", pnl_usd=160.0)
    intraday_withdrawn = engine.get_daily_summary()["daily_withdrawn_usd"]

    rec = engine.run_end_of_day_sweep()
    assert rec is None, "EOD sweep should return None when disabled"

    # Daily counters should still reset via rollover
    summary = engine.get_daily_summary()
    assert summary["daily_profit_usd"] == 0.0, "Daily profit should still reset after rollover"
    print(f"✅ EOD sweep disabled: intraday=${intraday_withdrawn:.2f}, no additional extraction")


def test_config_validation_bad_fraction():
    """DailyWithdrawalConfig.validate() should raise on fraction outside (0, 1]."""
    cfg = DailyWithdrawalConfig(withdrawal_fraction=0.0)
    try:
        cfg.validate()
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "withdrawal_fraction" in str(e)
    print("✅ Config validates withdrawal_fraction > 0")


def test_config_validation_negative_threshold():
    """DailyWithdrawalConfig.validate() should raise on negative threshold."""
    cfg = DailyWithdrawalConfig(min_daily_profit_usd=-10.0)
    try:
        cfg.validate()
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "min_daily_profit_usd" in str(e)
    print("✅ Config validates min_daily_profit_usd >= 0")


def test_force_withdrawal():
    """force_withdrawal should extract eligible profits immediately."""
    engine = _engine(min_daily_profit_usd=50.0, withdrawal_fraction=0.50, min_withdrawal_usd=1.0)
    engine.record_profit("BTC-USD", pnl_usd=200.0)
    # First auto-extraction happens during record_profit; clear by recording
    first = engine.get_daily_summary()["daily_withdrawn_usd"]

    # Now call force_withdrawal — since nothing new was added, ratchet should show $0 new
    rec = engine.force_withdrawal(note="test manual trigger")
    second = engine.get_daily_summary()["daily_withdrawn_usd"]
    assert second == first, "force_withdrawal should not re-extract already-withdrawn amounts"
    print(f"✅ force_withdrawal idempotent after full extraction: ${second:.2f}")


def test_get_daily_summary_fields():
    """get_daily_summary returns all expected keys with correct types."""
    engine = _engine()
    summary = engine.get_daily_summary()
    required_keys = [
        "date",
        "daily_profit_usd",
        "daily_withdrawn_usd",
        "daily_retained_usd",
        "withdrawal_rate_pct",
        "total_profit_recorded_usd",
        "total_withdrawn_usd",
        "withdrawals_today_count",
        "config",
    ]
    for key in required_keys:
        assert key in summary, f"Missing key: {key}"
    assert isinstance(summary["config"], dict)
    print("✅ get_daily_summary returns all expected keys")


def test_profit_lock_system_wires_daily_withdrawal():
    """ProfitLockSystem.daily_withdrawal should be an active DailyProfitWithdrawalEngine."""
    from profit_lock_system import get_profit_lock_system, ProfitLockSystem

    # Reset singleton for test isolation
    import profit_lock_system as _pls_mod
    orig = _pls_mod._SYSTEM_INSTANCE
    _pls_mod._SYSTEM_INSTANCE = None
    try:
        system = get_profit_lock_system()
        assert system.daily_withdrawal is not None, (
            "ProfitLockSystem.daily_withdrawal should be a DailyProfitWithdrawalEngine"
        )
        print(f"✅ ProfitLockSystem.daily_withdrawal active: {type(system.daily_withdrawal).__name__}")
    finally:
        _pls_mod._SYSTEM_INSTANCE = orig


def test_profit_lock_system_record_closed_profit_updates_daily():
    """record_closed_profit should update the daily withdrawal engine's daily profit."""
    from profit_lock_system import ProfitLockSystem
    import profit_lock_system as _pls_mod

    orig = _pls_mod._SYSTEM_INSTANCE
    _pls_mod._SYSTEM_INSTANCE = None
    try:
        system = ProfitLockSystem()
        if system.daily_withdrawal is None:
            print("⚠️  DailyProfitWithdrawalEngine not available — skipping")
            return

        initial = system.daily_withdrawal.get_daily_summary()["daily_profit_usd"]
        system.record_closed_profit("SOL-USD", pnl_usd=75.0)
        after = system.daily_withdrawal.get_daily_summary()["daily_profit_usd"]
        assert after >= initial + 75.0, (
            f"Expected daily profit to increase by $75; was ${initial:.2f}, now ${after:.2f}"
        )
        print(f"✅ ProfitLockSystem.record_closed_profit updated daily profit: ${after:.2f}")
    finally:
        _pls_mod._SYSTEM_INSTANCE = orig


def test_get_report_contains_daily_withdrawal_section():
    """ProfitLockSystem.get_report() should include the daily withdrawal section."""
    from profit_lock_system import ProfitLockSystem
    import profit_lock_system as _pls_mod

    orig = _pls_mod._SYSTEM_INSTANCE
    _pls_mod._SYSTEM_INSTANCE = None
    try:
        system = ProfitLockSystem()
        report = system.get_report()
        if system.daily_withdrawal is not None:
            assert "DAILY PROFIT WITHDRAWAL" in report.upper(), (
                "Report should contain daily withdrawal section"
            )
            print("✅ get_report() includes daily withdrawal section")
        else:
            assert "DAILY PROFIT WITHDRAWAL" in report.upper() or "NOT AVAILABLE" in report.upper()
            print("✅ get_report() shows daily withdrawal as NOT AVAILABLE (engine missing)")
    finally:
        _pls_mod._SYSTEM_INSTANCE = orig


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print("DAILY PROFIT WITHDRAWAL LOCK — UNIT TESTS")
    print("=" * 70)

    tests = [
        test_no_withdrawal_below_threshold,
        test_withdrawal_triggered_above_threshold,
        test_ratchet_no_double_withdraw,
        test_ratchet_grows_with_additional_profits,
        test_losses_ignored,
        test_end_of_day_sweep,
        test_end_of_day_sweep_disabled,
        test_config_validation_bad_fraction,
        test_config_validation_negative_threshold,
        test_force_withdrawal,
        test_get_daily_summary_fields,
        test_profit_lock_system_wires_daily_withdrawal,
        test_profit_lock_system_record_closed_profit_updates_daily,
        test_get_report_contains_daily_withdrawal_section,
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
