#!/usr/bin/env python3
# main.py
"""
Nija Trading Bot - Coinbase Advanced diagnostics & funded account fetcher.

Purpose:
- Strict PEM normalization & loading
- Coinbase server time check
- Outbound IP detection (helps solve IP whitelist 401s)
- Robust JWT generation for Coinbase Advanced (ES256)
- Detailed debugging for 401 Unauthorized (payload/header/outbound IP)
- /test_coinbase_connection and /fetch_funded_accounts routes
"""

import os
import time
import datetime
import json
import requests
import jwt
import logging
from flask import Flask, jsonify, request
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# -----------------------
# CONFIG
# -----------------------
SEND_LIVE_TRADES = False
RETRY_COUNT = 3
RETRY_DELAY = 1
CACHE_TTL = 30
LOG_FILE = "nija_trading_debug.log"
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
# ENV - REQUIRED
# -----------------------
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")
COINBASE_PEM_CONTENT_RAW = os.getenv("COINBASE_PEM_CONTENT")  # multiline OR escaped \n

# quick env validation
missing = [n for n, v in (("COINBASE_ORG_ID", COINBASE_ORG_ID),
                          ("COINBASE_API_KEY_ID", COINBASE_API_KEY_ID),
                          ("COINBASE_PEM_CONTENT", COINBASE_PEM_CONTENT_RAW)) if not v]
if missing:
    logging.error("Missing required environment variables: %s", ", ".join(missing))
    raise SystemExit(1)

# -----------------------
# PEM normalize & load
# -----------------------
def normalize_pem(raw: str) -> str:
    if raw is None:
        return ""
    pem = raw.strip()
    # allow escaped \n or literal newlines
    if "\\n" in pem and not "\n" in pem:
        pem = pem.replace("\\n", "\n")
    # trim extra leading/trailing whitespace
    pem = pem.strip()
    return pem

def load_private_key(pem_text: str):
    try:
        pem_bytes = pem_text.encode("utf-8")
        key_obj = serialization.load_pem_private_key(pem_bytes, password=None, backend=default_backend())
        logging.info("Private key loaded successfully.")
        return key_obj
    except Exception as e:
        logging.error("Failed to load private key: %s", e)
        return None

PEM = normalize_pem(COINBASE_PEM_CONTENT_RAW)
private_key_obj = load_private_key(PEM)
if not private_key_obj:
    logging.error("Cannot parse PEM. Re-check COINBASE_PEM_CONTENT (must include header/footer).")
    raise SystemExit(1)

SUB = f"/organizations/{COINBASE_ORG_ID}/apiKeys/{COINBASE_API_KEY_ID}"

# -----------------------
# FLASK app
# -----------------------
app = Flask(__name__)

# -----------------------
# Cache
# -----------------------
last_accounts = None
last_accounts_ts = 0

# -----------------------
# Outbound IP detection
# -----------------------
def get_outbound_ip():
    services = [
        ("https://api.ipify.org?format=json", "ipify"),
        ("https://ifconfig.co/json", "ifconfig.co"),
        ("https://ifconfig.me/all.json", "ifconfig.me"),
    ]
    for url, name in services:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                try:
                    data = r.json()
                    ip = data.get("ip") or data.get("ip_addr") or data.get("ip_address") or data.get("IP")
                    if ip:
                        return ip, name
                except ValueError:
                    txt = r.text.strip()
                    if txt:
                        return txt, name
        except Exception:
            continue
    return None, None

# -----------------------
# Server time check
# -----------------------
def coinbase_time_drift():
    try:
        r = requests.get("https://api.coinbase.com/v2/time", timeout=5)
        cb_epoch = int(r.json()["data"]["epoch"])
        local_epoch = int(time.time())
        return local_epoch - cb_epoch
    except Exception as e:
        logging.debug("Coinbase time check failed: %s", e)
        return None

# -----------------------
# JWT generation
# -----------------------
def generate_jwt(request_path: str, method: str = "GET", time_offset: int = 0):
    iat = int(time.time()) - time_offset
    payload = {
        "iat": iat,
        "exp": iat + 120,
        "sub": SUB,
        "request_path": request_path,
        "method": method.upper(),
        "jti": f"nija-{iat}"
    }
    headers = {"alg": "ES256", "kid": COINBASE_API_KEY_ID, "typ": "JWT"}
    try:
        token = jwt.encode(payload, private_key_obj, algorithm="ES256", headers=headers)
    except Exception as e:
        logging.exception("Failed to encode JWT: %s", e)
        return None, payload, headers
    logging.info("JWT generated: path=%s method=%s iat=%s exp=%s", request_path, method, payload["iat"], payload["exp"])
    return token, payload, headers

