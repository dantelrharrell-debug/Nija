# nija_client.py
import os
import time
import base64
import logging
import requests
from ecdsa import SigningKey, NIST256p

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nija_client")

# -----------------------------
# Environment / API settings
# -----------------------------
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")  # single-line PEM with \n
API_BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")  # Advanced default

if not API_KEY or not API_SECRET:
    log.error("Missing Coinbase credentials.")
    raise RuntimeError("COINBASE_API_KEY and COINBASE_API_SECRET must be set")

# Fix line breaks in ECDSA private key
if "\\n" in API_SECRET:
    API_SECRET = API_SECRET.replace("\\n", "\n")

# Load ECDSA private key
try:
    _PRIVATE_KEY = SigningKey.from_pem(API_SECRET)
    log.info("Coinbase ECDSA private key loaded successfully.")
except Exception as e:
    log.exception("Failed to load private key: %s", e)
    raise

# -----------------------------
# Signing function
# -----------------------------
def _sign(timestamp: str, method: str, path: str, body: str = "") -> str:
    """
    Returns base64-encoded ECDSA signature for Coinbase Advanced API.
    """
    message = timestamp + method.upper() + path + (body or "")
    sig = _PRIVATE_KEY.sign(message.encode())  # ECDSA sign
    return base64.b64encode(sig).decode()

# -----------------------------
# Request wrapper
# -----------------------------
def _cdp_request(method: str, path: str, body: str = "") -> requests.Response:
    timestamp = str(int(time.time()))
    signature_b64 = _sign(timestamp, method, path, body)
    
    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": signature_b64,
        "CB-ACCESS-TIMESTAMP": timestamp,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    url = API_BASE.rstrip("/") + path
    resp = requests.request(method, url, headers=headers, data=body, timeout=15)
    if resp.status_code == 401:
        log.error("Unauthorized: check Coinbase API key/private key")
        raise RuntimeError("Unauthorized: check Coinbase API key/private key")
    return resp

# -----------------------------
# Fetch USD spot balance
# -----------------------------
def get_usd_spot_balance() -> float:
    """
    Returns USD balance as float. Uses /v2/accounts route.
    """
    try:
        resp = _cdp_request("GET", "/v2/accounts")
        data = resp.json()
    except Exception as e:
        log.error("Failed to decode JSON: status=%s body=%s", getattr(resp, 'status_code', None), getattr(resp, 'text', None))
        raise RuntimeError("Failed to fetch USD Spot balance") from e

    for acct in data.get("data", []):
        balance = acct.get("balance", {})
        if balance.get("currency") == "USD":
            return float(balance.get("amount", 0))
    return 0.0

# -----------------------------
# Fetch all accounts (optional)
# -----------------------------
def get_all_accounts() -> list:
    try:
        resp = _cdp_request("GET", "/v2/accounts")
        return resp.json().get("data", [])
    except Exception as e:
        log.error("Failed to fetch all accounts: %s", e)
        raise
