import os
import time
import logging
import requests
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# ------------------------
# Environment / Keys
# ------------------------
PRIMARY_ORG_ID = os.environ.get("COINBASE_ORG_ID")
PRIMARY_API_KEY_ID = os.environ.get("COINBASE_API_KEY_ID")
PRIMARY_PEM_CONTENT = os.environ.get("COINBASE_PEM_CONTENT")

# Optional fallback key (unrestricted)
FALLBACK_ORG_ID = os.environ.get("COINBASE_FALLBACK_ORG_ID")
FALLBACK_API_KEY_ID = os.environ.get("COINBASE_FALLBACK_API_KEY_ID")
FALLBACK_PEM_CONTENT = os.environ.get("COINBASE_FALLBACK_PEM_CONTENT")

COINBASE_BASE_URL = "https://api.coinbase.com"

# ------------------------
# Helper: Detect outbound IP
# ------------------------
def get_outbound_ip():
    try:
        response = requests.get("https://api.ipify.org?format=json", timeout=5)
        ip = response.json().get("ip")
        logging.info(f"⚡ Current outbound IP on this run: {ip} (via ipify)")
        logging.info(f"--- Coinbase Advanced Whitelist line (paste this exact IP) ---\n{ip}\n---------------------------------------------------------------")
        return ip
    except Exception as e:
        logging.error(f"Unable to detect outbound IP: {e}")
        return None

# ------------------------
# Helper: Generate JWT for Coinbase Advanced
# ------------------------
def generate_jwt(org_id, key_id, pem_content):
    key = serialization.load_pem_private_key(pem_content.encode(), password=None, backend=default_backend())
    iat = int(time.time())
    payload = {
        "iat": iat,
        "exp": iat + 120,
        "sub": f"/organizations/{org_id}/apiKeys/{key_id}",
        "request_path": f"/api/v3/brokerage/organizations/{org_id}/key_permissions",
        "method": "GET",
        "jti": f"nija-{iat}"
    }
    headers = {"alg":"ES256","kid":key_id,"typ":"JWT"}
    token = jwt.encode(payload, key, algorithm="ES256", headers=headers)
    return token

# ------------------------
# Check key permissions
# ------------------------
def check_key(org_id, key_id, pem_content):
    logging.info(f"Checking key: org={org_id} kid={key_id}")
    try:
        token = generate_jwt(org_id, key_id, pem_content)
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{COINBASE_BASE_URL}/api/v3/brokerage/organizations/{org_id}/key_permissions"
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            logging.info(f"✅ Key validated: org={org_id} kid={key_id}")
            return True
        else:
            logging.warning(f"❌ {response.status_code} Unauthorized for org={org_id} kid={key_id}")
            return False
    except Exception as e:
        logging.error(f"Error checking key: {e}")
        return False

# ------------------------
# Main trading startup
# ------------------------
def start_trading():
    logging.info("🚀 Starting live trading...")
    try:
        from bot_live import execute_trades
        execute_trades()
    except Exception as e:
        logging.error(f"⚠️ Error during live trading: {e}")

if __name__ == "__main__":
    logging.info("🔥 Nija Trading Bot bootstrap starting...")
    ip = get_outbound_ip()

    # Step 1: Try primary key
    if PRIMARY_ORG_ID and PRIMARY_API_KEY_ID and PRIMARY_PEM_CONTENT:
        if check_key(PRIMARY_ORG_ID, PRIMARY_API_KEY_ID, PRIMARY_PEM_CONTENT):
            start_trading()
        else:
            logging.warning("Primary key validation failed.")
            # Step 2: Try fallback key
            if FALLBACK_ORG_ID and FALLBACK_API_KEY_ID and FALLBACK_PEM_CONTENT:
                logging.info("Attempting fallback key...")
                if check_key(FALLBACK_ORG_ID, FALLBACK_API_KEY_ID, FALLBACK_PEM_CONTENT):
                    start_trading()
                else:
                    logging.error("❌ Fallback key also failed. Fix keys or whitelist IP.")
            else:
                logging.error("No fallback key configured. Add COINBASE_FALLBACK_* env vars for unrestricted key.")
    else:
        logging.error("Primary key not fully configured. Set COINBASE_ORG_ID, COINBASE_API_KEY_ID, COINBASE_PEM_CONTENT.")

    logging.info("⚠️ If keys failed, copy/paste the following for Railway/Render environment setup:")
    logging.info(f"export COINBASE_ORG_ID={PRIMARY_ORG_ID}")
    logging.info(f"export COINBASE_API_KEY_ID={PRIMARY_API_KEY_ID}")
    logging.info("export COINBASE_PEM_CONTENT='(paste full PEM as MULTILINE value including header/footer)'")
    logging.info("export COINBASE_FALLBACK_ORG_ID=(optional fallback org)")
    logging.info("export COINBASE_FALLBACK_API_KEY_ID=(optional fallback kid)")
    logging.info("export COINBASE_FALLBACK_PEM_CONTENT='(optional fallback PEM)'")
