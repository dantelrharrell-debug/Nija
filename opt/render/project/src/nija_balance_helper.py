# nija_balance_helper.py
"""
Load Coinbase private key (PEM or DER) from:
  1) file at COINBASE_API_SECRET_PATH (preferred)
  2) COINBASE_PEM_CONTENT (the full PEM text; must include headers AND real newlines)
  3) COINBASE_PEM_B64 (base64 of a PEM or DER blob)
This module attempts multiple safe load strategies and logs detailed diagnostics.
It exposes get_rest_client() and get_usd_balance() helpers (example).
"""

import os
import logging
import base64
import textwrap
from decimal import Decimal

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_balance_helper")

# Config / env
PEM_PATH = os.getenv("COINBASE_API_SECRET_PATH", "/opt/render/project/secrets/coinbase.pem")
PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")   # full PEM as text (with real newlines)
PEM_B64 = os.getenv("COINBASE_PEM_B64")           # base64 of PEM or DER
# Note: COINBASE_API_SECRET (API secret) and COINBASE_API_KEY still required by Coinbase client.

private_key = None  # cryptography key object (if loaded)


def _try_load_pem_bytes(pem_bytes):
    """Try to load PEM bytes (with headers). Return key or raise."""
    return serialization.load_pem_private_key(pem_bytes, password=None, backend=default_backend())


def _try_load_der_bytes(der_bytes):
    """Try to load DER bytes (binary). Return key or raise."""
    return serialization.load_der_private_key(der_bytes, password=None, backend=default_backend())


def _wrap_and_chunk_der_to_pem(der_bytes, header="PRIVATE KEY"):
    """
    If we have raw DER bytes, wrap them into a PEM-like text.
    Useful when user provided raw base64 body without headers.
    """
    b64 = base64.b64encode(der_bytes).decode("ascii")
    # chunk into 64-char lines
    lines = textwrap.wrap(b64, 64)
    pem = "-----BEGIN {}-----\n".format(header)
    pem += "\n".join(lines)
    pem += "\n-----END {}-----\n".format(header)
    return pem.encode("utf-8")


def try_load_from_path(path: str):
    global private_key
    if not path:
        return None
    try:
        if not os.path.exists(path):
            logger.info(f"[NIJA-BALANCE] PEM path not found: {path}")
            return None
        with open(path, "rb") as f:
            data = f.read()
        # try PEM first
        try:
            key = _try_load_pem_bytes(data)
            logger.info("[NIJA-BALANCE] Loaded private key from PEM file path.")
            return key
        except Exception as e_pem:
            logger.debug(f"[NIJA-BALANCE] load_pem from path failed: {e_pem!r}")
        # try DER
        try:
            key = _try_load_der_bytes(data)
            logger.info("[NIJA-BALANCE] Loaded private key from DER file path.")
            return key
        except Exception as e_der:
            logger.debug(f"[NIJA-BALANCE] load_der from path failed: {e_der!r}")
            # try wrapping DER to PEM and load
            try:
                pem = _wrap_and_chunk_der_to_pem(data)
                key = _try_load_pem_bytes(pem)
                logger.info("[NIJA-BALANCE] Loaded private key after wrapping DER->PEM (path).")
                return key
            except Exception as e_wrap:
                logger.debug(f"[NIJA-BALANCE] wrap&load failed: {e_wrap!r}")
                logger.error("[NIJA-BALANCE] Failed to load key from file path (not valid PEM/DER).")
                return None
    except Exception as exc:
        logger.exception("[NIJA-BALANCE] Unexpected error while reading PEM path: %s", exc)
        return None


def try_load_from_pem_content(pem_content: str):
    """Try to load when env var contains full PEM or a headerless base64 body."""
    if not pem_content:
        return None
    try:
        b = pem_content.encode("utf-8")
        # If content already looks like PEM (contains BEGIN/END), try direct PEM load
        if b"-----BEGIN" in b and b"-----END" in b:
            try:
                key = _try_load_pem_bytes(b)
                logger.info("[NIJA-BALANCE] Loaded private key from COINBASE_PEM_CONTENT (PEM).")
                return key
            except Exception as e:
                logger.debug(f"[NIJA-BALANCE] load_pem from COINBASE_PEM_CONTENT failed: {e!r}")
        # If it looks like base64 (single-line) attempt base64 decode and try DER
        stripped = "".join(pem_content.split())  # remove whitespace/newlines
        # Heuristic: base64 characters only?
        if all(c.isalnum() or c in "+/=" for c in stripped):
            try:
                der = base64.b64decode(stripped)
                try:
                    key = _try_load_der_bytes(der)
                    logger.info("[NIJA-BALANCE] Loaded private key from COINBASE_PEM_CONTENT (base64 -> DER).")
                    return key
                except Exception as e_der:
                    logger.debug(f"[NIJA-BALANCE] load_der from decoded COINBASE_PEM_CONTENT failed: {e_der!r}")
                    # try wrap into PEM and load
                    try:
                        pem = _wrap_and_chunk_der_to_pem(der)
                        key = _try_load_pem_bytes(pem)
                        logger.info("[NIJA-BALANCE] Loaded private key from COINBASE_PEM_CONTENT after wrapping to PEM.")
                        return key
                    except Exception as e_wrap:
                        logger.debug(f"[NIJA-BALANCE] wrap&load failed: {e_wrap!r}")
            except Exception as b64err:
                logger.debug(f"[NIJA-BALANCE] COINBASE_PEM_CONTENT base64 decode failed: {b64err!r}")
        # final attempt: try pem bytes as-is
        try:
            key = _try_load_pem_bytes(b)
            logger.info("[NIJA-BALANCE] Loaded private key from COINBASE_PEM_CONTENT (final PEM attempt).")
            return key
        except Exception as final_err:
            logger.debug(f"[NIJA-BALANCE] final PEM attempt failed: {final_err!r}")
            logger.error("[NIJA-BALANCE] COINBASE_PEM_CONTENT present but couldn't be parsed as PEM/DER.")
            return None
    except Exception as exc:
        logger.exception("[NIJA-BALANCE] Unexpected error while parsing COINBASE_PEM_CONTENT: %s", exc)
        return None