# -----------------------
# Low-level GET with 401 debug
# -----------------------
def coinbase_get(request_path: str):
    url = f"https://api.coinbase.com{request_path}"
    for attempt in range(1, RETRY_COUNT + 1):
        token, payload, headers = generate_jwt(request_path, "GET")
        if token is None:
            logging.error("JWT generation failed; aborting request.")
            return None, None
        try:
            resp = requests.get(url, headers={
                "Authorization": f"Bearer {token}",
                "CB-VERSION": CB_VERSION_DATE,
                "Content-Type": "application/json"
            }, timeout=10)
        except Exception as e:
            logging.error("[Attempt %d] Request exception: %s", attempt, e)
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
            logging.error("[Attempt %d] 401 Unauthorized for %s", attempt, request_path)
            # log JWT payload & headers (unverified)
            try:
                logging.error("JWT payload (unverified): %s", json.dumps(payload))
                logging.error("JWT header (unverified): %s", json.dumps(headers))
            except Exception:
                logging.exception("Error logging JWT internals")
            # outbound IP (helpful for IP whitelist)
            ip, src = get_outbound_ip()
            if ip:
                logging.error("Outbound IP detected (%s): %s", src, ip)
                logging.error("If your key is IP restricted, whitelist this IP in Coinbase Advanced.")
            logging.error("Coinbase response body: %s", resp.text)
            if attempt < RETRY_COUNT:
                time.sleep(RETRY_DELAY)
                continue
            return None, resp
        # other statuses: log and retry if allowed
        logging.warning("[Attempt %d] Unexpected status %d for %s: %s", attempt, resp.status_code, request_path, resp.text)
        if attempt < RETRY_COUNT:
            time.sleep(RETRY_DELAY)
            continue
        return None, resp
    return None, None

# -----------------------
# check_key_permissions
# -----------------------
def check_key_permissions():
    path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/key_permissions"
    data, resp = coinbase_get(path)
    if resp is None:
        logging.error("No response from Coinbase while checking key permissions.")
        return None
    if resp.status_code == 200:
        logging.info("Key permissions: %s", json.dumps(data))
        return data
    logging.error("Key permissions check failed: %s", resp.text if resp is not None else "no response")
    return None

# -----------------------
# fetch_funded_accounts
# -----------------------
def fetch_funded_accounts():
    global last_accounts, last_accounts_ts
    if last_accounts and (time.time() - last_accounts_ts) < CACHE_TTL:
        logging.info("Returning cached funded accounts.")
        return last_accounts

    path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
    data, resp = coinbase_get(path)
    if resp is None:
        raise RuntimeError("No response fetching accounts.")
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to fetch accounts: {resp.status_code} {resp.text}")

    # Normalize response to a list of account dicts
    accounts_list = None
    if isinstance(data, dict):
        # common shapes: {"accounts": [...] } or {"data": [...]}
        if "accounts" in data and isinstance(data["accounts"], list):
            accounts_list = data["accounts"]
        elif "data" in data and isinstance(data["data"], list):
            accounts_list = data["data"]
        else:
            # search for the first list
            for v in data.values():
                if isinstance(v, list):
                    accounts_list = v
                    break
    elif isinstance(data, list):
        accounts_list = data

    if not accounts_list:
        logging.warning("Unexpected accounts response shape. Raw: %s", json.dumps(data))
        raise RuntimeError("Could not parse accounts response.")

    funded = []
    for a in accounts_list:
        # try common shapes
        bal = None
        if isinstance(a, dict):
            b = a.get("balance") or a.get("available") or a.get("cash_balance")
            if isinstance(b, dict):
                try:
                    bal = float(b.get("amount") or b.get("value") or b.get("quantity") or 0)
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
    logging.info("Fetched funded accounts count=%d", len(funded))
    return funded

# -----------------------
# Flask routes
# -----------------------
@app.route("/test_coinbase_connection", methods=["GET"])
def route_test_connection():
    ip, src = get_outbound_ip()
    drift = coinbase_time_drift()
    perms = check_key_permissions()
    accounts = None
    if perms and perms.get("can_view", False):
        try:
            accounts = fetch_funded_accounts()
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
        accounts = fetch_funded_accounts()
        return jsonify({"funded_accounts": accounts})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -----------------------
# Startup diagnostics & run
# -----------------------
if __name__ == "__main__":
    logging.info("🔥 Nija Trading Bot diagnostic startup...")

    # Outbound IP
    ip, src = get_outbound_ip()
    if ip:
        logging.info("Outbound IP detected: %s (via %s). If API key uses IP whitelist, add this IP.", ip, src)
    else:
        logging.info("Could not detect outbound IP. If API key uses IP whitelist, ensure server IPs are allowed.")

    # Drift check
    drift = coinbase_time_drift()
    logging.info("Coinbase time drift (local - coinbase) seconds: %s", str(drift))
    if drift is not None and abs(drift) > 10:
        logging.warning("Local clock differs from Coinbase by >10s. Fix server time or use a time_offset carefully.")

    # Key permissions check (this will reveal 401s)
    perms = check_key_permissions()
    if not perms:
        logging.error("❌ Key permissions check failed. Resolve 401 (PEM/ORG/KEY/IP/Permissions) before continuing.")
        raise SystemExit(1)

    if not perms.get("can_view", False):
        logging.error("❌ API key missing 'can_view' permission. Grant 'view' in Coinbase Advanced and retry.")
        raise SystemExit(1)

    # Attempt to fetch funded accounts once at startup
    try:
        funded = fetch_funded_accounts()
        logging.info("Initial funded accounts loaded: %s", json.dumps(funded)[:1000])
    except Exception as e:
        logging.warning("Could not load funded accounts on startup: %s", e)

    logging.info("Diagnostic server listening on 0.0.0.0:5000 - use /test_coinbase_connection")
    app.run(host="0.0.0.0", port=5000)
