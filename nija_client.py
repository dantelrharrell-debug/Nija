"""
Nija Coinbase client adapter / safe order wrapper.

This file exposes `NijaClientWrapper` which adapts a variety of coinbase client method
names into a stable interface used by NIJA strategy code:
  - get_spot_price(product_id) -> float
  - get_usd_balance() -> Decimal
  - create_order_safe(side, product_id, size_btc, usd_size, price_usd) -> underlying order response

It also logs structured JSON to stdout (captured by Render/Railway) and optionally POSTs
order notifications to webhook endpoints set via env vars:
 - RENDER_LOG_ENDPOINT
 - RAILWAY_LOG_ENDPOINT
 - GENERIC_LOG_ENDPOINT

Outbound webhook POSTs are HMAC-SHA256 signed (header X-NIJA-SIGNATURE) when
NIJA_OUTBOUND_SECRET is set in env. This enables the receiver to verify authenticity.
"""
from decimal import Decimal
import time
import logging
import os
import json
import sys
import hmac
import hashlib

# requests is optional (only needed for webhook POSTs). If not installed, HTTP notify is skipped.
try:
    import requests
except Exception:
    requests = None

logger = logging.getLogger("nija_client")
logger.setLevel(logging.INFO)
# Ensure log output goes to stdout so Render / Railway capture it in "safe" logs
if not logger.handlers:
    sh = logging.StreamHandler(stream=sys.stdout)
    sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(sh)

# Environment-driven webhook endpoints (optional)
RENDER_LOG_ENDPOINT = os.getenv("RENDER_LOG_ENDPOINT")
RAILWAY_LOG_ENDPOINT = os.getenv("RAILWAY_LOG_ENDPOINT")
GENERIC_LOG_ENDPOINT = os.getenv("GENERIC_LOG_ENDPOINT")

# Outbound signature secret (optional) - used to sign outgoing webhook posts
NIJA_OUTBOUND_SECRET = os.getenv("NIJA_OUTBOUND_SECRET")


def _compute_hmac_sha256_hex(secret: str, body_bytes: bytes) -> str:
    """Return hex HMAC-SHA256 of body using secret."""
    return hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()


def signed_post(url: str, payload: dict, secret: str, requests_module):
    """
    POST JSON payload to url and sign body with secret using header X-NIJA-SIGNATURE: sha256=<hex>.
    Returns requests.Response or raises requests exceptions.
    If requests_module is None, raises RuntimeError.
    """
    if requests_module is None:
        raise RuntimeError("requests module not available for HTTP POST")
    body = json.dumps(payload).encode("utf-8")
    sig = "sha256=" + _compute_hmac_sha256_hex(secret, body)
    headers = {"Content-Type": "application/json", "X-NIJA-SIGNATURE": sig}
    return requests_module.post(url, data=body, headers=headers, timeout=2.0)


