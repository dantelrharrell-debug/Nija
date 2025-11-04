# nija_client.py
"""
Robust Coinbase preflight + account helpers.

Features:
- Require only COINBASE_API_KEY and COINBASE_API_SECRET (passphrase optional)
- Tries to import a Client class from likely coinbase-advanced libs
- Manual REST fallback with base64 signature (default) and hex fallback
- Adds CB-ACCESS-PASSPHRASE header only when present
- Helpful logging for debugging 401 / timestamp skew
"""

import os
import time
import hmac
import hashlib
import base64
import logging
import requests
import datetime
from typing import Optional, Any

log = logging.getLogger("nija_client")
logging.basicConfig(level=logging.INFO)

# -----------------------------
# Env / config
# -----------------------------
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # optional
API_BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")
API_VERSION = os.getenv("COINBASE_API_VERSION", "2025-11-02")

if not API_KEY or not API_SECRET:
    raise RuntimeError("Missing one of COINBASE_API_KEY / COINBASE_API_SECRET")

# -----------------------------
# Import Client if available
# -----------------------------
ClientClass = None
client_import_source = None

def try_import_client():
    global ClientClass, client_import_source
    attempts = [
        ("coinbase_advanced_py", "Client"),
        ("coinbase_advanced_py.client", "Client"),
        ("coinbase_advanced", "Client"),
        ("coinbase_advanced_py", None),  # inspect module if no Client attr
    ]
    for module_path, attr in attempts:
        try:
            parts = module_path.split(".")
            module = __import__(module_path, fromlist=["*"])
            if attr:
                cls = getattr(module, attr, None)
                if cls:
                    ClientClass = cls
                    client_import_source = f"{module_path}.{attr}"
                    log.info("Imported Client from %s", client_import_source)
                    return
            else:
                # inspect module for plausible client names
                for name in ("Client", "client", "CoinbaseClient"):
                    cls = getattr(module, name, None)
                    if cls:
                        ClientClass = cls
                        client_import_source = f"{module_path}.{name}"
                        log.info("Imported Client from %s", client_import_source)
                        return
        except Exception as e:
            # import failure is okay; move on
            log.debug("Client import attempt %s failed: %s", module_path, str(e))
    # No client found
    log.info("No library Client found; will use manual REST fallback.")

try_import_client()

def make_client() -> Optional[Any]:
    """Instantiate the ClientClass if available; handle common constructor signatures."""
    if ClientClass is None:
        return None
    try:
        # try explicit kwargs
        return ClientClass(api_key=API_KEY, api_secret=API_SECRET, api_passphrase=API_PASSPHRASE)
    except Exception:
        try:
            # try positional
            return ClientClass(API_KEY, API_SECRET, API_PASSPHRASE)
        except Exception as e:
            log.warning("ClientClass instantiation failed: %s", e)
            return None

# -----------------------------
# Signature helpers
# -----------------------------
def _sig_base64_decode_then_b64(ts: str, method: str, path: str, body: str = "") -> str:
    """
    Preferred: decode API_SECRET as base64 if possible, HMAC-SHA256(prehash) with that,
    then base64-encode the digest (common expectation).
    """
    prehash = ts + method.upper() + path + body
    try:
        secret_bytes = base64.b64decode(API_SECRET)
    except Exception:
        # not base64; use raw bytes
        secret_bytes = API_SECRET.encode()
    sig_raw = hmac.new(secret_bytes, prehash.encode(), hashlib.sha256).digest()
    return base64.b64encode(sig_raw).decode()

def _sig_hex_no_decode(ts: str, method: str, path: str, body: str = "") -> str:
    """Alternate: hex digest of HMAC-SHA256 using raw secret bytes."""
    prehash = ts + method.upper() + path + body
    return hmac.new(API_SECRET.encode(), prehash.encode(), hashlib.sha256).hexdigest()

# -----------------------------
# Coinbase time helper (to detect server time skew)
# -----------------------------
def get_coinbase_server_time(timeout: float = 5.0) -> Optional[int]:
    """
    Call Coinbase /time endpoint and return server unix timestamp (int) if available.
    """
    try:
        resp = requests.get(API_BASE + "/time", timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            # common shapes: {"data":{"epoch":..., ...}} or {"epoch": ...}
            epoch = None
            if isinstance(data, dict):
                if "epoch" in data:
                    epoch = int(data["epoch"])
                elif "data" in data and isinstance(data["data"], dict) and "epoch" in data["data"]:
                    epoch = int(data["data"]["epoch"])
            if epoch:
                log.info("Coinbase server epoch=%s (%s UTC)", epoch, datetime.datetime.utcfromtimestamp(epoch).isoformat())
                return epoch
            log.debug("Coinbase /time unexpected shape: %s", data)
    except Exception as e:
        log.debug("Failed to call Coinbase /time: %s", e)
    return None

def log_local_and_server_time_hint():
    ts_local = int(time.time())
    log.info("local unix ts=%s (%s UTC)", ts_local, datetime.datetime.utcfromtimestamp(ts_local).isoformat())
    server_ts = get_coinbase_server_time()
    if server_ts:
        diff = server_ts - ts_local
        log.info("server-local ts diff = %s seconds", diff)
        if abs(diff) > 5:
            log.warning("Significant clock skew detected (server-local > 5s). Consider syncing clock or using server time for signatures.")

# -----------------------------
# Manual REST helpers
# -----------------------------
def _build_headers(sig: str, ts: str) -> dict:
    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": sig,
        "CB-ACCESS-TIMESTAMP": ts,
        "CB-VERSION": API_VERSION,
        "Content-Type": "application/json",
    }
    # include passphrase only if present
    if API_PASSPHRASE:
        headers["CB-ACCESS-PASSPHRASE"] = API_PASSPHRASE
    return headers

