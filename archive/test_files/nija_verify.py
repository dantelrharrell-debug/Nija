import os
import time
import datetime
import requests
import jwt  # PyJWT
import logging

# --- CONFIG ---
SEND_TEST_TRADE = False  # Set True to do a small test trade
LOG_FILE = "nija_verify.log"

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

if not all([COINBASE_ORG_ID, COINBASE_API_KEY_ID, COINBASE_API_SUB, COINBASE_PEM_CONTENT]):
    logging.error("❌ Missing Coinbase environment variables")
    exit(1)

private_key = COINBASE_PEM_CONTENT.replace("\\n", "\n")

# --- Helper: generate JWT ---
def generate_jwt(path: str, method: str = "GET") -> str:
    iat = int(time.time())
    payload = {
        "iat": iat,
        "exp": iat + 120,  # 2 minutes
        "sub": COINBASE_API_SUB,
        "request_path": path,
        "method": method,
        "jti": f"dbg-{iat}"
    }
    headers_jwt = {"alg": "ES256", "kid": COINBASE_API_KEY_ID, "typ": "JWT"}
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers_jwt)
    return token

# --- Helper: fetch accounts ---
def fetch_accounts():
    coinbase_path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
    token = generate_jwt(coinbase_path, "GET")
    url = "https://api.coinbase.com" + coinbase_path

    try:
        resp = requests.get(url, headers={
            "Authorization": f"Bearer {token}",
            "CB-VERSION": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
            "Content-Type": "application/json"
        }, timeout=10)
        logging.info(f"DEBUG /accounts status: {resp.status_code}")
        logging.info(f"DEBUG /accounts body: {resp.text}")
        if resp.status_code == 200:
            logging.info("✅ Coinbase connection verified. Accounts fetched successfully.")
            return resp.json()
        else:
            logging.error("❌ Coinbase connection failed.")
            return None
    except Exception as e:
        logging.error(f"❌ Exception fetching accounts: {e}")
        return None

# --- Optional test trade ---
def test_trade(symbol="BTC-USD", side="buy", size=0.001):
    if not SEND_TEST_TRADE:
        logging.info(f"⚠️ Test trade disabled: {side} {size} {symbol}")
        return
    coinbase_path = "/api/v3/brokerage/orders"
    token = generate_jwt(coinbase_path, "POST")
    url = "https://api.coinbase.com" + coinbase_path
    payload = {"symbol": symbol, "side": side.lower(), "type": "market", "quantity": str(size)}
    try:
        resp = requests.post(url, headers={
            "Authorization": f"Bearer {token}",
            "CB-VERSION": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
            "Content-Type": "application/json"
        }, json=payload, timeout=10)
        logging.info(f"DEBUG trade status: {resp.status_code}, body: {resp.text}")
        if resp.status_code in [200, 201]:
            logging.info("✅ Test trade executed successfully.")
        else:
            logging.error("❌ Test trade failed.")
    except Exception as e:
        logging.error(f"❌ Exception sending test trade: {e}")

# --- Run verification ---
if __name__ == "__main__":
    logging.info("🔥 Running Coinbase verification...")
    accounts = fetch_accounts()
    if accounts:
        logging.info("Accounts fetched: " + str(accounts))
    if SEND_TEST_TRADE:
        test_trade()
