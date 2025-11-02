# nija_balance_helper.py
import os
import base64
import logging
from decimal import Decimal
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# --- Logging (single place) ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("nija_balance_helper")

# --- Env / config ---
PEM_PATH = os.getenv("COINBASE_API_SECRET_PATH", "/opt/render/project/secrets/coinbase.pem")
PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")   # optional: full PEM with real newlines
PEM_B64 = os.getenv("COINBASE_PEM_B64")           # optional: base64-encoded PEM
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")

# --- Helpers to try loading a PEM from different sources ---
def try_load_bytes(data_bytes: bytes):
    try:
        serialization.load_pem_private_key(data_bytes, password=None, backend=default_backend())
        return True, None
    except Exception as e:
        return False, str(e)

def load_pem_from_path(path: str):
    if not os.path.exists(path):
        logger.debug(f"[NIJA-BALANCE] PEM path does not exist: {path}")
        return None
    try:
        with open(path, "rb") as f:
            data = f.read()
        ok, err = try_load_bytes(data)
        if ok:
            return data  # raw bytes; you can pass to library if needed
        logger.error("[NIJA-BALANCE] PEM at path failed to load: %s", err)
        # non-secret diagnostics:
        s = data.decode(errors="replace")
        if "\\n" in s:
            logger.error("[NIJA-BALANCE] PEM appears to include literal backslash-n (escaped). Use real newlines (Secret File).")
        if "..." in s:
            logger.error("[NIJA-BALANCE] PEM contains '...' placeholder — key truncated.")
        stripped = "".join(line for line in s.splitlines() if not line.startswith("-----"))
        logger.info("[NIJA-BALANCE] Base64 chars (path): %d", len(stripped))
        if len(stripped) % 4 != 0:
            logger.error("[NIJA-BALANCE] Base64 length not divisible by 4 — PEM likely truncated or missing padding '='.")
        return None
    except Exception as e:
        logger.error("[NIJA-BALANCE] Error reading PEM path: %s", e)
        return None

def load_pem_from_raw(pem_str: str):
    try:
        data = pem_str.encode()
        ok, err = try_load_bytes(data)
        if ok:
            return data
        logger.error("[NIJA-BALANCE] PEM from COINBASE_PEM_CONTENT failed: %s", err)
        return None
    except Exception as e:
        logger.error("[NIJA-BALANCE] Error processing COINBASE_PEM_CONTENT: %s", e)
        return None

def load_pem_from_b64(b64_str: str):
    try:
        data = base64.b64decode(b64_str)
    except Exception as e:
        logger.error("[NIJA-BALANCE] COINBASE_PEM_B64 is not valid base64: %s", e)
        return None
    ok, err = try_load_bytes(data)
    if ok:
        return data
    logger.error("[NIJA-BALANCE] PEM from COINBASE_PEM_B64 failed: %s", err)
    return None

# --- Try sources in order of preference ---
private_key_bytes = None

logger.info("[NIJA-BALANCE] Diagnostic: trying to load PEM/key from available sources")
if PEM_PATH:
    logger.info(f"[NIJA-BALANCE] Trying PEM path: {PEM_PATH}")
    private_key_bytes = load_pem_from_path(PEM_PATH)

if private_key_bytes is None and PEM_CONTENT:
    logger.info("[NIJA-BALANCE] Trying PEM from COINBASE_PEM_CONTENT env var")
    private_key_bytes = load_pem_from_raw(PEM_CONTENT)

if private_key_bytes is None and PEM_B64:
    logger.info("[NIJA-BALANCE] Trying PEM from COINBASE_PEM_B64 env var (base64)")
    private_key_bytes = load_pem_from_b64(PEM_B64)

if private_key_bytes:
    logger.info("[NIJA-BALANCE] PEM loaded successfully (bytes available)")
else:
    logger.warning("[NIJA-BALANCE] No valid PEM loaded. Coinbase client may fall back to simulated mode or balance fetch may fail.")

# --- Coinbase REST client helper (local import) ---
def get_rest_client():
    try:
        from coinbase.rest import RESTClient
    except Exception:
        logger.debug("[NIJA-BALANCE] coinbase.rest library not available in this environment")
        return None

    if not API_KEY or not API_SECRET:
        logger.warning("[NIJA-BALANCE] Missing API key/secret in env")
        return None

    try:
        # NOTE: some client libs accept a private key path or bytes; consult the lib docs.
        client = RESTClient(api_key=API_KEY, api_secret=API_SECRET)
        logger.info("[NIJA-BALANCE] Coinbase RESTClient initialized (credentials present)")
        return client
    except Exception as e:
        logger.error("[NIJA-BALANCE] Failed to init RESTClient: %s", e)
        return None

def get_usd_balance():
    client = get_rest_client()
    if not client:
        logger.warning("[NIJA-BALANCE] No client available, returning Decimal(0)")
        return Decimal(0)
    try:
        accounts = client.get_accounts()
        for acct in accounts.data:
            if acct.get("currency") == "USD":
                bal = Decimal(str(acct["balance"]["amount"]))
                logger.info("[NIJA-BALANCE] USD Balance fetched: %s", bal)
                return bal
        logger.warning("[NIJA-BALANCE] No USD account found, returning 0")
        return Decimal(0)
    except Exception as e:
        logger.error("[NIJA-BALANCE] Error fetching USD balance: %s", e)
        return Decimal(0)
