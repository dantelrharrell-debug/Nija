# main.py
import os
import time
import datetime
import requests
import jwt  # PyJWT
import logging
from flask import Flask, request, jsonify
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# --- CONFIG ---
SEND_LIVE_TRADES = False  # Set True to enable real trades
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
SUB = f"/organizations/{COINBASE_ORG_ID}/apiKeys/{COINBASE_API_KEY_ID}"

# Normalize PEM
private_key = COINBASE_PEM_CONTENT.replace("\\n", "\n").encode("utf-8")
private_key_obj = serialization.load_pem_private_key(private_key, password=None, backend=default_backend())

BASE_URL = "https://api.coinbase.com/api/v3/brokerage"

# --- Flask app ---
app = Flask(__name__)

# --- Cache ---
last_accounts = None
last_accounts_ts = 0

# --- Helper: generate JWT ---
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
    logging.debug("JWT preview: %s", token[:100])
    return token

# --- Helper: fetch accounts ---
def fetch_accounts():
    global last_accounts, last_accounts_ts
    path = f"/organizations/{COINBASE_ORG_ID}/accounts"
    request_path = f"/api/v3/brokerage{path}"
    url = BASE_URL + path

    if last_accounts and (time.time() - last_accounts_ts < CACHE_TTL):
        return last_accounts

    for attempt in range(RETRY_COUNT):
        try:
            token = generate_jwt(request_path, "GET")
            resp = requests.get(url, headers={
                "Authorization": f"Bearer {token}",
                "CB-VERSION": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
                "Content-Type": "application/json"
            }, timeout=10)

            if resp.status_code == 200:
                last_accounts = resp.json()
                last_accounts_ts = time.time()
                logging.info("✅ Coinbase accounts fetched successfully.")
                return last_accounts
            else:
                logging.warning("[Attempt %d] Failed to fetch accounts: %s %s", attempt+1, resp.status_code, resp.text)
        except Exception as e:
            logging.error("[Attempt %d] Exception fetching accounts: %s", attempt+1, e)
        time.sleep(RETRY_DELAY)

    raise RuntimeError("Failed to fetch Coinbase accounts after retries.")

# --- Helper: send trade ---
def send_trade(symbol: str, side: str, size: float):
    if not SEND_LIVE_TRADES:
        logging.info("⚠️ Test trade not sent: %s %s %s", side, size, symbol)
        return

    path = "/orders"
    url = BASE_URL + path
    token = generate_jwt("/api/v3/brokerage" + path, "POST")

    payload = {
        "symbol": symbol,
        "side": side.lower(),
        "type": "market",
        "quantity": str(size)
    }

    for attempt in range(RETRY_COUNT):
        try:
            resp = requests.post(url, headers={
                "Authorization": f"Bearer {token}",
                "CB-VERSION": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
                "Content-Type": "application/json"
            }, json=payload, timeout=10)

            if resp.status_code in [200, 201]:
                logging.info("✅ Trade executed: %s %s %s", side, size, symbol)
                logging.info(resp.json())
                return resp.json()
            else:
                logging.warning("[Attempt %d] Trade failed: %s %s", attempt+1, resp.status_code, resp.text)
        except Exception as e:
            logging.error("[Attempt %d] Exception sending trade: %s", attempt+1, e)
        time.sleep(RETRY_DELAY)

    logging.error("❌ Failed to send trade after retries: %s %s %s", side, size, symbol)
    return None

# --- Test Coinbase connection at startup ---
def test_coinbase_connection():
    try:
        accounts = fetch_accounts()
        logging.info("🎯 Coinbase connection verified. Accounts: %s", accounts)
        return True
    except Exception as e:
        logging.error("❌ Coinbase connection failed: %s", e)
        logging.error("❌ Check API keys or permissions before trading.")
        return False

# --- Flask routes ---
@app.route("/debug_jwt")
def debug_jwt_route():
    try:
        accounts = fetch_accounts()
        return jsonify({"status": "ok", "accounts": accounts})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

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
        logging.error("❌ Webhook error: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500

# --- Main ---
if __name__ == "__main__":
    logging.info("🔥 Nija Trading Bot starting...")

    # Test connection first
    test_coinbase_connection()

    # Start Flask
    app.run(host="0.0.0.0", port=5000)