class NijaClientWrapper:
    """
    Wraps your `coinbase_advanced_py` client instance (or any similar client) and
    provides helper methods NIJA expects.
    The wrapper tries multiple fallback method names so it works with slightly different libs.
    """
    def __init__(self, coinbase_client):
        """
        coinbase_client: the underlying client instance (e.g., coinbase_advanced_py.client.CoinbaseClient)
        """
        self.client = coinbase_client

    # ----------------------------
    # Spot price retrieval
    # ----------------------------
    def get_spot_price(self, product_id: str = 'BTC-USD') -> float:
        """
        Try several common methods to return the current product price as float.
        Raises RuntimeError if no method returns a price.
        """
        # Try: get_spot_price(product_id)
        try:
            if hasattr(self.client, "get_spot_price"):
                p = self.client.get_spot_price(product_id)
                return float(p)
        except Exception as e:
            logger.debug("get_spot_price() direct failed: %s", e)

        # Try: get_ticker(product_id)
        try:
            if hasattr(self.client, "get_ticker"):
                t = self.client.get_ticker(product_id)
                if isinstance(t, dict) and ('price' in t or 'last' in t):
                    return float(t.get('price') or t.get('last'))
        except Exception as e:
            logger.debug("get_ticker() failed: %s", e)

        # Try: ticker(product_id)
        try:
            if hasattr(self.client, "ticker"):
                t = self.client.ticker(product_id)
                if isinstance(t, dict) and 'price' in t:
                    return float(t['price'])
        except Exception as e:
            logger.debug("ticker() failed: %s", e)

        # Try: get_last_trade(product_id)
        try:
            if hasattr(self.client, "get_last_trade"):
                lt = self.client.get_last_trade(product_id)
                if isinstance(lt, dict) and 'price' in lt:
                    return float(lt['price'])
        except Exception as e:
            logger.debug("get_last_trade() failed: %s", e)

        raise RuntimeError("Failed to fetch spot price from underlying coinbase client.")

    # ----------------------------
    # USD balance retrieval
    # ----------------------------
    def get_usd_balance(self) -> Decimal:
        """
        Return available USD balance as Decimal. Tries common method names then falls back to scanning accounts.
        """
        try:
            if hasattr(self.client, "get_account_balance"):
                b = self.client.get_account_balance('USD')
                return Decimal(str(b))
        except Exception as e:
            logger.debug("get_account_balance('USD') failed: %s", e)

        # Fallback: scan get_accounts()
        try:
            if hasattr(self.client, "get_accounts"):
                accounts = self.client.get_accounts()
                for a in accounts:
                    # support both dict and object shapes
                    cur = (a.get('currency') if isinstance(a, dict) else getattr(a, 'currency', None))
                    if cur == 'USD':
                        available = (a.get('available') if isinstance(a, dict) else getattr(a, 'available', None))
                        balance = (a.get('balance') if isinstance(a, dict) else getattr(a, 'balance', None))
                        val = available or balance or 0
                        return Decimal(str(val))
        except Exception as e:
            logger.debug("get_accounts() scan failed: %s", e)

        # If no method worked
        raise RuntimeError("Failed to retrieve USD balance from underlying coinbase client.")

    # ----------------------------
    # Order placement with validation + retries
    # ----------------------------
    def create_order_safe(self, side: str, product_id: str, size_btc: Decimal, usd_size: Decimal, price_usd: Decimal):
        """
        Validate and attempt to place a market order. Returns the underlying client's response.

        Params:
          - side: 'buy' or 'sell'
          - product_id: e.g., 'BTC-USD'
          - size_btc: Decimal BTC amount to buy/sell
          - usd_size: Decimal USD equivalent (used for balance checks and logging)
          - price_usd: Decimal last price (for logging only)
        """
        if size_btc is None or usd_size is None:
            raise ValueError("size_btc and usd_size must be provided.")
        if size_btc <= 0:
            raise ValueError("Order size too small to place (size_btc <= 0).")
        if side not in ('buy', 'sell'):
            raise ValueError("side must be 'buy' or 'sell'.")

        # For buy orders, ensure we have sufficient USD available
        if side == 'buy':
            usd_bal = self.get_usd_balance()
            if usd_size > usd_bal:
                raise ValueError(f"Insufficient USD balance: need {usd_size}, have {usd_bal}")

        # Many clients expect string amounts
        size_str = format(size_btc, 'f')
        usd_str = format(usd_size, 'f')

        last_exc = None
        for attempt in range(3):
            try:
                logger.info("Placing order attempt %d: %s %s (btc=%s usd=%s price=%s)",
                            attempt + 1, side, product_id, size_str, usd_str, str(price_usd))

                # 1) try place_market_order(product_id=..., side=..., size=...)
                if hasattr(self.client, "place_market_order"):
                    resp = self.client.place_market_order(product_id=product_id, side=side, size=size_str)
                    # notify & log
                    try:
                        self._on_order_success(resp, side, product_id, size_btc, usd_size, price_usd)
                    except Exception as e:
                        logger.debug("post-order notify failed (ignored): %s", e)
                    return resp

                # 2) try create_order(product_id=..., side=..., order_type='market', size=...)
                if hasattr(self.client, "create_order"):
                    try:
                        resp = self.client.create_order(product_id=product_id, side=side, order_type='market', size=size_str)
                    except TypeError:
                        # try positional fallback
                        resp = self.client.create_order(product_id, side, 'market', size_str)
                    # notify & log
                    try:
                        self._on_order_success(resp, side, product_id, size_btc, usd_size, price_usd)
                    except Exception as e:
                        logger.debug("post-order notify failed (ignored): %s", e)
                    return resp

                # 3) try send_order or order(...)
                if hasattr(self.client, "send_order"):
                    resp = self.client.send_order(product_id=product_id, side=side, size=size_str, type='market')
                    try:
                        self._on_order_success(resp, side, product_id, size_btc, usd_size, price_usd)
                    except Exception as e:
                        logger.debug("post-order notify failed (ignored): %s", e)
                    return resp
                if hasattr(self.client, "order"):
                    resp = self.client.order(product_id=product_id, side=side, size=size_str, type='market')
                    try:
                        self._on_order_success(resp, side, product_id, size_btc, usd_size, price_usd)
                    except Exception as e:
                        logger.debug("post-order notify failed (ignored): %s", e)
                    return resp

                raise RuntimeError("No known order placement method found on coinbase client.")

            except Exception as e:
                last_exc = e
                logger.warning("Order attempt %d failed: %s", attempt + 1, e)
                time.sleep(0.4)

        logger.error("All order attempts failed. Last error: %s", last_exc)
        raise last_exc

    # ----------------------------
    # Order success handler / notifications
    # ----------------------------
    def _on_order_success(self, resp, side, product_id, size_btc: Decimal, usd_size: Decimal, price_usd: Decimal):
        """
        Called after an order is successfully placed/returned by the underlying client.
        - Writes a structured JSON line to stdout (captured by Render/Railway).
        - Optionally POSTs the same payload to webhook endpoints if env vars set.
        This method must never raise in production trading (we catch exceptions where it's called).
        """
        # Build a safe payload (do not include API keys or secrets)
        payload = {
            "event": "nija_order_placed",
            "side": side,
            "product_id": product_id,
            "size_btc": str(size_btc),
            "usd_size": str(usd_size),
            "price_usd": str(price_usd),
            "timestamp": int(time.time()),
            "response_sample": _summarize_response(resp)
        }

        # 1) Structured stdout log (Render/Railway capture)
        try:
            logger.info("ORDER_PLACED %s", json.dumps(payload))
        except Exception:
            # fallback to plain print in worst case
            try:
                print(json.dumps(payload), file=sys.stdout)
            except Exception:
                pass

        # 2) Optional webhook notifications (non-blocking / defensive)
        endpoints = [RENDER_LOG_ENDPOINT, RAILWAY_LOG_ENDPOINT, GENERIC_LOG_ENDPOINT]
        for ep in endpoints:
            if not ep:
                continue
            # Send minimal POST; swallow all errors and use short timeout
            try:
                if requests is None:
                    logger.debug("requests not available; skipping HTTP notify to %s", ep)
                    continue
                # If outbound secret is set, use signed_post helper; otherwise plain post
                try:
                    if NIJA_OUTBOUND_SECRET:
                        # signed_post raises if requests is None; we've already checked requests
                        _ = signed_post(ep, payload, NIJA_OUTBOUND_SECRET, requests)
                    else:
                        requests.post(ep, json=payload, headers={"Content-Type": "application/json"}, timeout=2.0)
                except Exception as e:
                    logger.debug("Webhook notify to %s failed (ignored): %s", ep, e)
            except Exception as e:
                # shouldn't happen, but be defensive
                logger.debug("Webhook path unexpected error (ignored): %s", e)


