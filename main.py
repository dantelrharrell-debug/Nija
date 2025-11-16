# main.py
# Nija Trading Bot — Flask + Coinbase Advanced API (live /accounts endpoint)
import os
import time
import requests
import jwt
import datetime
from threading import Thread
from flask import Flask, jsonify, request
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from loguru import logger

logger.add(lambda msg: print(msg, end=''))  # container-friendly stdout

# ----------------------------
# CONFIG
# ----------------------------
LOCAL_BOT_URL = "http://127.0.0.1:5000"  # used for internal calls in test mode
WEBHOOK_ENDPOINT = f"{LOCAL_BOT_URL}/webhook"
ACCOUNTS_ENDPOINT = f"{LOCAL_BOT_URL}/accounts"

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
COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")       # short UUID
COINBASE_API_SUB = os.getenv("COINBASE_API_SUB")            # full path
COINBASE_API_KID = os.getenv("COINBASE_API_KID") or COINBASE_API_SUB
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
COINBASE_PEM_PATH = os.getenv("COINBASE_PEM_PATH")

if not COINBASE_ORG_ID or not (COINBASE_API_KEY_ID or COINBASE_API_SUB):
    logger.error("Missing required Coinbase env vars: COINBASE_ORG_ID and COINBASE_API_KEY_ID or COINBASE_API_SUB")
    raise SystemExit(1)

# ----------------------------
# Load PEM (support literal \n)
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
# Helper: make a signed JWT (using provided sub and kid)
# ----------------------------
def make_jwt_for(sub: str, kid: str, request_path: str, method: str = "GET", expire_seconds: int = 120):
    iat = int(time.time())
    payload = {
        "iat": iat,
        "exp": iat + expire_seconds,
        "sub": sub,
        "request_path": request_path,
        "method": method
    }
    headers_jwt = {"alg": "ES256", "kid": kid}
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers_jwt)
    return token

# ----------------------------
# Call Coinbase with auto-sub fallback
# - tries short API key id as sub first, then full path sub
# - returns requests.Response or None
# ----------------------------
def call_coinbase_with_auto_sub(path: str, method: str = "GET", json_data=None, retries: int = 3):
    base_url = "https://api.coinbase.com"
    url = base_url + path

    # order to try: short id (if provided), then full path
    subs_to_try = []
    if COINBASE_API_KEY_ID:
        subs_to_try.append(COINBASE_API_KEY_ID)
    if COINBASE_API_SUB:
        subs_to_try.append(COINBASE_API_SUB)

    last_resp = None
    for sub_candidate in subs_to_try:
        for attempt in range(1, retries + 1):
            try:
                token = make_jwt_for(sub_candidate, COINBASE_API_KID or sub_candidate, request_path=path, method=method)
                headers = {
                    "Authorization": f"Bearer {token}",
                    "CB-VERSION": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
                    "Content-Type": "application/json"
                }
                logger.info(f"[Coinbase] Trying sub='{sub_candidate}' attempt {attempt} -> {method} {path}")
                if method.upper() == "GET":
                    resp = requests.get(url, headers=headers, timeout=10)
                else:
                    resp = requests.post(url, headers=headers, json=json_data, timeout=10)

                logger.info(f"[Coinbase] HTTP {resp.status_code}")
                # if success, return resp
                if resp.status_code in (200, 201):
                    return resp
                # 401 indicates JWT/sub/kid issue — try regenerating token (retry loop) then next sub
                if resp.status_code == 401:
                    logger.warning(f"⚠️ 401 for sub '{sub_candidate}', resp: {resp.text}")
                    last_resp = resp
                    time.sleep(1)
                    continue
                # other failures: return response (caller can log)
                last_resp = resp
                break
            except requests.exceptions.RequestException as e:
                logger.error(f"Request exception: {e}")
                last_resp = None
                time.sleep(1)
                continue
        # if we reached here and got a 200 we already returned; otherwise try next sub_candidate
    # all subs/attempts exhausted
    return last_resp

