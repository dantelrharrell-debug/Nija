# app/main.py
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
COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")

# ✅ Correct Advanced API sub with leading slash
COINBASE_API_SUB = f"/organizations/{COINBASE_ORG_ID}/apiKeys/{COINBASE_API_KEY_ID}"

# --- Encode PEM properly ---
private_key = COINBASE_PEM_CONTENT.replace("\\n", "\n").encode("utf-8")

# --- Flask app ---
app = Flask(__name__)

# --- Cache ---
last_accounts = None
last_accounts_ts = 0

# --- Helper: generate JWT ---
def generate_jwt(request_path: str, method: str = "GET") -> str:
    iat = int(time.time())
    payload = {
        "iat": iat,
        "exp": iat + 120,
        "sub": COINBASE_API_SUB,
        "request_path": request_path,
        "method": method.upper(),
        "jti": f"nija-{iat}"
    }
    headers = {"alg": "ES256", "kid": COINBASE_API_KEY_ID}

    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
    logging.debug(f"DEBUG_JWT preview: {token[:50]}...")  # safe preview
    return token

# --- Helper: fetch accounts ---
def fetch_accounts():
    global last_accounts, last_accounts_ts
    request_path = "/api/v3/brokerage/accounts"
    url = "https://api.coinbase.com" + request_path

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
                logging.info(f"Fetched Coinbase accounts: {last_accounts}")
                return last_accounts
            else:
                logging.warning(f"[Attempt {attempt+1}] Failed to fetch accounts: {resp.status_code} {resp.text}")
        except Exception as e:
            logging.error(f"[Attempt {attempt+1}] Exception fetching accounts: {e}")
        time.sleep(RETRY_DELAY)

    raise RuntimeError("Failed to fetch Coinbase accounts after retries.")

# --- Helper: send trade ---
def send_trade(symbol: str, side: str, size: float):
    if not SEND_LIVE_TRADES:
        logging.info(f"⚠️ Test trade not sent: {side} {size} {symbol}")
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

# --- Helper: test Coinbase connection ---
def test_coinbase_connection():
    try:
        fetch_accounts()
        logging.info("✅ Coinbase connection verified!")
        return True
    except Exception as e:
        logging.error(f"❌ Coinbase connection failed: {e}")
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
        logging.error(f"❌ Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# --- Main ---
if __name__ == "__main__":
    logging.info("🔥 Nija Trading Bot starting...")

    if test_coinbase_connection():
        logging.info("🎯 Ready to trade!")
    else:
        logging.error("❌ Check API keys or permissions before trading.")

    app.run(host="0.0.0.0", port=5000)
