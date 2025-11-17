# main.py
import os
import time
import datetime
import requests
import jwt
import logging
from flask import Flask, request, jsonify
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# --- CONFIG ---
SEND_LIVE_TRADES = False  # Set True to enable live trades
RETRY_COUNT = 3
RETRY_DELAY = 1  # seconds
CACHE_TTL = 30  # seconds for accounts cache
LOG_FILE = "nija_trading.log"

# --- Setup logging ---
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
console.setFormatter(formatter)
logging.getLogger("").addHandler(console)

# --- Load Coinbase env vars ---
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")

if not all([COINBASE_ORG_ID, COINBASE_API_KEY_ID, COINBASE_PEM_CONTENT]):
    logging.error("❌ Missing Coinbase environment variables! Exiting.")
    exit(1)

SUB = f"/organizations/{COINBASE_ORG_ID}/apiKeys/{COINBASE_API_KEY_ID}"
private_key = COINBASE_PEM_CONTENT.replace("\\n", "\n").encode("utf-8")
private_key_obj = serialization.load_pem_private_key(private_key, password=None, backend=default_backend())

# --- Flask app ---
app = Flask(__name__)

# --- Cache ---
last_accounts = None
last_accounts_ts = 0

# --- Helper: generate JWT ---
def generate_jwt(path: str, method: str = "GET") -> str:
    iat = int(time.time())
    payload = {
        "iat": iat,
        "exp": iat + 120,
        "sub": SUB,
        "request_path": path,
        "method": method.upper(),
        "jti": f"nija-{iat}"
    }
    headers = {"alg": "ES256", "kid": COINBASE_API_KEY_ID}
    token = jwt.encode(payload, private_key_obj, algorithm="ES256", headers=headers)
    return token

# --- Helper: check key permissions ---
def check_key_permissions():
    path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/key_permissions"
    url = f"https://api.coinbase.com{path}"

    for attempt in range(RETRY_COUNT):
        try:
            token = generate_jwt(path)
            resp = requests.get(url, headers={
                "Authorization": f"Bearer {token}",
                "CB-VERSION": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
                "Content-Type": "application/json"
            }, timeout=10)

            # Log drift info
            coinbase_time = int(resp.headers.get("CB-EPOCH", time.time()))
            local_time = int(time.time())
            drift = local_time - coinbase_time
            logging.info(f"Coinbase epoch: {coinbase_time}, Local epoch: {local_time}, Drift: {drift}s")
            if abs(drift) > 10:
                logging.warning("⚠️ Clock drift >10s! Sync server time.")

            if resp.status_code == 200:
                perms = resp.json()
                logging.info(f"✅ Key permissions: {perms}")
                if not perms.get("can_view", False):
                    logging.error("❌ Key missing 'view' permission.")
                if not perms.get("can_trade", False):
                    logging.warning("⚠️ Key missing 'trade' permission.")
                return perms
            elif resp.status_code == 401:
                logging.error(f"❌ 401 Unauthorized! Check PEM, ORG_ID, API_KEY_ID, timestamps, IP restrictions.")
                logging.error(f"JWT payload: {jwt.decode(token, options={'verify_signature': False})}")
                logging.error(f"JWT header: {jwt.get_unverified_header(token)}")
            else:
                logging.warning(f"[Attempt {attempt+1}] Failed: {resp.status_code} {resp.text}")
        except Exception as e:
            logging.error(f"[Attempt {attempt+1}] Exception fetching key permissions: {e}")
        time.sleep(RETRY_DELAY)
    return None

# --- Helper: fetch accounts ---
def fetch_accounts():
    global last_accounts, last_accounts_ts
    path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"

    if last_accounts and (time.time() - last_accounts_ts < CACHE_TTL):
        return last_accounts

    for attempt in range(RETRY_COUNT):
        try:
            token = generate_jwt(path)
            url = f"https://api.coinbase.com{path}"
            resp = requests.get(url, headers={
                "Authorization": f"Bearer {token}",
                "CB-VERSION": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
                "Content-Type": "application/json"
            }, timeout=10)

            if resp.status_code == 200:
                last_accounts = resp.json()
                last_accounts_ts = time.time()
                logging.info(f"Fetched accounts: {last_accounts}")
                return last_accounts
            else:
                logging.warning(f"[Attempt {attempt+1}] Failed to fetch accounts: {resp.status_code} {resp.text}")
        except Exception as e:
            logging.error(f"[Attempt {attempt+1}] Exception fetching accounts: {e}")
        time.sleep(RETRY_DELAY)

    raise RuntimeError("Failed to fetch Coinbase accounts after retries.")

# --- Flask Route: Test connection ---
@app.route("/test_coinbase_connection")
def test_coinbase_connection():
    perms = check_key_permissions()
    accounts = fetch_accounts() if perms and perms.get("can_view", False) else None
    return jsonify({
        "status": "ok",
        "permissions": perms,
        "accounts": accounts
    })

# --- Main ---
if __name__ == "__main__":
    logging.info("🔥 Nija Trading Bot starting...")

    perms = check_key_permissions()
    if not perms:
        logging.error("❌ Cannot verify API key permissions. Exiting.")
        exit(1)

    if not perms.get("can_view", False):
        logging.error("❌ Key does not have 'view' permission. Exiting.")
        exit(1)

    if not perms.get("can_trade", False):
        logging.warning("⚠️ Key does not have 'trade' permission. Live trades will not work.")

    try:
        fetch_accounts()
    except Exception as e:
        logging.error(f"❌ Could not fetch accounts: {e}")

    app.run(host="0.0.0.0", port=5000)
