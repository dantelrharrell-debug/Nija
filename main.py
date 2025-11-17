# --- main.py ---
import os
import time
import datetime
import requests
import jwt
import logging
from flask import Flask, jsonify
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# --- CONFIG ---
CACHE_TTL = 30  # seconds for accounts cache
RETRY_COUNT = 3
RETRY_DELAY = 1  # seconds
LOG_FILE = "nija_trading.log"

# --- Logging setup ---
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

# --- Coinbase env vars ---
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")

# --- Prepare JWT ---
SUB = f"/organizations/{COINBASE_ORG_ID}/apiKeys/{COINBASE_API_KEY_ID}"
private_key = COINBASE_PEM_CONTENT.replace("\\n","\n").encode("utf-8")
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
    logging.info(f"JWT generated: path={path}, method={method}, iat={iat}, exp={iat+120}")
    return token

# --- Helper: check key permissions ---
def check_key_permissions():
    path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/key_permissions"
    url = "https://api.coinbase.com" + path
    for attempt in range(RETRY_COUNT):
        try:
            token = generate_jwt(path)
            resp = requests.get(url, headers={
                "Authorization": f"Bearer {token}",
                "CB-VERSION": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
                "Content-Type": "application/json"
            }, timeout=10)

            if resp.status_code == 200:
                logging.info(f"✅ Key permissions fetched: {resp.json()}")
                return resp.json()
            else:
                logging.warning(f"[Attempt {attempt+1}] Failed: {resp.status_code} {resp.text}")
        except Exception as e:
            logging.error(f"[Attempt {attempt+1}] Exception fetching key permissions: {e}")
        time.sleep(RETRY_DELAY)
    raise RuntimeError("❌ Cannot verify API key permissions. Check PEM, ORG_ID, API_KEY_ID, IP restrictions.")

# --- Helper: fetch funded accounts ---
def fetch_accounts():
    global last_accounts, last_accounts_ts
    path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"

    if last_accounts and (time.time() - last_accounts_ts < CACHE_TTL):
        return last_accounts

    for attempt in range(RETRY_COUNT):
        try:
            token = generate_jwt(path)
            url = "https://api.coinbase.com" + path
            resp = requests.get(url, headers={
                "Authorization": f"Bearer {token}",
                "CB-VERSION": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
                "Content-Type": "application/json"
            }, timeout=10)

            if resp.status_code == 200:
                all_accounts = resp.json()
                # Filter funded accounts only
                funded_accounts = [a for a in all_accounts if float(a.get("balance", {}).get("amount", 0)) > 0]
                last_accounts = funded_accounts
                last_accounts_ts = time.time()
                logging.info(f"Fetched funded accounts: {funded_accounts}")
                return funded_accounts
            else:
                logging.warning(f"[Attempt {attempt+1}] Failed to fetch accounts: {resp.status_code} {resp.text}")
        except Exception as e:
            logging.error(f"[Attempt {attempt+1}] Exception fetching accounts: {e}")
        time.sleep(RETRY_DELAY)
    raise RuntimeError("❌ Failed to fetch Coinbase accounts after retries.")

# --- Flask route: test Coinbase connection ---
@app.route("/test_coinbase_connection")
def test_coinbase_connection():
    try:
        perms = check_key_permissions()
        accounts = fetch_accounts()
        return jsonify({"status": "ok", "permissions": perms, "funded_accounts": accounts})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- Main ---
if __name__ == "__main__":
    logging.info("🔥 Nija Trading Bot starting...")
    try:
        check_key_permissions()
        fetch_accounts()
    except Exception as e:
        logging.error(f"{e}")
        exit(1)

    app.run(host="0.0.0.0", port=5000)
