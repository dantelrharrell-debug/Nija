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
SEND_LIVE_TRADES = False  # True = send real trades
RETRY_COUNT = 3
RETRY_DELAY = 1  # seconds
LOG_FILE = "nija_trading_debug.log"

# --- Logging ---
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

# --- Prepare PEM key ---
private_key = COINBASE_PEM_CONTENT.replace("\\n", "\n").encode("utf-8")
private_key_obj = serialization.load_pem_private_key(private_key, password=None, backend=default_backend())

SUB = f"/organizations/{COINBASE_ORG_ID}/apiKeys/{COINBASE_API_KEY_ID}"

# --- Flask app ---
app = Flask(__name__)

# --- Server time check ---
def get_coinbase_time():
    try:
        resp = requests.get("https://api.coinbase.com/v2/time", timeout=5)
        if resp.status_code == 200:
            cb_time = resp.json()["data"]["epoch"]
            local_time = int(time.time())
            drift = local_time - cb_time
            logging.info(f"Coinbase epoch: {cb_time}, Local epoch: {local_time}, Drift: {drift}s")
            return drift
        else:
            logging.warning(f"Failed to fetch Coinbase time: {resp.status_code} {resp.text}")
            return None
    except Exception as e:
        logging.error(f"Exception fetching Coinbase time: {e}")
        return None

# --- JWT generation ---
def generate_jwt(path, method="GET", time_offset=0):
    iat = int(time.time()) - time_offset
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
    logging.info(f"JWT generated: path={path}, method={method}, iat={iat}, exp={iat+120}, sub={SUB}")
    return token

# --- Key permissions check ---
def check_key_permissions():
    path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/key_permissions"
    url = "https://api.coinbase.com" + path
    token = generate_jwt(path)

    for attempt in range(RETRY_COUNT):
        try:
            resp = requests.get(url, headers={
                "Authorization": f"Bearer {token}",
                "CB-VERSION": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
                "Content-Type": "application/json"
            }, timeout=10)

            if resp.status_code == 200:
                perms = resp.json()
                logging.info(f"✅ Key permissions: {perms}")
                return perms
            elif resp.status_code == 401:
                logging.error(f"❌ 401 Unauthorized! Check PEM, ORG_ID, API_KEY_ID, timestamps, IP restrictions.")
                logging.error(f"Response: {resp.text}")
            else:
                logging.warning(f"[Attempt {attempt+1}] Failed: {resp.status_code} {resp.text}")
        except Exception as e:
            logging.error(f"[Attempt {attempt+1}] Exception: {e}")
        time.sleep(RETRY_DELAY)
    return None

# --- Flask route to debug connection ---
@app.route("/test_coinbase_connection")
def test_coinbase_connection():
    drift = get_coinbase_time()
    perms = check_key_permissions()
    return jsonify({
        "server_time_drift": drift,
        "permissions": perms
    })

# --- Main bot startup ---
if __name__ == "__main__":
    logging.info("🔥 Nija Trading Bot starting...")

    drift = get_coinbase_time()
    if drift is not None and abs(drift) > 10:
        logging.warning("⚠️ Server time differs from Coinbase by >10s. Consider adjusting time offset in JWT.")

    perms = check_key_permissions()
    if not perms:
        logging.error("❌ Cannot verify API key permissions. Exiting.")
        exit(1)

    if not perms.get("can_view", False):
        logging.error("❌ Key missing 'view' permission. Exiting.")
        exit(1)

    if not perms.get("can_trade", False):
        logging.warning("⚠️ Key missing 'trade' permission. Live trades will not work.")

    app.run(host="0.0.0.0", port=5000)
