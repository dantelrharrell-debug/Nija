# nija_client_adapter.py
"""
Adapter wrapper for coinbase_advanced_py's CoinbaseClient to be used by NIJA.

Provides:
- NijaClientAdapter(coinbase_client)
  - get_spot_price(product_id='BTC-USD') -> float
  - get_usd_balance() -> Decimal
  - create_order_safe(side, product_id, size_btc: Decimal, usd_size: Decimal, price_usd: Decimal)
"""

from decimal import Decimal
import time
import logging

logger = logging.getLogger("nija_client_adapter")
logger.setLevel(logging.INFO)

class NijaClientAdapter:
    def __init__(self, coinbase_client):
        """
        coinbase_client: instance of coinbase_advanced_py.client.CoinbaseClient
        The adapter will attempt to use common method names and gracefully fallback.
        """
        self.client = coinbase_client

    # --- Spot price retrieval ---
    def get_spot_price(self, product_id: str = 'BTC-USD') -> float:
        """
        Try multiple common methods to fetch current spot price. Raise on failure.
        """
        # 1) try direct helper if lib exposes it
        try:
            if hasattr(self.client, "get_spot_price"):
                p = self.client.get_spot_price(product_id)
                return float(p)
        except Exception as e:
            logger.debug("get_spot_price() direct failed: %s", e)

        # 2) try ticker-like method
        try:
            if hasattr(self.client, "get_ticker"):
                t = self.client.get_ticker(product_id)
                # many tickers: {'price': 'xxxxx', ...}
                if isinstance(t, dict) and ('price' in t or 'last' in t):
                    pr = t.get('price') or t.get('last')
                    return float(pr)
        except Exception as e:
            logger.debug("get_ticker() failed: %s", e)

        # 3) try a generic 'ticker' attribute or 'get_last_trade'
        try:
            if hasattr(self.client, "ticker"):
                t = self.client.ticker(product_id)
                if isinstance(t, dict) and 'price' in t:
                    return float(t['price'])
        except Exception as e:
            logger.debug("ticker() failed: %s", e)

        try:
            if hasattr(self.client, "get_last_trade"):
                lt = self.client.get_last_trade(product_id)
                if isinstance(lt, dict) and 'price' in lt:
                    return float(lt['price'])
        except Exception as e:
            logger.debug("get_last_trade() failed: %s", e)

        raise RuntimeError("Failed to fetch spot price from coinbase client adapter.")

    # --- USD balance retrieval ---
    def get_usd_balance(self) -> Decimal:
        """
        Return available USD balance as Decimal.
        Tries:
        - get_account_balance('USD')
        - get_account('USD') or get_accounts() scan
        """
        try:
            if hasattr(self.client, "get_account_balance"):
                b = self.client.get_account_balance('USD')
                return Decimal(str(b))
        except Exception as e:
            logger.debug("get_account_balance('USD') failed: %s", e)

        # fallback scanning accounts list
        try:
            if hasattr(self.client, "get_accounts"):
                accounts = self.client.get_accounts()
                for a in accounts:
                    # support both object/dict shapes
                    if (isinstance(a, dict) and a.get('currency') == 'USD') or getattr(a, 'currency', None) == 'USD':
                        # prefer available, then balance
                        available = (a.get('available') if isinstance(a, dict) else getattr(a, 'available', None))
                        bal = (a.get('balance') if isinstance(a, dict) else getattr(a, 'balance', None))
                        val = available or bal or 0
                        return Decimal(str(val))
        except Exception as e:
            logger.debug("get_accounts() scan failed: %s", e)

        # last resort: try get_accounts_raw or similar
        raise RuntimeError("Failed to retrieve USD balance from coinbase client adapter.")

    # --- Order placement with safety checks & retries ---
    def create_order_safe(self, side: str, product_id: str, size_btc: Decimal, usd_size: Decimal, price_usd: Decimal):
        """
        Validate and attempt to place a market order. Returns whatever the underlying client returns.
        Raises on validation error or repeated failures.
        """
        if size_btc is None:
            raise ValueError("size_btc must be provided")
        if size_btc <= 0:
            raise ValueError("Order size too small to place (size_btc <= 0).")
        if side not in ('buy', 'sell'):
            raise ValueError("side must be 'buy' or 'sell'.")

        # For buys, ensure sufficient USD balance
        if side == 'buy':
            usd_bal = self.get_usd_balance()
            if usd_size > usd_bal:
                raise ValueError(f"Insufficient USD balance: need {usd_size}, have {usd_bal}")

        # Many clients expect strings
        size_str = format(size_btc, 'f')
        usd_str = format(usd_size, 'f')

        last_exc = None
        for attempt in range(3):
            try:
                logger.info("Placing order attempt %d: %s %s (btc=%s usd=%s price=%s)",
                            attempt+1, side, product_id, size_str, usd_str, str(price_usd))

                # 1) try common place_market_order signature
                if hasattr(self.client, "place_market_order"):
                    return self.client.place_market_order(product_id=product_id, side=side, size=size_str)

                # 2) try create_order with order_type/type param
                if hasattr(self.client, "create_order"):
                    # some libs: create_order(product_id, side, order_type='market', size=...)
                    try:
                        return self.client.create_order(product_id=product_id, side=side, order_type='market', size=size_str)
                    except TypeError:
                        # older signature different kw names:
                        return self.client.create_order(product_id, side, 'market', size_str)

                # 3) try a generic method 'order' or 'send_order'
                if hasattr(self.client, "send_order"):
                    return self.client.send_order(product_id=product_id, side=side, size=size_str, type='market')

                if hasattr(self.client, "order"):
                    return self.client.order(product_id=product_id, side=side, size=size_str, type='market')

                raise RuntimeError("No known order placement method found on coinbase client.")
            except Exception as e:
                last_exc = e
                logger.warning("Order attempt %d failed: %s", attempt+1, e)
                time.sleep(0.4)

        logger.error("All order attempts failed. Last error: %s", last_exc)
        raise last_exc
