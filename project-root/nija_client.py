# nija_client.py
import os
from decimal import Decimal
from coinbase_advanced_py import CoinbaseClient  # corrected import

class NijaCoinbaseClient:
    def __init__(self):
        self.client = CoinbaseClient(
            api_key=os.getenv("COINBASE_API_KEY"),
            api_secret=os.getenv("COINBASE_API_SECRET"),
            passphrase=os.getenv("COINBASE_PASSPHRASE"),
            sandbox=False  # ensure live trading
        )

    def get_accounts(self):
        """Return all account balances."""
        return self.client.get_accounts()

    def get_account_balance(self, currency):
        """Return the balance for a specific currency."""
        accounts = self.get_accounts()
        for acc in accounts:
            if acc['currency'] == currency:
                return Decimal(acc['balance'])
        return Decimal('0')

    def calculate_position_size(self, equity, risk_percent):
        """Calculate trade size based on equity and risk (min 2%, max 10%)."""
        risk_percent = min(max(risk_percent, 2), 10)  # clamp between 2 and 10%
        return (equity * Decimal(risk_percent) / Decimal('100'))

    def place_order(self, symbol, side, order_type, size, price=None):
        """
        Place an order on Coinbase.
        symbol: str, e.g., "BTC-USD"
        side: 'buy' or 'sell'
        order_type: 'market' or 'limit'
        size: float/Decimal amount in base currency
        price: float/Decimal, required if limit order
        """
        order_params = {
            "symbol": symbol,
            "side": side,
            "order_type": order_type,
            "size": str(size)  # ensure string for API
        }
        if order_type.lower() == 'limit':
            if price is None:
                raise ValueError("Price must be set for limit orders.")
            order_params['price'] = str(price)

        return self.client.place_order(**order_params)

    def get_open_orders(self, symbol=None):
        """Return all open orders, optionally filtered by symbol."""
        return self.client.get_open_orders(symbol=symbol)
