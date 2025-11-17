#!/usr/bin/env python3
# main.py
"""
Nija Trading Bot — final diagnostic + connection + fallback script for Coinbase Advanced (CDP).
- Strict PEM normalization
- Coinbase time drift check
- Outbound IP detection (for IP whitelist)
- Robust ES256 JWT generation
- Clear 401 diagnostics (JWT payload/header + outbound IP)
- Fallback key support (optional): tries primary key first, then fallback key automatically
- /test_coinbase_connection and /fetch_funded_accounts endpoints
"""

import os
import time
import datetime
import json
import logging
from typing import Optional, Tuple, Dict, Any
import requests
import jwt
from flask import Flask, jsonify
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# -----------------------
# CONFIG
# -----------------------
SEND_LIVE_TRADES = False        # Keep False until you're 100% ready
RETRY_COUNT = 3
RETRY_DELAY = 1                 # seconds
CACHE_TTL = 30
LOG_FILE = "nija_trading_final.log"
CB_VERSION_DATE = datetime.datetime.utcnow().strftime("%Y-%m-%d")

# -----------------------
# LOGGING
# -----------------------
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.getLogger("").addHandler(console)

# -----------------------
# ENV (primary + optional fallback)
# -----------------------
def env(name: str) -> Optional[str]:
    v = os.getenv(name)
    return v if v and v.strip() != "" else None

PRIMARY = {
    "ORG_ID": env("COINBASE_ORG_ID"),
    "KEY_ID": env("COINBASE_API_KEY_ID"),
    "PEM_RAW": env("COINBASE_PEM_CONTENT")
}

FALLBACK = {
    "ORG_ID": env("COINBASE_FALLBACK_ORG_ID"),
    "KEY_ID": env("COINBASE_FALLBACK_API_KEY_ID"),
    "PEM_RAW": env("COINBASE_FALLBACK_PEM_CONTENT")
}

if not PRIMARY["ORG_ID"] or not PRIMARY["KEY_ID"] or not PRIMARY["PEM_RAW"]:
    logging.error("Missing primary Coinbase env vars. Please set COINBASE_ORG_ID, COINBASE_API_KEY_ID, COINBASE_PEM_CONTENT.")
    raise SystemExit(1)

# -----------------------
# PEM normalization & loader
# -----------------------
def normalize_pem(raw: str) -> str:
    if raw is None:
        return ""
    pem = raw.strip()
    # if escaped newlines present, convert them to real newlines
    if "\\n" in pem and "\n" not in pem:
        pem = pem.replace("\\n", "\n")
    return pem.strip()

def load_private_key_from_pem(pem_text: str):
    try:
        key_obj = serialization.load_pem_private_key(pem_text.encode("utf-8"), password=None, backend=default_backend())
        return key_obj
    except Exception as e:
        logging.exception("Failed to load PEM key: %s", e)
        return None

def build_key_bundle(org_id: str, key_id: str, pem_raw: str) -> Optional[Dict[str, Any]]:
    pem = normalize_pem(pem_raw)
    key_obj = load_private_key_from_pem(pem)
    if not key_obj:
        return None
    sub = f"/organizations/{org_id}/apiKeys/{key_id}"
    return {"ORG_ID": org_id, "KEY_ID": key_id, "PEM": pem, "KEY_OBJ": key_obj, "SUB": sub}

primary_bundle = build_key_bundle(PRIMARY["ORG_ID"], PRIMARY["KEY_ID"], PRIMARY["PEM_RAW"])
if not primary_bundle:
    logging.error("Primary key bundle invalid. Check COINBASE_PEM_CONTENT formatting and values.")
    raise SystemExit(1)

fallback_bundle = None
if FALLBACK["ORG_ID"] and FALLBACK["KEY_ID"] and FALLBACK["PEM_RAW"]:
    fallback_bundle = build_key_bundle(FALLBACK["ORG_ID"], FALLBACK["KEY_ID"], FALLBACK["PEM_RAW"])
    if fallback_bundle:
        logging.info("Fallback key bundle loaded and available.")
    else:
        logging.warning("Fallback key bundle provided but failed to load. Ignoring fallback key.")

# -----------------------
# Flask app
# -----------------------
app = Flask(__name__)

# -----------------------
# Cache
# -----------------------
last_accounts = None
last_accounts_ts = 0

# -----------------------
# Helpers: outbound IP detection + time drift
# -----------------------
def get_outbound_ip() -> Tuple[Optional[str], Optional[str]]:
    services = [
        ("https://api.ipify.org?format=json", "ipify"),
        ("https://ifconfig.co/json", "ifconfig.co"),
        ("https://ifconfig.me/all.json", "ifconfig.me")
    ]
    for url, name in services:
        try:
            r = requests.get(url, timeout=4)
            if r.status_code == 200:
                j = None
                try:
                    j = r.json()
                except Exception:
                    pass
                if isinstance(j, dict):
                    ip = j.get("ip") or j.get("ip_addr") or j.get("IP")
                    if ip:
                        return ip, name
                else:
                    txt = r.text.strip()
                    if txt:
                        return txt, name
        except Exception:
            continue
    return None, None

