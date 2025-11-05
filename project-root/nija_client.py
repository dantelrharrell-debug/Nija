# nija_client.py
import os
import time
import hmac
import hashlib
import base64
import requests
import logging
from typing import Optional, Any, List, Dict

log = logging.getLogger("nija_client")
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO)

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # Accept None for Advanced/Base keys
API_BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")
CB_VERSION = os.getenv("COINBASE_API_VERSION", "2025-11-02")

if not API_KEY or not API_SECRET:
    raise RuntimeError("Missing COINBASE_API_KEY or COINBASE_API_SECRET environment variables.")

# Try importing official/3rd-party clients (optional)
ClientClass = None
client_import_source = None
for candidate in (
    ("coinbase_advanced_py", "Client"),
    ("coinbase_advanced_py.client", "Client"),
    ("coinbase_advanced", "Client"),
):
    try:
        module_name, class_name = candidate
        module = __import__(module_name, fromlist=[class_name])
        ClientClass = getattr(module, class_name)
        client_import_source = f"{module_name}.{class_name}"
        log.info("Imported client: %s", client_import_source)
        break
    except Exception:
        continue

def fetch_server_time() -> Optional[int]:
    try:
        r = requests.get(API_BASE + "/v2/time", timeout=10)
        r.raise_for_status()
        t = r.json().get("data", {}).get("epoch")
        if t:
            log.info("Coinbase server time: %s (UTC)", t)
            return int(t)
    except Exception as e:
        log.info("Could not fetch Coinbase server time: %s", e)
    return None

def _sig_hex_raw(ts: str, method: str, path: str, body: str = "") -> str:
    prehash = ts + method.upper() + path + body
    return hmac.new(API_SECRET.encode(), prehash.encode(), hashlib.sha256).hexdigest()

def _sig_b64_decoded_secret_then_b64(ts: str, method: str, path: str, body: str = "") -> str:
    prehash = ts + method.upper() + path + body
    try:
        secret_bytes = base64.b64decode(API_SECRET)
    except Exception:
        secret_bytes = API_SECRET.encode()
    sig_raw = hmac.new(secret_bytes, prehash.encode(), hashlib.sha256).digest()
    return base64.b64encode(sig_raw).decode()

def _request_with_sig(path: str, method: str = "GET", body: str = "", sig_method: str = "hex") -> requests.Response:
    if sig_method not in ("hex", "b64"):
        raise ValueError("sig_method must be 'hex' or 'b64'")
    ts = str(int(time.time()))
    sig = _sig_hex_raw(ts, method, path, body) if sig_method == "hex" else _sig_b64_decoded_secret_then_b64(ts, method, path, body)
    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": sig,
        "CB-ACCESS-TIMESTAMP": ts,
        "CB-VERSION": CB_VERSION,
        "Content-Type": "application/json",
    }
    if API_PASSPHRASE:
        headers["CB-ACCESS-PASSPHRASE"] = API_PASSPHRASE
    url = API_BASE + path
    log.debug("Requesting %s %s (sig=%s method=%s)", method, url, sig[:8], sig_method)
    r = requests.request(method, url, headers=headers, data=body, timeout=15)
    return r

def get_all_accounts() -> List[Dict[str, Any]]:
    # If a Client library is available, try it first (optional)
    if ClientClass:
        try:
            client = make_client()
            if client:
                log.info("Using library client: %s", client_import_source or "unknown")
                # try common method names
                for meth in ("get_accounts", "accounts", "get_accounts_sync", "get_accounts_list"):
                    if hasattr(client, meth):
                        res = getattr(client, meth)()
                        # try to normalize to list
                        if isinstance(res, dict) and "data" in res:
                            return res["data"]
                        return res
                # fallback generic request method
                if hasattr(client, "request"):
                    return client.request("GET", "/v2/accounts")
        except Exception as e:
            log.warning("Library client failed: %s (falling back to manual)", e)

    # Manual attempts: try base64-secret signature first (b64) then hex (raw)
    fetch_server_time()  # log server time for debugging
    for method in ("b64", "hex"):
        try:
            r = _request_with_sig("/v2/accounts", "GET", "", sig_method=method)
            log.info("manual_get_accounts_try method=%s status=%s", method, r.status_code)
            if r.status_code == 200:
                return r.json().get("data", r.json())
            elif r.status_code == 401:
                log.warning("%s attempt got 401 Unauthorized.", method)
                # continue to next method attempt
            else:
                log.warning("%s attempt status=%s text=%s", method, r.status_code, r.text[:300])
        except Exception as e:
            log.exception("manual_get_accounts_try method=%s failed: %s", method, e)

    # If reached: both failed
    raise RuntimeError(
        "Failed to fetch accounts via library or manual signature methods. "
        "Check API key/secret, key permissions (accounts/view), IP allowlist, and server time."
    )

def get_usd_spot_balance() -> float:
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
                try:
                    return float(str(amt))
                except Exception:
                    return 0.0
    return 0.0

def make_client():
    """Instantiate ClientClass if available."""
    if not ClientClass:
        return None
    try:
        # try common constructor signatures
        return ClientClass(api_key=API_KEY, api_secret=API_SECRET, api_passphrase=API_PASSPHRASE)
    except TypeError:
        try:
            return ClientClass(API_KEY, API_SECRET, API_PASSPHRASE)
        except Exception as e:
            log.warning("ClientClass instantiation failed: %s", e)
            return None

# CLI quick test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        log.info("COINBASE_API_KEY: %s", API_KEY[:4] + "****")
        log.info("COINBASE_API_SECRET: %s", API_SECRET[:4] + "****")
        log.info("COINBASE_API_PASSPHRASE: %s", bool(API_PASSPHRASE))
        accounts = get_all_accounts()
        log.info("Fetched %d accounts", len(accounts) if isinstance(accounts, list) else len(accounts.get("data", [])))
        usd = get_usd_spot_balance()
        log.info("USD balance: %s", usd)
    except Exception as e:
        log.exception("Preflight failed: %s", e)
        raise
