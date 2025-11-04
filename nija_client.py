# nija_client.py
import os
import time
import base64
import logging
import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_pem_private_key

# ----------------------------
# Logging
# ----------------------------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nija_client")

# ----------------------------
# Load environment variables
# ----------------------------
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")
PASSPHRASE = ""  # Coinbase Advanced keys do not use passphrase

if not API_KEY or not API_SECRET:
    log.error("Missing Coinbase credentials.")
    raise RuntimeError("COINBASE_API_KEY and COINBASE_API_SECRET must be set")

# Replace literal \n sequences with real newlines
if "\\n" in API_SECRET:
    API_SECRET = API_SECRET.replace("\\n", "\n")

# ----------------------------
# Load ECDSA private key
# ----------------------------
try:
    _PRIVATE_KEY = load_pem_private_key(API_SECRET.encode(), password=None)
    log.info("Coinbase ECDSA private key loaded successfully.")
except Exception as e:
    log.exception("Failed to load private key: %s", e)
    raise

# ----------------------------
# Helper: sign request
# ----------------------------
def sign_request(timestamp: str, method: str, path: str, body: str = "") -> str:
    message = (timestamp + method.upper() + path + (body or "")).encode()
    signature_der = _PRIVATE_KEY.sign(message, ec.ECDSA(hashes.SHA256()))
    signature_b64 = base64.b64encode(signature_der).decode()
    return signature_b64

# ----------------------------
# Helper: generic Coinbase request
# ----------------------------
def coinbase_request(method: str, path: str, body: str = "") -> dict:
    timestamp = str(int(time.time()))
    signature = sign_request(timestamp, method, path, body)
    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": signature,
        "CB-ACCESS-TIMESTAMP": timestamp,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    url = API_BASE.rstrip("/") + path
    resp = requests.request(method, url, headers=headers, data=body, timeout=15)
    log.debug("Coinbase response status=%s body=%s", resp.status_code, resp.text[:500])

    try:
        data = resp.json()
    except Exception:
        log.error("Failed to decode JSON. Status=%s Body=%s", resp.status_code, resp.text[:2000])
        if resp.status_code == 401:
            raise RuntimeError("Unauthorized: check Coinbase API key/private key")
        resp.raise_for_status()
    return data

# ----------------------------
# Get USD spot balance
# ----------------------------
def get_usd_spot_balance() -> float:
    data = coinbase_request("GET", "/v2/accounts")
    for acc in data.get("data", []):
        bal = acc.get("balance", {})
        if bal.get("currency") == "USD":
            return float(bal.get("amount", 0))
    return 0.0

# ----------------------------
# Get all accounts (optional helper)
# ----------------------------
def get_all_accounts() -> list:
    data = coinbase_request("GET", "/v2/accounts")
    return data.get("data", [])

# ----------------------------
# Debug test if run directly
# ----------------------------
if __name__ == "__main__":
    try:
        usd_balance = get_usd_spot_balance()
        log.info("✅ USD Spot Balance: %s", usd_balance)
        accounts = get_all_accounts()
        log.info("✅ All accounts fetched: %d accounts", len(accounts))
    except Exception as e:
        log.exception("❌ Error fetching accounts/balance: %s", e)
