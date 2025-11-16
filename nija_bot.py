# --- Add this helper ---
def test_coinbase_connection(client):
    """
    Test if the Coinbase client can fetch accounts.
    Returns True if successful, False otherwise.
    """
    try:
        accounts = client.get_accounts()  # or your fetch_accounts() method
        print(f"✅ Coinbase connection verified. Accounts fetched: {accounts}")
        return True
    except Exception as e:
        print(f"❌ Coinbase connection failed: {e}")
        return False

import os
import time
import datetime
import requests
import jwt  # PyJWT
import logging
from flask import Flask, request, jsonify

# --- CONFIG ---
SEND_LIVE_TRADES = False  # Set True to enable real trades
RETRY_COUNT = 3
RETRY_DELAY = 1  # seconds between retries
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
COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")  # short UUID
COINBASE_API_SUB = os.getenv("COINBASE_API_SUB")        # full path
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")

private_key = COINBASE_PEM_CONTENT.replace("\\n", "\n")

# --- Flask app ---
app = Flask(__name__)

# --- Cache for accounts ---
last_accounts_spot = None
last_accounts_adv = None
last_accounts_ts_spot = 0
last_accounts_ts_adv = 0

# --- Helper: generate JWT ---
def generate_jwt(path: str, method: str = "GET") -> str:
    iat = int(time.time())
    payload = {
        "iat": iat,
        "exp": iat + 120,
        "sub": COINBASE_API_SUB,
        "request_path": path,
        "method": method,
        "jti": f"nija-{iat}"
    }
    headers = {
        "alg": "ES256",
        "kid": COINBASE_API_KEY_ID,
        "typ": "JWT"
    }
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
    return token

# --- Helper: fetch accounts with caching ---
def fetch_accounts(advanced=False):
    global last_accounts_spot, last_accounts_adv, last_accounts_ts_spot, last_accounts_ts_adv

    coinbase_path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
    cache = last_accounts_adv if advanced else last_accounts_spot
    ts_cache = last_accounts_ts_adv if advanced else last_accounts_ts_spot

    if cache and (time.time() - ts_cache < CACHE_TTL):
        return cache

    for attempt in range(RETRY_COUNT):
        try:
            token = generate_jwt(coinbase_path, "GET")
            url = "https://api.coinbase.com" + coinbase_path
            resp = requests.get(url, headers={
                "Authorization": f"Bearer {token}",
                "CB-VERSION": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
                "Content-Type": "application/json"
            }, timeout=10)
            if resp.status_code == 200:
                accounts = resp.json()
                if advanced:
                    last_accounts_adv = accounts
                    last_accounts_ts_adv = time.time()
                else:
                    last_accounts_spot = accounts
                    last_accounts_ts_spot = time.time()
                logging.info(f"Fetched {'Advanced' if advanced else 'Spot'} accounts: {accounts}")
                return accounts
            else:
                logging.warning(f"[Attempt {attempt+1}] Failed to fetch {'Advanced' if advanced else 'Spot'} accounts: {resp.status_code} {resp.text}")
        except Exception as e:
            logging.error(f"[Attempt {attempt+1}] Exception fetching {'Advanced' if advanced else 'Spot'} accounts: {e}")
        time.sleep(RETRY_DELAY)

    raise RuntimeError(f"Failed to fetch {'Advanced' if advanced else 'Spot'} Coinbase accounts after retries.")

# --- Helper: send trade ---
def send_trade(symbol: str, side: str, size: float, advanced: bool = False):
    if not SEND_LIVE_TRADES:
        logging.info(f"⚠️ Test trade not sent: {side} {size} {symbol} (advanced={advanced})")
        return

    path = "/api/v3/brokerage/orders"
    token = generate_jwt(path, "POST")
    url = "https://api.coinbase.com" + path

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
                logging.info(f"✅ Trade executed: {side} {size} {symbol} (advanced={advanced})")
                logging.info(resp.json())
                return resp.json()
            else:
                logging.warning(f"[Attempt {attempt+1}] Trade failed: {resp.status_code} {resp.text}")
        except Exception as e:
            logging.error(f"[Attempt {attempt+1}] Exception sending trade: {e}")
        time.sleep(RETRY_DELAY)

    logging.error(f"❌ Failed to send trade after {RETRY_COUNT} attempts: {side} {size} {symbol}")
    return None

# --- Helper: test Coinbase connection ---
def test_coinbase_connection():
    success_spot = success_adv = False
    try:
        fetch_accounts(advanced=False)
        logging.info("✅ Coinbase Spot connection verified.")
        success_spot = True
    except Exception as e:
        logging.error(f"❌ Coinbase Spot connection failed: {e}")

    try:
        fetch_accounts(advanced=True)
        logging.info("✅ Coinbase Advanced connection verified.")
        success_adv = True
    except Exception as e:
        logging.error(f"❌ Coinbase Advanced connection failed: {e}")

    return success_spot and success_adv

# --- Routes ---
@app.route("/debug_jwt")
def debug_jwt_route():
    try:
        accounts_spot = fetch_accounts(advanced=False)
        accounts_adv = fetch_accounts(advanced=True)
        return jsonify({"status": "ok", "accounts_spot": accounts_spot, "accounts_advanced": accounts_adv})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/test_trade")
def test_trade_route():
    send_trade("BTC-USD", "buy", 0.001, advanced=False)
    send_trade("BTC-USD", "buy", 0.001, advanced=True)
    return "Check logs for trade output."

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.json
        symbol = data.get("symbol")
        side = data.get("side")
        size = float(data.get("size", 0))
        advanced = data.get("advanced", False)

        if not symbol or not side or size <= 0:
            return jsonify({"status": "error", "message": "Invalid payload"}), 400

        send_trade(symbol, side, size, advanced)
        return jsonify({"status": "ok"})
    except Exception as e:
        logging.error(f"❌ Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# --- Main ---
if __name__ == "__main__":
    logging.info("🔥 Nija Trading Bot starting...")

    # Test Coinbase connection at startup
    test_coinbase_connection()

    # Start Flask
    app.run(host="0.0.0.0", port=5000)
