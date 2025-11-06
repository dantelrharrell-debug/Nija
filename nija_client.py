"""
nija_client.py
--------------
Complete Coinbase Advanced Trade helper for fast live trading.

Features:
- On-the-fly CDP JWT generation (ES256) using COINBASE_API_SECRET (PEM) or COINBASE_PEM_PATH.
- List accounts (paginated).
- Place market BUY by USD quote using market_market_ioc.
- Dry-run / Sandbox behavior when LIVE_TRADING != "1".
- Exponential backoff + jitter retries for HTTP calls.
- Logging and optional webhook notifications (e.g. Slack, Discord, PagerDuty).
- Safety: refuses to place production orders unless LIVE_TRADING == "1".

Install:
    pip install requests pyjwt[crypto]

ENV VARS (required / optional):
- COINBASE_API_KEY        (required) e.g. "organizations/{org}/apiKeys/{id}" used as kid/sub
- COINBASE_API_SECRET     (required) PEM private key string (preserve newlines) OR escaped \\n
- COINBASE_PEM_PATH       (optional) file path to PEM if not using COINBASE_API_SECRET
- LIVE_TRADING            (optional) set to "1" to enable production order submission
- USE_SANDBOX             (optional) if "1", forces sandbox endpoints (useful for testing)
- WEBHOOK_URL             (optional) POST JSON to this URL on order success/failure
- RETRY_MAX               (optional) max retry attempts (default 5)
- RETRY_BASE_SECONDS      (optional) base backoff seconds (default 0.5)
- TIMEOUT_SECONDS         (optional) HTTP timeout seconds (default 15)

CAUTION:
- Never commit COINBASE_API_SECRET. Use secret managers.
- Test thoroughly in sandbox and use small orders when first going live.
"""

from typing import Optional, Dict, Any, List
import os
import time
import uuid
import json
import random
import logging
import requests
import jwt  # PyJWT
from functools import wraps

# ------------------------
# Configuration & Logging
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

COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_PEM = os.getenv("COINBASE_API_SECRET")
COINBASE_PEM_PATH = os.getenv("COINBASE_PEM_PATH")
LIVE_TRADING = os.getenv("LIVE_TRADING", "0") == "1"
FORCE_SANDBOX = os.getenv("USE_SANDBOX", "0") == "1"
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # optional

# Sandbox vs Prod endpoints
API_HOST = "api.coinbase.com"
if FORCE_SANDBOX:
    API_BASE = "https://api-public.sandbox.pro.coinbase.com"  # sandbox host (note: some CDP sandboxes differ)
    LOG.info("FORCING SANDBOX mode via USE_SANDBOX=1")
else:
    API_BASE = "https://api.coinbase.com"

ACCOUNTS_ENDPOINT = API_BASE + "/api/v3/brokerage/accounts"
ORDERS_ENDPOINT = API_BASE + "/api/v3/brokerage/orders"
PRICE_ENDPOINT_TEMPLATE = API_BASE + "/v2/prices/{pair}/spot"  # public spot price

# ------------------------
# Utilities: backoff + retries
# ------------------------
def retry_with_backoff(max_attempts: int = RETRY_MAX, base: float = RETRY_BASE, allowed_statuses: List[int] = None):
    """
    Decorator to retry a function (typically HTTP call) with exponential backoff and jitter.
    allowed_statuses: if provided, treat these HTTP statuses as retryable.
    """
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
                    status = None
                    if he.response is not None:
                        status = he.response.status_code
                    # Retry on allowed statuses
                    if status and status in allowed_statuses and attempt < max_attempts:
                        sleep = base * (2 ** (attempt - 1))  # exponential
                        jitter = random.uniform(0, sleep * 0.3)
                        delay = sleep + jitter
                        LOG.warning("HTTP %s error; retry %d/%d after %.2fs", status, attempt, max_attempts, delay)
                        time.sleep(delay)
                        continue
                    LOG.error("HTTP error (no retry): %s", he)
                    raise
                except (requests.ConnectionError, requests.Timeout) as e:
                    if attempt < max_attempts:
                        sleep = base * (2 ** (attempt - 1))
                        jitter = random.uniform(0, sleep * 0.3)
                        delay = sleep + jitter
                        LOG.warning("Network error; retry %d/%d after %.2fs", attempt, max_attempts, delay)
                        time.sleep(delay)
                        continue
                    LOG.error("Network error, max retries reached: %s", e)
                    raise
                except Exception:
                    # Other exceptions: no retry by default
                    raise
        return wrapper
    return deco

