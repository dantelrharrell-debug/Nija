# main.py (simplified)
import os, time, requests, jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# --- Coinbase JWT setup ---
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
COINBASE_PEM_PATH = os.getenv("COINBASE_PEM_PATH")
COINBASE_API_SUB = os.getenv("COINBASE_API_SUB")
COINBASE_API_KID = os.getenv("COINBASE_API_KID")

# Load PEM
if COINBASE_PEM_CONTENT:
    pem_text = COINBASE_PEM_CONTENT.replace("\\n", "\n").strip().strip('"').strip("'")
elif COINBASE_PEM_PATH:
    with open(COINBASE_PEM_PATH, "r", encoding="utf-8") as f:
        pem_text = f.read()
else:
    raise SystemExit("No PEM provided. Set COINBASE_PEM_CONTENT or COINBASE_PEM_PATH in env.")

private_key = serialization.load_pem_private_key(
    pem_text.encode(), password=None, backend=default_backend()
)

# Build JWT
sub = COINBASE_API_SUB
kid = COINBASE_API_KID or sub
path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
iat = int(time.time())
payload = {"iat": iat, "exp": iat + 120, "sub": sub, "request_path": path, "method": "GET"}
headers = {"alg": "ES256", "kid": kid}
token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)

# Test request (optional)
url = f"https://api.coinbase.com{path}"
resp = requests.get(url, headers={"Authorization": f"Bearer {token}", "CB-VERSION": "2025-11-12"})
print("HTTP Status:", resp.status_code)
print(resp.text)

# --- Then continue with your NijaBot startup ---
from nija_client import CoinbaseClient
bot = CoinbaseClient(token=token, org_id=COINBASE_ORG_ID)
bot.start_trading()

# main.py
import os, time, requests, jwt, json
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from flask import Flask, request, abort

# -----------------------------
# Flask Webhook Setup
# -----------------------------
app = Flask(__name__)
TV_WEBHOOK_SECRET = os.getenv("TV_WEBHOOK_SECRET")
TV_WEBHOOK_URL = os.getenv("TV_WEBHOOK_URL")

# -----------------------------
# Coinbase Environment
# -----------------------------
COINBASE_API_KEY_FULL = os.getenv("COINBASE_API_KEY_FULL")
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_PEM_PATH = os.getenv("COINBASE_PEM_PATH")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
LIVE_TRADING = os.getenv("LIVE_TRADING", "0") == "1"
MAX_TRADE_PERCENT = float(os.getenv("MAX_TRADE_PERCENT", 10))
MIN_TRADE_PERCENT = float(os.getenv("MIN_TRADE_PERCENT", 2))

logger.info("Starting Nija Trading Bot...")

# -----------------------------
# Load PEM
# -----------------------------
pem_text = None
if COINBASE_PEM_CONTENT:
    pem_text = COINBASE_PEM_CONTENT.replace("\\n", "\n").strip().strip('"').strip("'")
elif COINBASE_PEM_PATH:
    if not os.path.exists(COINBASE_PEM_PATH):
        raise SystemExit(f"PEM path not found: {COINBASE_PEM_PATH}")
    with open(COINBASE_PEM_PATH, "r", encoding="utf-8") as f:
        pem_text = f.read()
else:
    raise SystemExit("No PEM provided. Set COINBASE_PEM_CONTENT or COINBASE_PEM_PATH in env.")

try:
    private_key = serialization.load_pem_private_key(pem_text.encode(), password=None, backend=default_backend())
    logger.success("✅ PEM loaded successfully")
except Exception as e:
    raise SystemExit(f"❌ Failed to load PEM: {e}")

# -----------------------------
# Normalize API Key / kid
# -----------------------------
if COINBASE_API_KEY_FULL:
    kid = COINBASE_API_KEY_FULL
    api_key_id = COINBASE_API_KEY_FULL.split("/")[-1]
elif COINBASE_API_KEY:
    api_key_id = COINBASE_API_KEY
    kid = api_key_id
else:
    raise SystemExit("No API key provided. Set COINBASE_API_KEY_FULL or COINBASE_API_KEY in env.")

logger.info(f"Using API_KEY_ID (sub): {api_key_id}")
logger.info(f"Using kid header value: {kid}")

# -----------------------------
# Build JWT
# -----------------------------
def build_jwt(path: str) -> str:
    iat = int(time.time())
    payload = {
        "iat": iat,
        "exp": iat + 120,
        "sub": api_key_id,
        "request_path": path,
        "method": "GET"
    }
    token = jwt.encode(payload, private_key, algorithm="ES256", headers={"alg": "ES256", "kid": kid})
    return token

# -----------------------------
# Fetch funded accounts
# -----------------------------
def fetch_funded_accounts():
    path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
    token = build_jwt(path)
    url = f"https://api.coinbase.com{path}"
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}", "CB-VERSION": "2025-11-12"})
    if resp.status_code != 200:
        logger.error(f"⚠️ Failed to fetch accounts. Status: {resp.status_code} | Response: {resp.text}")
        raise SystemExit("Cannot fetch Coinbase accounts. Check API key, PEM, and permissions.")
    accounts = resp.json().get("data", [])
    funded = [a for a in accounts if float(a.get("balance", {}).get("amount", 0)) > 0]
    if not funded:
        logger.warning("No funded accounts found. Bot will not trade.")
    else:
        logger.success(f"✅ Found {len(funded)} funded account(s). Ready to trade!")
    return funded

funded_accounts = fetch_funded_accounts()

# -----------------------------
# Trading logic
# -----------------------------
def execute_trade(account, signal):
    # Example: trade size calculation
    balance = float(account.get("balance", {}).get("amount", 0))
    trade_amount = balance * (MAX_TRADE_PERCENT / 100)
    trade_amount = max(trade_amount, balance * (MIN_TRADE_PERCENT / 100))
    logger.info(f"Executing trade on account {account['id']}: {signal} | Amount: {trade_amount}")
    # Here you would call Coinbase API to create the order (buy/sell)
    # Placeholder:
    logger.info("⚡ Trade executed (simulated)")

# -----------------------------
# TradingView webhook endpoint
# -----------------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    if not request.headers.get("Authorization") == TV_WEBHOOK_SECRET:
        logger.warning("Unauthorized webhook attempt")
        abort(401)
    data = request.json
    logger.info(f"Received TradingView signal: {json.dumps(data)}")
    if LIVE_TRADING and funded_accounts:
        for account in funded_accounts:
            execute_trade(account, data.get("signal"))
    return {"status": "ok"}, 200

# -----------------------------
# Run Flask
# -----------------------------
if __name__ == "__main__":
    logger.info("🌟 Nija bot is live and waiting for TradingView signals...")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
