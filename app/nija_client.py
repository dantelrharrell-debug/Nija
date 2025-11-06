# nija_client.py
import os
import time
import json
import requests
import hmac
import hashlib
import base64
from typing import Tuple, Optional, Dict, Any

# Environment
API_KEY_ID     = os.getenv("COINBASE_KEY_NAME")
API_KEY_SECRET = os.getenv("COINBASE_KEY_SECRET")
REQUEST_HOST   = os.getenv("COINBASE_REQUEST_HOST", "api.cdp.coinbase.com")
BASE_URL       = os.getenv("COINBASE_API_BASE", f"https://{REQUEST_HOST}")
CB_PASSPHRASE  = os.getenv("COINBASE_API_PASSPHRASE", "")  # optional in some setups

if not API_KEY_ID or not API_KEY_SECRET:
    raise EnvironmentError("Missing Coinbase CDP API credentials: set COINBASE_KEY_NAME and COINBASE_KEY_SECRET")

# detect secret bytes: try base64 decode, otherwise use raw bytes
def _secret_bytes(secret: str) -> bytes:
    try:
        # try base64 decode
        b = base64.b64decode(secret, validate=True)
        if len(b) > 0:
            return b
    except Exception:
        pass
    return secret.encode("utf-8")

_SECRET_BYTES = _secret_bytes(API_KEY_SECRET)

# Compose signature per Coinbase CDP Exchange REST spec:
# message = timestamp + method + request_path + body
def _generate_signature(method: str, request_path: str, body: Optional[str] = "") -> Tuple[str,str]:
    timestamp = str(int(time.time()))
    body_str = body or ""
    message = timestamp + method.upper() + request_path + body_str
    mac = hmac.new(_SECRET_BYTES, message.encode("utf-8"), hashlib.sha256)
    signature = base64.b64encode(mac.digest()).decode()
    return timestamp, signature

def _headers(method: str, request_path: str, body: Optional[Dict]=None) -> Dict[str,str]:
    body_json = ""
    if body is not None:
        # compact JSON exactly as Coinbase expects (no spaces)
        body_json = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
    timestamp, signature = _generate_signature(method, request_path, body_json)
    headers = {
        "CB-ACCESS-KEY": API_KEY_ID,
        "CB-ACCESS-SIGN": signature,
        "CB-ACCESS-TIMESTAMP": timestamp,
        "Content-Type": "application/json",
    }
    # optional passphrase if your key uses one
    if CB_PASSPHRASE:
        headers["CB-ACCESS-PASSPHRASE"] = CB_PASSPHRASE
    return headers

def _url(path: str) -> str:
    # path must begin with "/"
    return BASE_URL.rstrip("/") + path

# Generic safe GET with simple retries
def _safe_get(path: str, params: Dict=None, retries: int=3, backoff: float=1.0) -> Dict[str,Any]:
    last_exc = None
    for attempt in range(1, retries+1):
        try:
            request_path = path  # includes leading slash
            url = _url(request_path)
            headers = _headers("GET", request_path, body=None)
            r = requests.get(url, headers=headers, params=params, timeout=10)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            last_exc = e
            time.sleep(backoff * attempt)
    raise last_exc

def _safe_post(path: str, body: Dict, retries: int=3, backoff: float=1.0) -> Dict[str,Any]:
    last_exc = None
    for attempt in range(1, retries+1):
        try:
            request_path = path
            url = _url(request_path)
            # headers must include body when signing
            headers = _headers("POST", request_path, body=body)
            r = requests.post(url, headers=headers, json=body, timeout=10)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            last_exc = e
            time.sleep(backoff * attempt)
    raise last_exc

# Public helpers

def get_account_balance() -> list:
    """
    Returns list of accounts (Coinbase returns {data:[...]}).
    """
    resp = _safe_get("/v2/accounts")
    return resp.get("data", [])

def calculate_position_size(account: dict, risk_min_pct: float=2.0, risk_max_pct: float=10.0, risk_pct: Optional[float]=None) -> str:
    """
    Determine trade size in account currency units.
    If account is USD, returns USD amount to deploy (string).
    If account is crypto, returns crypto amount to use.
    Default risk_pct is set to midpoint between min and max if not specified.
    """
    available = float(account.get("available", 0) or 0)
    if risk_pct is None:
        risk_pct = max(risk_min_pct, min(risk_max_pct, (risk_min_pct + risk_max_pct) / 2.0))
    size = available * (risk_pct / 100.0)
    # Coinbase expects string amounts; rounding to 8 decimal places to be safe.
    return f"{size:.8f}"

def place_order(product_id: str, side: str, size: str, price: Optional[str]=None, test: bool=False) -> dict:
    """
    Place market or limit order.
    If `test` True, will not send order; returns simulated result.
    """
    body = {
        "type": "market" if price is None else "limit",
        "side": side.lower(),
        "product_id": product_id,
        "size": str(size)
    }
    if price:
        body["price"] = str(price)
    if test:
        return {"simulated": True, "order": body}
    return _safe_post("/v2/orders", body)

# small convenience: find USD account or the first funded account
def find_funded_accounts(min_usd: float=0.0) -> list:
    accounts = get_account_balance()
    funded = []
    for a in accounts:
        try:
            avail = float(a.get("available", 0) or 0)
        except Exception:
            avail = 0.0
        if avail > 0 and (a.get("currency") is not None):
            funded.append(a)
    # If filtering by min_usd and we want USD account first:
    if min_usd > 0:
        usd_accounts = [a for a in funded if a.get("currency") == "USD" and float(a.get("available", 0) or 0) >= min_usd]
        if usd_accounts:
            return usd_accounts
    return funded
