import os
import time
import hmac
import hashlib
import base64
import logging
import requests

log = logging.getLogger("nija_client")
logging.basicConfig(level=logging.INFO)

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")  # optional for regular Coinbase API
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # optional
API_BASE_ADV = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")  # Advanced/Pro
API_BASE_REG = "https://api.coinbase.com/v2"  # Regular Coinbase

if not API_KEY:
    raise RuntimeError("Missing COINBASE_API_KEY")

# -------------------------
# Manual REST: Advanced/Pro
# -------------------------
def _sig_hex_no_decode(ts, method, path, body=""):
    prehash = ts + method.upper() + path + body
    return hmac.new(API_SECRET.encode(), prehash.encode(), hashlib.sha256).hexdigest()

def manual_advanced_get_accounts(method="hex"):
    """HMAC signature for Advanced API (Pro)."""
    if not API_PASSPHRASE:
        raise RuntimeError("Passphrase required for Advanced API")
    path = "/v2/accounts"
    ts = str(int(time.time()))
    sig = _sig_hex_no_decode(ts, "GET", path) if method=="hex" else base64.b64encode(hmac.new(base64.b64decode(API_SECRET), (ts+"GET"+path).encode(), hashlib.sha256).digest()).decode()
    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": sig,
        "CB-ACCESS-TIMESTAMP": ts,
        "CB-ACCESS-PASSPHRASE": API_PASSPHRASE,
        "CB-VERSION": "2025-11-04",
        "Content-Type": "application/json",
    }
    r = requests.get(API_BASE_ADV + path, headers=headers, timeout=15)
    return r

# -------------------------
# Manual REST: Regular Coinbase
# -------------------------
def manual_regular_get_accounts():
    """Regular Coinbase API using Bearer token (no passphrase)."""
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "CB-VERSION": "2025-11-04",
        "Content-Type": "application/json",
    }
    r = requests.get(f"{API_BASE_REG}/accounts", headers=headers, timeout=15)
    return r

# -------------------------
# Fetch accounts (auto-detect)
# -------------------------
def get_all_accounts():
    """Use Advanced if passphrase is set, else regular API."""
    try:
        if API_PASSPHRASE:
            log.info("Using Advanced API with passphrase")
            r = manual_advanced_get_accounts("hex")
            if r.status_code != 200:
                log.warning("Advanced API failed: %s %s", r.status_code, r.text[:300])
                r = manual_advanced_get_accounts("b64")
            r.raise_for_status()
            return r.json().get("data", r.json())
        else:
            log.info("Using Regular Coinbase API (no passphrase)")
            r = manual_regular_get_accounts()
            r.raise_for_status()
            return r.json().get("data", r.json())
    except Exception as e:
        log.exception("Failed to fetch accounts")
        raise RuntimeError("Failed to fetch accounts: " + str(e))

# -------------------------
# Fetch USD spot balance
# -------------------------
def get_usd_spot_balance():
    accts = get_all_accounts()
    if isinstance(accts, dict) and "data" in accts:
        accts = accts["data"]
    for a in accts:
        cur = a.get("currency") or a.get("currency_code") or a.get("asset")
        if cur == "USD":
            bal = a.get("balance") or a.get("available") or a.get("amount") or a.get("quantity")
            if isinstance(bal, dict):
                amt = bal.get("amount") or bal.get("value")
            else:
                amt = bal
            try:
                return float(amt)
            except Exception:
                continue
    return 0.0

# -------------------------
# Quick test
# -------------------------
if __name__ == "__main__":
    try:
        accts = get_all_accounts()
        log.info("Fetched %d accounts", len(accts) if isinstance(accts, list) else len(accts.get("data", [])))
        usd = get_usd_spot_balance()
        log.info("USD balance: %s", usd)
    except Exception as e:
        log.exception("Preflight failed")
