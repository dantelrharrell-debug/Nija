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

    def place_market_order(self, symbol: str, side: str, quantity: float) -> Dict:
        # Simulate a filled order and adjust mock balance for buys (quote_size in USD)
        try:
            filled = {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "filled_size": quantity,  # CRITICAL: retry_handler checks this field
                "size": quantity,
                "timestamp": datetime.now().isoformat(),
            }
            if side.lower() == "buy":
                self._balance = max(0.0, self._balance - float(quantity))
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
