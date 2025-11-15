# main.py
import os
import datetime
from loguru import logger
from app.nija_client import CoinbaseClient

# --- Load env vars ---
api_key = os.environ.get("COINBASE_API_KEY")
org_id = os.environ.get("COINBASE_ORG_ID")
pem_raw = os.environ.get("COINBASE_PEM_CONTENT")
kid = os.environ.get("COINBASE_KID")  # must be a string

if not pem_raw:
    raise ValueError("COINBASE_PEM_CONTENT is missing!")

# Fix PEM formatting (replace literal \n with real newlines)
pem = pem_raw.replace("\\n", "\n")

# --- Initialize Coinbase client ---
try:
    client = CoinbaseClient(api_key=api_key, org_id=org_id, pem=pem, kid=kid)
    logger.info("CoinbaseClient initialized successfully.")
except Exception as e:
    logger.exception("Failed to start Coinbase client or fetch accounts")
    raise e

# --- Build JWT and log header/payload ---
try:
    token = client._build_jwt()
    
    # Function to decode JWT header/payload
    def verify_jwt_struct(token):
        import base64, json
        h_b64, p_b64, _ = token.split(".")
        def b64fix(s): return s + "=" * ((4 - len(s) % 4) % 4)
        header = json.loads(base64.urlsafe_b64decode(b64fix(h_b64)))
        payload = json.loads(base64.urlsafe_b64decode(b64fix(p_b64)))
        return header, payload
    
    header, payload = verify_jwt_struct(token)
    logger.info(f"_build_jwt: JWT header.kid: {header.get('kid')}")
    logger.info(f"_build_jwt: JWT payload.sub: {payload.get('sub')}")
    logger.info(f"_build_jwt: Server UTC time: {datetime.datetime.utcnow().isoformat()}")
except Exception as e:
    logger.exception("Failed to decode/log JWT contents")
    raise e

# --- Test Coinbase API connection ---
try:
    status, resp = client.request_auto("GET", "/v2/accounts")
    logger.info(f"Coinbase API test status: {status}")
    if status != 200:
        logger.error(f"API response: {resp}")
except Exception as e:
    logger.exception("Coinbase API test failed")
