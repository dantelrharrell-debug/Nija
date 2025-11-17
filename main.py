# main.py
import os
import time
import datetime
import requests
import jwt
import logging
import json
from flask import Flask, jsonify, request
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# -----------------------
# CONFIG
# -----------------------
SEND_LIVE_TRADES = False        # Toggle to True only when you are 100% ready
RETRY_COUNT = 3
RETRY_DELAY = 1                # seconds
CACHE_TTL = 30                 # accounts cache
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
# ENV - must be set in Railway/Render
# -----------------------
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")
COINBASE_PEM_CONTENT_RAW = os.getenv("COINBASE_PEM_CONTENT")  # can be multiline or escaped \n

# -----------------------
# VALIDATE ENV
# -----------------------
missing = []
if not COINBASE_ORG_ID:
    missing.append("COINBASE_ORG_ID")
if not COINBASE_API_KEY_ID:
    missing.append("COINBASE_API_KEY_ID")
if not COINBASE_PEM_CONTENT_RAW:
    missing.append("COINBASE_PEM_CONTENT")

if missing:
    logging.error("Missing environment variables: %s. Set them before running.", ", ".join(missing))
    raise SystemExit(1)

# -----------------------
# UTIL: PEM normalization & private key loader
# -----------------------
def normalize_pem(raw: str) -> str:
    """
    Accepts either:
      - a real multiline PEM (preferred), or
      - a single-line value with escaped \\n sequences.
    Returns well-formed PEM (with real newlines).
    """
    if raw is None:
        return ""
    pem = raw.strip()
    # If user pasted escaped \n (literal backslash + n), convert them
    if "\\n" in pem and "-----BEGIN" in pem:
        pem = pem.replace("\\n", "\n")
    # Ensure header/footer exist and are on their own lines
    if not pem.startswith("-----BEGIN"):
        # maybe the user pasted without header/footer - can't recover
        logging.warning("PEM does not start with -----BEGIN. This is likely invalid.")
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
    logging.error("Cannot continue: PEM failed to parse. Re-check COINBASE_PEM_CONTENT.")
    raise SystemExit(1)

SUB = f"/organizations/{COINBASE_ORG_ID}/apiKeys/{COINBASE_API_KEY_ID}"

# -----------------------
# FLASK APP
# -----------------------
app = Flask(__name__)

# -----------------------
# CACHE
# -----------------------
last_accounts = None
last_accounts_ts = 0

# -----------------------
# Helper: outbound IP detection (for IP whitelist debugging)
# -----------------------
def get_outbound_ip():
    """
    Returns (ip, source) or (None, None) on failure.
    Tries a couple of known IP services; used only for debugging.
    """
    services = [
        ("https://api.ipify.org?format=json", "ipify"),
        ("https://ifconfig.co/json", "ifconfig.co"),
        ("https://ifconfig.me/all.json", "ifconfig.me")
    ]
    for url, name in services:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                try:
                    data = r.json()
                    # Different services use different keys
                    ip = data.get("ip") or data.get("ip_addr") or data.get("ip_address") or data.get("ip_addr_v4") or data.get("IP")
                    if not ip:
                        # For ifconfig.me style: try "raw" fallback
                        ip = data.get("raw", None)
                    if ip:
                        logging.info("Detected outbound IP via %s: %s", name, ip)
                        return ip, name
                except ValueError:
                    # Some endpoints return plain text; use that
                    txt = r.text.strip()
                    if txt:
                        logging.info("Detected outbound IP via %s (text): %s", name, txt)
                        return txt, name
        except Exception as e:
            logging.debug("Outbound IP check %s failed: %s", name, e)
    logging.warning("Could not determine outbound IP from common services.")
    return None, None

# -----------------------
# Helper: generate JWT (Coinbase Advanced)
# -----------------------
def generate_jwt(request_path: str, method: str = "GET", time_offset: int = 0):
    """
    request_path: exact request_path used in Coinbase docs, e.g. /api/v3/brokerage/organizations/<org>/key_permissions
    method: uppercase string
    time_offset: seconds to subtract from local time if you need to compensate drift (not recommended unless tested)
    """
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
    logging.info("✅ JWT generated: path=%s method=%s iat=%s exp=%s", request_path, method, payload["iat"], payload["exp"])
    return token, payload, headers

# -----------------------
# Helper: call Coinbase with retries & detailed 401 debug
# -----------------------
def coinbase_get(request_path: str):
    url = f"https://api.coinbase.com{request_path}"
    for attempt in range(1, RETRY_COUNT + 1):
        token, payload, headers = generate_jwt(request_path, "GET")
        if not token:
            logging.error("No JWT token generated; aborting request.")
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
            logging.info("[Attempt %d] Success: %s", attempt, request_path)
            try:
                return resp.json(), resp
            except Exception:
                return resp.text, resp
        elif resp.status_code == 401:
            logging.error("[Attempt %d] 401 Unauthorized for %s", attempt, request_path)
            # Unverified JWT details for debugging
            try:
                logging.error("JWT payload: %s", json.dumps(payload))
                logging.error("JWT header: %s", json.dumps(headers))
            except Exception:
                logging.error("Unable to log JWT internals.")
            # outbound IP info (helpful for IP whitelist)
            ip, src = get_outbound_ip()
            if ip:
                logging.error("Outbound IP detected (%s): %s", src, ip)
                logging.error("If your API key is IP restricted, whitelist this IP.")
            logging.error("Coinbase response body: %s", resp.text)
            # 401 is definitive for this token; retrying might help if transient, otherwise break
            if attempt < RETRY_COUNT:
                time.sleep(RETRY_DELAY)
                continue
            return None, resp
        else:
            logging.warning("[Attempt %d] Unexpected status %d: %s", attempt, resp.status_code, resp.text)
            if attempt < RETRY_COUNT:
                time.sleep(RETRY_DELAY)
                continue
            return None, resp
    return None, None

