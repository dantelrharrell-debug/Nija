import os
import time
import requests
import jwt  # PyJWT library
from cryptography.hazmat.primitives import serialization

# ========================
# 1️⃣ Load environment variables
# ========================
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")  # Full path or just ID
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")

if not all([COINBASE_ORG_ID, COINBASE_API_KEY, COINBASE_PEM_CONTENT]):
    raise ValueError("Missing Coinbase environment variables!")

# Extract API Key ID
API_KEY_ID = COINBASE_API_KEY.split('/')[-1]

# ========================
# 2️⃣ Load PEM private key
# ========================
private_key = serialization.load_pem_private_key(
    COINBASE_PEM_CONTENT.encode(),
    password=None
)

# ========================
# 3️⃣ Function to generate JWT
# ========================
def generate_jwt():
    payload = {
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,  # 5 min expiration
        "sub": API_KEY_ID
    }
    token = jwt.encode(payload, private_key, algorithm="ES256")
    return token

# ========================
# 4️⃣ Function to fetch accounts
# ========================
def get_accounts():
    token = generate_jwt()
    url = f"https://api.coinbase.com/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
    headers = {"Authorization": f"Bearer {token}"}

    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        print("✅ Accounts fetched successfully!")
        return response.json()
    else:
        print(f"❌ Failed to fetch accounts: {response.status_code}")
        print(response.text)
        return None

# ========================
# 5️⃣ Main bot loop
# ========================
def main_loop():
    print("🚀 Nija bot starting...")
    while True:
        accounts = get_accounts()
        # Example: just print balances for now
        if accounts:
            for acct in accounts.get("data", []):
                print(f"{acct['name']}: {acct['balance']['amount']} {acct['balance']['currency']}")
        # Wait before next poll
        time.sleep(10)

# ========================
# 6️⃣ Entry point
# ========================
if __name__ == "__main__":
    main_loop()
