# ----------------------------
# Preflight environment check
# ----------------------------
import os, logging, sys

log = logging.getLogger("nija_preflight")
logging.basicConfig(level=logging.INFO)

def preflight_check():
    required_vars = ["COINBASE_API_KEY", "COINBASE_API_SECRET"]
    missing_required = [v for v in required_vars if not os.getenv(v)]
    if missing_required:
        log.error("❌ Missing required Coinbase credentials: %s", ", ".join(missing_required))
        sys.exit(1)

    passphrase_present = bool(os.getenv("COINBASE_API_PASSPHRASE"))
    log.info("✅ COINBASE_API_KEY present: %s", bool(os.getenv("COINBASE_API_KEY")))
    log.info("✅ COINBASE_API_SECRET present: %s", bool(os.getenv("COINBASE_API_SECRET")))
    log.info("COINBASE_API_PASSPHRASE present: %s", passphrase_present)
    if not passphrase_present:
        log.warning("⚠️ COINBASE_API_PASSPHRASE not set — continuing without passphrase header.")

preflight_check()

# ----------------------------
# nija_client.py
# ----------------------------
import time
import hmac
import hashlib
import base64
import requests

log = logging.getLogger("nija_client")
logging.basicConfig(level=logging.INFO)

# Credentials (passphrase optional)
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # optional
API_BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

if not all([API_KEY, API_SECRET]):
    raise RuntimeError("Missing required COINBASE_API_KEY or COINBASE_API_SECRET")

# -------------------------
# Library Client (optional)
# -------------------------
ClientClass = None
client_import_source = None

try:
    from coinbase_advanced_py import Client as _Client
    ClientClass = _Client
    client_import_source = "coinbase_advanced_py.Client"
    log.info("Imported Client from coinbase_advanced_py.Client")
except Exception:
    try:
        from coinbase_advanced_py.client import Client as _Client
        ClientClass = _Client
        client_import_source = "coinbase_advanced_py.client.Client"
        log.info("Imported Client from coinbase_advanced_py.client.Client")
    except Exception:
        try:
            from coinbase_advanced import Client as _Client
            ClientClass = _Client
            client_import_source = "coinbase_advanced.Client"
            log.info("Imported Client from coinbase_advanced.Client")
        except Exception:
            log.warning("Could not import Client; falling back to manual REST requests.")
            ClientClass = None

def make_client():
    if ClientClass is None:
        return None
    try:
        return ClientClass(api_key=API_KEY, api_secret=API_SECRET, api_passphrase=API_PASSPHRASE)
    except TypeError:
        try:
            return ClientClass(API_KEY, API_SECRET, API_PASSPHRASE)
        except Exception as e:
            log.warning("ClientClass instantiation failed: %s", e)
            return None

# -------------------------
# Manual REST helpers
# -------------------------
def _sig_hex_no_decode(ts, method, path, body=""):
    prehash = ts + method.upper() + path + body
    return hmac.new(API_SECRET.encode(), prehash.encode(), hashlib.sha256).hexdigest()

def _sig_base64_decode_then_b64(ts, method, path, body=""):
    prehash = ts + method.upper() + path + body
    try:
        secret_bytes = base64.b64decode(API_SECRET)
    except Exception:
        secret_bytes = API_SECRET.encode()
    sig_raw = hmac.new(secret_bytes, prehash.encode(), hashlib.sha256).digest()
    return base64.b64encode(sig_raw).decode()

def manual_get_accounts_try(method="hex"):
    path = "/v2/accounts"
    ts = str(int(time.time()))
    sig = _sig_hex_no_decode(ts, "GET", path) if method=="hex" else _sig_base64_decode_then_b64(ts, "GET", path)
    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": sig,
        "CB-ACCESS-TIMESTAMP": ts,
        "CB-VERSION": "2025-11-04",
        "Content-Type": "application/json"
    }
    if API_PASSPHRASE:
        headers["CB-ACCESS-PASSPHRASE"] = API_PASSPHRASE

    r = requests.get(API_BASE + path, headers=headers, timeout=15)
    return r

# -------------------------
# Fetch accounts
# -------------------------
def get_all_accounts():
    client = make_client()
    if client:
        try:
            log.info("Using library Client from %s", client_import_source or "unknown")
            if hasattr(client, "get_accounts"):
                return client.get_accounts()
            if hasattr(client, "accounts"):
                return client.accounts()
            if hasattr(client, "request"):
                return client.request("GET", "/v2/accounts")
            raise RuntimeError("Library client found but no known method to list accounts.")
        except Exception as e:
            log.warning("Library client call failed: %s — will try manual REST fallback", e)

    # Manual REST fallback
    log.info("Trying manual REST fallback (base64 signature first)...")
    r_b64 = manual_get_accounts_try("b64")
    if r_b64.status_code == 200:
        return r_b64.json().get("data", r_b64.json())
    log.warning("b64-signature attempt failed: %s %s", r_b64.status_code, r_b64.text[:300])

    log.info("Trying manual REST fallback (hex signature)...")
    r_hex = manual_get_accounts_try("hex")
    if r_hex.status_code == 200:
        return r_hex.json().get("data", r_hex.json())
    log.warning("hex-signature attempt failed: %s %s", r_hex.status_code, r_hex.text[:300])

    raise RuntimeError(
        f"Failed to fetch accounts via library or manual methods. "
        f"b64_status={r_b64.status_code} hex_status={r_hex.status_code} "
        f"b64_resp={r_b64.text[:300]} hex_resp={r_hex.text[:300]}"
    )

# -------------------------
# Get USD spot balance
# -------------------------
def get_usd_spot_balance():
    accts = get_all_accounts()
    if isinstance(accts, dict) and "data" in accts:
        data = accts["data"]
    else:
        data = accts

    for a in data:
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
# CLI test
# -------------------------
if __name__ == "__main__":
    try:
        accts = get_all_accounts()
        log.info("Fetched %d accounts", len(accts) if isinstance(accts, list) else len(accts.get("data", [])))
        usd = get_usd_spot_balance()
        log.info("USD balance: %s", usd)
    except Exception as e:
        log.exception("Preflight failed: %s", e)
        raise