# ----------------------------
# Fetch funded accounts from Coinbase
# ----------------------------
def fetch_funded_accounts():
    path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
    resp = call_coinbase_with_auto_sub(path, method="GET", retries=3)
    if resp is None:
        logger.error("No response from Coinbase (network or exception).")
        return None
    if resp.status_code == 200:
        try:
            accounts = resp.json()
            # Coinbase returns list or object depending on endpoint; preserve as-is but try to normalize
            # If it's list-like under 'data', return that; otherwise return what we received.
            if isinstance(accounts, dict) and "data" in accounts:
                data = accounts["data"]
            else:
                data = accounts
            # Filter funded accounts (balance.amount > 0) if structure matches expected
            funded = []
            for a in data if isinstance(data, list) else []:
                try:
                    bal_amt = float(a.get("balance", {}).get("amount", 0) or 0)
                except Exception:
                    bal_amt = 0
                if bal_amt > 0:
                    funded.append(a)
            # If filter found items, return funded; else return raw data
            return {"data": funded if funded else data}
        except ValueError:
            logger.error("Failed to parse JSON from Coinbase response")
            return None
    else:
        logger.warning(f"Coinbase returned {resp.status_code}: {resp.text}")
        return None

# ----------------------------
# Internal "call bot" helper (used for local demo/test calls)
# ----------------------------
def call_bot(endpoint, method="GET", data=None, retries=2):
    for attempt in range(1, retries + 1):
        try:
            if method.upper() == "GET":
                resp = requests.get(endpoint, timeout=10)
            else:
                resp = requests.post(endpoint, json=data, timeout=10)
            logger.info(f"[Attempt {attempt}] {method} {endpoint} -> HTTP {resp.status_code}")
            if resp.status_code in (200, 201):
                return resp.json()
            else:
                logger.warning(f"⚠️ {method} failed: {resp.status_code} | {resp.text}")
                time.sleep(1)
        except Exception as e:
            logger.error(f"Request exception: {e}")
            time.sleep(1)
    logger.error(f"All retries failed for {endpoint}")
    return None

# ----------------------------
# Send trade to webhook (internal test)
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
# Fetch accounts wrapper used by /accounts route
# ----------------------------
def fetch_accounts_for_route():
    result = fetch_funded_accounts()
    if not result:
        return {"data": []}
    return result

# =============================
# Flask Web Server (routes)
# =============================
app = Flask(__name__)

@app.route("/accounts", methods=["GET"])
def get_accounts_route():
    """
    Returns Coinbase accounts (funded accounts preferred).
    Response format: { "data": [ ... ] }
    """
    logger.info("HTTP /accounts requested")
    accounts = fetch_accounts_for_route()
    return jsonify(accounts), 200

@app.route("/webhook", methods=["POST"])
def webhook_route():
    data = request.json
    logger.info(f"📩 Webhook received: {data}")
    # Here you could validate the webhook payload, signature, or call process_trading_signal
    # For safety this demo only acknowledges receipt.
    return jsonify({"status": "success", "received": data}), 200

# ----------------------------
# Demo: fetch /accounts (used by main)
# ----------------------------
def fetch_accounts_and_log():
    logger.info("🔹 Fetching Coinbase account balances (demo)...")
    result = fetch_funded_accounts()
    if not result:
        logger.warning("⚠️ No accounts returned.")
        return
    logger.success(f"✅ Fetched accounts: {len(result.get('data', [])) if isinstance(result.get('data'), list) else 'unknown'}")
    logger.info(result)

# ----------------------------
# Main startup
# ----------------------------
def main():
    # internal demo: send test trade to local webhook (only if webhook listener is reachable)
    try:
        send_trade(TRADE_PAYLOAD)
    except Exception as e:
        logger.error(f"Error sending internal trade: {e}")

    # wait and fetch accounts
    time.sleep(2)
    fetch_accounts_and_log()

if __name__ == "__main__":
    # run Flask in a background thread, then execute main logic
    Thread(target=lambda: app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)).start()
    main()
