# app/main.py
import os
import time
import datetime
import requests
import jwt  # PyJWT
import logging
from flask import Flask, request, jsonify

# --- CONFIG ---
SEND_LIVE_TRADES = False  
RETRY_COUNT = 3  
RETRY_DELAY = 1  
CACHE_TTL = 30  
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

# --- Load Coinbase environment variables ---
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")

# --- Build `sub` exactly as required by docs / examples ---
# From Coinbase Advanced API: `sub` should be like "organizations/{org_id}/apiKeys/{key_id}"
# Verified via SDK docs: coinbase-advanced-py uses this format.  [oai_citation:0‡GitHub](https://github.com/coinbase/coinbase-advanced-py?utm_source=chatgpt.com)
COINBASE_API_SUB = f"/organizations/{COINBASE_ORG_ID}/apiKeys/{COINBASE_API_KEY_ID}"

# --- Private key setup ---  
# Must preserve newlines. Use .replace("\\n", "\n") then encode to bytes.  
private_key = COINBASE_PEM_CONTENT.replace("\\n", "\n").encode("utf-8")

# --- Flask app setup ---
app = Flask(__name__)

# --- Cache for accounts (to reduce repeated loads) ---
last_accounts = None
last_accounts_ts = 0

# --- Helper: Generate JWT for REST calls ---
def generate_jwt(request_path: str, method: str = "GET") -> str:
    iat = int(time.time())
    payload = {
        "iat": iat,
        "exp": iat + 120,  # Token valid for 2 minutes
        "sub": COINBASE_API_SUB,
        "request_path": request_path,
        "method": method.upper(),
        "jti": f"nija-{iat}"
    }
    headers = {"alg": "ES256", "kid": COINBASE_API_KEY_ID}
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
    # Debug preview of JWT (not secret): log first part
    logging.debug(f"DEBUG_JWT: {token[:80]}...")
    return token

# --- Helper: Fetch Coinbase Advanced accounts ---
def fetch_accounts():
    global last_accounts, last_accounts_ts
    request_path = "/api/v3/brokerage/accounts"  # Must match Coinbase docs exactly  [oai_citation:1‡Coinbase Developer Docs](https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/rest-api?utm_source=chatgpt.com)
    url = "https://api.coinbase.com" + request_path

    # Use cache if recent
    if last_accounts and (time.time() - last_accounts_ts < CACHE_TTL):
        return last_accounts

    for attempt in range(1, RETRY_COUNT + 1):
        try:
            token = generate_jwt(request_path, "GET")
            resp = requests.get(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "CB-VERSION": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
                    "Content-Type": "application/json"
                },
                timeout=10
            )
            if resp.status_code == 200:
                last_accounts = resp.json()
                last_accounts_ts = time.time()
                logging.info(f"✅ Fetched accounts: {last_accounts}")
                return last_accounts
            else:
                logging.warning(f"[Attempt {attempt}] Failed to fetch accounts: {resp.status_code} {resp.text}")
        except Exception as e:
            logging.error(f"[Attempt {attempt}] Exception fetching accounts: {e}")
        time.sleep(RETRY_DELAY)

    # If we get here, all retries failed
    raise RuntimeError("Failed to fetch Coinbase accounts after retries")

# --- Helper: Send Trade (market) ---
def send_trade(symbol: str, side: str, size: float):
    if not SEND_LIVE_TRADES:
        logging.info(f"⚠️ Test trade (not live): {side} {size} {symbol}")
        return None

    path = "/api/v3/brokerage/orders"
    token = generate_jwt(path, "POST")
    url = "https://api.coinbase.com" + path

    payload = {
        "symbol": symbol,
        "side": side.lower(),
        "type": "market",
        "quantity": str(size)
    }

    for attempt in range(1, RETRY_COUNT + 1):
        try:
            resp = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "CB-VERSION": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=10
            )
            if resp.status_code in (200, 201):
                logging.info(f"✅ Trade executed: {side} {size} {symbol}")
                logging.info(resp.json())
                return resp.json()
            else:
                logging.warning(f"[Attempt {attempt}] Trade failed: {resp.status_code} {resp.text}")
        except Exception as e:
            logging.error(f"[Attempt {attempt}] Exception sending trade: {e}")
        time.sleep(RETRY_DELAY)

    logging.error("❌ Failed to send trade after retries")
    return None

# --- Helper: Test Coinbase connection on startup ---
def test_coinbase_connection():
    try:
        accounts = fetch_accounts()
        if accounts is not None:
            logging.info("✅ Coinbase connection verified!")
            return True
        else:
            logging.error("❌ Coinbase connection returned None")
            return False
    except Exception as e:
        logging.error(f"❌ Coinbase connection failed: {e}")
        return False

# --- Flask Endpoints ---
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
    return "Trade attempted, check logs."

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.json
        symbol = data.get("symbol")
        side = data.get("side")
        size = float(data.get("size", 0))

        if not symbol or not side or size <= 0:
            return jsonify({"status": "error", "message": "Invalid payload"}), 400

        result = send_trade(symbol, side, size)
        return jsonify({"status": "ok", "result": result})
    except Exception as e:
        logging.error(f"❌ Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# --- Main Execution ---
if __name__ == "__main__":
    logging.info("🔥 Nija Trading Bot starting...")

    if test_coinbase_connection():
        logging.info("🎯 Ready to trade!")
    else:
        logging.error("❌ Coinbase connection not verified — check key, PEM, or permissions.")

    app.run(host="0.0.0.0", port=5000)
