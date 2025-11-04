import os
import time
import base64
import requests
from nacl.signing import SigningKey

# -----------------------------
# --- Load Coinbase credentials
# -----------------------------
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")  # base64 Ed25519 key
API_BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

if not all([API_KEY, API_SECRET]):
    raise RuntimeError("Missing Coinbase API credentials in environment variables")

# Decode the Ed25519 key and ensure it's 32 bytes
decoded_secret = base64.b64decode(API_SECRET)
if len(decoded_secret) != 32:
    raise RuntimeError(f"API_SECRET must be exactly 32 bytes after base64 decode, got {len(decoded_secret)} bytes")
SIGNING_KEY = SigningKey(decoded_secret)

# -----------------------------
# --- Helper: sign request
# -----------------------------
def sign_request(method: str, path: str, body: str = "") -> tuple[str, str]:
    """
    Sign a Coinbase API request using Ed25519 key.
    Returns (timestamp, signature_base64)
    """
    timestamp = str(int(time.time()))
    message = timestamp + method.upper() + path + (body or "")
    signature = SIGNING_KEY.sign(message.encode()).signature
    signature_b64 = base64.b64encode(signature).decode()
    return timestamp, signature_b64

# -----------------------------
# --- Helper: Coinbase API call
# -----------------------------
def coinbase_request(method: str, path: str, body: str = "") -> dict:
    """
    Make a signed request to Coinbase API.
    Raises RuntimeError on 4xx/5xx errors.
    """
    timestamp, signature = sign_request(method, path, body)
    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": signature,
        "CB-ACCESS-TIMESTAMP": timestamp,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    url = API_BASE.rstrip("/") + path
    resp = requests.request(method, url, headers=headers, data=body, timeout=15)

    if resp.status_code >= 400:
        raise RuntimeError(f"Coinbase API error {resp.status_code}: {resp.text}")

    try:
        return resp.json()
    except ValueError:
        raise RuntimeError(f"Failed to decode JSON. Status={resp.status_code} Body={resp.text}")

# -----------------------------
# --- Helper functions
# -----------------------------
def get_usd_spot_balance() -> float:
    """
    Fetch USD balance from Coinbase account.
    """
    accounts = coinbase_request("GET", "/v2/accounts")
    for acc in accounts.get("data", []):
        if acc.get("balance", {}).get("currency") == "USD":
            return float(acc["balance"]["amount"])
    return 0.0

def get_all_accounts() -> list:
    """
    Fetch all accounts data from Coinbase.
    """
    accounts = coinbase_request("GET", "/v2/accounts")
    return accounts.get("data", [])

# -----------------------------
# --- Preflight check
# -----------------------------
def preflight_check():
    """
    Run basic checks before trading starts.
    """
    print("[NIJA] Preflight check running...")
    try:
        usd = get_usd_spot_balance()
        print(f"[NIJA] USD balance check OK: {usd}")
    except Exception as e:
        print(f"[NIJA] Preflight error: {e}")
        raise
    return True
