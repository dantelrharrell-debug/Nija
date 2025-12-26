#!/usr/bin/env python3
"""
Test script to verify the PositionCapEnforcer fix

This script demonstrates that the bug has been fixed and shows
how the enforcer will behave when it runs with real positions.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

# Mock broker for testing without real API calls
class MockCoinbaseBroker:
    """Mock broker for testing the enforcer without real API calls"""
    
    def __init__(self):
        self.connected = True
        self.orders_placed = []
        self.client = self  # Mock client to avoid AttributeError
        self.mock_positions = [
            {'currency': 'BAT', 'balance': 28.65, 'price': 0.214, 'usd_value': 6.14},
            {'currency': 'BTC', 'balance': 0.000069, 'price': 86521.74, 'usd_value': 5.97},
            {'currency': 'BCH', 'balance': 0.009875, 'price': 598.48, 'usd_value': 5.91},
            {'currency': 'AVAX', 'balance': 0.47374, 'price': 12.26, 'usd_value': 5.81},
            {'currency': 'FET', 'balance': 18.8, 'price': 0.208, 'usd_value': 3.92},
            {'currency': 'APT', 'balance': 1.193, 'price': 1.66, 'usd_value': 1.98},
            {'currency': 'ETH', 'balance': 0.000304, 'price': 2927.63, 'usd_value': 0.89},
            {'currency': 'CRV', 'balance': 2.1, 'price': 0.39, 'usd_value': 0.82},
            {'currency': 'ATOM', 'balance': 0.305094, 'price': 2.00, 'usd_value': 0.61},
            {'currency': 'XRP', 'balance': 0.147116, 'price': 1.84, 'usd_value': 0.27},
            {'currency': 'AAVE', 'balance': 0.001, 'price': 160.00, 'usd_value': 0.16},
            {'currency': 'DOT', 'balance': 0.074915, 'price': 1.73, 'usd_value': 0.13},
            {'currency': 'LINK', 'balance': 0.01, 'price': 12.00, 'usd_value': 0.12},
            {'currency': 'DOGE', 'balance': 0.5, 'price': 0.12, 'usd_value': 0.06},
            {'currency': 'HBAR', 'balance': 0.4, 'price': 0.10, 'usd_value': 0.04},
        ]
    
    def connect(self):
        """Mock connect"""
        return True
    
    def get_accounts(self):
        """Return mock accounts based on mock_positions"""
        class MockAccount:
            def __init__(self, currency, balance):
                self.currency = currency
                self.available_balance = type('obj', (), {'value': str(balance)})()
        
        accounts = [MockAccount(p['currency'], p['balance']) for p in self.mock_positions]
        # Add USD account
        accounts.append(MockAccount('USD', 5.47))
        
        return type('obj', (), {'accounts': accounts})()
    
    def get_product(self, symbol):
        """Return mock product data"""
        currency = symbol.split('-')[0]
        for p in self.mock_positions:
            if p['currency'] == currency:
                return type('obj', (), {'price': str(p['price'])})()
        return type('obj', (), {'price': '1.0'})()
    
    def place_market_order(self, symbol: str, side: str, quantity: float, size_type: str = 'quote'):
        """Mock place_market_order - records the order"""
        self.orders_placed.append({
            'symbol': symbol,
            'side': side,
            'quantity': quantity,
            'size_type': size_type
        })
        return {'status': 'filled', 'order_id': f'mock_{len(self.orders_placed)}'}


def main():
    """Test the enforcer with mock data"""
    print("="*80)
    print("TESTING POSITION CAP ENFORCER FIX")
    print("="*80)
    
    # Import the real enforcer
    from position_cap_enforcer import PositionCapEnforcer
    
    # Create enforcer with mock broker
    mock_broker = MockCoinbaseBroker()
    enforcer = PositionCapEnforcer(max_positions=8, broker=mock_broker)
    
    print(f"\nInitial state:")
    print(f"  Mock positions: {len(mock_broker.mock_positions)}")
    print(f"  Position cap: {enforcer.max_positions}")
    print(f"  Excess positions: {len(mock_broker.mock_positions) - enforcer.max_positions}")
    
    print(f"\nRunning enforcer.enforce_cap()...")
    print("-"*80)
    
    success, result = enforcer.enforce_cap()
    
    print("-"*80)
    print(f"\nResults:")
    print(f"  Success: {success}")
    print(f"  Current count: {result['current_count']}")
    print(f"  Max allowed: {result['max_allowed']}")
    print(f"  Excess: {result['excess']}")
    print(f"  Sold: {result['sold']}")
    print(f"  Status: {result['status']}")
    
    print(f"\nOrders placed: {len(mock_broker.orders_placed)}")
    for i, order in enumerate(mock_broker.orders_placed, 1):
        currency = order['symbol'].split('-')[0]
        print(f"  {i}. SELL {order['quantity']:.8f} {currency} (size_type={order['size_type']})")
    
    print("\n" + "="*80)
    print("FIX VERIFICATION")
    print("="*80)
    
    # Verify all orders have correct parameters
    all_correct = True
    for order in mock_broker.orders_placed:
        if 'quantity' not in str(order) or order['size_type'] != 'base':
            all_correct = False
            break
    
    if all_correct and len(mock_broker.orders_placed) == result['excess']:
        print("✅ FIX VERIFIED:")
        print("   - All sell orders use 'quantity' parameter (not 'size')")
        print("   - All sell orders use size_type='base' (crypto units)")
        print(f"   - Enforcer sold {result['sold']}/{result['excess']} excess positions")
        print("\n✅ THE BUG IS FIXED! The enforcer will now successfully liquidate excess positions.")
    else:
        print("❌ FIX VERIFICATION FAILED")
        if not all_correct:
            print("   - Some orders still using wrong parameters")
        if len(mock_broker.orders_placed) != result['excess']:
            print(f"   - Expected {result['excess']} orders, but {len(mock_broker.orders_placed)} were placed")
    
    return 0 if success else 1


if __name__ == '__main__':
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s'
    )
    
    sys.exit(main())
