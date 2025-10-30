# nija_coinbase_client.py
import os
import logging
import requests
from decimal import Decimal
from nija_coinbase_jwt import get_jwt_token

logger = logging.getLogger("nija_coinbase_client")
API_BASE = os.environ.get("COINBASE_API_BASE", "https://api.coinbase.com").rstrip("/")

def _headers():
    token = get_jwt_token()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

def api_get(path):
    url = f"{API_BASE}{path}"
    resp = requests.get(url, headers=_headers(), timeout=10)
    logger.debug("[NIJA-API] GET %s -> %s", url, resp.status_code)
    resp.raise_for_status()
    return resp.json()

def api_post(path, json_body):
    url = f"{API_BASE}{path}"
    resp = requests.post(url, headers=_headers(), json=json_body, timeout=10)
    logger.debug("[NIJA-API] POST %s -> %s", url, resp.status_code)
    resp.raise_for_status()
    return resp.json()

# Convenience: get accounts (v2)
def get_accounts():
    # v2 accounts endpoint
    return api_get("/v2/accounts")

def get_usd_balance():
    try:
        data = get_accounts()
        # Coinbase v2 returns data list under "data"
        for a in data.get("data", []):
            if a.get("currency") == "USD" or a.get("currency_code") == "USD":
                # balance may be nested
                bal = a.get("balance") or a.get("available_balance") or {}
                val = bal.get("amount") or bal.get("value") or bal.get("balance") or bal.get("amount")
                try:
                    return Decimal(str(val))
                except Exception:
                    continue
    except Exception as e:
        logger.warning("[NIJA] get_usd_balance error: %s", e)
    return Decimal("0")

# Place an order via Advanced Trade API (brokerage)
def place_order_market_quote(product_id: str, side: str, quote_size: str, client_order_id: str = None):
    """
    Places a market IOC order using quote_size (USD).
    product_id: e.g. 'BTC-USD'
    side: 'BUY' or 'SELL'
    quote_size: string amount in quote currency, e.g. "10.00"
    Returns the API JSON response.
    """
    if client_order_id is None:
        import uuid
        client_order_id = str(uuid.uuid4())

    body = {
      "client_order_id": client_order_id,
      "product_id": product_id,
      "side": side.upper(),  # BUY or SELL
      "order_configuration": {
        "market_market_ioc": {
          "quote_size": str(quote_size)
        }
      }
    }
    # endpoint per docs
    return api_post("/api/v3/brokerage/orders", body)
