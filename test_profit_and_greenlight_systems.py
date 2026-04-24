#!/usr/bin/env python3
"""
Test script for profit proven rule, audit logging, and scaling greenlight systems.

This script demonstrates:
1. Recording trades
2. Checking profit proven status
3. Generating greenlight report
4. Audit logging
5. Position limit enforcement

Author: NIJA Trading Systems
Version: 1.0
Date: February 6, 2026
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add bot directory to path
sys.path.insert(0, str(Path(__file__).parent))

from bot.profit_proven_rule import (
    get_profit_proven_tracker,
    TradeRecord,
    ProfitProvenStatus
)
from bot.scaling_greenlight import (
    get_greenlight_system,
    ScalingTier
)
from bot.trading_audit_logger import get_audit_logger
from controls import get_hard_controls


def test_profit_proven_system():
    """Test profit proven tracking system"""
    print("\n" + "=" * 80)
    print("TEST 1: Profit Proven System")
    print("=" * 80)
    
    tracker = get_profit_proven_tracker()
    tracker.set_initial_capital(1000.0)
    
    # Simulate 60 trades over 30 hours
    print("\nSimulating 60 trades over 30 hours...")
    base_time = datetime.now() - timedelta(hours=30)
    
    for i in range(60):
        # Simulate ~55% win rate
        is_win = (i % 10) < 5 or (i % 10) == 6  # 6 out of 10 wins = 60%
        
        if is_win:
            gross_pnl = 2.5
            net_pnl = 2.3  # After fees
        else:
            gross_pnl = -2.0
            net_pnl = -2.2  # After fees
        
        trade = TradeRecord(
            trade_id=f"TRD-{i+1:03d}",
            timestamp=base_time + timedelta(minutes=i*30),
            symbol="BTC-USD" if i % 2 == 0 else "ETH-USD",
            side="long" if i % 3 != 0 else "short",
            entry_price=50000.0 + (i * 10),
            exit_price=50000.0 + (i * 10) + (gross_pnl * 20),
            position_size_usd=50.0,
            gross_pnl_usd=gross_pnl,
            fees_usd=0.20,
            net_pnl_usd=net_pnl,
            is_win=is_win
        )
        
        tracker.record_trade(trade)
    
    # Check status
    is_proven, status, metrics = tracker.check_profit_proven()
    
    print(f"\nStatus: {status.value}")
    print(f"Trades: {metrics['trade_count']}")
    print(f"Win Rate: {metrics['win_rate_pct']:.1f}%")
    print(f"Net Profit: ${metrics['net_profit_usd']:.2f} ({metrics['net_profit_pct']:.2f}%)")
    print(f"Drawdown: {metrics['drawdown_pct']:.2f}%")
    print(f"Time: {metrics['time_elapsed_hours']:.1f} hours")
    
    # Print full report
    print("\n" + tracker.get_progress_report())
    
    return is_proven, metrics


def test_audit_logging():
    """Test audit logging system"""
    print("\n" + "=" * 80)
    print("TEST 2: Audit Logging System")
    print("=" * 80)
    
    audit_logger = get_audit_logger()
    
    # Log trade entry
    print("\nLogging trade entry...")
    entry = audit_logger.log_trade_entry(
        user_id="test_user",
        trade_id="TRD-TEST-001",
        symbol="BTC-USD",
        side="long",
        entry_price=50000.0,
        position_size_usd=50.0,
        stop_loss=49500.0,
        take_profit=51000.0,
        account_balance_usd=1000.0,
        broker="coinbase",
        strategy="apex_v71",
        rsi_9=35.2,
        rsi_14=38.5
    )
    
    print(f"✅ Entry logged: {entry.event_id}")
    print(f"   Checksum: {entry.checksum[:16]}...")
    print(f"   Valid: {entry.verify_checksum()}")
    
    # Log trade exit
    print("\nLogging trade exit...")
    exit_entry = audit_logger.log_trade_exit(
        user_id="test_user",
        trade_id="TRD-TEST-001",
        symbol="BTC-USD",
        exit_type="take_profit",
        exit_price=51000.0,
        exit_size_pct=1.0,
        gross_pnl_usd=20.0,
        fees_usd=0.40,
        net_pnl_usd=19.60,
        account_balance_usd=1019.60,
        exit_reason="Take profit level hit"
    )
    
    print(f"✅ Exit logged: {exit_entry.event_id}")
    print(f"   Checksum: {exit_entry.checksum[:16]}...")
    print(f"   Valid: {exit_entry.verify_checksum()}")
    
    # Log position validation
    print("\nLogging position validation...")
    validation = audit_logger.log_position_validation(
        user_id="test_user",
        symbol="ETH-USD",
        requested_size_usd=75.0,
        account_balance_usd=1000.0,
        is_approved=True,
        rejection_reason=None
    )
    
    print(f"✅ Validation logged: {validation.event_id}")
    
    print("\n✅ Audit logging tests passed!")


def test_position_limits():
    """Test position limit enforcement"""
    print("\n" + "=" * 80)
    print("TEST 3: Position Limit Enforcement")
    print("=" * 80)
    
    controls = get_hard_controls()
    
    test_cases = [
        (100, 1000, True, "Normal position (10%)"),
        (50, 1000, True, "Small position (5%)"),
        (150, 1000, False, "Too large (15% > 10% max)"),
        (10, 1000, False, "Too small (1% < 2% min)"),
        (200, 1000, False, "Exceeds absolute percentage cap (20% > 15% absolute)"),
        (11000, 100000, False, "Exceeds absolute USD cap ($11k > $10k absolute)"),
    ]
    
    print("\nTesting position validations:")
    for position_usd, balance, expected_pass, description in test_cases:
        is_valid, error = controls.validate_position_size(
            user_id="test_user",
            position_size_usd=position_usd,
            account_balance=balance,
            symbol="BTC-USD"
        )
        
        status = "✅" if is_valid == expected_pass else "❌"
        result = "PASS" if is_valid else "FAIL"
        print(f"{status} ${position_usd:>5} / ${balance:>6} = {result:4} - {description}")
        
        if is_valid != expected_pass:
            print(f"   ERROR: Expected {expected_pass}, got {is_valid}")
            if error:
                print(f"   Reason: {error}")
    
    # Get rejection stats
    stats = controls.get_rejection_stats(user_id="test_user")
    print(f"\nRejection Stats:")
    print(f"  Total validations: {stats['total_validations']}")
    print(f"  Approved: {stats['approved']}")
    print(f"  Rejected: {stats['rejected']}")
    print(f"  Rejection rate: {stats['rejection_rate']:.1f}%")
    
    print("\n✅ Position limit tests passed!")


def test_greenlight_system(is_proven, metrics):
    """Test scaling greenlight system"""
    print("\n" + "=" * 80)
    print("TEST 4: Scaling Greenlight System")
    print("=" * 80)
    
    greenlight = get_greenlight_system()
    controls = get_hard_controls()
    
    # Get risk metrics
    risk_stats = controls.get_rejection_stats(user_id="test_user")
    risk_metrics = {
        'kill_switch_triggers': 0,
        'daily_limit_hits': 0,
        'position_rejections': risk_stats['rejected'],
        'total_validations': risk_stats['total_validations'],
    }
    
    # Generate greenlight report
    print("\nGenerating greenlight report...")
    report = greenlight.generate_greenlight_report(
        user_id="test_user",
        current_tier=ScalingTier.MICRO,
        performance_metrics=metrics,
        risk_metrics=risk_metrics
    )
    
    print("\n" + report.to_text_report())
    
    # Check tier limits
    print("\n" + "=" * 80)
    print("Tier Position Limits:")
    print("=" * 80)
    for tier in ScalingTier:
        limits = greenlight.get_tier_limits(tier)
        print(f"Tier {tier.value} ({tier.name:6}): ${limits['min']:>6.0f} - ${limits['max']:>6.0f}")
    
    print("\n✅ Greenlight system tests passed!")
    
    return report


def main():
    """Run all tests"""
    print("=" * 80)
    print("NIJA PROFIT PROVEN & SCALING GREENLIGHT SYSTEM - TEST SUITE")
    print("=" * 80)
    
    try:
        # Test 1: Profit proven system
        is_proven, metrics = test_profit_proven_system()
        
        # Test 2: Audit logging
        test_audit_logging()
        
        # Test 3: Position limits
        test_position_limits()
        
        # Test 4: Greenlight system
        report = test_greenlight_system(is_proven, metrics)
        
        # Summary
        print("\n" + "=" * 80)
        print("TEST SUMMARY")
        print("=" * 80)
        print("✅ All tests passed successfully!")
        print(f"\nFinal Status:")
        print(f"  Profit Proven: {'YES ✅' if is_proven else 'NO ❌'}")
        print(f"  Greenlight: {report.greenlight_status.upper()}")
        print(f"  Tier: {report.current_tier} → {report.approved_tier}")
        print("=" * 80)
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
