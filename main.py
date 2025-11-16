import os
import time
import requests
import jwt  # PyJWT
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

# =============================
# Load environment variables
# =============================
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")  # Full path or just ID
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")

if not all([COINBASE_ORG_ID, COINBASE_API_KEY, COINBASE_PEM_CONTENT]):
    raise ValueError("❌ Missing one of the Coinbase environment variables.")

# Extract API Key ID from full path if needed
API_KEY_ID = COINBASE_API_KEY.split("/")[-1]

# =============================
# Load PEM private key
# =============================
try:
    # Convert literal \n to actual newlines
    pem_corrected = COINBASE_PEM_CONTENT.replace("\\n", "\n")
    private_key = serialization.load_pem_private_key(
        pem_corrected.encode(),
        password=None,
        backend=default_backend()
    )
    print("✅ PEM private key loaded successfully")
except Exception as e:
    print(f"❌ Failed to load PEM key: {e}")
    raise e

# =============================
# Generate JWT
# =============================
try:
    payload = {
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,  # 5 minutes validity
        "sub": API_KEY_ID
    }
    token = jwt.encode(payload, private_key, algorithm="ES256")
    print("✅ JWT generated successfully")
    print("JWT preview (first 50 chars):", token[:50])
except Exception as e:
    print(f"❌ Failed to generate JWT: {e}")
    raise e

# =============================
# Fetch Coinbase Accounts
# =============================
try:
    url = f"https://api.coinbase.com/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        print("✅ Accounts fetched successfully!")
        print(response.json())
    else:
        print(f"❌ Failed to fetch accounts. Status: {response.status_code}")
        print(response.text)
except Exception as e:
    print(f"❌ Error fetching accounts: {e}")
    raise e

# =============================
# Main Loop (optional heartbeat)
# =============================
while True:
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            print(f"✅ Accounts fetch OK at {time.strftime('%X')}")
        else:
            print(f"❌ Accounts fetch failed at {time.strftime('%X')}, status: {response.status_code}")
        time.sleep(30)  # Wait 30s before next fetch
    except Exception as e:
        print(f"❌ Exception during heartbeat: {e}")
        time.sleep(30)
