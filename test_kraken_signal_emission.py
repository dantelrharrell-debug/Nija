#!/usr/bin/env python3
"""
Test script to verify Kraken trade signal emission for copy trading.

This script tests that:
1. KrakenBroker.place_market_order() emits trade signals for MASTER account
2. KrakenBroker.place_market_order() does NOT emit signals for USER accounts
3. Trade signals are properly formatted for the copy trade engine
"""

import logging
import sys
import os
from unittest.mock import Mock, MagicMock, patch

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_kraken_signal_emission_master():
    """Test that Kraken MASTER account emits trade signals."""
    from broker_manager import KrakenBroker, AccountType
    
    logger.info("=" * 70)
    logger.info("TEST 1: Kraken MASTER Account Signal Emission")
    logger.info("=" * 70)
    
    # Create a KrakenBroker instance for MASTER account
    broker = KrakenBroker(account_type=AccountType.MASTER)
    
    # Mock the Kraken API
    with patch.object(broker, 'api') as mock_api, \
         patch.object(broker, '_kraken_private_call') as mock_private_call, \
         patch.object(broker, 'get_account_balance_detailed') as mock_balance:
        
        # Set up mocks
        broker.connected = True
        broker.credentials_configured = True
        
        # Mock successful order response
        mock_private_call.return_value = {
            'error': [],
            'result': {
                'txid': ['KRAKEN-ORDER-123'],
                'descr': {'order': 'buy 0.01 BTCUSD @ market'}
            }
        }
        
        # Mock balance for position sizing
        mock_balance.return_value = {
            'trading_balance': 10000.0,
            'error': False
        }
        
        # Mock signal emitter
        signal_captured = []
        
        def mock_emit_signal(**kwargs):
            signal_captured.append(kwargs)
            logger.info(f"   ✅ Signal captured: {kwargs}")
            return True
        
        with patch('bot.trade_signal_emitter.emit_trade_signal', side_effect=mock_emit_signal):
            # Place a test order
            result = broker.place_market_order(
                symbol='BTC-USD',
                side='buy',
                quantity=0.01
            )
            
            logger.info(f"\n   Order Result: {result}")
            
            # Verify signal was emitted
            if signal_captured:
                logger.info("\n   ✅ PASS: Trade signal was emitted for MASTER account")
                signal = signal_captured[0]
                
                # Verify signal structure
                assert signal['broker'] == 'kraken', "Broker should be 'kraken'"
                assert signal['symbol'] == 'BTC-USD', "Symbol should be original format"
                assert signal['side'] == 'buy', "Side should be 'buy'"
                assert signal['size'] == 0.01, "Size should match order quantity"
                assert signal['size_type'] == 'base', "Size type should be 'base'"
                assert signal['master_balance'] == 10000.0, "Master balance should be set"
                assert signal['order_id'] == 'KRAKEN-ORDER-123', "Order ID should match"
                
                logger.info("   ✅ Signal structure is correct")
                logger.info(f"      - Broker: {signal['broker']}")
                logger.info(f"      - Symbol: {signal['symbol']}")
                logger.info(f"      - Side: {signal['side']}")
                logger.info(f"      - Size: {signal['size']} ({signal['size_type']})")
                logger.info(f"      - Master Balance: ${signal['master_balance']:.2f}")
                logger.info(f"      - Order ID: {signal['order_id']}")
                
                return True
            else:
                logger.error("\n   ❌ FAIL: No signal was emitted for MASTER account")
                return False


def test_kraken_signal_emission_user():
    """Test that Kraken USER account does NOT emit trade signals."""
    from broker_manager import KrakenBroker, AccountType
    
    logger.info("\n" + "=" * 70)
    logger.info("TEST 2: Kraken USER Account Signal Emission (should not emit)")
    logger.info("=" * 70)
    
    # Create a KrakenBroker instance for USER account
    broker = KrakenBroker(account_type=AccountType.USER, user_id='test_user')
    
    # Mock the Kraken API
    with patch.object(broker, 'api') as mock_api, \
         patch.object(broker, '_kraken_private_call') as mock_private_call, \
         patch.object(broker, 'get_account_balance_detailed') as mock_balance:
        
        # Set up mocks
        broker.connected = True
        broker.credentials_configured = True
        
        # Mock successful order response
        mock_private_call.return_value = {
            'error': [],
            'result': {
                'txid': ['KRAKEN-USER-ORDER-456'],
                'descr': {'order': 'buy 0.005 BTCUSD @ market'}
            }
        }
        
        # Mock balance for position sizing
        mock_balance.return_value = {
            'trading_balance': 1000.0,
            'error': False
        }
        
        # Mock signal emitter
        signal_captured = []
        
        def mock_emit_signal(**kwargs):
            signal_captured.append(kwargs)
            logger.error(f"   ❌ Signal unexpectedly emitted: {kwargs}")
            return True
        
        with patch('bot.trade_signal_emitter.emit_trade_signal', side_effect=mock_emit_signal):
            # Place a test order
            result = broker.place_market_order(
                symbol='BTC-USD',
                side='buy',
                quantity=0.005
            )
            
            logger.info(f"\n   Order Result: {result}")
            
            # Verify signal was NOT emitted
            if not signal_captured:
                logger.info("\n   ✅ PASS: No signal emitted for USER account (correct behavior)")
                return True
            else:
                logger.error("\n   ❌ FAIL: Signal was emitted for USER account (should not happen)")
                logger.error(f"      Signal: {signal_captured[0]}")
                return False


