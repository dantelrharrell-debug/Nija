# nija_client.py
import os
import time
import json
import logging
import requests
import hmac
import hashlib
import base64

log = logging.getLogger("nija_client")
logging.basicConfig(level=logging.INFO)

# Env
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # optional — you said none, code tolerates that
API_BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")
CB_VERSION = os.getenv("COINBASE_CB_VERSION", "2025-11-05")

if not all([API_KEY, API_SECRET]):
    raise RuntimeError("❌ Missing Coinbase credentials: COINBASE_API_KEY or COINBASE_API_SECRET")


def _make_signature(timestamp: str, method: str, request_path: str, body: str = "") -> str:
    """
    Coinbase signature: HMAC SHA256 of (timestamp + method + request_path + body),
    then base64-encode the raw digest. API_SECRET may already be base64-encoded;
    try decoding first, otherwise use raw bytes.
    """
    prehash = timestamp + method.upper() + request_path + (body or "")
    try:
        secret_bytes = base64.b64decode(API_SECRET)
    except Exception:
        secret_bytes = API_SECRET.encode()
    sig = hmac.new(secret_bytes, prehash.encode(), hashlib.sha256).digest()
    return base64.b64encode(sig).decode()


def _send_request(path: str, method: str = "GET", body: str = "", params: dict | None = None, timeout: int = 15):
    """
    Send signed request to Coinbase. Raises RuntimeError on 401 with helpful guidance.
    """
    ts = str(int(time.time()))
    request_path = path if path.startswith("/") else "/" + path
    signature = _make_signature(ts, method, request_path, body)

    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": signature,
        "CB-ACCESS-TIMESTAMP": ts,
        "CB-VERSION": CB_VERSION,
        "Content-Type": "application/json",
    }
    # add passphrase only if set (some key types require it)
    if API_PASSPHRASE:
        headers["CB-ACCESS-PASSPHRASE"] = API_PASSPHRASE

    url = API_BASE.rstrip("/") + request_path
    log.debug("Request to %s %s headers=%s", method, url, {k: (v if k != "CB-ACCESS-SIGN" else "REDACTED") for k, v in headers.items()})
    r = requests.request(method, url, headers=headers, data=body or None, params=params, timeout=timeout)

    if r.status_code == 401:
        # helpful message: either permissions, wrong secret format (base64 vs raw), or passphrase needed
        msg = r.text or "Unauthorized"
        guidance = (
            "❌ 401 Unauthorized. Possible causes:\n"
            " - API key missing required permissions (enable 'View' and/or 'Wallet' / 'Accounts')\n"
            " - API key is an Advanced/Base key and requires different signing or a passphrase\n"
            " - API_SECRET encoding mismatch (try regenerating the key or encoding/decoding the secret)\n"
        )
        # If there is no passphrase present, mention that some keys need a passphrase
        if not API_PASSPHRASE:
            guidance += "Note: COINBASE_API_PASSPHRASE is not set. If your key requires a passphrase, set it in env.\n"
        raise RuntimeError(f"❌ 401 Unauthorized from Coinbase: {msg}\n{guidance}")

    if not r.ok:
        raise RuntimeError(f"❌ Request failed: {r.status_code} {r.text}")

    return r.json()


# -------------------------
# Public helpers
# -------------------------
def get_all_accounts():
    """
    Return list of account dicts (normalized from {'data': [...]})
    """
    resp = _send_request("/v2/accounts", method="GET")
    # many Coinbase endpoints return {'data': [...]}; normalize to list
    if isinstance(resp, dict) and "data" in resp:
        return resp["data"]
    if isinstance(resp, list):
        return resp
    # otherwise return raw
    return resp


def get_usd_spot_balance():
    """
    Return USD spot balance as float (0.0 if none).
    """
    accounts = get_all_accounts()
    # handle when accounts is not a list
    if not isinstance(accounts, list):
        log.warning("get_all_accounts returned unexpected shape; attempting to parse anyway.")
        try:
            accounts = accounts.get("data", [])
        except Exception:
            return 0.0

    for a in accounts:
        # different libs / responses use different keys: try several possibilities
        cur = None
        if "currency" in a:
            # coinbase 'account' object: a['balance'] is dict with currency/amount
            # but some shapes have top-level 'currency'
            cur = a.get("currency") or (a.get("balance") or {}).get("currency")
        else:
            # other shapes
            bal = a.get("balance") or a.get("available") or {}
            cur = (bal.get("currency") if isinstance(bal, dict) else None) or a.get("currency_code") or a.get("asset")

        if cur == "USD" or (isinstance(cur, str) and cur.upper() == "USD"):
            # extract amount from different shapes
            bal = a.get("balance") or a.get("available") or a.get("amount") or {}
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


# If module run directly, quick debug
if __name__ == "__main__":
    log.info("🔍 nija_client debug run")
    try:
        accts = get_all_accounts()
        log.info("Fetched %d accounts", len(accts) if isinstance(accts, list) else 0)
        usd = get_usd_spot_balance()
        log.info("USD spot balance: %s", usd)
    except Exception as exc:
        log.exception("Preflight error: %s", exc)
        raise
