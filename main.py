# main.py (paste in your project root)
import os
import time
import requests
import jwt  # PyJWT
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# Load environment variables (set in Railway or locally)
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")  # full path
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")

if not COINBASE_ORG_ID or not COINBASE_API_KEY or not COINBASE_PEM_CONTENT:
    raise Exception("Missing required Coinbase environment variables.")

# Extract API key ID from full path
API_KEY_ID = COINBASE_API_KEY.split('/')[-1]

# Fix PEM formatting
pem_corrected = COINBASE_PEM_CONTENT.replace("\\n", "\n")

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

# Function to generate JWT (5-minute validity)
def generate_jwt():
    payload = {
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,  # 5 minutes
        "sub": API_KEY_ID
    }
    token = jwt.encode(payload, private_key, algorithm="ES256")
    return token

# Function to fetch accounts
def fetch_accounts():
    token = generate_jwt()
    headers = {
        "Authorization": f"Bearer {token}",
        "CB-VERSION": "2025-11-01"  # Use current API version
    }
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
        print(f"❌ Error fetching accounts: {e}")

# Main loop example (retries every 10 seconds)
if __name__ == "__main__":
    while True:
        fetch_accounts()
        time.sleep(10)