def try_load_from_b64(b64_str: str):
    if not b64_str:
        return None
    try:
        raw = base64.b64decode(b64_str)
        # try DER
        try:
            key = _try_load_der_bytes(raw)
            logger.info("[NIJA-BALANCE] Loaded private key from COINBASE_PEM_B64 (DER).")
            return key
        except Exception as e_der:
            logger.debug(f"[NIJA-BALANCE] load_der from COINBASE_PEM_B64 failed: {e_der!r}")
        # try wrap into PEM and load
        try:
            pem = _wrap_and_chunk_der_to_pem(raw)
            key = _try_load_pem_bytes(pem)
            logger.info("[NIJA-BALANCE] Loaded private key from COINBASE_PEM_B64 after wrapping DER->PEM.")
            return key
        except Exception as e_wrap:
            logger.debug(f"[NIJA-BALANCE] wrap&load from COINBASE_PEM_B64 failed: {e_wrap!r}")
            logger.error("[NIJA-BALANCE] COINBASE_PEM_B64 present but could not be parsed as DER/PEM.")
            return None
    except Exception as exc:
        logger.error("[NIJA-BALANCE] COINBASE_PEM_B64 is not valid base64 or failed to decode: %s", exc)
        return None


# Try sources in preferred order
logger.info("[NIJA-BALANCE] Diagnostic: trying to load key from available sources")

# 1) from file path
private_key = try_load_from_path(PEM_PATH)

# 2) from COINBASE_PEM_CONTENT (env)
if private_key is None and PEM_CONTENT:
    logger.info("[NIJA-BALANCE] Trying COINBASE_PEM_CONTENT (env var).")
    private_key = try_load_from_pem_content(PEM_CONTENT)

# 3) from COINBASE_PEM_B64 (env)
if private_key is None and PEM_B64:
    logger.info("[NIJA-BALANCE] Trying COINBASE_PEM_B64 (base64 env var).")
    private_key = try_load_from_b64(PEM_B64)

if private_key:
    logger.info("[NIJA-BALANCE] PEM/DER loaded successfully ✅")
else:
    logger.warning("[NIJA-BALANCE] No valid PEM/DER loaded. Coinbase balance fetch may fail or fallback to simulated mode.")


# --- Example: small REST client helper (wrap coinbase.rest) ---
def get_rest_client():
    """
    Lazily initialize coinbase REST client; returns None if API_KEY/API_SECRET missing.
    The coinbase client may also require the private key; if not loaded the client might still work
    in JWT mode if the library supports passing API_SECRET directly.
    """
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    if not api_key or not api_secret:
        logger.warning("[NIJA-BALANCE] Missing API key/secret in environment")
        return None
    try:
        # Local import to avoid import-time errors if coinbase library not present in some envs
        from coinbase.rest import RESTClient
        client = RESTClient(api_key=api_key, api_secret=api_secret)
        logger.info("[NIJA-BALANCE] Coinbase RESTClient initialized (credentials present)")
        return client
    except Exception as e:
        logger.exception("[NIJA-BALANCE] Failed to initialize Coinbase RESTClient: %s", e)
        return None


def get_usd_balance():
    """
    Fetch USD balance using available client helpers.
    Returns Decimal('0') on error.
    """
    client = get_rest_client()
    if not client:
        return Decimal('0')
    try:
        accounts = client.get_accounts()
        # account objects vary by client; attempt robust extraction
        for acct in getattr(accounts, "data", accounts) or []:
            # acct might be dict-like or object-like
            if isinstance(acct, dict):
                curr = acct.get("currency")
                balance_amount = acct.get("balance", {}).get("amount") if acct.get("balance") else acct.get("available")
            else:
                curr = getattr(acct, "currency", None)
                # prefer available_balance or balance
                balance_amount = getattr(acct, "available_balance", None) or getattr(acct, "balance", None)
                if hasattr(balance_amount, "get"):
                    balance_amount = balance_amount.get("amount")
            if str(curr).upper() in ("USD", "USDC"):
                try:
                    return Decimal(str(balance_amount or "0"))
                except Exception:
                    logger.debug("[NIJA-BALANCE] Could not parse balance amount: %s", balance_amount)
        logger.warning("[NIJA-BALANCE] No USD account found, returning 0")
    except Exception as e:
        logger.exception("[NIJA-BALANCE] Error fetching USD balance: %s", e)
    return Decimal("0")
