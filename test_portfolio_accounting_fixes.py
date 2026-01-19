"""
Test Suite for Portfolio Accounting and Forced Stop-Loss
=========================================================

Tests the core fixes:
1. Portfolio-first accounting (total equity tracking)
2. Forced stop-loss execution
3. User portfolio states
4. Broker adapters
"""

import sys
import os

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

def test_portfolio_state():
    """Test FIX #1: Portfolio State with Total Equity."""
    print("\n" + "="*70)
    print("TEST 1: Portfolio State (Total Equity Accounting)")
    print("="*70)
    
    from portfolio_state import PortfolioState, UserPortfolioState, get_portfolio_manager
    
    # Create portfolio with $1000 cash, no positions
    portfolio = PortfolioState(available_cash=1000.0)
    
    assert portfolio.available_cash == 1000.0
    assert portfolio.total_equity == 1000.0, "Empty portfolio should have equity = cash"
    assert portfolio.position_count == 0
    
    print(f"✅ Empty portfolio: cash=${portfolio.available_cash}, equity=${portfolio.total_equity}")
    
    # Add a position: bought 1 BTC at $50k, now worth $52k
    portfolio.add_position(
        symbol="BTC-USD",
        quantity=1.0,
        entry_price=50000.0,
        current_price=52000.0
    )
    
    # After buying $50k of BTC, cash should drop to $950k (assuming we had $1M)
    # Let's reset for simpler test
    portfolio.available_cash = 500.0  # Simulating $500 left after $500 purchase
    
    assert portfolio.position_count == 1
    assert portfolio.total_position_value == 52000.0, "Position value should be quantity * current_price"
    assert portfolio.unrealized_pnl == 2000.0, "Unrealized P&L should be (52k - 50k) * 1"
    assert portfolio.total_equity == 52500.0, "Total equity should be cash + position value"
    
    print(f"✅ With 1 position:")
    print(f"   Cash: ${portfolio.available_cash:.2f}")
    print(f"   Position Value: ${portfolio.total_position_value:.2f}")
    print(f"   Unrealized P&L: ${portfolio.unrealized_pnl:.2f}")
    print(f"   TOTAL EQUITY: ${portfolio.total_equity:.2f}")
    
    # Test user portfolio
    user_portfolio = UserPortfolioState(
        available_cash=100.0,
        user_id="test_user",
        broker_type="coinbase"
    )
    
    assert user_portfolio.user_id == "test_user"
    assert user_portfolio.broker_type == "coinbase"
    assert user_portfolio.total_equity == 100.0
    
    print(f"✅ User portfolio: {user_portfolio.user_id} on {user_portfolio.broker_type}, equity=${user_portfolio.total_equity:.2f}")
    
    # Test portfolio manager
    manager = get_portfolio_manager()
    
    master = manager.initialize_master_portfolio(available_cash=5000.0)
    assert master.total_equity == 5000.0
    print(f"✅ Portfolio manager: master initialized with ${master.total_equity:.2f}")
    
    user1 = manager.initialize_user_portfolio("user1", "kraken", 200.0)
    assert user1.total_equity == 200.0
    assert user1.user_id == "user1"
    print(f"✅ Portfolio manager: user1 initialized with ${user1.total_equity:.2f}")
    
    print("✅ TEST 1 PASSED: Portfolio accounting works correctly")
    return True


def test_forced_stop_loss():
    """Test FIX #2: Forced Stop-Loss Execution."""
    print("\n" + "="*70)
    print("TEST 2: Forced Stop-Loss Execution")
    print("="*70)
    
    from forced_stop_loss import ForcedStopLoss
    
    # Mock broker for testing
    class MockBroker:
        def __init__(self):
            self.orders = []
        
        def place_market_order(self, symbol, side, quantity, size_type):
            order = {
                'symbol': symbol,
                'side': side,
                'quantity': quantity,
                'size_type': size_type,
                'order_id': f'order_{len(self.orders)}',
                'status': 'filled'
            }
            self.orders.append(order)
            return order
        
        def get_current_price(self, symbol):
            return 50000.0  # Mock price
    
    broker = MockBroker()
    forced_sl = ForcedStopLoss(broker)
    
    # Test stop-loss trigger check
    triggered = forced_sl.check_stop_loss_triggered(
        symbol="BTC-USD",
        entry_price=50000.0,
        current_price=49500.0,  # Down 1%
        stop_loss_pct=-0.01  # -1% stop
    )
    
    assert triggered == True, "Stop-loss should trigger at -1%"
    print(f"✅ Stop-loss trigger detection: -1% loss triggers -1% stop")
    
    # Test forced sell
    success, result, error = forced_sl.force_sell_position(
        symbol="BTC-USD",
        quantity=0.5,
        reason="Test stop-loss"
    )
    
    assert success == True, "Forced sell should succeed with mock broker"
    assert len(broker.orders) == 1, "Should have 1 order"
    assert broker.orders[0]['side'] == 'sell'
    assert broker.orders[0]['quantity'] == 0.5
    assert broker.orders[0]['size_type'] == 'base'  # Must use base (quantity) not quote (USD)
    
    print(f"✅ Forced sell executed: {broker.orders[0]}")
    
    # Test batch forced sell
    positions = [
        {'symbol': 'ETH-USD', 'quantity': 10.0},
        {'symbol': 'SOL-USD', 'quantity': 100.0},
    ]
    
    results = forced_sl.force_sell_multiple_positions(positions, reason="Batch test")
    
    assert len(results) == 2, "Should have results for 2 positions"
    assert all(success for success, _, _ in results.values()), "All should succeed"
    assert len(broker.orders) == 3, "Should have 3 total orders now"
    
    print(f"✅ Batch forced sell: {len(results)} positions sold")
    
    print("✅ TEST 2 PASSED: Forced stop-loss works correctly")
    return True


