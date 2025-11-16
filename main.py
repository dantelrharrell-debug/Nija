import os
import time
import requests
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from loguru import logger

# ----------------------------
# Container-friendly logging
# ----------------------------
logger.add(lambda msg: print(msg, end=''))

# ----------------------------
# Load environment variables
# ----------------------------
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_SUB = os.getenv("COINBASE_API_SUB")
COINBASE_API_KID = os.getenv("COINBASE_API_KID") or COINBASE_API_SUB
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
COINBASE_PEM_PATH = os.getenv("COINBASE_PEM_PATH")

if not COINBASE_ORG_ID or not COINBASE_API_SUB:
    raise SystemExit("❌ Missing COINBASE_ORG_ID or COINBASE_API_SUB in env")

# ----------------------------
# Load PEM safely
# ----------------------------
if COINBASE_PEM_CONTENT:
    pem_text = COINBASE_PEM_CONTENT.replace("\\n", "\n").replace('\r', '').strip().strip('"').strip("'")
elif COINBASE_PEM_PATH:
    with open(COINBASE_PEM_PATH, "r", encoding="utf-8") as f:
        pem_text = f.read().replace('\r', '').strip()
else:
    raise SystemExit("❌ No PEM provided. Set COINBASE_PEM_CONTENT or COINBASE_PEM_PATH in env.")

try:
    private_key = serialization.load_pem_private_key(
        pem_text.encode(), password=None, backend=default_backend()
    )
    logger.success("✅ PEM loaded successfully")
except Exception as e:
    raise SystemExit(f"❌ Failed to load PEM: {e}")

sub = COINBASE_API_SUB
kid = COINBASE_API_KID
logger.info(f"JWT sub: {sub}")
logger.info(f"JWT kid: {kid}")

# ----------------------------
# JWT generator
# ----------------------------
def generate_jwt(path, method="GET"):
    iat = int(time.time())
    payload = {
        "iat": iat,
        "exp": iat + 120,
        "sub": sub,
        "request_path": path,
        "method": method
    }
    headers_jwt = {"alg": "ES256", "kid": kid}
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers_jwt)
    return token

# ----------------------------
# Safe request with retries
# ----------------------------
def safe_request(path, method="GET", data=None, max_retries=5, retry_delay=2):
    for attempt in range(1, max_retries + 1):
        try:
            token = generate_jwt(path, method)
            url = f"https://api.coinbase.com{path}"
            headers = {
                "Authorization": f"Bearer {token}",
                "CB-VERSION": "2025-11-12",
                "Content-Type": "application/json"
            }

            resp = requests.get(url, headers=headers, timeout=10) if method.upper() == "GET" else requests.post(url, headers=headers, json=data, timeout=10)
            logger.info(f"[Attempt {attempt}] HTTP Status: {resp.status_code}")

            if resp.status_code in [200, 201]:
                logger.success("✅ Request successful")
                return resp.json()
            elif resp.status_code == 401:
                logger.warning("⚠️ 401 Unauthorized. Regenerating JWT...")
                time.sleep(retry_delay)
            else:
                logger.error(f"⚠️ Request failed: {resp.text}")
                break
        except requests.exceptions.RequestException as e:
            logger.error(f"⚠️ Request exception: {e}")
            time.sleep(retry_delay)
    logger.error("❌ All retries failed. Check API key, PEM, permissions, or container clock.")
    return None

# ----------------------------
# Fetch funded accounts with balance
# ----------------------------
def fetch_funded_accounts():
    path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
    accounts = safe_request(path, method="GET")
    if not accounts:
        return None
    # Filter accounts with USD balance > 0
    funded = [a for a in accounts if float(a.get("balance", {}).get("amount", 0)) > 0]
    return funded

# ----------------------------
# Calculate position size
# ----------------------------
def calculate_size(account, percent=0.05, product_price=50000):
    """Example: 5% of account balance"""
    usd_balance = float(account.get("balance", {}).get("amount", 0))
    amount_to_spend = usd_balance * percent
    size = round(amount_to_spend / product_price, 6)
    return str(size)

# ----------------------------
# Place an order
# ----------------------------
def place_order(account_id, side, product_id, size):
    path = f"/api/v3/brokerage/accounts/{account_id}/orders"
    data = {
        "side": side.upper(),
        "product_id": product_id,
        "size": size,
        "type": "market"
    }
    response = safe_request(path, method="POST", data=data)
    if response:
        logger.success(f"✅ Order placed: {side} {size} {product_id}")
        logger.info(response)
    else:
        logger.error("❌ Failed to place order")

# ----------------------------
# Process trading signals
# ----------------------------
def process_trading_signal(signal, accounts):
    logger.info(f"📡 Received trading signal: {signal}")
    if not accounts:
        logger.error("No funded accounts available")
        return
    # Pick account with highest USD balance
    account = max(accounts, key=lambda a: float(a.get("balance", {}).get("amount", 0)))
    # Example: product price hardcoded, replace with live price if available
    price = 50000 if signal["product"] == "BTC-USD" else 1
    size = calculate_size(account, percent=0.05, product_price=price)
    place_order(account["id"], signal["side"], signal["product"], size)

# ----------------------------
# Main bot logic
# ----------------------------
def main():
    logger.info("Starting Nija Trading Bot...")

    accounts = fetch_funded_accounts()
    if not accounts:
        logger.error("Cannot fetch Coinbase accounts. Stopping bot.")
        return

    logger.info("Bot connected! Accounts fetched successfully.")
    logger.info(accounts)

    # Demo signals (replace with TradingView/websocket signals)
    demo_signals = [
        {"side": "BUY", "product": "BTC-USD"},
        {"side": "SELL", "product": "BTC-USD"}
    ]

    for signal in demo_signals:
        process_trading_signal(signal, accounts)
        time.sleep(1)

    logger.info("Bot run complete. Ready for live signals.")

if __name__ == "__main__":
    main()
