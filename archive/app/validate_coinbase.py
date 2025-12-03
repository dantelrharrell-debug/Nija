import os
import jwt
import time
import requests
from loguru import logger

logger.add(lambda msg: print(msg, end=''))

def validate_coinbase():
    org_id = os.environ.get("COINBASE_ORG_ID")
    api_key = os.environ.get("COINBASE_API_KEY")
    pem_raw = os.environ.get("COINBASE_PEM_CONTENT")

    if not org_id or not api_key or not pem_raw:
        logger.error("❌ One or more Coinbase env vars are missing.")
        return False

    try:
        # Format PEM properly
        pem = pem_raw.replace("\\n", "\n").strip()
        payload = {
            "sub": org_id,
            "iat": int(time.time()),
            "exp": int(time.time()) + 30
        }
        token = jwt.encode(payload, pem, algorithm="ES256")
        headers = {
            "Authorization": f"Bearer {token}",
            "CB-ACCESS-KEY": api_key
        }

        r = requests.get("https://api.coinbase.com/v2/accounts", headers=headers, timeout=5)
        if r.status_code == 200:
            logger.success("✅ Coinbase credentials validated successfully!")
            return True
        else:
            logger.error(f"❌ Coinbase responded with {r.status_code}: {r.text}")
            return False

    except Exception as e:
        logger.error(f"❌ Exception during validation: {e}")
        return False


if __name__ == "__main__":
    if not validate_coinbase():
        logger.error("Aborting startup: Coinbase credentials invalid.")
        exit(1)
    else:
        logger.success("Pre-flight check passed. You can start the bot now.")
