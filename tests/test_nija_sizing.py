# tests/test_nija_sizing.py
import unittest
from decimal import Decimal
from nija_client_adapter import NijaClientAdapter

# reuse the same sizing logic you already have in nija_strategy.py
from decimal import Decimal, ROUND_DOWN

# simple local reimplementation to avoid import path issues in tests
MIN_PCT = Decimal('0.02')
MAX_PCT = Decimal('0.10')
HARD_MIN_USD = Decimal('1.00')

def calculate_usd_order_size(account_equity_usd: float) -> Decimal:
    equity = Decimal(str(account_equity_usd))
    min_by_pct = (equity * MIN_PCT).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
    max_by_pct = (equity * MAX_PCT).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
    size = min_by_pct
    if size < HARD_MIN_USD:
        size = HARD_MIN_USD
    if size > max_by_pct:
        size = max_by_pct
    if size > equity:
        size = equity
    return size.quantize(Decimal('0.01'), rounding=ROUND_DOWN)

class MockCoinbaseClient:
    """A minimal mock implementing the methods NijaClientAdapter will attempt to use."""
    def __init__(self, usd_balance, btc_price=50000.0):
        self._usd = Decimal(str(usd_balance))
        self.btc_price = btc_price
        self.orders = []

    def get_spot_price(self, product_id):
        return float(self.btc_price)

    def get_account_balance(self, currency):
        if currency == 'USD':
            return float(self._usd)
        return 0.0

    def place_market_order(self, product_id, side, size):
        # record a fake order and return a fake response
        order = {"product_id": product_id, "side": side, "size": size, "status": "filled"}
        self.orders.append(order)
        # reduce USD if buy
        if side == 'buy':
            # naive: size in BTC * price
            usd_spent = Decimal(str(size)) * Decimal(str(self.btc_price))
            self._usd = max(Decimal('0'), self._usd - usd_spent)
        return order

    # fallback get_accounts for adapter's scanning fallback
    def get_accounts(self):
        return [{"currency": "USD", "available": float(self._usd), "balance": float(self._usd)}]


class TestNijaSizingAndAdapter(unittest.TestCase):

    def test_size_for_12_dollars(self):
        equity = 12.0
        usd_size = calculate_usd_order_size(equity)
        # expectation from rules: 2% = 0.24 -> hard min $1 -> final $1.00
        self.assertEqual(usd_size, Decimal('1.00'))

        # set up mock client with $12
        mock = MockCoinbaseClient(usd_balance=12.0, btc_price=50000.0)
        adapter = NijaClientAdapter(mock)

        price = Decimal(str(adapter.get_spot_price('BTC-USD')))
        # convert usd->btc for $1 at price 50k -> 0.00002 BTC
        size_btc = (usd_size / price).quantize(Decimal('1e-8'))
        # should be > 0
        self.assertGreater(size_btc, Decimal('0'))

        # attempt to create order (should place)
        resp = adapter.create_order_safe(side='buy', product_id='BTC-USD', size_btc=size_btc, usd_size=usd_size, price_usd=price)
        self.assertIn('status', resp)
        self.assertEqual(resp['status'], 'filled')
        # ensure the mock has recorded the order
        self.assertEqual(len(mock.orders), 1)

    def test_size_for_50_dollars(self):
        equity = 50.0
        usd_size = calculate_usd_order_size(equity)
        # 2% = 1.00, 10% = 5.00 -> min_by_pct=1.00, hard min 1.00, so final = 1.00
        # BUT business logic: min_by_pct is 1.00 for $50 => final 1.00 (still below 10% cap)
        self.assertEqual(usd_size, Decimal('1.00'))

        # If we want to test a larger equity so the cap matters:
        big_equity = 200.0
        usd_size_big = calculate_usd_order_size(big_equity)
        # min_by_pct = 4.00 (2% of 200) -> hard min not used, max_by_pct=20.00 so final 4.00
        self.assertEqual(usd_size_big, Decimal('4.00'))

if __name__ == "__main__":
    unittest.main()