# ------------------------
# JWT generation (CDP)
# ------------------------
def _load_private_key_pem() -> str:
    """
    Load PEM from env var or file. If COINBASE_API_SECRET contains escaped \\n, convert to real newlines.
    """
    pem = COINBASE_PEM
    if pem and "\\n" in pem:
        pem = pem.replace("\\n", "\n")
    if not pem and COINBASE_PEM_PATH:
        with open(COINBASE_PEM_PATH, "r") as f:
            pem = f.read()
    if not pem:
        raise RuntimeError("COINBASE_API_SECRET or COINBASE_PEM_PATH must be set (private key PEM)")
    return pem

def generate_cdp_jwt(api_key: str, lifetime_seconds: int = 120, method: Optional[str] = None,
                     host: Optional[str] = None, path: Optional[str] = None) -> str:
    """
    Generate short-lived JWT for Coinbase CDP.
    - api_key: value used as kid/sub (COINBASE_API_KEY)
    """
    if not api_key:
        raise RuntimeError("COINBASE_API_KEY must be set")
    private_key = _load_private_key_pem()
    now = int(time.time())
    payload = {
        "iss": "cdp",
        "nbf": now,
        "iat": now,
        "exp": now + lifetime_seconds,
        "sub": api_key
    }
    if method and host and path:
        payload["uris"] = [f"{method.upper()} {host} {path}"]

    headers = {"kid": api_key, "nonce": uuid.uuid4().hex}
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token

# ------------------------
# HTTP helpers (with retry)
# ------------------------
@retry_with_backoff()
def _http_get(url: str, headers: Dict[str, str] = None, params: Dict[str, Any] = None, timeout: float = TIMEOUT):
    r = requests.get(url, headers=headers or {}, params=params or {}, timeout=timeout)
    try:
        r.raise_for_status()
    except requests.HTTPError:
        # attach response to exception for retry decorator to inspect
        raise
    return r

@retry_with_backoff()
def _http_post(url: str, headers: Dict[str, str] = None, json_body: Any = None, timeout: float = TIMEOUT):
    r = requests.post(url, headers=headers or {}, json=json_body or {}, timeout=timeout)
    try:
        r.raise_for_status()
    except requests.HTTPError:
        raise
    return r

# ------------------------
# Webhook notifications
# ------------------------
def notify_webhook(event_type: str, payload: Dict[str, Any]):
    """
    POSTs a JSON payload to WEBHOOK_URL if set. Silent if not configured.
    Keeps failure non-fatal (logs only).
    """
    if not WEBHOOK_URL:
        return
    try:
        body = {"event": event_type, "timestamp": int(time.time()), "payload": payload}
        # best effort: no retries to avoid webhook blocking; you can change this
        r = requests.post(WEBHOOK_URL, json=body, timeout=5)
        r.raise_for_status()
        LOG.info("Webhook notify success: %s", event_type)
    except Exception as e:
        LOG.warning("Webhook notify failed: %s", e)

# ------------------------
# Core: list accounts (paginated)
# ------------------------
def list_accounts(limit_per_page: int = 100) -> List[Dict[str, Any]]:
    """
    Return list of accounts (raw objects from Coinbase). Uses JWT per request.
    """
    if not COINBASE_API_KEY:
        raise RuntimeError("COINBASE_API_KEY required")

    all_accounts = []
    params = {"limit": limit_per_page}
    url = ACCOUNTS_ENDPOINT

    while True:
        token = generate_cdp_jwt(COINBASE_API_KEY, method="GET", host=API_HOST, path="/api/v3/brokerage/accounts")
        headers = {"Authorization": f"Bearer {token}"}
        LOG.debug("GET %s params=%s", url, params)
        r = _http_get(url, headers=headers, params=params)
        j = r.json()
        accounts = j.get("accounts", []) or []
        all_accounts.extend(accounts)
        if j.get("has_next"):
            params["cursor"] = j.get("cursor")
        else:
            break
    LOG.info("Fetched %d accounts", len(all_accounts))
    return all_accounts

