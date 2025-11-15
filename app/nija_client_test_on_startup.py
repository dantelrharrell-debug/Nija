# Insert near the top of your app's startup (start_bot_main.py or app/nija_client.py)
import os, time, jwt, requests, datetime
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# Setup logger (keeps using your existing logging style)
logger.remove()
logger.add(lambda m: print(m, end=""), level=os.environ.get("LOG_LEVEL", "INFO"))

def ensure_pem_file():
    pem_env = os.environ.get("COINBASE_PEM_CONTENT")
    pem_path = "/app/coinbase.pem"
    if not pem_env:
        logger.info("COINBASE_PEM_CONTENT not set in env; checking COINBASE_PEM_PATH")
        return pem_path  # may be set externally
    # If PEM contains literal '\n' sequences, convert them to real newlines
    if "\\n" in pem_env and "\n" not in pem_env:
        pem_text = pem_env.replace("\\n", "\n")
    else:
        pem_text = pem_env
    # Trim accidental leading/trailing quotes or spaces
    pem_text = pem_text.strip().strip('"').strip("'") + "\n"
    # Write to file (overwrite each startup)
    with open(pem_path, "w", newline="\n") as f:
        f.write(pem_text)
    logger.info(f"Wrote PEM to {pem_path} ({len(pem_text)} bytes)")
    return pem_path

def load_private_key(path):
    with open(path, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None, backend=default_backend())

def make_jwt_and_test():
    try:
        pem_path = os.environ.get("COINBASE_PEM_PATH") or ensure_pem_file()
        org_id = os.environ.get("COINBASE_ORG_ID")
        kid = os.environ.get("COINBASE_JWT_KID")
        if not org_id:
            logger.error("COINBASE_ORG_ID missing from env. Set it in Render environment.")
            return
        key = load_private_key(pem_path)
        iat = int(time.time())
        payload = {"sub": org_id, "iat": iat, "exp": iat + 300}
        headers = {"kid": kid} if kid else {}
        token = jwt.encode(payload, key, algorithm="ES256", headers=headers)
        # Print small previews to logs for debugging (DO NOT expose full PEM)
        logger.info("Generated JWT (first 200 chars):\n" + (token[:200] if token else ""))
        # Inspect header/payload without verifying signature
        try:
            hdr = jwt.get_unverified_header(token)
            pld = jwt.decode(token, options={"verify_signature": False})
            logger.info(f"JWT header (unverified): {hdr}")
            logger.info(f"JWT payload (unverified): {pld}")
        except Exception as e:
            logger.warning(f"Failed to decode JWT locally: {e}")
        # Server time for clock-skew checks
        logger.info("Server UTC time: " + datetime.datetime.utcnow().isoformat())
        # Test request to Coinbase -- short timeout
        cb_headers = {
            "Authorization": f"Bearer {token}",
            "CB-VERSION": os.environ.get("CB_API_VERSION", "2025-01-01")
        }
        try:
            resp = requests.get("https://api.coinbase.com/v2/accounts", headers=cb_headers, timeout=12)
            logger.info(f"Coinbase test response: {resp.status_code}")
            logger.info("Coinbase response text (truncated 1000 chars):\n" + (resp.text[:1000] if resp.text else ""))
        except Exception as e:
            logger.error(f"Coinbase request exception: {e}")
    except Exception as e:
        logger.exception("Error in make_jwt_and_test: " + str(e))

# Run test immediately on startup (it will print to deploy logs)
make_jwt_and_test()
# Continue with the rest of your startup below...
