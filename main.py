import os
import time
import datetime
import requests
import jwt
import logging
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# --- Configure logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# --- Load Coinbase credentials from environment variables ---
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")

if not COINBASE_ORG_ID or not COINBASE_API_KEY_ID or not COINBASE_PEM_CONTENT:
    logging.error("❌ Missing Coinbase environment variables: ORG_ID, API_KEY_ID, PEM_CONTENT")
    exit(1)

# --- Prepare PEM key object ---
try:
    private_key = COINBASE_PEM_CONTENT.replace("\\n", "\n").encode("utf-8")
    private_key_obj = serialization.load_pem_private_key(private_key, password=None, backend=default_backend())
except Exception as e:
    logging.error(f"❌ Failed to load PEM key: {e}")
    exit(1)

# --- Helper to generate JWT ---
def generate_jwt(path, method="GET"):
    iat = int(time.time())
    payload = {
        "iat": iat,
        "exp": iat + 120,
        "sub": f"/organizations/{COINBASE_ORG_ID}/apiKeys/{COINBASE_API_KEY_ID}",
        "request_path": path,
        "method": method,
        "jti": f"nija-{iat}"
    }
    headers = {
        "alg": "ES256",
        "kid": COINBASE_API_KEY_ID,
        "typ": "JWT"
    }
    token = jwt.encode(payload, private_key_obj, algorithm="ES256", headers=headers)
    logging.info(f"✅ JWT generated: path={path}, method={method}, iat={iat}, exp={iat+120}")
    logging.debug(f"JWT payload: {payload}")
    logging.debug(f"JWT header: {headers}")
    return token

# --- Helper to check key permissions ---
def check_coinbase_key_permissions():
    path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/key_permissions"
    url = f"https://api.coinbase.com{path}"
    token = generate_jwt(path)

    try:
        resp = requests.get(url, headers={
            "Authorization": f"Bearer {token}",
            "CB-VERSION": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
            "Content-Type": "application/json"
        }, timeout=10)
    except Exception as e:
        logging.error(f"❌ Request failed: {e}")
        return False

    if resp.status_code == 200:
        logging.info(f"✅ Coinbase API key verified successfully!")
        logging.info(f"Permissions: {resp.json()}")
        return True
    elif resp.status_code == 401:
        logging.error("❌ 401 Unauthorized! Check the following:")
        logging.error("- PEM content is correct and properly formatted")
        logging.error("- ORG_ID matches the organization of the API key")
        logging.error("- API_KEY_ID matches the key you generated")
        logging.error("- Your server IP is allowed if IP restrictions are enabled")
        logging.error(f"Response: {resp.text}")
    else:
        logging.error(f"❌ Unexpected response: {resp.status_code} {resp.text}")
    return False

# --- Helper to fetch funded accounts ---
def fetch_funded_accounts():
    path = "/api/v3/brokerage/accounts"
    url = f"https://api.coinbase.com{path}"
    token = generate_jwt(path)

    try:
        resp = requests.get(url, headers={
            "Authorization": f"Bearer {token}",
            "CB-VERSION": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
            "Content-Type": "application/json"
        }, timeout=10)

        if resp.status_code == 200:
            logging.info("✅ Funded accounts fetched successfully!")
            accounts = resp.json()
            for a in accounts.get("accounts", []):
                logging.info(f"- {a['currency']} : {a['balance']} {a['currency']}")
            return accounts
        else:
            logging.error(f"❌ Failed to fetch accounts: {resp.status_code} {resp.text}")
    except Exception as e:
        logging.error(f"❌ Request failed: {e}")
    return None

# --- Main bot startup ---
if __name__ == "__main__":
    logging.info("🔥 Nija Trading Bot starting...")

    # Step 1: Check key permissions first
    if not check_coinbase_key_permissions():
        logging.error("❌ Cannot verify API key permissions. Exiting.")
        exit(1)

    # Step 2: Fetch funded accounts
    fetch_funded_accounts()
