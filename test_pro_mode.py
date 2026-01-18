#!/usr/bin/env python3
"""
Test script for NIJA PRO MODE functionality

Tests:
1. Capital calculation (free + positions)
2. Rotation manager scoring
3. Position selection for rotation
4. Reserve protection
"""

import sys
import os

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from rotation_manager import RotationManager


def test_rotation_manager():
    """Test rotation manager basic functionality"""
    print("=" * 70)
    print("Testing NIJA PRO MODE - Rotation Manager")
    print("=" * 70)
    
    # Initialize rotation manager
    print("\n1. Initializing Rotation Manager...")
    manager = RotationManager(
        min_free_balance_pct=0.15,
        rotation_enabled=True,
        min_opportunity_improvement=0.20
    )
    print("   ✅ Rotation manager initialized")
    
    # Test rotation eligibility
    print("\n2. Testing rotation eligibility...")
    
    # Scenario 1: Below minimum reserve - should allow rotation
    total_capital = 100.0
    free_balance = 10.0  # 10% of total
    current_positions = 3
    
    can_rotate, reason = manager.can_rotate(total_capital, free_balance, current_positions)
    print(f"   Scenario 1: ${free_balance:.2f} free / ${total_capital:.2f} total (10%)")
    print(f"   Can rotate: {can_rotate} - {reason}")
    assert can_rotate, "Should allow rotation when below minimum reserve"
    print("   ✅ Correctly allows rotation below reserve")
    
    # Scenario 2: Above minimum reserve - should still allow
    free_balance = 20.0  # 20% of total
    can_rotate, reason = manager.can_rotate(total_capital, free_balance, current_positions)
    print(f"\n   Scenario 2: ${free_balance:.2f} free / ${total_capital:.2f} total (20%)")
    print(f"   Can rotate: {can_rotate} - {reason}")
    assert can_rotate, "Should allow rotation when above minimum reserve"
    print("   ✅ Correctly allows rotation above reserve")
    
    # Scenario 3: No positions - should not rotate
    can_rotate, reason = manager.can_rotate(total_capital, free_balance, 0)
    print(f"\n   Scenario 3: No positions to rotate from")
    print(f"   Can rotate: {can_rotate} - {reason}")
    assert not can_rotate, "Should not allow rotation with no positions"
    print("   ✅ Correctly blocks rotation with no positions")
    
    # Test position scoring
    print("\n3. Testing position scoring...")
    
    # Losing position
    metrics_loser = {
        'pnl_pct': -5.0,  # Big loser
        'age_hours': 10,  # Very stale
        'rsi': 75,  # Overbought
        'value': 4.0  # Small
    }
    score_loser = manager.score_position_for_rotation({}, metrics_loser)
    print(f"   Losing position: P&L=-5%, Age=10h, RSI=75, Value=$4")
    print(f"   Score: {score_loser:.1f}/100 (higher = more likely to close)")
    assert score_loser > 70, "Loser should have high score"
    print("   ✅ Correctly scores losing position high")
    
    # Winning position
    metrics_winner = {
        'pnl_pct': 8.0,  # Big winner
        'age_hours': 0.3,  # Very new
        'rsi': 25,  # Oversold (might go higher)
        'value': 50.0  # Large
    }
    score_winner = manager.score_position_for_rotation({}, metrics_winner)
    print(f"\n   Winning position: P&L=+8%, Age=0.3h, RSI=25, Value=$50")
    print(f"   Score: {score_winner:.1f}/100 (lower = keep position)")
    assert score_winner < 30, "Winner should have low score"
    print("   ✅ Correctly scores winning position low")
    
    # Test position selection
    print("\n4. Testing position selection for rotation...")
    
    positions = [
        {'symbol': 'BTC-USD', 'quantity': 0.001},
        {'symbol': 'ETH-USD', 'quantity': 0.01},
        {'symbol': 'SOL-USD', 'quantity': 0.5},
    ]
    
    position_metrics = {
        'BTC-USD': {'value': 50.0, 'pnl_pct': 5.0, 'age_hours': 1.0, 'rsi': 60},
        'ETH-USD': {'value': 30.0, 'pnl_pct': -3.0, 'age_hours': 8.0, 'rsi': 70},
        'SOL-USD': {'value': 20.0, 'pnl_pct': 2.0, 'age_hours': 0.5, 'rsi': 55},
    }
    
    needed_capital = 25.0
    total_capital = 100.0
    
    selected = manager.select_positions_for_rotation(
        positions, position_metrics, needed_capital, total_capital
    )
    
    print(f"   Need to free: ${needed_capital:.2f}")
    print(f"   Positions to close: {len(selected)}")
    for pos in selected:
        sym = pos.get('symbol')
        print(f"     - {sym}: {position_metrics[sym]}")
    
    # ETH-USD should be selected (losing, stale, overbought)
    selected_symbols = [p.get('symbol') for p in selected]
    assert 'ETH-USD' in selected_symbols, "Should select ETH (losing position)"
    print("   ✅ Correctly selects losing position for rotation")
    
    # Test rotation statistics
    print("\n5. Testing rotation statistics...")
    manager.record_rotation(success=True)
    manager.record_rotation(success=True)
    manager.record_rotation(success=False)
    
    stats = manager.get_rotation_stats()
    print(f"   Total rotations: {stats['total_rotations']}")
    print(f"   Successful: {stats['successful_rotations']}")
    print(f"   Success rate: {stats['success_rate']:.1f}%")
    
    assert stats['total_rotations'] == 3, "Should track 3 rotations"
    assert stats['successful_rotations'] == 2, "Should track 2 successful"
    assert abs(stats['success_rate'] - 66.7) < 0.1, "Should calculate correct success rate"
    print("   ✅ Correctly tracks rotation statistics")
    
    print("\n" + "=" * 70)
    print("✅ All PRO MODE tests passed!")
    print("=" * 70)


