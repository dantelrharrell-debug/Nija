# ✅ main.py - Nija Trading Bot (Live Trading Ready)
import os
import time
import jwt
import datetime
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from loguru import logger

logger.remove()
logger.add(lambda msg: print(msg, end=''))

# ----------------------------
# Load Coinbase environment variables
# ----------------------------
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")        # short UUID
COINBASE_API_SUB = os.getenv("COINBASE_API_SUB")              # full path
COINBASE_API_KID = os.getenv("COINBASE_API_KID") or COINBASE_API_KEY_ID
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
COINBASE_PEM_PATH = os.getenv("COINBASE_PEM_PATH")

# Trading parameters
MIN_ALLOCATION = 0.02  # 2% of account balance
MAX_ALLOCATION = 0.10  # 10% of account balance

if not COINBASE_ORG_ID or not COINBASE_API_KEY_ID or not (COINBASE_API_SUB or COINBASE_API_KID):
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

try:
    private_key = serialization.load_pem_private_key(
        pem_text.encode(), password=None, backend=default_backend()
    )
    logger.success("✅ PEM loaded successfully")
except Exception as e:
    logger.error(f"❌ Failed to load PEM: {e}")
    raise SystemExit(1)

# ----------------------------
# JWT Generation
# ----------------------------
def generate_jwt(sub, kid, request_path="/api/v3/brokerage/organizations/{org}/accounts", method="GET", expiry_sec=120):
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
# Coinbase API Call (safe, with retries)
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
            if method.upper() == "GET":
                r = requests.get(url, headers=headers, timeout=10)
            else:
                r = requests.post(url, headers=headers, json=data, timeout=10)
        except Exception as e:
            logger.error(f"Attempt {attempt}: Request exception: {e}")
            time.sleep(1)
            continue

        status = r.status_code
        if status in (200, 201):
            return r.json()
        if status == 401:
            logger.warning(f"Attempt {attempt}: 401 Unauthorized. JWT rejected.")
            time.sleep(1)
            continue
        logger.error(f"Attempt {attempt}: Request failed {status} -> {r.text}")
        time.sleep(1)
    return None

# ----------------------------
# Detect working sub/kid
# ----------------------------
subs_to_try = [COINBASE_API_KEY_ID, COINBASE_API_SUB]
working_sub = None

for candidate_sub in subs_to_try:
    token = generate_jwt(candidate_sub, COINBASE_API_KID)
    resp = call_coinbase(f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts", token)
    if resp and "data" in resp:
        working_sub = candidate_sub
        logger.success(f"✅ Working sub detected: {working_sub}")
        break

if not working_sub:
    logger.error("❌ No valid sub found. Check API key, PEM, and permissions.")
    raise SystemExit(1)

sub = working_sub
kid = COINBASE_API_KID

# ----------------------------
# Fetch funded accounts
# ----------------------------
def fetch_funded_accounts():
    token = generate_jwt(sub, kid, f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts")
    resp = call_coinbase(f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts", token)
    if not resp:
        logger.error("❌ Failed to fetch accounts")
        return None
    data = resp.get("data", [])
    funded = [a for a in data if float(a.get("balance", {}).get("amount", 0)) > 0]
    return funded

# ----------------------------
# Place an order
# ----------------------------
def place_order(account_id, symbol, side, usd_amount):
    path = f"/api/v3/brokerage/accounts/{account_id}/orders"
    data = {
        "symbol": symbol,
        "side": side,           # "buy" or "sell"
        "type": "market",
        "funds": str(usd_amount)  # USD amount
    }
    token = generate_jwt(sub, kid, path, method="POST")
    resp = call_coinbase(path, token, method="POST", data=data)
    if resp:
        logger.success(f"✅ {side.upper()} order placed for {symbol}: {usd_amount} USD")
        return resp
    logger.error(f"❌ Failed to place {side} order for {symbol}")
    return None

# ----------------------------
# Calculate position size
# ----------------------------
def calculate_allocation(balance):
    amt = balance * MAX_ALLOCATION
    if amt < balance * MIN_ALLOCATION:
        amt = balance * MIN_ALLOCATION
    return round(amt, 2)

# ----------------------------
# Main loop
# ----------------------------
def main():
    logger.info("Starting Nija Trading Bot (Live Trading Mode)...")
    accounts = fetch_funded_accounts()
    if not accounts:
        logger.error("No funded accounts available. Exiting.")
        return

    # Example: trade BTC-USD in first funded account
    account = accounts[0]
    balance = float(account.get("balance", {}).get("amount", 0))
    allocation = calculate_allocation(balance)
    logger.info(f"Account {account['id']} balance: {balance} USD, allocation: {allocation} USD")

    # Place a BUY order for BTC-USD
    place_order(account["id"], "BTC-USD", "buy", allocation)

    # Optional: place a SELL after 10% price increase or any strategy
    # Here just an example placeholder
    # place_order(account["id"], "BTC-USD", "sell", allocation)

if __name__ == "__main__":
    main()
