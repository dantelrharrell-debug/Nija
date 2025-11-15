# app/nija_client.py
import os, time, jwt, requests, datetime
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

logger.remove()
logger.add(lambda m: print(m, end=""), level=os.environ.get("LOG_LEVEL", "INFO"))

PEM_FILE_PATH = "/app/coinbase.pem"

def write_pem_from_env():
    pem_env = os.environ.get("COINBASE_PEM_CONTENT")
    if not pem_env:
        logger.info("COINBASE_PEM_CONTENT not set in environment. Skipping PEM write.")
        return None
    if "\\n" in pem_env and "\n" not in pem_env:
        pem_text = pem_env.replace("\\n", "\n")
    else:
        pem_text = pem_env
    pem_text = pem_text.strip().strip('"').strip("'")
    if not pem_text.endswith("\n"):
        pem_text += "\n"
    if len(pem_text) < 200:
        logger.warning("COINBASE_PEM_CONTENT looks very short (<200 bytes). This is likely truncated.")
    try:
        with open(PEM_FILE_PATH, "w", newline="\n") as f:
            f.write(pem_text)
        logger.info(f"Wrote PEM to {PEM_FILE_PATH} ({len(pem_text)} bytes)")
        return PEM_FILE_PATH
    except Exception as e:
        logger.exception("Failed to write PEM file: " + str(e))
        return None

def load_private_key(path):
    with open(path, "rb") as f:
        data = f.read()
    try:
        key = serialization.load_pem_private_key(data, password=None, backend=default_backend())
        logger.info("Private key loaded OK.")
        return key
    except Exception as e:
        logger.exception("Could not deserialize PEM private key: " + str(e))
        raise

def build_jwt(private_key, org_id, kid):
    iat = int(time.time())
    payload = {"sub": org_id, "iat": iat, "exp": iat + 300}
    headers = {"kid": kid} if kid else {}
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
    return token

def test_coinbase(token):
    headers = {"Authorization": f"Bearer {token}", "CB-VERSION": os.environ.get("CB_API_VERSION", "2025-01-01")}
    try:
        resp = requests.get("https://api.coinbase.com/v2/accounts", headers=headers, timeout=12)
        return resp
    except Exception as e:
        logger.exception("Coinbase request failed: " + str(e))
        return None

def startup_test():
    logger.info("=== Nija Coinbase JWT startup test ===")
    pem_path = os.environ.get("COINBASE_PEM_PATH") or write_pem_from_env()
    org_id = os.environ.get("COINBASE_ORG_ID")
    kid = os.environ.get("COINBASE_JWT_KID")

    logger.info(f"PEM_PATH: {pem_path}")
    logger.info(f"ORG_ID : {org_id}")
    logger.info(f"KID    : {kid}")
    logger.info("Server UTC time: " + datetime.datetime.utcnow().isoformat())

    if not pem_path or not org_id:
        logger.error("Missing PEM_PATH or ORG_ID; cannot proceed with JWT generation.")
        return

    try:
        key = load_private_key(pem_path)
    except Exception:
        logger.error("Private key load failed; see above for error details.")
        return

    token = build_jwt(key, org_id, kid)
    logger.info("Generated JWT (preview): " + (token[:200] if token else ""))
    try:
        unverified_header = jwt.get_unverified_header(token)
        unverified_payload = jwt.decode(token, options={"verify_signature": False})
        logger.info("JWT header (unverified): " + str(unverified_header))
        logger.info("JWT payload (unverified): " + str(unverified_payload))
    except Exception as e:
        logger.warning("Failed to decode JWT locally: " + str(e))

    resp = test_coinbase(token)
    if resp is None:
        logger.error("No response from Coinbase (exception).")
        return
    logger.info(f"Coinbase test response: {resp.status_code}")
    logger.info("Coinbase response text (truncated 2000 chars):\n" + (resp.text[:2000] if resp.text else ""))

startup_test()

def get_coinbase_headers():
    pem_path = os.environ.get("COINBASE_PEM_PATH") or PEM_FILE_PATH
    org_id = os.environ.get("COINBASE_ORG_ID")
    kid = os.environ.get("COINBASE_JWT_KID")
    key = load_private_key(pem_path)
    token = build_jwt(key, org_id, kid)
    return {"Authorization": f"Bearer {token}", "CB-VERSION": os.environ.get("CB_API_VERSION", "2025-01-01")}
