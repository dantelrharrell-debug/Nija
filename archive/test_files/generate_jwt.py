import os, time, jwt, json
from pathlib import Path

# ======== CONFIG ==========
API_KEY = os.getenv("COINBASE_API_KEY")  # The public key ID from Coinbase dashboard
PRIVATE_KEY_PATH = "coinbase_private_key.pem"  # Path to PEM file
ORGANIZATION_ID = os.getenv("COINBASE_ORG_ID")  # from API Key page
# ==========================

def generate_coinbase_jwt():
    with open(PRIVATE_KEY_PATH, "r") as f:
        private_key = f.read()

    now = int(time.time())
    payload = {
        "sub": API_KEY,
        "iss": ORGANIZATION_ID,
        "nbf": now,
        "iat": now,
        "exp": now + 600,  # 10-minute expiry
    }
    token = jwt.encode(payload, private_key, algorithm="ES256")
    print("\n✅ Coinbase JWT generated successfully:\n")
    print(token)
    print("\nSet this in your environment as:")
    print(f"COINBASE_JWT={token}\n")

if __name__ == "__main__":
    generate_coinbase_jwt()
