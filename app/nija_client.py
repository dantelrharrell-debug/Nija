# app/nija_client.py

import os
from coinbase.rest import RESTClient  # Coinbase SDK
from loguru import logger

# 1️⃣ Load environment variables
ORG_ID = os.environ.get("COINBASE_ORG_ID")
API_KEY = os.environ.get("COINBASE_API_KEY")
PEM_RAW = os.environ.get("COINBASE_PEM_CONTENT")

# 2️⃣ Fix PEM newlines (Railway sometimes converts "\n" to literal "\\n")
if PEM_RAW and "\\n" in PEM_RAW:
    PEM_RAW = PEM_RAW.replace("\\n", "\n")

# 3️⃣ Initialize Coinbase REST client
client = RESTClient(
    api_key=API_KEY,
    api_secret=PEM_RAW,
)

logger.info("Coinbase REST client initialized.")

# 4️⃣ Test block to verify auth
if __name__ == "__main__":
    try:
        accounts = client.get_accounts()
        print("✅ Accounts:", accounts.data)
    except Exception as e:
        print("❌ Coinbase auth failed:", e)
