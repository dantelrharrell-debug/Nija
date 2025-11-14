# app/nija_client.py

import os
from coinbase.rest import RESTClient  # Coinbase Advanced SDK
from loguru import logger

# 1️⃣ Load environment variables
ORG_ID = os.environ.get("COINBASE_ORG_ID")
API_KEY = os.environ.get("COINBASE_API_KEY")
PEM_RAW = os.environ.get("COINBASE_PEM_CONTENT")

# 2️⃣ Fix PEM newlines if Railway converted them
if PEM_RAW and "\\n" in PEM_RAW:
    PEM_RAW = PEM_RAW.replace("\\n", "\n")

# Optional: log for debugging (remove in production)
logger.info(f"PEM length: {len(PEM_RAW) if PEM_RAW else 'None'}")

# 3️⃣ Initialize Coinbase REST client
client = RESTClient(
    api_key=API_KEY,
    api_secret=PEM_RAW,
)

# 4️⃣ Test fetching accounts
def test_accounts():
    try:
        accounts = client.get_accounts()
        print("✅ Accounts fetched successfully:")
        for a in accounts.data:
            print(f"- {a.id} | {a.name} | Balance: {a.balance.amount} {a.balance.currency}")
    except Exception as e:
        print("❌ Coinbase auth failed:", e)
        logger.error(e)

# 5️⃣ Allow script to be run directly
if __name__ == "__main__":
    test_accounts()
