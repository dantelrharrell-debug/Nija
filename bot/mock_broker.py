"""
Mock broker for paper/smoke testing without real credentials.
Implements the BaseBroker interface with synthetic data.
"""

from typing import Dict, List
from datetime import datetime, timedelta
import random

from broker_manager import BaseBroker, BrokerType


class MockBroker(BaseBroker):
    """Paper-mode mock broker that simulates balances, candles, and orders."""

    def __init__(self, starting_balance: float = 10000.0):
        super().__init__(BrokerType.COINBASE)
        self._balance = float(starting_balance)
        self.client = None

    def connect(self) -> bool:
        self.connected = True
        return True

    def get_account_balance(self) -> float:
        return float(self._balance)

    def place_market_order(self, symbol: str, side: str, quantity: float, size_type: str = 'quote') -> Dict:
        """
        Place a market order in paper mode.
        
        Args:
            symbol: Trading pair (e.g., BTC-USD)
            side: 'buy' or 'sell'
            quantity: Amount to trade
            size_type: 'quote' (USD) or 'base' (crypto) - determines how quantity is interpreted
        """
        # Simulate a filled order and adjust mock balance
        try:
            # For buys, deduct USD (quote currency)
            # For sells, we'd ideally add USD back, but mock broker doesn't track holdings
            if side.lower() == "buy":
                self._balance = max(0.0, self._balance - float(quantity))
            elif side.lower() == "sell":
                # Simulate selling crypto for USD
                # In paper mode, we estimate USD received (quantity is crypto amount if size_type='base')
                if size_type == 'base':
                    # quantity is crypto amount, estimate price ~$100
                    estimated_usd = float(quantity) * 100.0
                else:
                    # quantity is already USD
                    estimated_usd = float(quantity)
                self._balance += estimated_usd
            
            filled = {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "filled_size": quantity,  # CRITICAL: retry_handler checks this field
                "size": quantity,
                "timestamp": datetime.now().isoformat(),
            }
            return {"status": "filled", "order": filled, "filled_size": quantity}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def get_positions(self) -> List[Dict]:
        # Minimal: no tracked positions for mock
        return []

    def get_candles(self, symbol: str, timeframe: str, count: int) -> List[Dict]:
        # Generate simple synthetic OHLCV series
        now = datetime.now()
        tf_seconds = {
            "1m": 60,
            "5m": 300,
            "15m": 900,
            "1h": 3600,
            "1d": 86400,
        }.get(timeframe, 300)

        candles: List[Dict] = []
        price = 100.0 + random.uniform(-1, 1)
        for i in range(count):
            t = now - timedelta(seconds=tf_seconds * (count - i))
            delta = random.uniform(-0.8, 0.8)
            open_p = max(1.0, price)
            close_p = max(1.0, price + delta)
            high_p = max(open_p, close_p) + random.uniform(0, 0.5)
            low_p = min(open_p, close_p) - random.uniform(0, 0.5)
            vol = max(1.0, random.uniform(50, 500))

            candles.append({
                "start": int(t.timestamp()),
                "open": str(open_p),
                "high": str(high_p),
                "low": str(low_p),
                "close": str(close_p),
                "volume": str(vol),
            })
            price = close_p

        return candles

    def supports_asset_class(self, asset_class: str) -> bool:
        return asset_class.lower() == "crypto"
