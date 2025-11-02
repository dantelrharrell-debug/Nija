# nija_balance_helper.py
import os
import base64
import logging
from decimal import Decimal
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# --- logger (module-level; don't call basicConfig in many places) ---
logger = logging.getLogger("nija_balance_helper")
if not logger.handlers:
    # only set an ephemeral handler if none exist (avoid duplicate logs)
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(ch)
logger.setLevel(logging.INFO)

# --- PEM config ---
PEM_PATH = os.getenv("COINBASE_API_SECRET_PATH", "/opt/render/project/secrets/coinbase.pem")
PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")   # optional: actual PEM with real newlines
PEM_B64 = os.getenv("COINBASE_PEM_B64")           # optional: base64-encoded PEM

def _try_load_pem_bytes(b: bytes):
    """Return (True, None) if load succeeds, (False, err_str) otherwise."""
    try:
        serialization.load_pem_private_key(b, password=None, backend=default_backend())
        return True, None
    except Exception as e:
        return False, str(e)

# --- 1) Try PEM at path (preferred) ---
if PEM_PATH and os.path.exists(PEM_PATH):
    try:
        with open(PEM_PATH, "rb") as f:
            b = f.read()
        ok, err = _try_load_pem_bytes(b)
        logger.info("PEM path exists: %s, load_ok=%s", PEM_PATH, ok)
        if not ok:
            # don't log key contents — only metadata and helpful hints
            s = b.decode(errors="replace")
            middle = "".join(line for line in s.splitlines() if not line.strip().startswith("-----"))
            logger.error("PEM at path failed to load: %s", err)
            logger.info("Base64 chars (path, excluding headers): %d", len(middle))
            if len(middle) % 4 != 0:
                logger.error("Base64 length not divisible by 4 — PEM may be truncated or missing padding '=' at end.")
            if "..." in s:
                logger.error("PEM contains '...' placeholder — key truncated.")
            if "\\n" in s:
                logger.error("PEM contains literal backslash-n sequences (escaped newlines). Use real newlines.")
    except Exception as e:
        logger.error("Error reading PEM path %s: %s", PEM_PATH, e)
else:
    logger.info("PEM path not present: %s", PEM_PATH)

# --- 2) Try raw PEM content from COINBASE_PEM_CONTENT (must contain real newlines) ---
if PEM_CONTENT:
    b = PEM_CONTENT.encode()
    ok, err = _try_load_pem_bytes(b)
    logger.info("PEM from COINBASE_PEM_CONTENT load_ok=%s", ok)
    if not ok:
        logger.error("COINBASE_PEM_CONTENT load failed: %s", err)
        if "\\n" in PEM_CONTENT:
            logger.error("COINBASE_PEM_CONTENT appears to have escaped \\n sequences. Use actual newlines or provide base64 in COINBASE_PEM_B64.")

# --- 3) Try base64-encoded PEM (COINBASE_PEM_B64) ---
if PEM_B64:
    try:
        dec = base64.b64decode(PEM_B64)
        ok, err = _try_load_pem_bytes(dec)
        logger.info("PEM from COINBASE_PEM_B64 load_ok=%s", ok)
        if not ok:
            logger.error("COINBASE_PEM_B64 load failed: %s", err)
    except Exception as e:
        logger.error("COINBASE_PEM_B64 not valid base64: %s", e)

# --- Helper: get USD balance (robust across client shapes) ---
def get_usd_balance(client) -> Decimal:
    """
    Fetch USD balance from a Coinbase client object.
    - client may provide: get_spot_account_balances(), get_account_balances(), get_accounts() etc.
    - Returns Decimal(0) on missing client or failure (so bot won't trade).
    """
    if client is None:
        logger.warning("[NIJA-BALANCE] No client provided to get_usd_balance(), returning 0")
        return Decimal("0")
    try:
        # 1) coinbase_advanced style: get_spot_account_balances -> dict like {"USD": 100.0}
        if hasattr(client, "get_spot_account_balances"):
            try:
                balances = client.get_spot_account_balances()
                usd = balances.get("USD") or balances.get("USDC") or 0
                return Decimal(str(usd))
            except Exception:
                logger.debug("get_spot_account_balances attempt failed, trying other methods")

        # 2) some libs: get_account_balances -> dict
        if hasattr(client, "get_account_balances"):
            try:
                balances = client.get_account_balances()
                usd = balances.get("USD") or balances.get("USDC") or 0
                return Decimal(str(usd))
            except Exception:
                logger.debug("get_account_balances attempt failed, trying other methods")

        # 3) generic: get_accounts() -> may return object with .data or iterable of dicts/objects
        if hasattr(client, "get_accounts"):
            accs = client.get_accounts()
            # handle wrappers that return .data
            items = getattr(accs, "data", accs)
            # iterate
            for a in items:
                if isinstance(a, dict):
                    currency = a.get("currency") or a.get("currency_code")
                    # different shapes: available_balance, balance, available
                    amt = a.get("available_balance") or (a.get("balance") or {}).get("amount") or a.get("available")
                    if currency and str(currency).upper() in ("USD", "USDC"):
                        return Decimal(str(amt or 0))
                else:
                    # object-like
                    currency = getattr(a, "currency", None)
                    amt = getattr(a, "available_balance", None) or getattr(a, "balance", None)
                    if currency and str(currency).upper() in ("USD", "USDC"):
                        # if balance is object with amount field
                        if hasattr(amt, "get"):
                            amt_val = amt.get("amount") if isinstance(amt, dict) else None
                            if amt_val is not None:
                                return Decimal(str(amt_val))
                        return Decimal(str(amt or 0))

        # Nothing matched
        logger.warning("[NIJA-BALANCE] No recognized account structure found on client; returning 0")
        return Decimal("0")
    except Exception as e:
        logger.exception("[NIJA-BALANCE] Exception while fetching USD balance: %s", e)
        return Decimal("0")