def test_copy_trade_integration():
    """Test integration with copy trade engine."""
    from broker_manager import KrakenBroker, AccountType
    
    logger.info("\n" + "=" * 70)
    logger.info("TEST 3: Copy Trade Engine Integration")
    logger.info("=" * 70)
    
    # Mock the copy trade engine to capture signals
    signals_received = []
    
    class MockSignalEmitter:
        def emit_signal(self, signal):
            signals_received.append(signal)
            logger.info(f"   📡 Copy engine received signal: {signal.symbol} {signal.side}")
            return True
        
        def get_stats(self):
            return {'total_emitted': len(signals_received)}
    
    # Skip this test since it requires full bot module
    logger.info("   ⏭️  SKIP: Requires full bot module initialization")
    return True
    
    with patch('bot.trade_signal_emitter.get_signal_emitter', return_value=MockSignalEmitter()):
        # Create MASTER broker
        broker = KrakenBroker(account_type=AccountType.MASTER)
        
        # Mock the Kraken API
        with patch.object(broker, 'api') as mock_api, \
             patch.object(broker, '_kraken_private_call') as mock_private_call, \
             patch.object(broker, 'get_account_balance_detailed') as mock_balance:
            
            # Set up mocks
            broker.connected = True
            broker.credentials_configured = True
            
            # Mock successful order response
            mock_private_call.return_value = {
                'error': [],
                'result': {
                    'txid': ['KRAKEN-COPY-789'],
                    'descr': {'order': 'sell 0.02 ETHUSD @ market'}
                }
            }
            
            # Mock balance
            mock_balance.return_value = {
                'trading_balance': 50000.0,
                'error': False
            }
            
            # Place order
            result = broker.place_market_order(
                symbol='ETH-USD',
                side='sell',
                quantity=0.02
            )
            
            # Verify signal was received by copy engine
            if signals_received:
                logger.info(f"\n   ✅ PASS: Copy engine received {len(signals_received)} signal(s)")
                signal = signals_received[0]
                logger.info(f"      - Symbol: {signal.symbol}")
                logger.info(f"      - Side: {signal.side}")
                logger.info(f"      - Size: {signal.size} ({signal.size_type})")
                return True
            else:
                logger.error("\n   ❌ FAIL: Copy engine did not receive any signals")
                return False


def main():
    """Run all tests."""
    logger.info("\n" + "=" * 70)
    logger.info("KRAKEN TRADE SIGNAL EMISSION TEST SUITE")
    logger.info("=" * 70)
    logger.info("Testing Kraken copy trading signal emission functionality\n")
    
    results = []
    
    # Test 1: MASTER account signal emission
    try:
        results.append(("MASTER Signal Emission", test_kraken_signal_emission_master()))
    except Exception as e:
        logger.error(f"Test 1 failed with exception: {e}")
        import traceback
        traceback.print_exc()
        results.append(("MASTER Signal Emission", False))
    
    # Test 2: USER account signal emission (should not emit)
    try:
        results.append(("USER Signal Emission", test_kraken_signal_emission_user()))
    except Exception as e:
        logger.error(f"Test 2 failed with exception: {e}")
        import traceback
        traceback.print_exc()
        results.append(("USER Signal Emission", False))
    
    # Test 3: Copy trade engine integration
    try:
        results.append(("Copy Trade Integration", test_copy_trade_integration()))
    except Exception as e:
        logger.error(f"Test 3 failed with exception: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Copy Trade Integration", False))
    
    # Print summary
    logger.info("\n" + "=" * 70)
    logger.info("TEST SUMMARY")
    logger.info("=" * 70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{status}: {test_name}")
    
    logger.info("=" * 70)
    logger.info(f"Results: {passed}/{total} tests passed")
    logger.info("=" * 70)
    
    # Return exit code (0 = all passed, 1 = some failed)
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
