print("🌟 Script is running. Env vars:")
print("COINBASE_ORG_ID:", os.getenv("COINBASE_ORG_ID"))
print("COINBASE_API_KEY:", os.getenv("COINBASE_API_KEY")[:6] + "...")  # partial for security
print("COINBASE_PEM_CONTENT length:", len(os.getenv("COINBASE_PEM_CONTENT") or ""))

import os
import time
import requests
import jwt  # PyJWT library
from cryptography.hazmat.primitives import serialization

# --------------------------
# Load environment variables
# --------------------------
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")  # Full path
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")  # With literal \n

# Extract only the API Key ID from full path
API_KEY_ID = COINBASE_API_KEY.split('/')[-1]

# --------------------------
# Load PEM private key safely
# --------------------------
# Replace literal \n with actual newlines
pem_corrected = COINBASE_PEM_CONTENT.replace("\\n", "\n")

try:
    private_key = serialization.load_pem_private_key(
        pem_corrected.encode(),
        password=None
    )
    print("✅ PEM private key loaded successfully")
except Exception as e:
    print("❌ Failed to load PEM private key:", e)
    exit(1)

# --------------------------
# Generate JWT
# --------------------------
def generate_jwt():
    payload = {
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,  # 5 min expiration
        "sub": API_KEY_ID
    }
    token = jwt.encode(payload, private_key, algorithm="ES256")
    return token

# --------------------------
# Test: Fetch Coinbase accounts
# --------------------------
def fetch_accounts():
    token = generate_jwt()
    headers = {"Authorization": f"Bearer {token}"}
    url = f"https://api.coinbase.com/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            print("✅ Accounts fetched successfully!")
            print(response.json())
        else:
            print(f"❌ Failed to fetch accounts. Status: {response.status_code}")
            print(response.text)
    except Exception as e:
        print("❌ Error fetching accounts:", e)

# --------------------------
# Main bot loop (simple heartbeat)
# --------------------------
if __name__ == "__main__":
    print("🚀 Nija bot starting...")
    while True:
        fetch_accounts()
        print("⏱ Waiting 5 seconds before next heartbeat...\n")
        time.sleep(5)
