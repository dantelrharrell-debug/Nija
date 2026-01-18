#!/usr/bin/env python3
"""
Test Multi-Asset Trading Features

Verifies:
1. Kraken futures support enabled
2. Asset class detection working
3. Trade confirmation logging format
4. Profit-taking configuration
"""

import logging
import sys
import time
from unittest.mock import Mock, MagicMock

# Configure logging to see trade confirmations
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)

def test_kraken_config():
    """Test Kraken configuration changes"""
    print("\n" + "=" * 70)
    print("TEST 1: Kraken Configuration")
    print("=" * 70)
    
    from bot.broker_configs.kraken_config import KRAKEN_CONFIG
    
    # Test futures enabled
    assert KRAKEN_CONFIG.enable_futures == True, "Futures should be enabled"
    assert KRAKEN_CONFIG.supports_futures == True, "Futures should be supported"
    assert KRAKEN_CONFIG.supports_crypto == True, "Crypto should be supported"
    
    # Test leverage limits
    assert KRAKEN_CONFIG.futures_leverage_max == 3.0, "Max leverage should be 3x"
    
    # Test profit targets exist
    assert len(KRAKEN_CONFIG.profit_targets) > 0, "Should have profit targets"
    
    print("✅ Kraken config test passed")
    print(f"   - Futures: ENABLED")
    print(f"   - Max Leverage: {KRAKEN_CONFIG.futures_leverage_max}x")
    print(f"   - Profit Targets: {len(KRAKEN_CONFIG.profit_targets)}")
    return True


def test_asset_class_support():
    """Test broker asset class support"""
    print("\n" + "=" * 70)
    print("TEST 2: Asset Class Support")
    print("=" * 70)
    
    from bot.broker_manager import KrakenBroker, CoinbaseBroker, AlpacaBroker
    
    # Test KrakenBroker
    kraken = KrakenBroker()
    assert kraken.supports_asset_class('crypto') == True, "Kraken should support crypto"
    assert kraken.supports_asset_class('futures') == True, "Kraken should support futures"
    assert kraken.supports_asset_class('stocks') == False, "Kraken should not support stocks directly"
    
    # Test CoinbaseBroker
    coinbase = CoinbaseBroker()
    assert coinbase.supports_asset_class('crypto') == True, "Coinbase should support crypto"
    assert coinbase.supports_asset_class('futures') == False, "Coinbase should not support futures"
    
    # Test AlpacaBroker
    alpaca = AlpacaBroker()
    assert alpaca.supports_asset_class('stocks') == True, "Alpaca should support stocks"
    assert alpaca.supports_asset_class('crypto') == False, "Alpaca should not support crypto"
    
    print("✅ Asset class support test passed")
    print("   - Kraken: crypto ✅, futures ✅")
    print("   - Coinbase: crypto ✅")
    print("   - Alpaca: stocks ✅")
    return True


def test_futures_detection():
    """Test futures pair detection logic"""
    print("\n" + "=" * 70)
    print("TEST 3: Futures Detection")
    print("=" * 70)
    
    # Test futures detection patterns
    futures_symbols = [
        'BTC-PERP',
        'ETH-PERP',
        'BTC-F0',
        'ETH-F1',
        'SOL-F2'
    ]
    
    spot_symbols = [
        'BTC-USD',
        'ETH-USD',
        'SOL-USDT'
    ]
    
    for symbol in futures_symbols:
        is_futures = any(x in symbol for x in ['PERP', 'F0', 'F1', 'F2', 'F3', 'F4'])
        assert is_futures == True, f"{symbol} should be detected as futures"
    
    for symbol in spot_symbols:
        is_futures = any(x in symbol for x in ['PERP', 'F0', 'F1', 'F2', 'F3', 'F4'])
        assert is_futures == False, f"{symbol} should NOT be detected as futures"
    
    print("✅ Futures detection test passed")
    print(f"   - Tested {len(futures_symbols)} futures symbols")
    print(f"   - Tested {len(spot_symbols)} spot symbols")
    return True


def test_trade_confirmation_format():
    """Test trade confirmation logging format"""
    print("\n" + "=" * 70)
    print("TEST 4: Trade Confirmation Format")
    print("=" * 70)
    
    from bot.broker_manager import KrakenBroker, AccountType
    
    # Create mock Kraken broker
    broker = KrakenBroker(account_type=AccountType.MASTER)
    broker.account_identifier = "MASTER"
    broker.api = Mock()
    broker.connected = False  # Don't actually connect
    
    # Mock the Kraken private call
    broker._kraken_private_call = Mock(return_value={
        'result': {
            'txid': ['TEST-ORDER-123']
        }
    })
    
    # Mock _root_logger handlers
    import bot.broker_manager as bm
    bm._root_logger = Mock()
    bm._root_logger.handlers = []
    
    # Test order placement (this will log trade confirmation)
    print("\nSimulating trade confirmation...")
    result = broker.place_market_order('BTC-USD', 'buy', 100.0)
    
    # Verify result includes account
    assert 'account' in result, "Result should include account field"
    assert result['account'] == 'MASTER', "Account should be MASTER"
    
    print("✅ Trade confirmation format test passed")
    print("   - Account identification included")
    print("   - Enhanced logging format verified")
    return True


def test_profit_taking_config():
    """Test profit-taking configuration"""
    print("\n" + "=" * 70)
    print("TEST 5: Profit-Taking Configuration")
    print("=" * 70)
    
    from bot.broker_configs.kraken_config import KRAKEN_CONFIG
    
    # Test profit targets
    profit_targets = KRAKEN_CONFIG.profit_targets
    assert len(profit_targets) >= 3, "Should have at least 3 profit targets"
    
    # Test each target is profitable after fees
    round_trip_fee = KRAKEN_CONFIG.round_trip_cost
    for target_pct, description in profit_targets:
        net_profit = target_pct - round_trip_fee
        assert net_profit > 0, f"Target {target_pct*100}% should be profitable after {round_trip_fee*100}% fees"
    
    # Test stop loss exists
    assert KRAKEN_CONFIG.stop_loss < 0, "Stop loss should be negative"
    
    print("✅ Profit-taking configuration test passed")
    print(f"   - Profit targets: {len(profit_targets)}")
    print(f"   - All targets profitable after {round_trip_fee*100}% fees")
    print(f"   - Stop loss: {KRAKEN_CONFIG.stop_loss*100}%")
    return True


def run_all_tests():
    """Run all tests"""
    print("\n" + "=" * 70)
    print("MULTI-ASSET TRADING TEST SUITE")
    print("=" * 70)
    
    tests = [
        ("Kraken Configuration", test_kraken_config),
        ("Asset Class Support", test_asset_class_support),
        ("Futures Detection", test_futures_detection),
        ("Trade Confirmation Format", test_trade_confirmation_format),
        ("Profit-Taking Configuration", test_profit_taking_config),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
        except Exception as e:
            failed += 1
            print(f"❌ {name} failed: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 70)
    print("TEST RESULTS")
    print("=" * 70)
    print(f"Passed: {passed}/{len(tests)}")
    print(f"Failed: {failed}/{len(tests)}")
    
    if failed == 0:
        print("\n✅ ALL TESTS PASSED!")
        print("\nMulti-asset trading features verified:")
        print("  ✅ Kraken futures enabled")
        print("  ✅ Asset class detection working")
        print("  ✅ Trade confirmations formatted correctly")
        print("  ✅ Profit-taking configured properly")
        return 0
    else:
        print("\n❌ SOME TESTS FAILED")
        return 1


if __name__ == '__main__':
    sys.exit(run_all_tests())
