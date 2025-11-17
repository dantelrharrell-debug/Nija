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
SEND_LIVE_TRADES = False  # Set True to enable real trades
RETRY_COUNT = 3
RETRY_DELAY = 1  # seconds
CACHE_TTL = 30  # seconds
LOG_FILE = "nija_trading.log"

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

# --- Coinbase Env Vars ---
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")

SUB = f"/organizations/{COINBASE_ORG_ID}/apiKeys/{COINBASE_API_KEY_ID}"
private_key = COINBASE_PEM_CONTENT.replace("\\n","\n").encode("utf-8")
private_key_obj = serialization.load_pem_private_key(private_key, password=None, backend=default_backend())

# --- Flask App ---
app = Flask(__name__)

# --- Cache ---
last_accounts = None
last_accounts_ts = 0

# --- JWT Helper ---
def generate_jwt(path, method="GET"):
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

# --- Check Key Permissions ---
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
            
            if resp.status_code == 200:
                perms = resp.json()
                logging.info(f"✅ Key permissions: {perms}")
                return perms
            else:
                logging.warning(f"[Attempt {attempt+1}] Failed to fetch key permissions: {resp.status_code} {resp.text}")
        except Exception as e:
            logging.error(f"[Attempt {attempt+1}] Exception fetching key permissions: {e}")
        time.sleep(RETRY_DELAY)
    return None

# --- Fetch Accounts ---
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

# --- Send Trade ---
def send_trade(symbol: str, side: str, size: float):
    if not SEND_LIVE_TRADES:
        logging.info(f"⚠️ Test trade not sent: {side} {size} {symbol}")
        return

    path = "/api/v3/brokerage/orders"
    token = generate_jwt(path)
    url = f"https://api.coinbase.com{path}"
    payload = {"symbol": symbol, "side": side.lower(), "type": "market", "quantity": str(size)}

    for attempt in range(RETRY_COUNT):
        try:
            resp = requests.post(url, headers={
                "Authorization": f"Bearer {token}",
                "CB-VERSION": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
                "Content-Type": "application/json"
            }, json=payload, timeout=10)
            
            if resp.status_code in [200, 201]:
                logging.info(f"✅ Trade executed: {side} {size} {symbol}")
                logging.info(resp.json())
                return resp.json()
            else:
                logging.warning(f"[Attempt {attempt+1}] Trade failed: {resp.status_code} {resp.text}")
        except Exception as e:
            logging.error(f"[Attempt {attempt+1}] Exception sending trade: {e}")
        time.sleep(RETRY_DELAY)
    logging.error(f"❌ Failed to send trade after {RETRY_COUNT} attempts: {side} {size} {symbol}")
    return None

# --- Routes ---
@app.route("/debug_jwt")
def debug_jwt_route():
    perms = check_key_permissions()
    accounts = fetch_accounts() if perms and perms.get("can_view", False) else None
    return jsonify({"status": "ok", "permissions": perms, "accounts": accounts})

@app.route("/test_trade")
def test_trade_route():
    send_trade("BTC-USD", "buy", 0.001)
    return "Check logs for trade output."

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.json
        symbol = data.get("symbol")
        side = data.get("side")
        size = float(data.get("size", 0))
        if not symbol or not side or size <= 0:
            return jsonify({"status": "error", "message": "Invalid payload"}), 400
        send_trade(symbol, side, size)
        return jsonify({"status": "ok"})
    except Exception as e:
        logging.error(f"❌ Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# --- Test Coinbase Connection Route ---
@app.route("/test_coinbase_connection")
def test_coinbase_connection():
    import datetime, requests, jwt
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.backends import default_backend

    SUB = f"/organizations/{COINBASE_ORG_ID}/apiKeys/{COINBASE_API_KEY_ID}"
    private_key = COINBASE_PEM_CONTENT.replace("\\n","\n").encode("utf-8")
    private_key_obj = serialization.load_pem_private_key(private_key, password=None, backend=default_backend())

    def generate_jwt(path):
        iat = int(time.time())
        payload = {
            "iat": iat,
            "exp": iat + 120,
            "sub": SUB,
            "request_path": path,
            "method": "GET",
            "jti": f"test-{iat}"
        }
        token = jwt.encode(payload, private_key_obj, algorithm="ES256", headers={"alg":"ES256","kid":COINBASE_API_KEY_ID})
        return token

    path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/key_permissions"
    url = f"https://api.coinbase.com{path}"
    token = generate_jwt(path)

    try:
        resp = requests.get(url, headers={
            "Authorization": f"Bearer {token}",
            "CB-VERSION": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
            "Content-Type": "application/json"
        }, timeout=10)
        return {
            "status_code": resp.status_code,
            "response": resp.json() if resp.status_code == 200 else resp.text
        }
    except Exception as e:
        return {"error": str(e)}

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