def coinbase_time_drift_seconds() -> Optional[int]:
    try:
        r = requests.get("https://api.coinbase.com/v2/time", timeout=5)
        cb_epoch = int(r.json()["data"]["epoch"])
        local_epoch = int(time.time())
        return local_epoch - cb_epoch
    except Exception:
        return None

# -----------------------
# JWT generation (for a given bundle)
# -----------------------
def generate_jwt_for_bundle(bundle: Dict[str, Any], request_path: str, method: str = "GET", time_offset: int = 0) -> Tuple[Optional[str], Dict[str, Any], Dict[str, Any]]:
    iat = int(time.time()) - time_offset
    payload = {
        "iat": iat,
        "exp": iat + 120,
        "sub": bundle["SUB"],
        "request_path": request_path,
        "method": method.upper(),
        "jti": f"nija-{iat}"
    }
    headers = {"alg": "ES256", "kid": bundle["KEY_ID"], "typ": "JWT"}
    try:
        token = jwt.encode(payload, bundle["KEY_OBJ"], algorithm="ES256", headers=headers)
        return token, payload, headers
    except Exception as e:
        logging.exception("Failed to encode JWT: %s", e)
        return None, payload, headers

# -----------------------
# Low-level request with debug; tries with a provided bundle
# -----------------------
def coinbase_get_with_bundle(bundle: Dict[str, Any], request_path: str) -> Tuple[Optional[Any], Optional[requests.Response]]:
    url = f"https://api.coinbase.com{request_path}"
    for attempt in range(1, RETRY_COUNT + 1):
        token, payload, headers = generate_jwt_for_bundle(bundle, request_path, "GET")
        if not token:
            logging.error("JWT generation failed for bundle %s", bundle.get("KEY_ID"))
            return None, None
        try:
            resp = requests.get(url, headers={
                "Authorization": f"Bearer {token}",
                "CB-VERSION": CB_VERSION_DATE,
                "Content-Type": "application/json"
            }, timeout=10)
        except Exception as e:
            logging.error("[Attempt %d] Request error: %s", attempt, e)
            if attempt < RETRY_COUNT:
                time.sleep(RETRY_DELAY)
                continue
            return None, None

        if resp.status_code == 200:
            try:
                return resp.json(), resp
            except Exception:
                return resp.text, resp

        if resp.status_code == 401:
            logging.error("[Attempt %d] 401 Unauthorized for %s using key %s", attempt, request_path, bundle.get("KEY_ID"))
            # Log JWT internals (unverified) and outbound IP for whitelist debugging
            try:
                logging.error("JWT payload (unverified): %s", json.dumps(payload))
                logging.error("JWT header (unverified): %s", json.dumps(headers))
            except Exception:
                logging.exception("Error logging JWT internals")
            ip, src = get_outbound_ip()
            if ip:
                logging.error("Outbound IP detected (%s): %s", src, ip)
                logging.error("If your key is IP restricted, whitelist this IP in Coinbase Advanced.")
            logging.error("Coinbase response body: %s", resp.text)
            if attempt < RETRY_COUNT:
                time.sleep(RETRY_DELAY)
                continue
            return None, resp

        # Other non-200 codes: retry a few times then return the response object
        logging.warning("[Attempt %d] Unexpected status %d for %s: %s", attempt, resp.status_code, request_path, resp.text)
        if attempt < RETRY_COUNT:
            time.sleep(RETRY_DELAY)
            continue
        return None, resp
    return None, None

# -----------------------
# High-level: try primary then fallback automatically
# -----------------------
def call_coinbase_try_fallback(request_path: str) -> Tuple[Optional[Any], Optional[requests.Response], Optional[Dict[str, Any]]]:
    """
    Returns (data, response, bundle_used)
    """
    # Try primary
    data, resp = coinbase_get_with_bundle(primary_bundle, request_path)
    if resp is not None and resp.status_code == 200:
        return data, resp, primary_bundle

    # Primary failed with 401 or other; if fallback exists, try fallback
    if fallback_bundle:
        logging.info("Primary key failed; attempting fallback key (no-IP key).")
        data2, resp2 = coinbase_get_with_bundle(fallback_bundle, request_path)
        if resp2 is not None and resp2.status_code == 200:
            logging.info("Fallback key succeeded. Switching to fallback for this session.")
            return data2, resp2, fallback_bundle
        # fallback failed too
        logging.error("Fallback key also failed: %s", resp2.text if resp2 is not None else "no response")
        return None, resp2, fallback_bundle
    else:
        logging.error("Primary key failed and no fallback key is configured.")
        return None, resp, primary_bundle

