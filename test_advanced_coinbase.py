import os
import time
import jwt
import requests

# --- Load environment variables ---
COINBASE_ISS = os.getenv("COINBASE_ISS")          # Your Coinbase Advanced API Key ID
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")  # Your private key in PEM format

BASE_URL = "https://api.coinbase.com"  # Advanced API base URL

def test_advanced_keys():
    if not COINBASE_ISS or not COINBASE_PEM_CONTENT:
        print("❌ Missing COINBASE_ISS or COINBASE_PEM_CONTENT in environment")
        return

    # --- Prepare JWT ---
    timestamp = int(time.time())
    payload = {
        "iss": COINBASE_ISS,
        "iat": timestamp,
        "exp": timestamp + 300  # 5 minutes expiry
    }

    try:
        token = jwt.encode(payload, COINBASE_PEM_CONTENT, algorithm="ES256")
    except Exception as e:
        print("❌ JWT creation failed:", e)
        return

    headers = {
        "Authorization": f"Bearer {token}"
    }

    # --- Hit the accounts endpoint ---
    try:
        r = requests.get(f"{BASE_URL}/accounts", headers=headers)
        print("Status Code:", r.status_code)
        print("Response:", r.text)
        if r.status_code == 200:
            print("✅ Advanced API keys are valid!")
        else:
            print("❌ Advanced API keys invalid or unauthorized")
    except Exception as e:
        print("❌ Request failed:", e)

if __name__ == "__main__":
    test_advanced_keys()
