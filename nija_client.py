# nija_client.py
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
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")
API_BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

if not all([API_KEY, API_SECRET, API_PASSPHRASE]):
    raise RuntimeError("Missing one of COINBASE_API_KEY / COINBASE_API_SECRET / COINBASE_API_PASSPHRASE")

# -------------------------
# Try to import a Client
# -------------------------
ClientClass = None
client_import_source = None

try:
    # first attempt (common expectation)
    from coinbase_advanced_py import Client as _Client
    ClientClass = _Client
    client_import_source = "coinbase_advanced_py.Client"
    log.info("Imported Client from coinbase_advanced_py.Client")
except Exception:
    try:
        # second attempt: submodule
        from coinbase_advanced_py.client import Client as _Client
        ClientClass = _Client
        client_import_source = "coinbase_advanced_py.client.Client"
        log.info("Imported Client from coinbase_advanced_py.client.Client")
    except Exception:
        try:
            # third attempt: different top-level package name
            from coinbase_advanced import Client as _Client
            ClientClass = _Client
            client_import_source = "coinbase_advanced.Client"
            log.info("Imported Client from coinbase_advanced.Client")
        except Exception:
            # no client import; we'll fall back to manual requests and also emit diagnostics
            log.warning("Could not import a Client class from coinbase_advanced_py or coinbase_advanced.")
            # Emit diagnostic: list attributes of the installed module(s) so you can inspect
            try:
                import coinbase_advanced_py as cab
                log.info("coinbase_advanced_py module attrs: %s", dir(cab)[:80])
            except Exception:
                log.info("coinbase_advanced_py not importable for introspection.")
            try:
                import coinbase_advanced as cab2
                log.info("coinbase_advanced module attrs: %s", dir(cab2)[:80])
            except Exception:
                log.info("coinbase_advanced not importable for introspection.")
            ClientClass = None

def make_client():
    """Return a library client if available, otherwise None."""
    if ClientClass is None:
        return None
    # instantiate according to typical constructor signatures
    try:
        return ClientClass(api_key=API_KEY, api_secret=API_SECRET, api_passphrase=API_PASSPHRASE)
    except TypeError:
        # some clients expect different arg names
        try:
            return ClientClass(API_KEY, API_SECRET, API_PASSPHRASE)
        except Exception as e:
            log.warning("ClientClass instantiation failed: %s", e)
            return None

# -------------------------
# Manual REST fallback(s)
# -------------------------
def _sig_hex_no_decode(ts, method, path, body=""):
    # HMAC SHA256 hex digest using raw secret bytes (no base64 decode)
    prehash = ts + method.upper() + path + body
    return hmac.new(API_SECRET.encode(), prehash.encode(), hashlib.sha256).hexdigest()

def _sig_base64_decode_then_b64(ts, method, path, body=""):
    # Some libs expect API_SECRET to be base64-encoded; decode then HMAC and base64-encode signature
    prehash = ts + method.upper() + path + body
    try:
        secret_bytes = base64.b64decode(API_SECRET)
    except Exception:
        # not base64; fall back to raw bytes
        secret_bytes = API_SECRET.encode()
    sig_raw = hmac.new(secret_bytes, prehash.encode(), hashlib.sha256).digest()
    return base64.b64encode(sig_raw).decode()

def manual_get_accounts_try(method="hex"):
    path = "/v2/accounts"
    ts = str(int(time.time()))
    if method == "hex":
        sig = _sig_hex_no_decode(ts, "GET", path, "")
    else:
        sig = _sig_base64_decode_then_b64(ts, "GET", path, "")
    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": sig,
        "CB-ACCESS-TIMESTAMP": ts,
        "CB-ACCESS-PASSPHRASE": API_PASSPHRASE,
        "CB-VERSION": "2025-11-02",
        "Content-Type": "application/json",
    }
    r = requests.get(API_BASE + path, headers=headers, timeout=15)
    return r

def get_all_accounts():
    """
    Preferred: use library Client if available.
    Fallback: try manual requests with two signature variants and return parsed JSON or raise.
    """
    client = make_client()
    if client:
        try:
            log.info("Using library Client from %s", client_import_source or "unknown")
            # many clients provide get_accounts() or accounts() — try common names
            if hasattr(client, "get_accounts"):
                return client.get_accounts()
            if hasattr(client, "accounts"):
                # might be a property or coro
                res = client.accounts()
                return res
            # fallback: try generic 'request' method
            if hasattr(client, "request"):
                return client.request("GET", "/v2/accounts")
            raise RuntimeError("Library client found but no known method to list accounts.")
        except Exception as e:
            log.warning("Library client call failed: %s — will try manual REST fallback", e)

    # Manual fallback: try hex-signature then base64-signature
    log.info("Trying manual REST fallback with hex HMAC signature...")
    r = manual_get_accounts_try("hex")
    if r.status_code == 200:
        return r.json().get("data", r.json())
    log.warning("hex-signature attempt failed: %s %s", r.status_code, r.text[:300])

    log.info("Trying manual REST fallback with base64-decoded secret -> base64 signature...")
    r = manual_get_accounts_try("b64")
    if r.status_code == 200:
        return r.json().get("data", r.json())
    log.warning("base64-signature attempt failed: %s %s", r.status_code, r.text[:300])

    # If both failed, raise with the most helpful message
    raise RuntimeError(
        "Failed to fetch accounts via library or manual signature methods. "
        "Check API key/secret/passphrase, key permissions, and that server time is synced."
    )

def get_usd_spot_balance():
    accts = get_all_accounts()
    # accts may be list of dicts or dict containing 'data'
    # normalize
    if isinstance(accts, dict) and "data" in accts:
        data = accts["data"]
    else:
        data = accts
    # find USD
    for a in data:
        cur = a.get("currency") or a.get("currency_code") or a.get("asset")
        if cur == "USD":
            # try different balance shapes
            bal = a.get("balance") or a.get("available") or a.get("amount") or a.get("quantity")
            if isinstance(bal, dict):
                amt = bal.get("amount") or bal.get("value")
            else:
                amt = bal
            try:
                return float(amt)
            except Exception:
                try:
                    return float(str(amt))
                except Exception:
                    return 0.0
    return 0.0

# quick local CLI test
if __name__ == "__main__":
    try:
        accts = get_all_accounts()
        log.info("Preflight: fetched %d accounts", len(accts) if isinstance(accts, list) else len(accts.get("data", [])))
        usd = get_usd_spot_balance()
        log.info("USD balance: %s", usd)
    except Exception as e:
        log.exception("Preflight failed: %s", e)
        raise
