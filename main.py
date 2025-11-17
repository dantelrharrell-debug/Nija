# main.py
import os
import time
import logging
import requests
import datetime

# Optional crypto/jwt imports for Coinbase Advanced (JWT) flow
try:
    import jwt as pyjwt
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.backends import default_backend
    HAS_JWT_LIBS = True
except Exception:
    HAS_JWT_LIBS = False

# -----------------------
# Config (env-driven)
# -----------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
RETRY_DELAY = int(os.getenv("CB_RETRY_DELAY", "5"))        # seconds between attempts
MAX_RETRIES = os.getenv("CB_MAX_RETRIES", "0")             # 0 = infinite retries
ALLOW_UNSAFE_LIVE = os.getenv("ALLOW_UNSAFE_LIVE", "false").lower() in ("1","true","yes")

COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")  # the kid / key id
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")       # fallback/simple header option
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")  # full PEM, possibly with \n escaped

# -----------------------
# Logging
# -----------------------
logging.basicConfig(level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("nija")

# -----------------------
# Helpers
# -----------------------
def get_outbound_ip():
    try:
        r = requests.get("https://api.ipify.org?format=json", timeout=5)
        ip = r.json().get("ip")
        logger.info("⚡ Current outbound IP on this run: %s", ip)
        return ip
    except Exception as e:
        logger.warning("Unable to detect outbound IP: %s", e)
        return None

def normalize_pem(raw: str):
    if not raw:
        return None
    pem = raw.strip()
    # support escaped newlines
    if "\\n" in pem and "\n" not in pem:
        pem = pem.replace("\\n", "\n")
    # ensure header/footer are preserved
    return pem

# -----------------------
# Coinbase Advanced JWT generation (if PEM available)
# -----------------------
def load_private_key_from_env():
    if not HAS_JWT_LIBS:
        logger.warning("PyJWT / cryptography not installed; cannot use JWT flow.")
        return None
    raw = COINBASE_PEM_CONTENT
    if not raw:
        return None
    pem = normalize_pem(raw)
    try:
        key_obj = serialization.load_pem_private_key(pem.encode("utf-8"), password=None, backend=default_backend())
        logger.info("Private key loaded successfully.")
        return key_obj
    except Exception as e:
        logger.error("Failed to parse PEM private key: %s", e)
        return None

def generate_jwt_for_path(key_obj, kid: str, sub: str, path: str, method: str="GET"):
    """
    Returns a JWT string or None on failure. Expects key_obj from cryptography.
    """
    try:
        iat = int(time.time())
        payload = {
            "iat": iat,
            "exp": iat + 120,
            "sub": sub,
            "request_path": path,
            "method": method.upper(),
            "jti": f"nija-{iat}"
        }
        headers = {"alg": "ES256", "kid": kid, "typ": "JWT"}
        token = pyjwt.encode(payload, key_obj, algorithm="ES256", headers=headers)
        logger.debug("JWT generated: path=%s method=%s iat=%s exp=%s", path, method, iat, iat+120)
        return token
    except Exception as e:
        logger.exception("Failed to generate JWT: %s", e)
        return None

# -----------------------
# Check key permissions
# -----------------------
def call_key_permissions_with_jwt(key_obj, kid, org_id):
    path = f"/api/v3/brokerage/organizations/{org_id}/key_permissions"
    sub = f"/organizations/{org_id}/apiKeys/{kid}"
    token = generate_jwt_for_path(key_obj, kid, sub, path, method="GET")
    if not token:
        logger.error("Cannot generate JWT for key_permissions call.")
        return None, None
    url = "https://api.coinbase.com" + path
    headers = {
        "Authorization": f"Bearer {token}",
        "CB-VERSION": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
        "Content-Type": "application/json"
    }
    try:
        r = requests.get(url, headers=headers, timeout=10)
        return r.status_code, r
    except Exception as e:
        logger.error("Exception calling Coinbase key_permissions: %s", e)
        return None, None

def call_key_permissions_with_header(api_key, org_id):
    path = f"/api/v3/brokerage/organizations/{org_id}/key_permissions"
    url = "https://api.coinbase.com" + path
    headers = {
        "CB-ACCESS-KEY": api_key,
        "CB-VERSION": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
        "Content-Type": "application/json"
    }
    try:
        r = requests.get(url, headers=headers, timeout=10)
        return r.status_code, r
    except Exception as e:
        logger.error("Exception calling Coinbase key_permissions (header): %s", e)
        return None, None

def check_coinbase_permissions():
    """
    Tries JWT flow first (if PEM + API_KEY_ID present), otherwise fallback to header flow.
    Returns True if permissions verified (200), False otherwise.
    """
    ip = get_outbound_ip()

    # Try JWT path if we have the pieces
    key_obj = None
    if COINBASE_PEM_CONTENT and COINBASE_API_KEY_ID and COINBASE_ORG_ID and HAS_JWT_LIBS:
        key_obj = load_private_key_from_env()
        if key_obj:
            status, resp = call_key_permissions_with_jwt(key_obj, COINBASE_API_KEY_ID, COINBASE_ORG_ID)
            if status == 200:
                logger.info("✅ Coinbase Advanced JWT key_permissions OK.")
                return True
            elif status == 401:
                logger.error("❌ 401 Unauthorized (JWT). Check PEM, ORG_ID, API_KEY_ID, and IP whitelist.")
                if ip: logger.error("Detected outbound IP to whitelist: %s", ip)
                logger.debug("Coinbase response: %s", getattr(resp, "text", None))
                return False
            else:
                logger.error("Coinbase returned status: %s (JWT). Body: %s", status, getattr(resp, "text", None))
                return False
        else:
            logger.warning("Could not load private key for JWT; falling back to header flow if possible.")

    # Fallback to header-based check if provided
    if COINBASE_API_KEY and COINBASE_ORG_ID:
        status, resp = call_key_permissions_with_header(COINBASE_API_KEY, COINBASE_ORG_ID)
        if status == 200:
            logger.info("✅ Coinbase key_permissions OK (header fallback).")
            return True
        elif status == 401:
            logger.error("❌ 401 Unauthorized (header). Check API_KEY, ORG_ID and IP whitelist.")
            if ip: logger.error("Detected outbound IP to whitelist: %s", ip)
            logger.debug("Coinbase response: %s", getattr(resp, "text", None))
            return False
        else:
            logger.error("Coinbase returned status: %s (header). Body: %s", status, getattr(resp, "text", None))
            return False

    # Nothing usable to check
    logger.error("No valid Coinbase credentials found in environment to perform permission check.")
    return False

# -----------------------
# Live trading starter
# -----------------------
def start_trading():
    logger.info("🚀 Starting LIVE trading now.")
    try:
        from bot_live import execute_trades
    except Exception as e:
        logger.exception("Could not import bot_live.execute_trades(): %s", e)
        return

    try:
        execute_trades()
    except Exception as e:
        logger.exception("Exception during execute_trades(): %s", e)

# -----------------------
# Bootstrap / main loop
# -----------------------
def main():
    logger.info("🔥 Nija Trading Bot bootstrap starting...")
    logger.info("Config: ALLOW_UNSAFE_LIVE=%s, MAX_RETRIES=%s, RETRY_DELAY=%ss",
                ALLOW_UNSAFE_LIVE, MAX_RETRIES, RETRY_DELAY)

    # Quick env sanity
    if not (COINBASE_ORG_ID and (COINBASE_PEM_CONTENT and COINBASE_API_KEY_ID or COINBASE_API_KEY)):
        logger.warning("Warning: Coinbase env vars incomplete. Ensure COINBASE_ORG_ID + (COINBASE_PEM_CONTENT & COINBASE_API_KEY_ID) or COINBASE_API_KEY are set.")

    # If override requested, skip checks (unsafe)
    if ALLOW_UNSAFE_LIVE:
        logger.warning("ALLOW_UNSAFE_LIVE is enabled — skipping Coinbase permission checks. Starting live trading UNSAFE.")
        start_trading()
        return

    attempts = 0
    max_retries = int(MAX_RETRIES) if str(MAX_RETRIES).isdigit() else 0

    while True:
        attempts += 1
        logger.info("Checking Coinbase API permissions (attempt %d)...", attempts)
        ok = check_coinbase_permissions()
        if ok:
            logger.info("Coinbase permissions validated. Launching live trading.")
            start_trading()
            break
        else:
            logger.error("Coinbase permission check failed (attempt %d).", attempts)
            if max_retries > 0 and attempts >= max_retries:
                logger.error("Reached max retries (%d). Exiting.", max_retries)
                break
            logger.info("Will retry in %s seconds. Make sure to whitelist the outbound IP shown earlier.", RETRY_DELAY)
            time.sleep(RETRY_DELAY)

if __name__ == "__main__":
    main()
