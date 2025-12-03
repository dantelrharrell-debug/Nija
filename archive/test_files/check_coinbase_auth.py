# check_coinbase_auth.py
import os
import time
import jwt
import requests
from dotenv import load_dotenv

# Load .env
if os.path.exists(".env"):
    load_dotenv()

COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
COINBASE_API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE", "")

def generate_jwt(api_key, pem_content):
    # JWT payload
    iat = int(time.time())
    payload = {
        "sub": api_key,
        "iat": iat,
        "exp": iat + 300  # 5 min expiration
    }

    # Create JWT
    try:
        token = jwt.encode(payload, pem_content, algorithm="ES256")
        return token
    except Exception as e:
        print(f"❌ Failed to generate JWT: {e}")
        return None

def test_coinbase_auth():
    print("🔹 Generating JWT...")
    token = generate_jwt(COINBASE_API_KEY, COINBASE_PEM_CONTENT)
    if not token:
        print("❌ JWT generation failed. Check your PEM format.")
        return

    print(f"✅ JWT generated (first 50 chars): {token[:50]}...")

    url = "https://api.coinbase.com/advanced/accounts"
    headers = {
        "CB-VERSION": "2025-11-14",
        "Authorization": f"Bearer {token}",
    }

    print("🔹 Testing Coinbase /accounts endpoint...")
    try:
        resp = requests.get(url, headers=headers)
        if resp.status_code == 200:
            print("✅ Authentication successful! Your key is valid.")
        elif resp.status_code == 401:
            print("❌ Unauthorized (401). Check your key, org ID, or permissions.")
        else:
            print(f"⚠️ Unexpected response {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"❌ Request failed: {e}")

if __name__ == "__main__":
    test_coinbase_auth()