# -----------------------
# Key permissions & fetch accounts
# -----------------------
def check_key_permissions_try_fallback() -> Optional[Dict[str, Any]]:
    path = f"/api/v3/brokerage/organizations/{primary_bundle['ORG_ID']}/key_permissions"
    data, resp, bundle = call_coinbase_try_fallback(path)
    if resp is None:
        logging.error("No response checking key permissions (both primary and fallback if present).")
        return None
    if resp.status_code == 200:
        logging.info("Key permissions (using key %s): %s", bundle.get("KEY_ID"), json.dumps(data)[:2000])
        return data
    logging.error("Key permissions check failed: %s", resp.text)
    return None

def fetch_funded_accounts_try_fallback():
    global last_accounts, last_accounts_ts
    if last_accounts and (time.time() - last_accounts_ts) < CACHE_TTL:
        logging.info("Returning cached funded accounts.")
        return last_accounts

    path = f"/api/v3/brokerage/organizations/{primary_bundle['ORG_ID']}/accounts"
    data, resp, bundle = call_coinbase_try_fallback(path)
    if resp is None:
        raise RuntimeError("No response fetching accounts.")
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to fetch accounts: {resp.status_code} {resp.text}")

    # parse accounts list robustly
    accounts_list = None
    if isinstance(data, dict):
        if "accounts" in data and isinstance(data["accounts"], list):
            accounts_list = data["accounts"]
        elif "data" in data and isinstance(data["data"], list):
            accounts_list = data["data"]
        else:
            for v in data.values():
                if isinstance(v, list):
                    accounts_list = v
                    break
    elif isinstance(data, list):
        accounts_list = data

    if not accounts_list:
        logging.warning("Unexpected accounts response shape. Raw: %s", json.dumps(data)[:2000])
        raise RuntimeError("Could not parse accounts response.")

    funded = []
    for a in accounts_list:
        bal = None
        if isinstance(a, dict):
            b = a.get("balance") or a.get("available") or a.get("cash_balance")
            if isinstance(b, dict):
                try:
                    bal = float(b.get("amount") or b.get("value") or 0)
                except Exception:
                    bal = None
            else:
                try:
                    bal = float(b)
                except Exception:
                    bal = None
        if bal and bal > 0:
            funded.append(a)

    last_accounts = funded
    last_accounts_ts = time.time()
    logging.info("Fetched funded accounts count=%d (using key %s)", len(funded), bundle.get("KEY_ID") if bundle else "unknown")
    return funded

# -----------------------
# Flask routes (public)
# -----------------------
@app.route("/test_coinbase_connection", methods=["GET"])
def route_test_connection():
    ip, src = get_outbound_ip()
    drift = coinbase_time_drift_seconds()
    perms = check_key_permissions_try_fallback()
    accounts = None
    if perms and perms.get("can_view", False):
        try:
            accounts = fetch_funded_accounts_try_fallback()
        except Exception as e:
            accounts = {"error_fetching": str(e)}
    return jsonify({
        "outbound_ip": {"ip": ip, "service": src},
        "coinbase_time_drift_seconds": drift,
        "key_permissions": perms,
        "funded_accounts": accounts
    })

@app.route("/fetch_funded_accounts", methods=["GET"])
def route_fetch_accounts():
    try:
        accounts = fetch_funded_accounts_try_fallback()
        return jsonify({"funded_accounts": accounts})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -----------------------
# STARTUP routine
# -----------------------
if __name__ == "__main__":
    logging.info("🔥 Nija Trading Bot final startup...")

    ip, src = get_outbound_ip()
    if ip:
        logging.info("Outbound IP detected: %s (via %s). If your key is IP restricted, whitelist this IP in Coinbase Advanced.", ip, src)
    else:
        logging.info("Could not detect outbound IP. If your key is IP restricted, ensure server IPs are allowed.")

    drift = coinbase_time_drift_seconds()
    logging.info("Coinbase time drift (local - coinbase) seconds: %s", str(drift))
    if drift is not None and abs(drift) > 10:
        logging.warning("Local clock differs from Coinbase by >10s. Fix server time or use time_offset carefully.")

    perms = check_key_permissions_try_fallback()
    if not perms:
        logging.error("❌ Key permissions check failed for both primary and fallback keys (if configured). Resolve PEM/ORG/KEY/IP/Permissions.")
        raise SystemExit(1)

    if not perms.get("can_view", False):
        logging.error("❌ API key missing 'can_view' permission. Grant 'view' in Coinbase Advanced and retry.")
        raise SystemExit(1)

    try:
        funded = fetch_funded_accounts_try_fallback()
        logging.info("Initial funded accounts loaded: %s", json.dumps(funded)[:2000])
    except Exception as e:
        logging.warning("Could not load funded accounts on startup: %s", e)

    logging.info("Server listening on 0.0.0.0:5000 - use /test_coinbase_connection")
    app.run(host="0.0.0.0", port=5000)
