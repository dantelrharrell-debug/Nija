# ==============================
# Nija Trading Bot – Live Script
# ==============================
import os
import time
import requests
import jwt
import datetime
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from loguru import logger
from flask import Flask, jsonify, request

# ---------------------------
# Flask app
# ---------------------------
app = Flask(__name__)
logger.add(lambda msg: print(msg, end=''))  # Container-friendly stdout

# ----------------------------
# CONFIG
# ----------------------------
RAILWAY_APP_URL = "https://f8276a50-c18a-44e9-8c33-fe3de57ebd57.up.railway.app"  # Your live Railway URL
WEBHOOK_ENDPOINT = f"{RAILWAY_APP_URL}/webhook"
ACCOUNTS_ENDPOINT = f"{RAILWAY_APP_URL}/accounts"

# Optional: Test trade
TEST_ORDER = True
TRADE_PAYLOAD = {
    "symbol": "BTC-USD",
    "side": "buy",
    "size": 0.001,
    "type": "market",
    "test": TEST_ORDER
}

# ----------------------------
# Coinbase Env Vars
# ----------------------------
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")
COINBASE_API_SUB = os.getenv("COINBASE_API_SUB")
COINBASE_API_KID = os.getenv("COINBASE_API_KID") or COINBASE_API_SUB
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
COINBASE_PEM_PATH = os.getenv("COINBASE_PEM_PATH")

if not COINBASE_ORG_ID or not COINBASE_API_KEY_ID or not COINBASE_API_SUB:
    logger.error("Missing required Coinbase environment variables!")
    raise SystemExit(1)

# ----------------------------
# Load PEM
# ----------------------------
if COINBASE_PEM_CONTENT:
    pem_text = COINBASE_PEM_CONTENT.replace("\\n", "\n").replace("\r", "").strip().strip('"').strip("'")
elif COINBASE_PEM_PATH:
    if not os.path.exists(COINBASE_PEM_PATH):
        logger.error(f"PEM path not found: {COINBASE_PEM_PATH}")
        raise SystemExit(1)
    with open(COINBASE_PEM_PATH, "r", encoding="utf-8") as f:
        pem_text = f.read().replace("\r", "").strip()
else:
    logger.error("No PEM provided. Set COINBASE_PEM_CONTENT or COINBASE_PEM_PATH.")
    raise SystemExit(1)

try:
    private_key = serialization.load_pem_private_key(
        pem_text.encode(), password=None, backend=default_backend()
    )
    logger.success("✅ PEM loaded successfully")
except Exception as e:
    logger.error(f"❌ Failed to load PEM: {e}")
    raise SystemExit(1)

# ----------------------------
# JWT Generator
# ----------------------------
def generate_jwt(request_path, method="GET", sub=COINBASE_API_SUB, kid=COINBASE_API_KID):
    iat = int(time.time())
    payload = {
        "iat": iat,
        "exp": iat + 120,
        "sub": sub,
        "request_path": request_path,
        "method": method
    }
    headers_jwt = {"alg": "ES256", "kid": kid}
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers_jwt)
    return token

# ----------------------------
# Safe GET/POST to bot
# ----------------------------
def call_bot(endpoint, method="GET", data=None, retries=3):
    for attempt in range(1, retries + 1):
        try:
            if method.upper() == "GET":
                resp = requests.get(endpoint, timeout=10)
            else:
                resp = requests.post(endpoint, json=data, timeout=10)
            status = resp.status_code
            logger.info(f"[Attempt {attempt}] {method} {endpoint} -> HTTP {status}")
            if status in (200, 201):
                return resp.json()
            else:
                logger.warning(f"⚠️ {method} failed: {status} | {resp.text}")
                time.sleep(1)
        except Exception as e:
            logger.error(f"Request exception: {e}")
            time.sleep(1)
    logger.error(f"All retries failed for {endpoint}")
    return None

# ----------------------------
# Send Trade Webhook
# ----------------------------
def send_trade(payload):
    logger.info("🔹 Sending trade webhook...")
    response = call_bot(WEBHOOK_ENDPOINT, method="POST", data=payload)
    if response:
        logger.success("✅ Webhook sent successfully!")
        logger.info(f"Bot response: {response}")
    else:
        logger.error("❌ Webhook failed")
    return response

# ----------------------------
# Fetch Account Balances
# ----------------------------
def fetch_accounts():
    logger.info("🔹 Fetching Coinbase account balances...")
    response = call_bot(ACCOUNTS_ENDPOINT, method="GET")
    if not response or "data" not in response:
        logger.warning("⚠️ No accounts returned. Check your bot's /accounts endpoint.")
        return []
    accounts = response["data"]
    logger.success(f"✅ Fetched {len(accounts)} accounts")
    for acc in accounts[:10]:
        balance = acc.get("balance", {})
        logger.info(f"- {acc['id']} | {acc.get('currency')} | {balance.get('amount')}")
    return accounts

# ----------------------------
# Flask /accounts route
# ----------------------------
@app.route("/accounts", methods=["GET"])
def get_accounts():
    # Replace with real bot logic: fetch balances from Coinbase API
    accounts_data = [
        {"id": "1", "currency": "USD", "balance": {"amount": "150.00"}},
        {"id": "2", "currency": "BTC", "balance": {"amount": "0.002"}}
    ]
    return jsonify({"data": accounts_data})

# ----------------------------
# Main
# ----------------------------
def main():
    # Send test trade
    send_trade(TRADE_PAYLOAD)

    # Wait a few seconds
    logger.info("\n⏳ Waiting 3 seconds for bot to process trade...")
    time.sleep(3)

    # Fetch account balances
    fetch_accounts()

if __name__ == "__main__":
    # Run bot logic in background if needed
    main()

    # Start Flask server
    app.run(host="0.0.0.0", port=5000)
