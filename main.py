#!/usr/bin/env python3
# main.py -- Nija Trading Bot + DEBUG JWT snippet
import os
import time
import requests
import jwt
import datetime
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from loguru import logger
from flask import Flask, jsonify, request
from threading import Thread

logger.remove()
logger.add(lambda msg: print(msg, end=''))  # container-friendly stdout

# ----------------------------
# CONFIG / SAFETY SWITCHES
# ----------------------------
SEND_TEST_TRADE = False   # set True only when you want the script to POST a test trade on startup
DEBUG_JWT_TEST = True     # keep True to run the debug JWT -> /accounts call at startup

LOCAL_HOST = "127.0.0.1"
LOCAL_PORT = 5000
LOCAL_BOT_URL = f"http://{LOCAL_HOST}:{LOCAL_PORT}"
WEBHOOK_ENDPOINT = f"{LOCAL_BOT_URL}/webhook"
ACCOUNTS_ENDPOINT = f"{LOCAL_BOT_URL}/accounts"

# Example test trade payload (not sent unless SEND_TEST_TRADE True)
TEST_ORDER = True
TRADE_PAYLOAD = {
    "symbol": "BTC-USD",
    "side": "buy",
    "size": 0.001,
    "type": "market",
    "test": TEST_ORDER
}

# ----------------------------
# Env vars
# ----------------------------
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")            # uuid only
COINBASE_API_SUB = os.getenv("COINBASE_API_SUB")                 # full path
COINBASE_API_KID = os.getenv("COINBASE_API_KID") or COINBASE_API_SUB
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
COINBASE_PEM_PATH = os.getenv("COINBASE_PEM_PATH")

# Quick env debug
logger.info("🔹 Verifying Coinbase env variables...\n")
logger.info("COINBASE_ORG_ID: %s\n" % (COINBASE_ORG_ID))
logger.info("COINBASE_API_KEY_ID (short UUID): %s\n" % (COINBASE_API_KEY_ID))
logger.info("COINBASE_API_SUB (full path): %s\n" % (COINBASE_API_SUB))
logger.info("COINBASE_PEM_CONTENT length: %s\n" % (len(COINBASE_PEM_CONTENT or "")))

# Basic required check
if not COINBASE_ORG_ID or not COINBASE_API_KEY_ID or not COINBASE_API_SUB:
    logger.error("Missing required Coinbase env vars. Set COINBASE_ORG_ID, COINBASE_API_KEY_ID, COINBASE_API_SUB\n")
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
    logger.success("✅ PEM loaded successfully\n")
except Exception as e:
    logger.error(f"❌ Failed to load PEM: {e}\n")
    raise SystemExit(1)

# ----------------------------
# JWT helpers
# ----------------------------
def make_jwt(sub: str, kid: str, request_path: str = "/", method: str = "GET", expiry_sec: int = 120):
    iat = int(time.time())
    payload = {
        "iat": iat,
        "exp": iat + expiry_sec,
        "sub": sub,
        "request_path": request_path,
        "method": method,
        "jti": f"dbg-{iat}"
    }
    headers_jwt = {"alg": "ES256", "kid": kid}
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers_jwt)
    return token

# ----------------------------
# Local bot HTTP helpers
# ----------------------------
def call_bot(endpoint, method="GET", data=None, retries=3):
    for attempt in range(1, retries + 1):
        try:
            if method.upper() == "GET":
                resp = requests.get(endpoint, timeout=10)
            else:
                resp = requests.post(endpoint, json=data, timeout=10)
            status = resp.status_code
            logger.info(f"[Attempt {attempt}] {method} {endpoint} -> HTTP {status}\n")
            if status in (200, 201):
                try:
                    return resp.json()
                except Exception:
                    return resp.text
            else:
                logger.warning(f"⚠️ {method} failed: {status} | {resp.text}\n")
                time.sleep(1)
        except Exception as e:
            logger.error(f"Request exception: {e}\n")
            time.sleep(1)
    logger.error(f"All retries failed for {endpoint}\n")
    return None

