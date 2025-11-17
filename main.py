#!/usr/bin/env python3
"""
main.py - Coinbase Advanced (CDP) validator + auto-fallback

Usage:
 - Set env vars: COINBASE_ORG_ID, COINBASE_API_KEY_ID, COINBASE_PEM_CONTENT
 - Optional fallback: COINBASE_FALLBACK_ORG_ID, COINBASE_FALLBACK_API_KEY_ID, COINBASE_FALLBACK_PEM_CONTENT
 - Run container / python main.py
"""

import os
import time
import logging
import json
import base64
import requests
import jwt  # PyJWT
from typing import Optional, Tuple
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("nija-coinbase-check")

COINBASE_BASE_URL = os.environ.get("COINBASE_BASE_URL", "https://api.coinbase.com")

# --- env (primary + fallback) ---
PRIMARY_ORG = os.environ.get("COINBASE_ORG_ID")
PRIMARY_KID = os.environ.get("COINBASE_API_KEY_ID")
PRIMARY_PEM_RAW = os.environ.get("COINBASE_PEM_CONTENT")

FALLBACK_ORG = os.environ.get("COINBASE_FALLBACK_ORG_ID")
FALLBACK_KID = os.environ.get("COINBASE_FALLBACK_API_KEY_ID")
FALLBACK_PEM_RAW = os.environ.get("COINBASE_FALLBACK_PEM_CONTENT")

# ----------------------------------------
# PEM normalization and load helpers
# ----------------------------------------
def safe_strip_quotes(s: str) -> str:
    if not s:
        return s
    s = s.strip()
    if (s.startswith("'") and s.endswith("'")) or (s.startswith('"') and s.endswith('"')):
        s = s[1:-1]
    return s.strip()

def normalize_pem(raw: Optional[str]) -> Optional[str]:
    """Try a few heuristics to get a valid PEM string."""
    if not raw:
        return None
    s = safe_strip_quotes(raw)

    # If it's the PEM already with escaped newline sequences, convert them
    if "\\n" in s and "\n" not in s:
        s = s.replace("\\n", "\n")

    # If entire PEM is base64 (no header/footer) -> attempt to detect and rebuild full PEM
    # Typical base64 body will be long, contain +/ and =, and not contain 'BEGIN' text.
    short = s.strip()
    if ("BEGIN" not in short and "END" not in short) and len(short) > 100 and all(ch not in short for ch in ("\n", " ")) and ("=" in short or "/" in short or "+" in short):
        # assume this is the inner base64 body; wrap with header/footer
        log.info("normalize_pem: detected possible base64-only key; wrapping with header/footer")
        wrapped = "-----BEGIN EC PRIVATE KEY-----\n"
        # break into 64 char lines
        for i in range(0, len(short), 64):
            wrapped += short[i:i+64] + "\n"
        wrapped += "-----END EC PRIVATE KEY-----\n"
        return wrapped

    # If it looks like a PEM but header/footer are present in same-line -> ensure newline formatting
    if "BEGIN" in s and "END" in s and ("\\n" in raw or "\\r" in raw):
        s = s.replace("\\r", "").replace("\\n", "\n")

    # Ensure correct line endings and no stray characters
    lines = [ln.rstrip() for ln in s.splitlines() if ln.strip() != ""]
    if not lines:
        return None
    # If header/footer missing but there are base64-like lines, attempt to reconstruct
    if not any("BEGIN" in ln for ln in lines) or not any("END" in ln for ln in lines):
        # attempt to locate base64 block inside
        joined = "".join(lines)
        if len(joined) > 100 and ("=" in joined or "/" in joined or "+" in joined):
            log.info("normalize_pem: reconstructing PEM from base64 block present")
            body = joined
            wrapped = "-----BEGIN EC PRIVATE KEY-----\n"
            for i in range(0, len(body), 64):
                wrapped += body[i:i+64] + "\n"
            wrapped += "-----END EC PRIVATE KEY-----\n"
            return wrapped
        # otherwise return raw joined as-is
        s = "\n".join(lines) + "\n"
        return s

    # Otherwise, re-join normalized lines to a PEM
    normalized = "\n".join(lines) + ("\n" if not lines[-1].endswith("\n") else "")
    return normalized