def _summarize_response(resp):
    """
    Produce a small, safe summary of the underlying client's response for telemetry.
    Avoid including raw auth tokens or bulky data.
    """
    try:
        if resp is None:
            return None
        # if dict-like, pick small keys if present
        if isinstance(resp, dict):
            return {k: resp.get(k) for k in ['id', 'status', 'filled_size', 'size', 'price'] if k in resp}
        # if object with attrs, try to map similar small set
        summary = {}
        for k in ('id', 'status', 'filled_size', 'size', 'price'):
            val = getattr(resp, k, None)
            if val is not None:
                summary[k] = val
        if summary:
            return summary
        # fallback to str(resp) truncated
        s = str(resp)
        return s if len(s) < 400 else s[:400] + "..."
    except Exception:
        return None


# Optional: convenience factory if you want to pass e.g. raw API keys here in future
def wrap_coinbase_client(raw_client):
    """
    Convenience helper to create the wrapper. Keeps imports in user code tiny:
      from nija_client import wrap_coinbase_client
      client = wrap_coinbase_client(my_coinbase_client)
    """
    return NijaClientWrapper(raw_client)


# Basic smoke-test block (only runs when file executed directly)
if __name__ == '__main__':
    # Quick smoke test using a very small mock-like object
    class _Mock:
        def __init__(self):
            self._usd = 12.0
            self.btc_price = 50000.0
            self.orders = []
        def get_spot_price(self, product_id): return float(self.btc_price)
        def get_account_balance(self, currency): return float(self._usd) if currency == 'USD' else 0.0
        def place_market_order(self, product_id, side, size):
            o = {"product_id": product_id, "side": side, "size": size, "status": "filled", "id": "mock-123"}
            self.orders.append(o)
            return o
        def get_accounts(self): return [{"currency": "USD", "available": float(self._usd), "balance": float(self._usd)}]

    mock = _Mock()
    wrapper = NijaClientWrapper(mock)
    price = wrapper.get_spot_price('BTC-USD')
    bal = wrapper.get_usd_balance()
    print("price:", price, "usd balance:", bal)
    from decimal import Decimal
    resp = wrapper.create_order_safe('buy', 'BTC-USD', Decimal('0.00002'), Decimal('1.00'), Decimal(str(price)))
    print("order resp:", resp)
