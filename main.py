import os
import logging
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')

# --- Load Env Variables ---
COINBASE_ORG_ID = os.getenv('COINBASE_ORG_ID')
COINBASE_API_KEY_ID = os.getenv('COINBASE_API_KEY_ID')
COINBASE_PEM_CONTENT = os.getenv('COINBASE_PEM_CONTENT')

if not all([COINBASE_ORG_ID, COINBASE_API_KEY_ID, COINBASE_PEM_CONTENT]):
    logging.error("❌ One or more Coinbase env variables are missing.")
    exit(1)

# --- Normalize and Check PEM ---
try:
    pem_bytes = COINBASE_PEM_CONTENT.encode('utf-8')
    key = serialization.load_pem_private_key(pem_bytes, password=None, backend=default_backend())
    logging.info("✅ PEM loaded successfully and valid EC key.")
except Exception as e:
    logging.error(f"❌ Failed to load PEM. Check formatting and copy/paste: {e}")
    exit(1)

# --- Print Current Outbound IP for Coinbase whitelist ---
try:
    ip = requests.get("https://api.ipify.org").text
    logging.info(f"⚡ Current outbound IP (for whitelist in Coinbase Advanced): {ip}")
except Exception as e:
    logging.warning(f"⚠️ Could not fetch outbound IP: {e}")

# --- Optional: Test JWT Creation ---
# (Simple check to ensure key works for signing; real bot would generate JWT)
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

try:
    signature = key.sign(b"test", ec.ECDSA(hashes.SHA256()))
    logging.info("✅ PEM can sign data (ready for JWT).")
except Exception as e:
    logging.error(f"❌ PEM cannot sign data: {e}")
    exit(1)

logging.info("🔥 Coinbase PEM and API key check complete. If all passes, bot can start trading after IP whitelist.")