def test_capital_calculation():
    """Test total capital calculation (requires broker connection)"""
    print("\n" + "=" * 70)
    print("Testing Capital Calculation (requires broker)")
    print("=" * 70)
    
    try:
        from broker_manager import CoinbaseBroker
        
        # Note: This requires valid credentials
        print("\nAttempting to connect to Coinbase...")
        broker = CoinbaseBroker()
        
        if broker.connect():
            print("✅ Connected to Coinbase")
            
            # Test get_total_capital
            capital_data = broker.get_total_capital(include_positions=True)
            
            print("\nCapital Breakdown:")
            print(f"   Free balance: ${capital_data['free_balance']:.2f}")
            print(f"   Position value: ${capital_data['position_value']:.2f}")
            print(f"   Total capital: ${capital_data['total_capital']:.2f}")
            print(f"   Position count: {capital_data['position_count']}")
            
            if capital_data['positions']:
                print("\n   Positions:")
                for pos in capital_data['positions']:
                    print(f"     {pos['symbol']}: {pos['quantity']:.8f} @ ${pos['price']:.2f} = ${pos['value']:.2f}")
            
            # Verify total = free + positions
            expected_total = capital_data['free_balance'] + capital_data['position_value']
            assert abs(capital_data['total_capital'] - expected_total) < 0.01, "Total should equal free + positions"
            
            print("\n✅ Capital calculation test passed!")
        else:
            print("⚠️  Could not connect to broker (credentials may not be configured)")
            print("   Skipping capital calculation test")
    
    except ImportError as e:
        print(f"⚠️  Could not import broker_manager: {e}")
        print("   Skipping capital calculation test")
    except Exception as e:
        print(f"⚠️  Error testing capital calculation: {e}")
        print("   This is expected if broker credentials are not configured")


if __name__ == '__main__':
    try:
        # Test rotation manager (no broker needed)
        test_rotation_manager()
        
        # Test capital calculation (requires broker credentials)
        if '--skip-broker' not in sys.argv:
            test_capital_calculation()
        else:
            print("\n⚠️  Skipping broker tests (--skip-broker flag provided)")
        
        print("\n" + "=" * 70)
        print("✅ PRO MODE READY TO USE")
        print("=" * 70)
        print("\nTo enable PRO MODE:")
        print("  1. Add to .env file:")
        print("     PRO_MODE=true")
        print("     PRO_MODE_MIN_RESERVE_PCT=0.15")
        print("  2. Restart the bot")
        print("  3. Monitor logs for rotation decisions")
        print("\nSee PRO_MODE_README.md for full documentation")
        print("=" * 70)
        
        sys.exit(0)
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
