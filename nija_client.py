# nija_client.py
"""
Safer Coinbase CDP helper.

- DOES NOT raise on import if env vars missing (prevents container crash loops).
- Provides credentials_present(), validate_creds(), and clear error messages.
- HMAC signing supports raw secret or base64 secret.
- Simple GET/POST helpers with retries.
"""

import os
import time
import json
import requests
import hmac
import hashlib
import base64
from typing import Optional, Dict, Any, Tuple

# Env names (these must be set in Render)
API_KEY_ID     = os.getenv("COINBASE_KEY_NAME")       # e.g. organizations/.../apiKeys/...
API_KEY_SECRET = os.getenv("COINBASE_KEY_SECRET")     # base64 or raw secret
REQUEST_HOST   = os.getenv("COINBASE_REQUEST_HOST", "api.cdp.coinbase.com")
BASE_URL       = os.getenv("COINBASE_API_BASE", f"https://{REQUEST_HOST}")
CB_PASSPHRASE  = os.getenv("COINBASE_API_PASSPHRASE", "")

def credentials_present() -> bool:
    """Return True if both key id and secret are present."""
    return bool(API_KEY_ID and API_KEY_SECRET)

def debug_env_masked() -> Dict[str, str]:
    """Return masked view of env vars for logs (safe to print)."""
    def mask(s):
        if not s:
            return "NOT SET"
        if len(s) <= 8:
            return "*" * len(s)
        return s[:4] + "..." + s[-4:]
    return {
        "COINBASE_KEY_NAME": mask(API_KEY_ID),
        "COINBASE_KEY_SECRET": mask(API_KEY_SECRET),
        "COINBASE_REQUEST_HOST": REQUEST_HOST,
        "COINBASE_API_BASE": BASE_URL,
        "COINBASE_API_PASSPHRASE": "***" if CB_PASSPHRASE else "NOT SET"
    }

# Attempt to get secret bytes: prefer base64 decode, fall back to raw utf-8 bytes
def _secret_bytes(secret: str) -> bytes:
    if not secret:
        return b""
    # try strict base64 decode first
    try:
        b = base64.b64decode(secret, validate=True)
        if len(b) > 0:
            return b
    except Exception:
        pass
    # fall back to raw bytes
    return secret.encode("utf-8")

# Lazy SECRET_BYTES - computed when needed so import won't fail
def _get_secret_bytes() -> bytes:
    sec = os.getenv("COINBASE_KEY_SECRET", "")
    return _secret_bytes(sec)

def _generate_signature(method: str, request_path: str, body: str = "") -> Tuple[str, str]:
    """
    Compose message per Coinbase CDP: timestamp + method + request_path + body
    Return (timestamp, signature_base64)
    """
    secret_bytes = _get_secret_bytes()
    timestamp = str(int(time.time()))
    message = timestamp + method.upper() + request_path + (body or "")
    mac = hmac.new(secret_bytes, message.encode("utf-8"), hashlib.sha256)
    signature = base64.b64encode(mac.digest()).decode()
    return timestamp, signature

def _headers(method: str, request_path: str, body: Optional[Dict] = None) -> Dict[str, str]:
    body_json = ""
    if body is not None:
        body_json = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
    timestamp, signature = _generate_signature(method, request_path, body_json)
    headers = {
        "CB-ACCESS-KEY": os.getenv("COINBASE_KEY_NAME", ""),
        "CB-ACCESS-SIGN": signature,
        "CB-ACCESS-TIMESTAMP": timestamp,
        "Content-Type": "application/json",
    }
    if CB_PASSPHRASE:
        headers["CB-ACCESS-PASSPHRASE"] = CB_PASSPHRASE
    return headers

def _url(path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    return BASE_URL.rstrip("/") + path

# Safe wrappers with retries. They raise informative exceptions when credentials missing.
class MissingCredsError(Exception):
    pass

def _ensure_creds():
    if not credentials_present():
        raise MissingCredsError(
            "Coinbase credentials missing. Set COINBASE_KEY_NAME and COINBASE_KEY_SECRET in the service environment."
        )

def _safe_get(path: str, params: Dict = None, retries: int = 3, backoff: float = 1.0) -> Dict[str, Any]:
    _ensure_creds()
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            request_path = path if path.startswith("/") else "/" + path
            r = requests.get(_url(request_path), headers=_headers("GET", request_path, body=None), params=params, timeout=10)
            r.raise_for_status()
            return r.json()
        except requests.HTTPError as e:
            # If 401/403 propagate as is so caller can see it
            last_exc = e
            # if 4xx don't retry except maybe 429
            if r.status_code >= 400 and r.status_code < 500 and r.status_code != 429:
                raise
        except requests.RequestException as e:
            last_exc = e
        time.sleep(backoff * attempt)
    raise last_exc

def _safe_post(path: str, body: Dict, retries: int = 3, backoff: float = 1.0) -> Dict[str, Any]:
    _ensure_creds()
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            request_path = path if path.startswith("/") else "/" + path
            headers = _headers("POST", request_path, body=body)
            r = requests.post(_url(request_path), headers=headers, json=body, timeout=10)
            r.raise_for_status()
            return r.json()
        except requests.HTTPError as e:
            last_exc = e
            if r.status_code >= 400 and r.status_code < 500 and r.status_code != 429:
                raise
        except requests.RequestException as e:
            last_exc = e
        time.sleep(backoff * attempt)
    raise last_exc

# Public helpers

def get_account_balance() -> list:
    """
    Returns list of accounts from /v2/accounts (returns [] on error).
    Caller should handle exceptions (e.g., MissingCredsError or HTTP errors).
    """
    data = _safe_get("/v2/accounts")
    # Many implementations return {"data": [...]}
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    # If API returns list directly:
    if isinstance(data, list):
        return data
    return []

def find_funded_accounts(min_usd: float = 0.0) -> list:
    accts = get_account_balance()
    funded = []
    for a in accts:
        try:
            avail = float(a.get("available", 0) or 0)
        except Exception:
            avail = 0.0
        if avail > 0:
            funded.append(a)
    # prefer USD accounts meeting min_usd if asked
    if min_usd > 0:
        usd_ok = [a for a in funded if a.get("currency") == "USD" and float(a.get("available", 0) or 0) >= min_usd]
        if usd_ok:
            return usd_ok
    return funded

def calculate_position_size(account: dict, risk_min_pct: float = 2.0, risk_max_pct: float = 10.0, risk_pct: Optional[float] = None) -> str:
    try:
        available = float(account.get("available", 0) or 0)
    except Exception:
        available = 0.0
    if risk_pct is None:
        risk_pct = max(risk_min_pct, min(risk_max_pct, (risk_min_pct + risk_max_pct) / 2.0))
    size = available * (risk_pct / 100.0)
    return f"{size:.8f}"

def place_order(product_id: str, side: str, size: str = None, price: Optional[str] = None, extra_body: Optional[Dict] = None, test: bool = False) -> Dict[str, Any]:
    """
    Place an order. If `test` True -> simulate.
    extra_body can include 'funds' for market buys if your API expects that.
    """
    if test:
        return {"simulated": True, "product_id": product_id, "side": side, "size": size, "price": price, "extra": extra_body}

    body = {"type": "market" if price is None else "limit", "side": side.lower(), "product_id": product_id}
    if size is not None:
        body["size"] = str(size)
    if price is not None:
        body["price"] = str(price)
    if extra_body:
        body.update(extra_body)
    return _safe_post("/v2/orders", body)
