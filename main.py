# ✅ main.py - Nija Trading Bot with TradingView Webhook Listener
import os
import time
import jwt
import datetime
import requests
from flask import Flask, request, jsonify
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from loguru import logger

logger.remove()
logger.add(lambda msg: print(msg, end=''))

# ----------------------------
# Environment variables
# ----------------------------
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")        
COINBASE_API_SUB = os.getenv("COINBASE_API_SUB")              
COINBASE_API_KID = os.getenv("COINBASE_API_KID") or COINBASE_API_KEY_ID
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
COINBASE_PEM_PATH = os.getenv("COINBASE_PEM_PATH")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "supersecret")  # TradingView sends this in the alert

# Trading parameters
MIN_ALLOCATION = 0.02  # 2% of balance
MAX_ALLOCATION = 0.10  # 10% of balance

if not COINBASE_ORG_ID or not COINBASE_API_KEY_ID:
    logger.error("❌ Missing required Coinbase env vars.")
    raise SystemExit(1)

# ----------------------------
# Load PEM
# ----------------------------
if COINBASE_PEM_CONTENT:
    pem_text = COINBASE_PEM_CONTENT.replace("\\n", "\n").replace("\r", "").strip().strip('"').strip("'")
elif COINBASE_PEM_PATH:
    if not os.path.exists(COINBASE_PEM_PATH):
        logger.error(f"❌ PEM path not found: {COINBASE_PEM_PATH}")
        raise SystemExit(1)
    with open(COINBASE_PEM_PATH, "r", encoding="utf-8") as f:
        pem_text = f.read().replace("\r", "").strip()
else:
    logger.error("❌ No PEM provided.")
    raise SystemExit(1)

private_key = serialization.load_pem_private_key(
    pem_text.encode(), password=None, backend=default_backend()
)
logger.success("✅ PEM loaded successfully")

# ----------------------------
# JWT Generation
# ----------------------------
def generate_jwt(sub, kid, request_path, method="GET", expiry_sec=120):
    iat = int(time.time())
    payload = {
        "iat": iat,
        "exp": iat + expiry_sec,
        "sub": sub,
        "request_path": request_path,
        "method": method
    }
    headers_jwt = {"alg": "ES256", "kid": kid}
    return jwt.encode(payload, private_key, algorithm="ES256", headers=headers_jwt)

# ----------------------------
# Coinbase API call
# ----------------------------
def call_coinbase(path, token, method="GET", data=None, retries=3):
    url = f"https://api.coinbase.com{path}"
    for attempt in range(1, retries+1):
        headers = {
            "Authorization": f"Bearer {token}",
            "CB-VERSION": "2025-11-16",
            "Content-Type": "application/json"
        }
        try:
            r = requests.get(url, headers=headers, timeout=10) if method.upper() == "GET" else requests.post(url, headers=headers, json=data, timeout=10)
        except Exception as e:
            logger.error(f"Attempt {attempt}: Request exception: {e}")
            time.sleep(1)
            continue

        if r.status_code in (200, 201):
            return r.json()
        if r.status_code == 401:
            logger.warning(f"Attempt {attempt}: 401 Unauthorized. JWT rejected.")
            time.sleep(1)
            continue
        logger.error(f"Attempt {attempt}: Failed {r.status_code} -> {r.text}")
        time.sleep(1)
    return None

# ----------------------------
# Fetch funded accounts
# ----------------------------
def fetch_funded_accounts():
    token = generate_jwt(COINBASE_API_SUB, COINBASE_API_KID, f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts")
    resp = call_coinbase(f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts", token)
    if not resp:
        logger.error("❌ Failed to fetch accounts")
        return None
    funded = [a for a in resp.get("data", []) if float(a.get("balance", {}).get("amount", 0)) > 0]
    return funded

# ----------------------------
# Calculate allocation
# ----------------------------
def calculate_allocation(balance):
    amt = balance * MAX_ALLOCATION
    if amt < balance * MIN_ALLOCATION:
        amt = balance * MIN_ALLOCATION
    return round(amt, 2)

# ----------------------------
# Place order
# ----------------------------
def place_order(account_id, symbol, side, usd_amount):
    path = f"/api/v3/brokerage/accounts/{account_id}/orders"
    data = {
        "symbol": symbol,
        "side": side,
        "type": "market",
        "funds": str(usd_amount)
    }
    token = generate_jwt(COINBASE_API_SUB, COINBASE_API_KID, path, method="POST")
    resp = call_coinbase(path, token, method="POST", data=data)
    if resp:
        logger.success(f"✅ {side.upper()} order executed for {symbol}: {usd_amount} USD")
        return resp
    logger.error(f"❌ Failed to execute {side} order for {symbol}")
    return None

# ----------------------------
# Flask Webhook Listener
# ----------------------------
app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    if not data:
        return jsonify({"error": "No JSON payload"}), 400

    # Verify secret
    if data.get("secret") != WEBHOOK_SECRET:
        return jsonify({"error": "Unauthorized"}), 401

    symbol = data.get("symbol")
    side = data.get("side")  # "buy" or "sell"
    if not symbol or not side:
        return jsonify({"error": "Missing symbol or side"}), 400

    accounts = fetch_funded_accounts()
    if not accounts:
        return jsonify({"error": "No funded accounts"}), 400

    account = accounts[0]
    balance = float(account.get("balance", {}).get("amount", 0))
    allocation = calculate_allocation(balance)
    logger.info(f"Trading signal received: {side.upper()} {symbol} | Allocation: {allocation} USD")

    order_resp = place_order(account["id"], symbol, side, allocation)
    return jsonify({"status": "success", "order": order_resp})

# ----------------------------
# Run Flask app
# ----------------------------
if __name__ == "__main__":
    logger.info("Starting Nija Trading Bot Webhook listener on port 5000...")
    app.run(host="0.0.0.0", port=5000)