def load_private_key_from_pem(pem_text: str):
    """Attempt to load PEM into cryptography key object. Returns None on failure with logged reason."""
    try:
        key_obj = serialization.load_pem_private_key(pem_text.encode("utf-8"), password=None, backend=default_backend())
        log.info("Private key loaded successfully.")
        return key_obj
    except Exception as e:
        log.error("Unable to load PEM file. See https://cryptography.io/en/latest/faq/#why-can-t-i-import-my-pem-file for details. %s", e)
        # Try base64 decode attempt if the input may be base64 of UTF-8 PEM
        try:
            # if pem_text is itself base64 of a PEM, decode and try again
            maybe_b64 = pem_text.strip()
            # strip header/footer if accidentally included
            if maybe_b64.startswith("-----BEGIN"):
                # already tried, give up
                return None
            decoded = base64.b64decode(maybe_b64 + "===")  # padding tolerant
            decoded_text = decoded.decode("utf-8", errors="ignore")
            if "BEGIN" in decoded_text:
                log.info("load_private_key_from_pem: base64-decoded to a PEM-looking value, trying to load that.")
                try:
                    return serialization.load_pem_private_key(decoded_text.encode("utf-8"), password=None, backend=default_backend())
                except Exception:
                    return None
        except Exception:
            pass
        return None

# ----------------------------------------
# JWT generation + test helpers
# ----------------------------------------
def generate_jwt_for_key(org: str, kid: str, key_obj, method: str = "GET", request_path: Optional[str] = None) -> str:
    iat = int(time.time())
    if not request_path:
        request_path = f"/api/v3/brokerage/organizations/{org}/key_permissions"
    payload = {
        "iat": iat,
        "exp": iat + 120,
        "sub": f"/organizations/{org}/apiKeys/{kid}",
        "request_path": request_path,
        "method": method.upper(),
        "jti": f"nija-{iat}"
    }
    headers = {"alg": "ES256", "kid": kid, "typ": "JWT"}
    token = jwt.encode(payload, key_obj, algorithm="ES256", headers=headers)
    return token, payload, headers

def call_key_permissions_with_token(token: str) -> Tuple[Optional[int], Optional[str], Optional[requests.Response]]:
    url = f"{COINBASE_BASE_URL}/api/v3/brokerage/organizations/{PRIMARY_ORG}/key_permissions"
    try:
        r = requests.get(url, headers={
            "Authorization": f"Bearer {token}",
            "CB-VERSION": time.strftime("%Y-%m-%d")
        }, timeout=10)
        return r.status_code, r.text, r
    except Exception as e:
        log.error("HTTP call failed: %s", e)
        return None, str(e), None

def inspect_token_unverified(token: str):
    try:
        decoded = jwt.decode(token, options={"verify_signature": False})
    except Exception:
        decoded = None
    try:
        header = jwt.get_unverified_header(token)
    except Exception:
        header = None
    return header, decoded

# ----------------------------------------
# High-level test flow
# ----------------------------------------
def detect_outbound_ip() -> Optional[str]:
    # Use ipify (fast). If fails, return None.
    try:
        r = requests.get("https://api.ipify.org?format=json", timeout=5)
        ip = r.json().get("ip")
        if ip:
            log.info("⚡ Current outbound IP on this run: %s (via ipify)", ip)
            log.info("--- Coinbase Advanced Whitelist line (paste this exact IP) ---")
            log.info(ip)
            log.info("---------------------------------------------------------------")
            return ip
    except Exception as e:
        log.warning("Could not detect outbound IP via ipify: %s", e)
    return None

