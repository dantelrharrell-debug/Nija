# nija_client.py
# -------------------------
# Coinbase client & manual REST fallback with preflight and skew adjustment
# -------------------------

import os
import time
import hmac
import hashlib
import base64
import logging
import requests
import sys

# -------------------------
# Logging
# -------------------------
log = logging.getLogger("nija_client")
logging.basicConfig(level=logging.INFO)

# -------------------------
# Environment variables / preflight
# -------------------------
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # optional
API_BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

def preflight_check():
    required_vars = ["COINBASE_API_KEY", "COINBASE_API_SECRET"]
    missing_required = [v for v in required_vars if not os.getenv(v)]
    if missing_required:
        log.error("❌ Missing required Coinbase credentials: %s", ", ".join(missing_required))
        sys.exit(1)
    log.info("✅ COINBASE_API_KEY present: %s", bool(API_KEY))
    log.info("✅ COINBASE_API_SECRET present: %s", bool(API_SECRET))
    log.info("COINBASE_API_PASSPHRASE present: %s", bool(API_PASSPHRASE))
    if not API_PASSPHRASE:
        log.warning("⚠️ COINBASE_API_PASSPHRASE not set — continuing without passphrase if key allows.")

preflight_check()

# -------------------------
# Server time helper + skew adjustment
# -------------------------
_time_skew = None

def get_coinbase_server_time():
    """Fetch Coinbase server time in UNIX timestamp."""
    try:
        r = requests.get(API_BASE + "/v2/time", timeout=10)
        r.raise_for_status()
        server_ts = int(r.json()["data"]["epoch"])
        log.info("Coinbase server time: %s (UTC)", server_ts)
        return server_ts
    except Exception as e:
        log.warning("Failed to fetch Coinbase server time: %s", e)
        return int(time.time())

def get_adjusted_ts():
    """Return timestamp adjusted for server vs local skew."""
    global _time_skew
    local_ts = int(time.time())
    if _time_skew is None:
        server_ts = get_coinbase_server_time()
        _time_skew = local_ts - server_ts
        if abs(_time_skew) > 5:
            log.warning(
                "⚠️ Detected time skew: local ts=%s, server ts=%s, skew=%s seconds",
                local_ts, server_ts, _time_skew
            )
    return str(local_ts - _time_skew)

# -------------------------
# Try to import a Client
# -------------------------
ClientClass = None
client_import_source = None
for attempt in [
    ("coinbase_advanced_py", "Client"),
    ("coinbase_advanced_py.client", "Client"),
    ("coinbase_advanced", "Client")
]:
    module_name, cls_name = attempt
    try:
        mod = __import__(module_name, fromlist=[cls_name])
        ClientClass = getattr(mod, cls_name)
        client_import_source = f"{module_name}.{cls_name}"
        log.info("Imported Client from %s", client_import_source)
        break
    except Exception:
        continue

if ClientClass is None:
    log.warning("No library Client found; will use manual REST fallback.")

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
# Manual REST fallback
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
    ts = get_adjusted_ts()
    sig = _sig_hex_no_decode(ts, "GET", path) if method == "hex" else _sig_base64_decode_then_b64(ts, "GET", path)
    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": sig,
        "CB-ACCESS-TIMESTAMP": ts,
        "CB-ACCESS-PASSPHRASE": API_PASSPHRASE or "",
        "CB-VERSION": "2025-11-02",
        "Content-Type": "application/json",
    }
    r = requests.get(API_BASE + path, headers=headers, timeout=15)
    return r

def get_all_accounts():
    client = make_client()
    if client:
        for method_name in ["get_accounts", "accounts", "request"]:
            try:
                if hasattr(client, method_name):
                    fn = getattr(client, method_name)
                    res = fn() if callable(fn) else fn
                    return res
            except Exception as e:
                log.warning("Library client call failed: %s", e)
    # Manual fallback
    for method in ["b64", "hex"]:
        log.info("Trying manual REST fallback: %s", method)
        r = manual_get_accounts_try(method)
        if r.status_code == 200:
            return r.json().get("data", r.json())
        log.warning("%s attempt failed: %s %s", method, r.status_code, r.text[:300])
    raise RuntimeError(
        "Failed to fetch accounts via library or manual signature methods. "
        "Check API key/secret/passphrase, permissions (wallet/accounts), and server time sync."
    )

# -------------------------
# USD spot balance helper
# -------------------------
def get_usd_spot_balance():
    accts = get_all_accounts()
    data = accts.get("data", accts) if isinstance(accts, dict) else accts
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
                return 0.0
    return 0.0

# -------------------------
# Local CLI preflight test
# -------------------------
if __name__ == "__main__":
    log.info("Running full preflight check...")
    preflight_check()
    get_adjusted_ts()  # detect skew
    try:
        accts = get_all_accounts()
        log.info("Fetched %d accounts", len(accts) if isinstance(accts, list) else len(accts.get("data", [])))
        usd = get_usd_spot_balance()
        log.info("USD balance: %s", usd)
    except Exception as e:
        log.exception("Preflight failed: %s", e)
        raise
