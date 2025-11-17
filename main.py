import os
import time
import logging
import requests
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# --- Load environment variables ---
PRIMARY_ORG = os.environ.get("COINBASE_ORG_ID")
PRIMARY_KID = os.environ.get("COINBASE_API_KEY_ID")
PRIMARY_PEM = os.environ.get("COINBASE_PEM_CONTENT")

FALLBACK_ORG = os.environ.get("COINBASE_FALLBACK_ORG_ID")
FALLBACK_KID = os.environ.get("COINBASE_FALLBACK_API_KEY_ID")
FALLBACK_PEM = os.environ.get("COINBASE_FALLBACK_PEM_CONTENT")

COINBASE_API_BASE = os.environ.get("COINBASE_BASE_URL", "https://api.coinbase.com")

# --- Helper: detect outbound IP ---
def get_outbound_ip():
    try:
        ip = requests.get("https://api.ipify.org?format=json", timeout=5).json().get("ip")
        logging.info(f"⚡ Current outbound IP on this run: {ip} (via ipify)")
        logging.info(f"--- Coinbase Advanced Whitelist line (paste this exact IP) ---\n{ip}\n---------------------------------------------------------------")
        return ip
    except Exception as e:
        logging.error(f"Unable to detect outbound IP: {e}")
        return None

# --- Helper: create JWT ---
def make_jwt(org_id, kid, pem_content):
    key = serialization.load_pem_private_key(
        pem_content.encode(), password=None, backend=default_backend()
    )
    iat = int(time.time())
    payload = {
        "iat": iat,
        "exp": iat + 120,
        "sub": f"/organizations/{org_id}/apiKeys/{kid}",
        "request_path": f"/api/v3/brokerage/organizations/{org_id}/key_permissions",
        "method": "GET",
        "jti": f"check-{iat}"
    }
    headers = {"alg": "ES256", "kid": kid, "typ": "JWT"}
    token = jwt.encode(payload, key, algorithm="ES256", headers=headers)
    return token

# --- Helper: test key ---
def test_key(org_id, kid, pem_content):
    try:
        token = make_jwt(org_id, kid, pem_content)
        url = f"{COINBASE_API_BASE}/api/v3/brokerage/organizations/{org_id}/key_permissions"
        resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=5)
        if resp.status_code == 200:
            logging.info(f"✅ Key valid: org={org_id} kid={kid}")
            return True
        else:
            logging.warning(f"❌ [{resp.status_code}] Unauthorized for org={org_id} kid={kid}")
            return False
    except Exception as e:
        logging.error(f"Error testing key org={org_id} kid={kid}: {e}")
        return False

# --- Main startup ---
def main():
    get_outbound_ip()
    
    if PRIMARY_ORG and PRIMARY_KID and PRIMARY_PEM:
        logging.info(f"Checking primary key: org={PRIMARY_ORG} kid={PRIMARY_KID}")
        if test_key(PRIMARY_ORG, PRIMARY_KID, PRIMARY_PEM):
            logging.info("✅ Using primary key for live trading.")
            return
        else:
            logging.warning("Primary key failed.")
    else:
        logging.warning("Primary key not fully configured in environment.")

    if FALLBACK_ORG and FALLBACK_KID and FALLBACK_PEM:
        logging.info(f"Checking fallback key: org={FALLBACK_ORG} kid={FALLBACK_KID}")
        if test_key(FALLBACK_ORG, FALLBACK_KID, FALLBACK_PEM):
            logging.info("✅ Using fallback key for live trading.")
            return
        else:
            logging.warning("Fallback key failed.")
    else:
        logging.warning("No fallback key configured.")

    logging.error("❌ Coinbase key validation failed. Fix the following:")
    logging.info("\n--- Railway / Render env export lines (copy & paste) ---")
    logging.info(f"export COINBASE_ORG_ID={PRIMARY_ORG or '<your_org>'}")
    logging.info(f"export COINBASE_API_KEY_ID={PRIMARY_KID or '<your_kid>'}")
    logging.info(f"export COINBASE_PEM_CONTENT='(paste full PEM as MULTILINE value including header/footer)'")
    logging.info(f"export COINBASE_FALLBACK_ORG_ID={FALLBACK_ORG or '<optional fallback org>'}")
    logging.info(f"export COINBASE_FALLBACK_API_KEY_ID={FALLBACK_KID or '<optional fallback kid>'}")
    logging.info(f"export COINBASE_FALLBACK_PEM_CONTENT='(optional fallback PEM)'")
    logging.info("------------------------------------------------------")
    logging.info("After updating env or whitelist, restart your container.")

if __name__ == "__main__":
    logging.info("🔥 Nija Trading Bot bootstrap starting...")
    main()