def test_broker_adapters():
    """Test FIX #4: Broker-Specific Execution Adapters."""
    print("\n" + "="*70)
    print("TEST 3: Broker-Specific Execution Adapters")
    print("="*70)
    
    from broker_adapters import (
        OrderIntent, TradeIntent, 
        CoinbaseAdapter, KrakenAdapter, AlpacaAdapter,
        BrokerAdapterFactory
    )
    
    # Test Coinbase adapter
    coinbase = CoinbaseAdapter()
    
    # Normal trade
    intent = TradeIntent(
        intent_type=OrderIntent.BUY,
        symbol="BTC-USD",
        quantity=0.1,
        size_usd=5000.0,
        size_type="base"
    )
    
    order = coinbase.validate_and_adjust(intent)
    
    assert order.valid == True, "Valid order should pass"
    assert order.symbol == "BTC-USD"
    print(f"✅ Coinbase adapter: valid order passed - {order.symbol}")
    
    # Too small order
    small_intent = TradeIntent(
        intent_type=OrderIntent.BUY,
        symbol="ETH-USD",
        quantity=0.001,
        size_usd=0.50,  # Below $1 minimum
        size_type="base"
    )
    
    small_order = coinbase.validate_and_adjust(small_intent)
    
    assert small_order.valid == False, "Too small order should fail"
    assert "minimum" in small_order.error_message.lower()
    print(f"✅ Coinbase adapter: rejected small order (${small_intent.size_usd:.2f} < $1 min)")
    
    # Force execute (stop-loss) should bypass size checks
    force_intent = TradeIntent(
        intent_type=OrderIntent.STOP_LOSS,
        symbol="ETH-USD",
        quantity=0.001,
        size_usd=0.50,
        size_type="base",
        force_execute=True
    )
    
    force_order = coinbase.validate_and_adjust(force_intent)
    
    assert force_order.valid == True, "Forced order should bypass size checks"
    assert len(force_order.warnings) > 0, "Should have warning about force execute"
    print(f"✅ Coinbase adapter: forced stop-loss bypassed size checks")
    
    # Test Kraken adapter
    kraken = KrakenAdapter()
    
    # Kraken doesn't support BUSD
    busd_intent = TradeIntent(
        intent_type=OrderIntent.BUY,
        symbol="ETH-BUSD",  # Not supported on Kraken
        quantity=1.0,
        size_usd=100.0,
        size_type="base"
    )
    
    busd_order = kraken.validate_and_adjust(busd_intent)
    
    assert busd_order.valid == False, "BUSD pairs not supported on Kraken"
    assert "BUSD" in busd_order.error_message or "not support" in busd_order.error_message.lower()
    print(f"✅ Kraken adapter: rejected unsupported BUSD pair")
    
    # Test symbol normalization
    assert kraken.normalize_symbol("BTC-USD") == "BTC/USD"
    assert coinbase.normalize_symbol("BTC/USD") == "BTC-USD"
    print(f"✅ Symbol normalization: Coinbase uses '-', Kraken uses '/'")
    
    # Test adapter factory
    cb_adapter = BrokerAdapterFactory.create_adapter("coinbase")
    assert isinstance(cb_adapter, CoinbaseAdapter)
    
    kr_adapter = BrokerAdapterFactory.create_adapter("kraken")
    assert isinstance(kr_adapter, KrakenAdapter)
    
    al_adapter = BrokerAdapterFactory.create_adapter("alpaca", account_value=30000.0)
    assert isinstance(al_adapter, AlpacaAdapter)
    
    print(f"✅ Broker adapter factory: creates correct adapter types")
    
    print("✅ TEST 3 PASSED: Broker adapters work correctly")
    return True


def run_all_tests():
    """Run all tests."""
    print("\n" + "="*70)
    print("NIJA PORTFOLIO ACCOUNTING & STOP-LOSS TEST SUITE")
    print("="*70)
    
    tests = [
        ("Portfolio State", test_portfolio_state),
        ("Forced Stop-Loss", test_forced_stop_loss),
        ("Broker Adapters", test_broker_adapters),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
            else:
                failed += 1
                print(f"❌ {name} FAILED")
        except Exception as e:
            failed += 1
            print(f"❌ {name} FAILED with exception: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    print(f"✅ Passed: {passed}/{len(tests)}")
    print(f"❌ Failed: {failed}/{len(tests)}")
    print("="*70)
    
    if failed == 0:
        print("🎉 ALL TESTS PASSED!")
        return True
    else:
        print("⚠️  SOME TESTS FAILED")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
