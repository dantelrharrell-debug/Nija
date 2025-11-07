# nija_client.py
import os
import time
import uuid
import json
import random
import logging
import requests
import jwt
from functools import wraps
from typing import Optional, Dict, Any, List

# ------------------------
# Logging setup
# ------------------------
LOG = logging.getLogger("nija_client")
LOG.setLevel(os.getenv("LOG_LEVEL", "INFO"))
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
if not LOG.handlers:
    LOG.addHandler(handler)

RETRY_MAX = int(os.getenv("RETRY_MAX", "5"))
RETRY_BASE = float(os.getenv("RETRY_BASE_SECONDS", "0.5"))
TIMEOUT = float(os.getenv("TIMEOUT_SECONDS", "15"))

# ------------------------
# Retry decorator
# ------------------------
def retry_with_backoff(max_attempts: int = RETRY_MAX, base: float = RETRY_BASE,
                       allowed_statuses: List[int] = None):
    allowed_statuses = allowed_statuses or [429, 500, 502, 503, 504]

    def deco(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            attempt = 0
            while True:
                try:
                    attempt += 1
                    return func(*args, **kwargs)
                except requests.HTTPError as he:
                    status = he.response.status_code if he.response else None
                    if status and status in allowed_statuses and attempt < max_attempts:
                        sleep = base * (2 ** (attempt - 1))
                        jitter = random.uniform(0, sleep * 0.3)
                        LOG.warning("HTTP %s error; retry %d/%d after %.2fs", status, attempt, max_attempts, sleep + jitter)
                        time.sleep(sleep + jitter)
                        continue
                    LOG.error("HTTP error (no retry): %s", he)
                    raise
                except (requests.ConnectionError, requests.Timeout) as e:
                    if attempt < max_attempts:
                        sleep = base * (2 ** (attempt - 1))
                        jitter = random.uniform(0, sleep * 0.3)
                        LOG.warning("Network error; retry %d/%d after %.2fs", attempt, max_attempts, sleep + jitter)
                        time.sleep(sleep + jitter)
                        continue
                    LOG.error("Network error, max retries reached: %s", e)
                    raise
        return wrapper
    return deco

# ------------------------
# CoinbaseClient class
# ------------------------
class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.private_key_pem = self._load_private_key_pem()
        self.live_trading = os.getenv("LIVE_TRADING", "0") == "1"
        self.force_sandbox = os.getenv("USE_SANDBOX", "0") == "1"
        self.webhook_url = os.getenv("WEBHOOK_URL")

        self.api_host = "api.coinbase.com"
        if self.force_sandbox:
            self.api_base = "https://api-public.sandbox.pro.coinbase.com"
            LOG.info("FORCING SANDBOX mode")
        else:
            self.api_base = "https://api.coinbase.com"

        self.accounts_endpoint = self.api_base + "/api/v3/brokerage/accounts"
        self.orders_endpoint = self.api_base + "/api/v3/brokerage/orders"
        self.price_endpoint_template = self.api_base + "/v2/prices/{pair}/spot"

    # ------------------------
    # Private helpers
    # ------------------------
    def _load_private_key_pem(self) -> str:
        pem = os.getenv("COINBASE_API_SECRET")
        path = os.getenv("COINBASE_PEM_PATH")
        if pem and "\\n" in pem:
            pem = pem.replace("\\n", "\n")
        if not pem and path:
            with open(path, "r") as f:
                pem = f.read()
        if not pem:
            raise RuntimeError("COINBASE_API_SECRET or COINBASE_PEM_PATH required")
        return pem

    def _generate_jwt(self, lifetime_seconds: int = 120, method: Optional[str] = None,
                      host: Optional[str] = None, path: Optional[str] = None) -> str:
        now = int(time.time())
        payload = {
            "iss": "cdp",
            "iat": now,
            "nbf": now,
            "exp": now + lifetime_seconds,
            "sub": self.api_key
        }
        if method and host and path:
            payload["uris"] = [f"{method.upper()} {host} {path}"]

        headers = {"kid": self.api_key, "nonce": uuid.uuid4().hex}
        token = jwt.encode(payload, self.private_key_pem, algorithm="ES256", headers=headers)
        if isinstance(token, bytes):
            token = token.decode("utf-8")
        return token

    def _auth_header(self, method: str = "GET", path: str = "") -> Dict[str, str]:
        token = self._generate_jwt(method=method, host=self.api_host, path=path)
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def _notify_webhook(self, event_type: str, payload: Dict[str, Any]):
        if not self.webhook_url:
            return
        try:
            body = {"event": event_type, "timestamp": int(time.time()), "payload": payload}
            r = requests.post(self.webhook_url, json=body, timeout=5)
            r.raise_for_status()
            LOG.info("Webhook notify success: %s", event_type)
        except Exception as e:
            LOG.warning("Webhook notify failed: %s", e)

    @retry_with_backoff()
    def _http_get(self, url: str, headers: Dict[str, str] = None, params: Dict[str, Any] = None, timeout: float = 15):
        r = requests.get(url, headers=headers or {}, params=params or {}, timeout=timeout)
        r.raise_for_status()
        return r

    @retry_with_backoff()
    def _http_post(self, url: str, headers: Dict[str, str] = None, json_body: Any = None, timeout: float = 15):
        r = requests.post(url, headers=headers or {}, json=json_body or {}, timeout=timeout)
        r.raise_for_status()
        return r

    # ------------------------
    # Public methods
    # ------------------------
    def list_accounts(self, limit_per_page: int = 100) -> List[Dict[str, Any]]:
        all_accounts = []
        params = {"limit": limit_per_page}
        url = self.accounts_endpoint

        while True:
            headers = self._auth_header(method="GET", path="/api/v3/brokerage/accounts")
            r = self._http_get(url, headers=headers, params=params)
            j = r.json()
            accounts = j.get("accounts", []) or []
            all_accounts.extend(accounts)
            if j.get("has_next"):
                params["cursor"] = j.get("cursor")
            else:
                break
        LOG.info("Fetched %d accounts", len(all_accounts))
        return all_accounts

    def place_market_buy_by_quote(self, product_id: str, usd_quote: float, client_order_id: Optional[str] = None,
                                  dry_run: Optional[bool] = None) -> Dict[str, Any]:
        return self._place_order("BUY", product_id, usd_quote, client_order_id, dry_run)

    def place_market_sell_by_quote(self, product_id: str, usd_quote: float, client_order_id: Optional[str] = None,
                                   dry_run: Optional[bool] = None) -> Dict[str, Any]:
        return self._place_order("SELL", product_id, usd_quote, client_order_id, dry_run)

    def _place_order(self, side: str, product_id: str, usd_quote: float, client_order_id: Optional[str], dry_run: Optional[bool]):
        if usd_quote <= 0:
            raise ValueError("usd_quote must be > 0")

        simulate = True if (dry_run if dry_run is not None else not self.live_trading) else False

        if simulate:
            simulated = {
                "id": "sim-" + str(uuid.uuid4()),
                "client_order_id": client_order_id or str(uuid.uuid4()),
                "product_id": product_id,
                "side": side,
                "order_configuration": {"market_market_ioc": {"quote_size": f"{usd_quote:.2f}"}},
                "status": "SIMULATED",
                "filled_size": "0",
                "filled_value": f"{usd_quote:.2f}",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            }
            LOG.info("DRY-RUN %s ORDER: %s", side, simulated["client_order_id"])
            self._notify_webhook("order.simulated", simulated)
            return {"simulated": True, "order": simulated}

        headers = self._auth_header(method="POST", path="/api/v3/brokerage/orders")
        payload = {
            "client_order_id": client_order_id or str(uuid.uuid4()),
            "product_id": product_id,
            "side": side,
            "order_configuration": {"market_market_ioc": {"quote_size": f"{usd_quote:.2f}"}}
        }
        LOG.info("Submitting %s order: client_order_id=%s product=%s usd_quote=%s",
                 side, payload["client_order_id"], product_id, usd_quote)
        try:
            r = self._http_post(self.orders_endpoint, headers=headers, json_body=payload)
            j = r.json()
            LOG.info("%s Order submitted: id=%s status=%s", side, j.get("id"), j.get("status"))
            self._notify_webhook("order.submitted", {"request": payload, "response": j})
            return {"simulated": False, "order": j}
        except Exception as e:
            LOG.exception("%s order submission failed", side)
            self._notify_webhook("order.failed", {"request": payload, "error": str(e)})
            raise

    @retry_with_backoff()
    def get_spot_price_usd(self, currency: str) -> float:
        c = currency.upper()
        if c in ("USD", "USDC", "USDT"):
            return 1.0
        pair = f"{c}-USD"
        url = self.price_endpoint_template.format(pair=pair)
        r = self._http_get(url)
        j = r.json()
        amt = j.get("data", {}).get("amount")
        if amt is None:
            raise RuntimeError("No spot price returned for " + currency)
        return float(amt)

# ------------------------
# Quick CLI test
# ------------------------
if __name__ == "__main__":
    try:
        client = CoinbaseClient()
        LOG.info("Listing accounts...")
        accounts = client.list_accounts()
        for a in accounts[:10]:
            avail = a.get("available_balance") or {}
            val = avail.get("value") or avail.get("amount") or "0"
            LOG.info("acct %s | %s | %s", a.get("uuid"), a.get("currency", "n/a"), val)

        LOG.info("Attempting example dry-run buy (10 USD BTC-USD)...")
        resp = client.place_market_buy_by_quote("BTC-USD", 10.0)
        LOG.info("Buy result: %s", json.dumps(resp, indent=2))

        LOG.info("Attempting example dry-run sell (10 USD BTC-USD)...")
        resp2 = client.place_market_sell_by_quote("BTC-USD", 10.0)
        LOG.info("Sell result: %s", json.dumps(resp2, indent=2))
    except Exception as exc:
        LOG.exception("Error in nija_client CLI: %s", exc)