# ------------------------
# Core: place market buy by USD quote (market_market_ioc)
# ------------------------
def place_market_buy_by_quote(product_id: str, usd_quote: float, client_order_id: Optional[str] = None,
                              dry_run: Optional[bool] = None) -> Dict[str, Any]:
    """
    Place a market BUY using quote_size in USD.
    - product_id: e.g. "BTC-USD"
    - usd_quote: USD amount to spend
    - dry_run: if True forces a simulated run even when LIVE_TRADING=1; if None, obeys LIVE_TRADING flag
    Returns response JSON (or simulated response if dry-run).
    """
    if usd_quote <= 0:
        raise ValueError("usd_quote must be > 0")
    if not COINBASE_API_KEY:
        raise RuntimeError("COINBASE_API_KEY required")

    simulate = True if (dry_run if dry_run is not None else not LIVE_TRADING) else False

    # If sandbox enforced by env, use sandbox endpoints or still generate JWT? For many sandboxes you may not need JWT;
    # here we still generate JWT for parity, but you can change behavior if Coinbase sandbox requires different auth.
    if simulate:
        # Dry-run: do not submit; build a simulated response object similar to production response
        simulated = {
            "id": "sim-" + str(uuid.uuid4()),
            "client_order_id": client_order_id or str(uuid.uuid4()),
            "product_id": product_id,
            "side": "BUY",
            "order_configuration": {"market_market_ioc": {"quote_size": f"{usd_quote:.2f}"}},
            "status": "SIMULATED",
            "filled_size": "0",
            "filled_value": f"{usd_quote:.2f}",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }
        LOG.info("DRY-RUN ORDER (not sent): %s %s %s", simulated["client_order_id"], product_id, usd_quote)
        notify_webhook("order.simulated", simulated)
        return {"simulated": True, "order": simulated}

    # Production path: LIVE_TRADING==True
    token = generate_cdp_jwt(COINBASE_API_KEY, method="POST", host=API_HOST, path="/api/v3/brokerage/orders")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "client_order_id": client_order_id or str(uuid.uuid4()),
        "product_id": product_id,
        "side": "BUY",
        "order_configuration": {
            "market_market_ioc": {
                "quote_size": f"{usd_quote:.2f}"
            }
        }
    }
    LOG.info("Submitting order client_order_id=%s product=%s usd_quote=%s", payload["client_order_id"], product_id, usd_quote)
    try:
        r = _http_post(ORDERS_ENDPOINT, headers=headers, json_body=payload)
        j = r.json()
        LOG.info("Order submitted: id=%s status=%s", j.get("id"), j.get("status"))
        notify_webhook("order.submitted", {"request": payload, "response": j})
        return {"simulated": False, "order": j}
    except Exception as e:
        LOG.exception("Order submission failed")
        notify_webhook("order.failed", {"request": payload, "error": str(e)})
        raise

# ------------------------
# Optional: helper to get spot price (public)
# ------------------------
@retry_with_backoff()
def get_spot_price_usd(currency: str) -> float:
    """
    Returns USD price per 1 unit of `currency` using public spot endpoint.
    For USD-like stablecoins returns 1.0
    """
    c = currency.upper()
    if c in ("USD", "USDC", "USDT"):
        return 1.0
    pair = f"{c}-USD"
    url = PRICE_ENDPOINT_TEMPLATE.format(pair=pair)
    r = _http_get(url)
    j = r.json()
    amt = j.get("data", {}).get("amount")
    if amt is None:
        raise RuntimeError("No spot price returned for " + currency)
    return float(amt)

# ------------------------
# CLI / Example usage (safe)
# ------------------------
if __name__ == "__main__":
    # Quick smoke tests - safe by default (won't trade unless LIVE_TRADING=1)
    try:
        LOG.info("=== NIJA CLIENT START ===")
        LOG.info("LIVE_TRADING=%s FORCE_SANDBOX=%s", LIVE_TRADING, FORCE_SANDBOX)
        LOG.info("Listing accounts for sanity check...")
        accounts = list_accounts()
        # Print summary
        for a in accounts[:10]:
            # available_balance may be nested differently in some responses; guard accordingly
            avail = a.get("available_balance") or {}
            val = avail.get("value") or a.get("available_balance", {}).get("amount") or "0"
            LOG.info("acct %s | %s | %s", a.get("uuid"), a.get("currency", "n/a"), val)
        LOG.info("Total accounts fetched: %d", len(accounts))

        # Example dry-run buy (won't execute unless LIVE_TRADING=1)
        LOG.info("Attempting example buy dry-run (10 USD BTC-USD)...")
        resp = place_market_buy_by_quote("BTC-USD", 10.0, dry_run=None)  # obeys LIVE_TRADING flag
        LOG.info("Place result: %s", json.dumps(resp, indent=2))
    except Exception as exc:
        LOG.exception("Error in nija_client main: %s", exc)
