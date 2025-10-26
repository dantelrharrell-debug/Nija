# nija_client.py
import logging
from decimal import Decimal
import time

logger = logging.getLogger("nija_client")
logger.setLevel(logging.INFO)

class NijaClientWrapper:
    def __init__(self, coinbase_client):
        """
        coinbase_client: instance of your coinbase_advanced_py client or similar
        Must implement:
          - get_spot_price(product_id) -> float
          - place_market_order(product_id, side, size) -> order response (or similar)
          - get_account_balance(currency) -> Decimal USD or BTC
        """
        self.client = coinbase_client

    # --- Example adapter for getting spot price ---
    def get_spot_price(self, product_id: str = 'BTC-USD') -> float:
        # adapt to whichever method your lib exposes. Example names:
        # try client.get_spot_price or client.get_last_trade or client.ticker(product_id)
        try:
            # Prefer a library method
            return float(self.client.get_spot_price(product_id))
        except Exception:
            # fallback: if your client exposes public ticker
            try:
                ticker = self.client.get_ticker(product_id)
                return float(ticker['price'])
            except Exception as e:
                logger.error("Failed to fetch spot price: %s", e)
                raise

    def get_usd_balance(self) -> Decimal:
        """Return available USD balance (Decimal) from Coinbase account."""
        try:
            bal = self.client.get_account_balance('USD')
            return Decimal(str(bal))
        except Exception:
            # fallback scanning accounts
            accounts = self.client.get_accounts()
            for a in accounts:
                if a.get('currency') == 'USD':
                    return Decimal(str(a.get('available') or a.get('balance') or 0))
            raise

    def create_order_safe(self, side: str, product_id: str, size_btc: Decimal, usd_size: Decimal, price_usd: Decimal):
        """
        Validate and place order. Returns order dict on success, raises on failure.
        - side: 'buy' or 'sell'
        - size_btc: Decimal BTC size (must be > 0)
        - usd_size: Decimal USD size
        - price_usd: Decimal last price (for logging)
        """
        if size_btc <= 0:
            raise ValueError("Order size too small to place (size_btc <= 0).")

        if side not in ('buy', 'sell'):
            raise ValueError("side must be 'buy' or 'sell'.")

        # quick balance check for buy (ensure enough USD)
        if side == 'buy':
            usd_bal = self.get_usd_balance()
            if usd_size > usd_bal:
                raise ValueError(f"Insufficient USD balance: need {usd_size}, have {usd_bal}")

        # Optionally convert to strings, since many clients expect str amounts
        size_str = format(size_btc, 'f')
        usd_str = format(usd_size, 'f')

        # Attempt order placement with retries
        last_exc = None
        for attempt in range(3):
            try:
                logger.info("Placing %s order: product=%s btc=%s usd=%s price=%s (attempt %d)",
                            side, product_id, size_str, usd_str, str(price_usd), attempt + 1)
                # adapt to your coinbase client's order method name
                # Example: place_market_order(product_id, side, size_btc) or create_order with type='market'
                resp = None
                if hasattr(self.client, 'place_market_order'):
                    resp = self.client.place_market_order(product_id=product_id, side=side, size=size_str)
                elif hasattr(self.client, 'create_order'):
                    resp = self.client.create_order(product_id=product_id, side=side, order_type='market', size=size_str)
                else:
                    # if you only have a low-level send method
                    resp = self.client.send_order(product_id=product_id, side=side, size=size_str, type='market')

                logger.info("Order response: %s", resp)
                return resp
            except Exception as e:
                last_exc = e
                logger.warning("Order attempt %d failed: %s", attempt + 1, e)
                time.sleep(0.5)

        # if we reach here, all attempts failed
        logger.error("All order attempts failed: %s", last_exc)
        raise last_exc
