# app/nija_client.py

import os
from coinbase.rest import RESTClient  # Coinbase Advanced SDK
from loguru import logger

# 1️⃣ Load environment variables
ORG_ID = os.environ.get("COINBASE_ORG_ID")
API_KEY = os.environ.get("COINBASE_API_KEY")
PEM_RAW = os.environ.get("COINBASE_PEM_CONTENT")

# 2️⃣ Clean PEM automatically
def clean_pem(pem: str) -> str:
    if not pem:
        raise ValueError("❌ COINBASE_PEM_CONTENT not found in environment variables.")
    
    # Remove any accidental prefix like 'COINBASE_PEM_CONTENT='
    if pem.startswith("COINBASE_PEM_CONTENT="):
        pem = pem.split("=", 1)[1]

    # Replace literal "\n" with real line breaks
    pem = pem.replace("\\n", "\n").strip()

    # Ensure PEM starts and ends correctly
    if not pem.startswith("-----BEGIN") or not pem.endswith("-----END EC PRIVATE KEY-----"):
        raise ValueError("❌ PEM format invalid after cleanup.")
    
    return pem

try:
    PEM_CLEAN = clean_pem(PEM_RAW)
except Exception as e:
    logger.error(e)
    PEM_CLEAN = None

# 3️⃣ Initialize Coinbase REST client
if PEM_CLEAN:
    client = RESTClient(
        api_key=API_KEY,
        api_secret=PEM_CLEAN,
    )
else:
    client = None
    logger.error("❌ Coinbase client not initialized due to PEM issues.")

# 4️⃣ Test connection
def test_coinbase_connection():
    if not client:
        logger.error("❌ Coinbase client not available.")
        return

    try:
        accounts = client.get_accounts()
        logger.success("✅ Coinbase accounts fetched successfully:")
        for a in accounts.data:
            logger.info(f"- {a.id} | {a.name} | Balance: {a.balance.amount} {a.balance.currency}")
    except Exception as e:
        logger.error(f"❌ Coinbase auth failed: {e}")

# 5️⃣ Run test if executed directly
if __name__ == "__main__":
    test_coinbase_connection()
