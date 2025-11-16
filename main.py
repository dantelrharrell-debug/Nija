import os
import time
import requests
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# --- Load env vars ---
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")

# Convert literal \n to real newlines
pem_corrected = COINBASE_PEM_CONTENT.replace("\\n", "\n")

# Load private key
try:
    private_key = serialization.load_pem_private_key(
        pem_corrected.encode(),
        password=None,
        backend=default_backend()
    )
    print("✅ PEM private key loaded successfully")
except Exception as e:
    print(f"❌ Failed to load PEM key: {e}")
    raise e

# Extract API key ID from full path if needed
API_KEY_ID = COINBASE_API_KEY.split('/')[-1]

# Generate JWT
payload = {
    "iat": int(time.time()),
    "exp": int(time.time()) + 300,
    "sub": API_KEY_ID
}

token = jwt.encode(payload, private_key, algorithm="ES256")
print("✅ JWT generated successfully")
print("JWT preview (first 50 chars):", token[:50])

# Optional: test accounts endpoint (won’t crash if fails)
try:
    url = f"https://api.coinbase.com/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        print("✅ Accounts fetched successfully!")
        print(response.json())
    else:
        print(f"⚠️ Failed to fetch accounts. Status: {response.status_code}")
except Exception as e:
    print(f"⚠️ Exception fetching accounts: {e}")

# Heartbeat/log for live bot
print("🌟 Nija bot is live and waiting for Coinbase signals...")

# --- continue with your normal main loop here ---