def send_test_webhook(payload):
    logger.info("🔹 Sending test trade webhook to local /webhook...\n")
    return call_bot(WEBHOOK_ENDPOINT, method="POST", data=payload)

def fetch_local_accounts():
    logger.info("🔹 Fetching accounts from local /accounts...\n")
    return call_bot(ACCOUNTS_ENDPOINT, method="GET")

# ----------------------------
# Flask app (webhook + accounts)
# ----------------------------
app = Flask(__name__)

@app.route("/accounts", methods=["GET"])
def get_accounts():
    # Replace with real Coinbase fetching logic once JWT succeeds
    demo = [
        {"id": "1", "currency": "USD", "balance": {"amount": "150.00"}},
        {"id": "2", "currency": "BTC", "balance": {"amount": "0.002"}}
    ]
    return jsonify({"data": demo})

@app.route("/webhook", methods=["POST"])
def webhook():
    payload = request.json
    logger.info(f"📩 Webhook received: {payload}\n")
    # Placeholder: real trading logic would go here (use Coinbase calls when JWT works)
    return jsonify({"status": "success", "received": payload})

# ----------------------------
# DEBUG: generate a JWT with full-path sub/kid, print it, and call Coinbase /accounts
# ----------------------------
def debug_coinbase_jwt_test():
    if not DEBUG_JWT_TEST:
        logger.info("DEBUG_JWT_TEST disabled; skipping JWT test.\n")
        return

    logger.info("=== DEBUG: generating JWT and calling Coinbase /accounts ===\n")
    full_sub = COINBASE_API_SUB            # organizations/<org>/apiKeys/<id>
    full_kid = COINBASE_API_KID or COINBASE_API_SUB
    coinbase_path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"

    # Make token (explicit)
    iat = int(time.time())
    payload = {
        "iat": iat,
        "exp": iat + 120,
        "sub": full_sub,
        "request_path": coinbase_path,
        "method": "GET",
        "jti": f"dbg-{iat}"
    }
    headers_jwt = {"alg": "ES256", "kid": full_kid}
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers_jwt)

    logger.info("DEBUG JWT (preview): %s\n" % token[:200])

    # Test call
    url = "https://api.coinbase.com" + coinbase_path
    try:
        resp = requests.get(url, headers={
            "Authorization": f"Bearer {token}",
            "CB-VERSION": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
            "Content-Type": "application/json"
        }, timeout=10)
        logger.info("DEBUG /accounts status: %s\n" % resp.status_code)
        logger.info("DEBUG /accounts body: %s\n" % resp.text)
    except Exception as e:
        logger.error("DEBUG /accounts request exception: %s\n" % str(e))

    logger.info("=== DEBUG complete ===\n")

# ----------------------------
# Main orchestrator
# ----------------------------
def main_logic():
    # Optionally send a test webhook to the running local Flask app
    if SEND_TEST_TRADE:
        resp = send_test_webhook(TRADE_PAYLOAD)
        logger.info("Test webhook response: %s\n" % resp)
    else:
        logger.info("SEND_TEST_TRADE is False — not sending test trade on startup.\n")

    # Give the webhook a moment
    time.sleep(1)

    # Try fetching local accounts
    local_accounts = fetch_local_accounts()
    logger.info("Local /accounts returned: %s\n" % (local_accounts or "None"))

    # Run debug JWT test against Coinbase
    debug_coinbase_jwt_test()

# ----------------------------
# Start Flask + run main logic
# ----------------------------
def start():
    # Launch Flask in a background thread, then run main logic in main thread
    server_thread = Thread(target=lambda: app.run(host="0.0.0.0", port=LOCAL_PORT, debug=False, use_reloader=False))
    server_thread.daemon = True
    server_thread.start()

    # Wait briefly for server to bind
    time.sleep(0.8)
    try:
        main_logic()
    except Exception as e:
        logger.error(f"Main logic exception: {e}\n")

if __name__ == "__main__":
    start()