def manual_get_accounts_try(method: str = "b64") -> requests.Response:
    """
    Try to fetch /v2/accounts using either base64-decoded-secret -> base64(signature) (b64)
    or hex HMAC digest (hex).
    """
    path = "/v2/accounts"
    ts = str(int(time.time()))
    if method == "hex":
        sig = _sig_hex_no_decode(ts, "GET", path, "")
    else:
        sig = _sig_base64_decode_then_b64(ts, "GET", path, "")

    headers = _build_headers(sig, ts)
    try:
        r = requests.get(API_BASE + path, headers=headers, timeout=15)
    except Exception as e:
        log.exception("manual_get_accounts_try: request error for method=%s: %s", method, e)
        raise

    log.info("manual_get_accounts_try method=%s ts=%s status=%s", method, ts, r.status_code)
    if r.status_code != 200:
        # log limited body for debugging (avoid huge dumps or secrets)
        body_preview = r.text[:1000] if r.text else "<empty body>"
        log.debug("manual_get_accounts_try response body preview: %s", body_preview)
    return r

# -----------------------------
# Top-level functions
# -----------------------------
def get_all_accounts() -> Any:
    """
    Try library client first (if available). Otherwise, fallback to manual REST attempts.
    Returns the parsed JSON (list or dict as returned by server) or raises RuntimeError.
    """
    # 1) Library client attempt
    client = make_client()
    if client:
        try:
            log.info("Using library client from %s", client_import_source or "unknown")
            # common method names
            if hasattr(client, "get_accounts"):
                return client.get_accounts()
            if hasattr(client, "accounts"):
                # could be callable or property
                attr = getattr(client, "accounts")
                if callable(attr):
                    return attr()
                return attr
            if hasattr(client, "request"):
                return client.request("GET", "/v2/accounts")
            # last resort: try generic 'get' method
            if hasattr(client, "get"):
                return client.get("/v2/accounts")
            log.warning("Library client found but no known method to list accounts; falling back to REST.")
        except Exception as e:
            log.warning("Library client call failed (%s) — falling back to manual REST: %s", client_import_source, e)

    # 2) Manual REST fallback: try base64-first, then hex
    log.info("Trying manual REST fallback (base64 signature first)...")
    # Try base64-style signature first (most likely)
    r = manual_get_accounts_try("b64")
    if r.status_code == 200:
        try:
            return r.json().get("data", r.json())
        except Exception:
            return r.json()
    # If 401 and server time might be skewed, log server time hint
    if r.status_code == 401:
        log.warning("Received 401 from Coinbase during b64 attempt. Checking server time for possible skew...")
        log_local_and_server_time_hint()

    log.info("b64 attempt failed (status=%s). Trying hex digest fallback...", r.status_code)
    r2 = manual_get_accounts_try("hex")
    if r2.status_code == 200:
        try:
            return r2.json().get("data", r2.json())
        except Exception:
            return r2.json()

    # both attempts failed -> collect helpful diagnostics and raise
    msg = (
        "Failed to fetch accounts via library or manual signature methods. "
        f"b64_status={r.status_code} hex_status={r2.status_code}. "
        "Check API key/secret/passphrase, key permissions (wallet/accounts), and server time sync."
    )
    # attach first 500 chars of responses to help debugging
    resp_b64_preview = (r.text[:500] if r is not None and r.text else "<no body>")
    resp_hex_preview = (r2.text[:500] if r2 is not None and r2.text else "<no body>")
    log.error("%s\nb64_resp=%s\nhex_resp=%s", msg, resp_b64_preview, resp_hex_preview)
    raise RuntimeError(msg + f" b64_resp={resp_b64_preview} hex_resp={resp_hex_preview}")

def get_usd_spot_balance() -> float:
    """
    Normalize account shapes and return USD spot/equivalent balance as float.
    """
    accts = get_all_accounts()
    # normalize to list of account dicts
    data = accts
    if isinstance(accts, dict) and "data" in accts:
        data = accts["data"]

    if not isinstance(data, list):
        # If library client returned something else (like an object), try to coerce
        log.debug("get_usd_spot_balance: unexpected accounts shape; returning 0.0")
        return 0.0

    for a in data:
        # try a number of possible currency keys
        cur = a.get("currency") or a.get("currency_code") or a.get("asset") or a.get("coin")
        if cur == "USD":
            # balance might be nested object or string
            bal = a.get("balance") or a.get("available") or a.get("amount") or a.get("quantity") or a.get("balance_amount")
            if isinstance(bal, dict):
                amt = bal.get("amount") or bal.get("value") or bal.get("balance")
            else:
                amt = bal
            try:
                return float(amt)
            except Exception:
                try:
                    return float(str(amt))
                except Exception:
                    return 0.0
    # not found
    return 0.0

# -----------------------------
# CLI test (safe for local use)
# -----------------------------
if __name__ == "__main__":
    log.info("Running nija_client.py CLI preflight test")
    try:
        log.info("API_KEY present: %s", bool(API_KEY))
        log.info("API_SECRET present: %s", bool(API_SECRET))
        log.info("API_PASSPHRASE present: %s", bool(API_PASSPHRASE))
        log_local_and_server_time_hint()

        accts = get_all_accounts()
        if isinstance(accts, list):
            log.info("Preflight: fetched %d accounts", len(accts))
        else:
            try:
                count = len(accts.get("data", []))
                log.info("Preflight: fetched %d accounts (from data)", count)
            except Exception:
                log.info("Preflight: accounts shape: %s", type(accts))

        usd = get_usd_spot_balance()
        log.info("USD balance: %s", usd)
    except Exception as e:
        log.exception("Preflight failed: %s", e)
        raise
        