def test_single_key(org: str, kid: str, pem_raw: Optional[str]) -> Tuple[bool, dict]:
    """Return (ok, details). If ok==False, details contains debug info."""
    details = {"org": org, "kid": kid}
    if not org or not kid or not pem_raw:
        details["error"] = "Missing env: ORG/KID/PEM"
        log.warning("test_single_key: missing variables for org/kid/pem")
        return False, details

    pem_norm = normalize_pem(pem_raw)
    if not pem_norm:
        details["error"] = "PEM empty after normalization"
        log.error("PEM empty after normalization")
        return False, details

    details["pem_preview"] = (pem_norm[:200] + "...") if len(pem_norm) > 200 else pem_norm
    key_obj = load_private_key_from_pem(pem_norm)
    if not key_obj:
        details["error"] = "Unable to parse PEM into a private key object"
        return False, details

    token, payload, headers = generate_jwt_for_key(org, kid, key_obj)
    details["jwt_payload_preview"] = payload
    details["jwt_headers_preview"] = headers

    # optional: print the first 200 chars of token for debugging
    details["jwt_preview"] = (str(token)[:200] + "...") if token else None

    # try call
    url = f"{COINBASE_BASE_URL}/api/v3/brokerage/organizations/{org}/key_permissions"
    try:
        r = requests.get(url, headers={"Authorization": f"Bearer {token}", "CB-VERSION": time.strftime("%Y-%m-%d")}, timeout=8)
        details["http_status"] = r.status_code
        details["http_text_preview"] = r.text[:1000] if r.text else ""
        if r.status_code == 200:
            details["ok"] = True
            log.info("✅ Key valid: org=%s kid=%s", org, kid)
            return True, details
        else:
            log.warning("❌ [%s] for org=%s kid=%s", r.status_code, org, kid)
            details["ok"] = False
            return False, details
    except Exception as e:
        details["error"] = f"HTTP request error: {e}"
        log.error("HTTP request error: %s", e)
        return False, details

def print_fix_instructions(primary_ok: bool, primary_details: dict, fallback_present: bool):
    log.error("❌ Coinbase key validation failed. Fix the following:")
    # Whitelist hint printed earlier - print again if available
    ip = detect_outbound_ip()
    if ip:
        log.error("1) Whitelist the container outbound IP in Coinbase Advanced (edit the API key and add this IP):\n   %s", ip)
    log.error("2) Ensure these env vars match your Coinbase Advanced API key (copy/paste into Railway/Render):")
    log.error("export COINBASE_ORG_ID=%s", PRIMARY_ORG or "<ORG_ID>")
    log.error("export COINBASE_API_KEY_ID=%s", PRIMARY_KID or "<KID>")
    log.error("export COINBASE_PEM_CONTENT='(paste full PEM as MULTILINE value including header/footer)'")
    log.error("")
    log.error("If you cannot whitelist dynamic container IPs, create a new Advanced API key with NO IP restrictions and set it as fallback by adding:")
    log.error("export COINBASE_FALLBACK_ORG_ID=<ORG_OF_FALLBACK_KEY>")
    log.error("export COINBASE_FALLBACK_API_KEY_ID=<KID_OF_FALLBACK_KEY>")
    log.error("export COINBASE_FALLBACK_PEM_CONTENT='(paste fallback PEM here)'")
    log.error("Then restart the container.")
    # Helpful debugging details
    log.error("Primary details (short): %s", json.dumps({k: primary_details.get(k) for k in ("org","kid","http_status","error") if primary_details.get(k) is not None}, indent=2))

# ----------------------------------------
# Run main flow
# ----------------------------------------
def main():
    log.info("🔥 Nija Trading Bot bootstrap starting...")
    outbound_ip = detect_outbound_ip()

    # Test primary
    log.info("Checking primary key: org=%s kid=%s", PRIMARY_ORG, PRIMARY_KID)
    primary_ok, primary_details = test_single_key(PRIMARY_ORG, PRIMARY_KID, PRIMARY_PEM_RAW)

    if primary_ok:
        log.info("🎯 Connected with primary key. You can now proceed to trading setup.")
        return

    log.warning("Primary key validation failed.")
    # If fallback present, try it
    if FALLBACK_ORG and FALLBACK_KID and FALLBACK_PEM_RAW:
        log.info("Trying fallback key: org=%s kid=%s", FALLBACK_ORG, FALLBACK_KID)
        fallback_ok, fallback_details = test_single_key(FALLBACK_ORG, FALLBACK_KID, FALLBACK_PEM_RAW)
        if fallback_ok:
            log.info("🎯 Connected with fallback key. You can now proceed to trading setup.")
            return
        else:
            log.warning("Fallback key validation failed.")
            print_fix_instructions(False, primary_details, True)
            # print more fallback details
            log.error("Fallback details (short): %s", json.dumps({k: fallback_details.get(k) for k in ("org","kid","http_status","error") if fallback_details.get(k) is not None}, indent=2))
            return
    else:
        print_fix_instructions(False, primary_details, False)
        return

if __name__ == "__main__":
    main()
