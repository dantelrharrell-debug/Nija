import os
import datetime
from loguru import logger
from app.nija_client import CoinbaseClient

# --- Config / Credentials ---
api_key = os.getenv("COINBASE_API_KEY")  # or just paste your key
org_id  = os.getenv("COINBASE_ORG_ID")
pem     = os.getenv("COINBASE_PEM_CONTENT")  # multiline private key
kid     = os.getenv("COINBASE_KID")         # Key ID from Coinbase

logger.info("Nija bot starting... (main.py)")

# --- Initialize CoinbaseClient ---
try:
    client = CoinbaseClient(api_key=api_key, org_id=org_id, pem=pem, kid=kid)
    logger.info("CoinbaseClient initialized")
except Exception as e:
    logger.exception("Failed to init CoinbaseClient: {}", e)
    raise

# --- JWT verification helper ---
def verify_jwt_struct(token):
    import base64, json
    h_b64, p_b64, _ = token.split(".")
    def b64fix(s):
        return s + "=" * ((4 - len(s) % 4) % 4)
    header = json.loads(base64.urlsafe_b64decode(b64fix(h_b64)))
    payload = json.loads(base64.urlsafe_b64decode(b64fix(p_b64)))
    return header, payload

# --- Log actual JWT values ---
try:
    token = client._build_jwt()  # Make sure _build_jwt exists in your client
    header, payload = verify_jwt_struct(token)
    logger.info(f"_build_jwt: JWT header.kid: {header.get('kid')}")
    logger.info(f"_build_jwt: JWT payload.sub: {payload.get('sub')}")
    logger.info(f"_build_jwt: Server UTC time: {datetime.datetime.utcnow().isoformat()}")
except Exception as e:
    logger.exception("Failed to decode/log JWT contents: {}", e)

# --- Simple API test ---
try:
    status, resp = client.request_auto("GET", "/v2/accounts")
    logger.info(f"Coinbase API test status: {status}")
except Exception as e:
    logger.exception("Coinbase API test failed: {}", e)

# --- Start bot main ---
try:
    from app.start_bot_main import start_bot_main
    start_bot_main()
except Exception as e:
    logger.exception("Failed to start bot main: {}", e)
