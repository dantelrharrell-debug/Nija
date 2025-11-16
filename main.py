import os
import time
import requests
import jwt  # PyJWT library
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# ----------------------------
# Load environment variables
# ----------------------------
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")  # Full path or just ID
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")

if not COINBASE_ORG_ID or not COINBASE_API_KEY or not COINBASE_PEM_CONTENT:
    raise EnvironmentError("❌ Missing Coinbase environment variables!")

# Extract API key ID if full path
API_KEY_ID = COINBASE_API_KEY.split('/')[-1]

# ----------------------------
# Load PEM private key safely
# ----------------------------
try:
    # Convert literal \n to real newlines and strip whitespace
    pem_corrected = COINBASE_PEM_CONTENT.replace("\\n", "\n").strip()
    
    private_key = serialization.load_pem_private_key(
        pem_corrected.encode(),
        password=None,
        backend=default_backend()
    )
    print("✅ PEM private key loaded successfully")
except Exception as e:
    print(f"❌ Failed to load PEM key: {e}")
    raise e

# ----------------------------
# Generate JWT for Coinbase Advanced API
# ----------------------------
def generate_jwt():
    payload = {
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,  # 5 min validity
        "sub": API_KEY_ID
    }
    token = jwt.encode(payload, private_key, algorithm="ES256")
    return token

# ----------------------------
# Fetch Coinbase accounts
# ----------------------------
def fetch_accounts():
    token = generate_jwt()
    headers = {"Authorization": f"Bearer {token}"}
    url = f"https://api.coinbase.com/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            print("✅ Accounts fetched successfully!")
            print(response.json())
            return response.json()
        else:
            print(f"❌ Failed to fetch accounts. Status: {response.status_code}")
            print(response.text)
            return None
    except Exception as e:
        print(f"❌ Exception while fetching accounts: {e}")
        return None

# ----------------------------
# Main bot loop
# ----------------------------
def main_loop():
    print("🌟 Nija bot starting...")
    while True:
        accounts = fetch_accounts()
        if accounts:
            print("Accounts ready. Bot is live.")
            # Here you can trigger your trading logic
        else:
            print("Retrying in 5 seconds...")
            time.sleep(5)

if __name__ == "__main__":
    main_loop()
