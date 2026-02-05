"""
Test Market Readiness Gate
===========================

Tests the three operating modes: IDLE, CAUTIOUS, AGGRESSIVE
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.market_readiness_gate import MarketReadinessGate, MarketMode
from datetime import datetime, timedelta


def test_aggressive_mode():
    """Test AGGRESSIVE mode conditions"""
    print("\n" + "=" * 70)
    print("TEST 1: AGGRESSIVE MODE")
    print("=" * 70)
    
    gate = MarketReadinessGate(state_file="/tmp/test_market_readiness_aggressive.json")
    
    # Set up optimal conditions
    atr = 100.0  # $100 ATR
    current_price = 15000.0  # $15k (0.67% ATR)
    adx = 30.0  # Strong trend
    volume_percentile = 70.0  # High volume
    spread_pct = 0.0010  # 0.10% spread
    
    # Add some winning trades to meet win rate
    for i in range(10):
        gate.record_trade_result(0.015)  # 1.5% profit (meaningful)
    
    mode, conditions, details = gate.check_market_readiness(
        atr=atr,
        current_price=current_price,
        adx=adx,
        volume_percentile=volume_percentile,
        spread_pct=spread_pct
    )
    
    print(f"Mode: {mode.value.upper()}")
    print(f"ATR: {conditions.atr_pct * 100:.2f}%")
    print(f"ADX: {conditions.adx:.1f}")
    print(f"Volume Percentile: {conditions.volume_percentile:.0f}%")
    print(f"Win Rate (24h): {conditions.win_rate_24h * 100:.1f}%")
    print(f"Allow Entries: {details['allow_entries']}")
    print(f"Position Size Multiplier: {details['position_size_multiplier']}")
    
    assert mode == MarketMode.AGGRESSIVE, "Should be AGGRESSIVE mode"
    assert details['allow_entries'], "Should allow entries"
    print("✅ AGGRESSIVE mode test PASSED")


def test_cautious_mode():
    """Test CAUTIOUS mode conditions"""
    print("\n" + "=" * 70)
    print("TEST 2: CAUTIOUS MODE")
    print("=" * 70)
    
    gate = MarketReadinessGate(state_file="/tmp/test_market_readiness_cautious.json")
    
    # Set up marginal conditions
    atr = 70.0  # $70 ATR
    current_price = 15000.0  # $15k (0.47% ATR - between 0.4% and 0.6%)
    adx = 22.0  # Moderate trend (between 18 and 25)
    volume_percentile = 50.0  # Moderate volume (≥ 40%)
    spread_pct = 0.0012  # 0.12% spread
    entry_score = 88  # A+ setup
    
    mode, conditions, details = gate.check_market_readiness(
        atr=atr,
        current_price=current_price,
        adx=adx,
        volume_percentile=volume_percentile,
        spread_pct=spread_pct,
        entry_score=entry_score
    )
    
    print(f"Mode: {mode.value.upper()}")
    print(f"ATR: {conditions.atr_pct * 100:.2f}%")
    print(f"ADX: {conditions.adx:.1f}")
    print(f"Volume Percentile: {conditions.volume_percentile:.0f}%")
    print(f"Entry Score: {entry_score}/100")
    print(f"Allow Entries: {details['allow_entries']}")
    print(f"Position Size Multiplier: {details['position_size_multiplier']}")
    print(f"Min Entry Score: {details.get('min_entry_score', 'N/A')}")
    
    assert mode == MarketMode.CAUTIOUS, "Should be CAUTIOUS mode"
    assert details['allow_entries'], "Should allow entries for A+ setup"
    assert details['position_size_multiplier'] == 0.20, "Should cap at 20%"
    print("✅ CAUTIOUS mode test PASSED")


def test_cautious_mode_blocked():
    """Test CAUTIOUS mode blocking low-score entries"""
    print("\n" + "=" * 70)
    print("TEST 3: CAUTIOUS MODE - LOW SCORE BLOCKED")
    print("=" * 70)
    
    gate = MarketReadinessGate(state_file="/tmp/test_market_readiness_cautious_blocked.json")
    
    # Same marginal conditions but low entry score
    atr = 70.0
    current_price = 15000.0
    adx = 22.0
    volume_percentile = 50.0
    spread_pct = 0.0012
    entry_score = 75  # Below 85 threshold
    
    mode, conditions, details = gate.check_market_readiness(
        atr=atr,
        current_price=current_price,
        adx=adx,
        volume_percentile=volume_percentile,
        spread_pct=spread_pct,
        entry_score=entry_score
    )
    
    print(f"Mode: {mode.value.upper()}")
    print(f"Entry Score: {entry_score}/100")
    print(f"Allow Entries: {details['allow_entries']}")
    print(f"Min Entry Score: {details.get('min_entry_score', 'N/A')}")
    
    assert mode == MarketMode.CAUTIOUS, "Should be CAUTIOUS mode"
    assert not details['allow_entries'], "Should block low-score entries"
    print("✅ CAUTIOUS mode blocking test PASSED")


def test_idle_mode_low_atr():
    """Test IDLE mode - Low ATR"""
    print("\n" + "=" * 70)
    print("TEST 4: IDLE MODE - LOW ATR")
    print("=" * 70)
    
    gate = MarketReadinessGate(state_file="/tmp/test_market_readiness_idle_atr.json")
    
    # Low ATR condition
    atr = 50.0  # $50 ATR
    current_price = 15000.0  # $15k (0.33% ATR - below 0.4%)
    adx = 30.0  # Good trend but ATR too low
    volume_percentile = 70.0
    spread_pct = 0.0010
    
    mode, conditions, details = gate.check_market_readiness(
        atr=atr,
        current_price=current_price,
        adx=adx,
        volume_percentile=volume_percentile,
        spread_pct=spread_pct
    )
    
    print(f"Mode: {mode.value.upper()}")
    print(f"ATR: {conditions.atr_pct * 100:.2f}%")
    print(f"Reasons: {', '.join(details['reasons'])}")
    print(f"Message: {details['message']}")
    print(f"Allow Entries: {details['allow_entries']}")
    
    assert mode == MarketMode.IDLE, "Should be IDLE mode"
    assert not details['allow_entries'], "Should not allow entries"
    print("✅ IDLE mode (low ATR) test PASSED")


def test_idle_mode_circuit_breaker():
    """Test IDLE mode - Recent circuit breaker clear"""
    print("\n" + "=" * 70)
    print("TEST 5: IDLE MODE - CIRCUIT BREAKER COOLDOWN")
    print("=" * 70)
    
    gate = MarketReadinessGate(state_file="/tmp/test_market_readiness_idle_cb.json")
    
    # Record circuit breaker clear 1 hour ago
    one_hour_ago = datetime.utcnow() - timedelta(hours=1)
    gate.record_circuit_breaker_clear(one_hour_ago)
    
    # Good market conditions but circuit breaker recent
    atr = 100.0
    current_price = 15000.0
    adx = 30.0
    volume_percentile = 70.0
    spread_pct = 0.0010
    
    mode, conditions, details = gate.check_market_readiness(
        atr=atr,
        current_price=current_price,
        adx=adx,
        volume_percentile=volume_percentile,
        spread_pct=spread_pct
    )
    
    print(f"Mode: {mode.value.upper()}")
    print(f"Circuit Breaker Hours Ago: {conditions.circuit_breaker_cleared_hours_ago:.1f}")
    print(f"Reasons: {', '.join(details['reasons'])}")
    print(f"Allow Entries: {details['allow_entries']}")
    
    assert mode == MarketMode.IDLE, "Should be IDLE mode"
    assert not details['allow_entries'], "Should not allow entries"
    print("✅ IDLE mode (circuit breaker) test PASSED")


def test_idle_mode_non_meaningful_wins():
    """Test IDLE mode - Consecutive non-meaningful wins"""
    print("\n" + "=" * 70)
    print("TEST 6: IDLE MODE - NON-MEANINGFUL WINS")
    print("=" * 70)
    
    gate = MarketReadinessGate(state_file="/tmp/test_market_readiness_idle_wins.json")
    
    # Record 3 consecutive small wins (not meaningful)
    gate.record_trade_result(0.001)  # 0.1% - below 0.2% threshold
    gate.record_trade_result(0.0015)  # 0.15%
    gate.record_trade_result(0.0018)  # 0.18%
    
    # Good market conditions but non-meaningful wins
    atr = 100.0
    current_price = 15000.0
    adx = 30.0
    volume_percentile = 70.0
    spread_pct = 0.0010
    
    mode, conditions, details = gate.check_market_readiness(
        atr=atr,
        current_price=current_price,
        adx=adx,
        volume_percentile=volume_percentile,
        spread_pct=spread_pct
    )
    
    print(f"Mode: {mode.value.upper()}")
    print(f"Consecutive Non-Meaningful Wins: {conditions.consecutive_non_meaningful_wins}")
    print(f"Reasons: {', '.join(details['reasons'])}")
    print(f"Allow Entries: {details['allow_entries']}")
    
    assert mode == MarketMode.IDLE, "Should be IDLE mode"
    assert not details['allow_entries'], "Should not allow entries"
    print("✅ IDLE mode (non-meaningful wins) test PASSED")


def test_win_rate_tracking():
    """Test win rate calculation"""
    print("\n" + "=" * 70)
    print("TEST 7: WIN RATE TRACKING")
    print("=" * 70)
    
    gate = MarketReadinessGate(state_file="/tmp/test_market_readiness_winrate.json")
    
    # Record mix of trades
    gate.record_trade_result(0.015)   # Win (meaningful)
    gate.record_trade_result(-0.010)  # Loss
    gate.record_trade_result(0.020)   # Win (meaningful)
    gate.record_trade_result(0.018)   # Win (meaningful)
    gate.record_trade_result(-0.008)  # Loss
    gate.record_trade_result(0.025)   # Win (meaningful)
    
    win_rate, total, meaningful = gate.calculate_win_rate_24h()
    
    print(f"Total Trades: {total}")
    print(f"Win Rate: {win_rate * 100:.1f}%")
    print(f"Meaningful Wins: {meaningful}")
    
    assert total == 6, "Should have 6 trades"
    assert win_rate == 4/6, "Should have 66.7% win rate"
    assert meaningful == 4, "Should have 4 meaningful wins"
    print("✅ Win rate tracking test PASSED")


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("MARKET READINESS GATE TEST SUITE")
    print("=" * 70)
    
    try:
        test_aggressive_mode()
        test_cautious_mode()
        test_cautious_mode_blocked()
        test_idle_mode_low_atr()
        test_idle_mode_circuit_breaker()
        test_idle_mode_non_meaningful_wins()
        test_win_rate_tracking()
        
        print("\n" + "=" * 70)
        print("✅ ALL TESTS PASSED")
        print("=" * 70)
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ TEST ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