# -----------------------
# Key Permissions check
# -----------------------
def check_key_permissions():
    path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/key_permissions"
    data, resp = coinbase_get(path)
    if resp is None:
        logging.error("No response from Coinbase when checking permissions.")
        return None
    if resp.status_code == 200:
        logging.info("Key permissions payload: %s", json.dumps(data))
        return data
    else:
        logging.error("Key permissions check failed: %s", resp.text if resp is not None else "no resp")
        return None

# -----------------------
# Fetch funded accounts
# -----------------------
def fetch_funded_accounts():
    global last_accounts, last_accounts_ts
    if last_accounts and (time.time() - last_accounts_ts) < CACHE_TTL:
        logging.info("Returning cached accounts.")
        return last_accounts

    path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
    data, resp = coinbase_get(path)
    if resp is None:
        raise RuntimeError("No response fetching accounts.")
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to fetch accounts: {resp.status_code} {resp.text}")

    # Response shape might differ; attempt robust handling
    accounts_list = None
    if isinstance(data, dict):
        # Some responses: { "accounts": [...] } or direct list
        if "accounts" in data and isinstance(data["accounts"], list):
            accounts_list = data["accounts"]
        elif "data" in data and isinstance(data["data"], list):
            accounts_list = data["data"]
        else:
            # try to detect list in dict values
            for v in data.values():
                if isinstance(v, list):
                    accounts_list = v
                    break
    elif isinstance(data, list):
        accounts_list = data

    if accounts_list is None:
        logging.warning("Could not parse accounts structure from response. Raw data logged.")
        logging.debug("Accounts raw: %s", json.dumps(data))
        raise RuntimeError("Unexpected accounts response shape.")

    funded = []
    for a in accounts_list:
        # attempt to fetch balance in common shapes
        balance_amount = None
        balance_obj = a.get("balance") if isinstance(a, dict) else None
        if isinstance(balance_obj, dict):
            amt = balance_obj.get("amount") or balance_obj.get("value") or balance_obj.get("currency_amount")
            try:
                balance_amount = float(amt)
            except Exception:
                balance_amount = None
        # fallback: some APIs return "available" or "cash_balance"
        if balance_amount is None:
            for key in ("available", "cash_balance", "balance"):
                val = a.get(key) if isinstance(a, dict) else None
                try:
                    if isinstance(val, (str, int, float)):
                        balance_amount = float(val)
                        break
                    elif isinstance(val, dict) and "amount" in val:
                        balance_amount = float(val["amount"])
                        break
                except Exception:
                    balance_amount = None

        if balance_amount and balance_amount > 0:
            funded.append(a)

    last_accounts = funded
    last_accounts_ts = time.time()
    logging.info("Fetched funded accounts count: %d", len(funded))
    return funded

# -----------------------
# Flask routes
# -----------------------
@app.route("/test_coinbase_connection", methods=["GET"])
def route_test_connection():
    """
    Returns:
      - outbound IP (for IP whitelist)
      - coinbase server time drift check
      - key permissions (if available)
      - funded accounts (if permissions allow)
    """
    ip, src = get_outbound_ip()
    # coinbase time
    try:
        t = requests.get("https://api.coinbase.com/v2/time", timeout=5)
        coinbase_epoch = int(t.json()["data"]["epoch"])
        local_epoch = int(time.time())
        drift = local_epoch - coinbase_epoch
    except Exception as e:
        logging.debug("Coinbase time fetch failed: %s", e)
        drift = None

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
# STARTUP CHECKS
# -----------------------
if __name__ == "__main__":
    logging.info("🔥 Nija Trading Bot diagnostic startup...")

    # 1) detect outbound IP
    ip, src = get_outbound_ip()
    if ip:
        logging.info("Outbound IP detected: %s (from %s). If your key is IP restricted, whitelist this IP.", ip, src)
    else:
        logging.info("Could not detect outbound IP. If your key is IP restricted, you must ensure server IP is whitelisted.")

    # 2) check clock drift with Coinbase
    try:
        r = requests.get("https://api.coinbase.com/v2/time", timeout=5)
        cb_epoch = int(r.json()["data"]["epoch"])
        local_epoch = int(time.time())
        drift = local_epoch - cb_epoch
        logging.info("Coinbase epoch: %s, Local epoch: %s, Drift: %ss", cb_epoch, local_epoch, drift)
        if abs(drift) > 10:
            logging.warning("⚠️ Local clock differs from Coinbase by >10s. Consider fixing server time.")
    except Exception as e:
        logging.warning("Could not fetch Coinbase time for drift check: %s", e)

    # 3) check key permissions (this will show the root cause if 401)
    perms = check_key_permissions()
    if not perms:
        logging.error("❌ Key permissions check failed. Resolve 401 (PEM/ORG/KEY/IP) before continuing.")
        # exit so the container does not keep restarting and hammering Coinbase
        raise SystemExit(1)

    # 4) validate view permission and fetch accounts
    if not perms.get("can_view", False):
        logging.error("❌ API key missing 'can_view' permission. Grant 'view' in Coinbase Advanced and retry.")
        raise SystemExit(1)

    try:
        funded = fetch_funded_accounts()
        logging.info("Initial funded accounts loaded: %s", funded)
    except Exception as e:
        logging.warning("Could not load funded accounts on startup: %s", e)

    # 5) run flask for interactive testing endpoints
    logging.info("Diagnostic server listening on 0.0.0.0:5000 - use /test_coinbase_connection")
    app.run(host="0.0.0.0", port=5000)
