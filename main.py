# main.py
"""
Nija Trading Bot — Coinbase Advanced connection checker + auto-fallback

Behavior:
- Reads primary Advanced key from env:
    COINBASE_ORG_ID
    COINBASE_API_KEY_ID
    COINBASE_PEM_CONTENT    (multiline or escaped \n)
- Optional fallback key envs:
    COINBASE_FALLBACK_ORG_ID
    COINBASE_FALLBACK_API_KEY_ID
    COINBASE_FALLBACK_PEM_CONTENT
- Detects outbound IP and prints the exact whitelist line for Coinbase Advanced.
- Attempts /key_permissions with primary JWT; if 401, tries fallback if present.
- If success, prints success and returns the JSON (or minimal info).
- If both fail, prints exact export lines for Railway/Render and next steps.
"""

import os
import time
import json
import logging
import requests
import jwt
from typing import Optional, Tuple
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# ---- Config / constants ----
LOG_FILE = os.getenv("NIJA_LOG_FILE", "nija_trading.log")
CB_BASE = "https://api.coinbase.com"
CB_VERSION = time.strftime("%Y-%m-%d")
RETRY_COUNT = int(os.getenv("NIJA_RETRY_COUNT", "3"))
RETRY_DELAY = float(os.getenv("NIJA_RETRY_DELAY", "1"))

# ---- Logging ----
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.getLogger("").addHandler(console)

# ---- Env loader helpers ----
def env(name: str) -> Optional[str]:
    v = os.getenv(name)
    return v if v and v.strip() != "" else None

def normalize_pem(raw: str) -> str:
    """
    Accepts either a real multiline PEM or an escaped one with \n
    and returns a normalized multiline PEM string.
    """
    if not raw:
        return ""
    pem = raw.strip()
    # convert escaped newlines into real newlines if needed
    if "\\n" in pem and "\n" not in pem:
        pem = pem.replace("\\n", "\n")
    # Ensure header/footer are on separate lines and no stray whitespace
    lines = [line.strip() for line in pem.splitlines() if line.strip() != ""]
    if not lines:
        return ""
    return "\n".join(lines) + ("\n" if not lines[-1].endswith("\n") else "")

def load_private_key(pem_text: str):
    try:
        key = serialization.load_pem_private_key(pem_text.encode("utf-8"), password=None, backend=default_backend())
        logging.info("Private key loaded successfully.")
        return key
    except Exception as e:
        logging.error("Failed to parse PEM: %s", e)
        return None

# ---- outbound IP detection ----
def get_outbound_ip() -> Optional[Tuple[str,str]]:
    # Tries multiple services until one returns an IP
    services = [
        ("https://api.ipify.org?format=json","ipify"),
        ("https://ifconfig.co/json","ifconfig.co"),
        ("https://ifconfig.me/all.json","ifconfig.me"),
    ]
    for url, name in services:
        try:
            r = requests.get(url, timeout=4)
            if r.status_code == 200:
                try:
                    j = r.json()
                    ip = j.get("ip") or j.get("ip_addr") or j.get("IP")
                    if ip:
                        return ip, name
                except Exception:
                    txt = r.text.strip()
                    if txt:
                        return txt, name
        except Exception:
            continue
    return None

# ---- JWT gen & call ----
def make_sub(org_id: str, key_id: str) -> str:
    return f"/organizations/{org_id}/apiKeys/{key_id}"

def generate_jwt(private_key_obj, kid: str, sub: str, path: str, method: str="GET") -> Optional[str]:
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
        headers = {"alg":"ES256","kid":kid,"typ":"JWT"}
        token = jwt.encode(payload, private_key_obj, algorithm="ES256", headers=headers)
        # Ensure token is str on all PyJWT versions
        if isinstance(token, bytes):
            token = token.decode()
        logging.debug("JWT generated: path=%s method=%s iat=%s", path, method, iat)
        return token
    except Exception as e:
        logging.exception("Failed to generate JWT: %s", e)
        return None

def call_key_permissions(token: str, org_id: str) -> Tuple[Optional[int], Optional[dict], Optional[str]]:
    path = f"/api/v3/brokerage/organizations/{org_id}/key_permissions"
    url = CB_BASE + path
    headers = {
        "Authorization": f"Bearer {token}",
        "CB-VERSION": CB_VERSION,
        "Content-Type": "application/json"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        try:
            j = resp.json()
        except Exception:
            j = None
        return resp.status_code, j, resp.text
    except Exception as e:
        logging.error("Exception calling /key_permissions: %s", e)
        return None, None, str(e)

# ---- Core: try a single key set ----
def try_key(org_id: str, key_id: str, pem_raw: str) -> Tuple[bool, Optional[dict], dict]:
    """
    Attempts to verify a single Coinbase Advanced key set.
    Returns (success_bool, json_response_if_any, debug_info)
    """
    debug = {"org_id": org_id, "key_id": key_id}
    if not org_id or not key_id or not pem_raw:
        debug["error"] = "Missing env for org/key/pem"
        logging.warning("Missing org/key/pem for this key set: %s", debug)
        return False, None, debug

    pem = normalize_pem(pem_raw)
    key_obj = load_private_key(pem)
    if not key_obj:
        debug["error"] = "failed to load pem"
        return False, None, debug

    sub = make_sub(org_id, key_id)
    request_path = f"/api/v3/brokerage/organizations/{org_id}/key_permissions"
    token = generate_jwt(key_obj, key_id, sub, request_path, method="GET")
    if not token:
        debug["error"] = "jwt_generation_failed"
        return False, None, debug

    # try the request (with a retry loop)
    for attempt in range(1, RETRY_COUNT + 1):
        status, j, text = call_key_permissions(token, org_id)
        logging.info("[Attempt %d] /key_permissions -> %s", attempt, status)
        if status == 200:
            logging.info("✅ Key validated for org=%s kid=%s", org_id, key_id)
            return True, j, {"status": status, "body": j}
        if status == 401:
            logging.warning("❌ 401 Unauthorized for org=%s kid=%s", org_id, key_id)
            return False, None, {"status": status, "body_text": text}
        if status is None:
            logging.warning("Request error: %s", text)
        else:
            logging.warning("Unexpected status %s body: %s", status, text)
        time.sleep(RETRY_DELAY)
    return False, None, {"status": status, "body_text": text}

# ---- Print copy/paste helper lines ----
def print_railway_env_lines(org, kid, pem):
    print("\n--- Railway / Render env export lines (copy & paste) ---")
    print(f"export COINBASE_ORG_ID={org}")
    print(f"export COINBASE_API_KEY_ID={kid}")
    print("export COINBASE_PEM_CONTENT='(paste full PEM as MULTILINE value including header/footer)'")
    print("Example PEM (multiline):")
    print("-----BEGIN EC PRIVATE KEY-----")
    print("MHcCAQEE...")
    print("...rest of key...")
    print("-----END EC PRIVATE KEY-----")
    print("\nIf your UI requires single-line, use the escaped form (example):")
    escaped = (pem or "").replace("\n", "\\n")
    print(f"export COINBASE_PEM_CONTENT='{escaped}'")
    print("------------------------------------------------------\n")

def print_whitelist_line(ip: str):
    if ip:
        print("\n--- Coinbase Advanced Whitelist line (paste this exact IP) ---")
        print(ip)
        print("---------------------------------------------------------------\n")

# ---- Main application flow ----
def main():
    logging.info("🔥 Nija Trading Bot bootstrap starting...")

    # Load primary
    PRIMARY_ORG = env("COINBASE_ORG_ID")
    PRIMARY_KID = env("COINBASE_API_KEY_ID")
    PRIMARY_PEM = env("COINBASE_PEM_CONTENT")

    # Load fallback (optional)
    FALLBACK_ORG = env("COINBASE_FALLBACK_ORG_ID")
    FALLBACK_KID = env("COINBASE_FALLBACK_API_KEY_ID")
    FALLBACK_PEM = env("COINBASE_FALLBACK_PEM_CONTENT")

    # Detect outbound IP
    outbound = get_outbound_ip()
    if outbound:
        ip, src = outbound
        logging.info("⚡ Current outbound IP on this run: %s (via %s)", ip, src)
        print_whitelist_line(ip)
    else:
        logging.warning("Could not detect outbound IP. If Coinbase returns 401, find egress IP from your PaaS dashboard or run 'curl https://api.ipify.org' from the host.")

    # Sanity: ensure primary org/kid/pem present
    if not (PRIMARY_ORG and PRIMARY_KID and PRIMARY_PEM):
        logging.error("Primary Coinbase Advanced key envs missing. Please set COINBASE_ORG_ID, COINBASE_API_KEY_ID, COINBASE_PEM_CONTENT.")
        print_railway_env_lines(PRIMARY_ORG or "<ORG_ID>", PRIMARY_KID or "<KEY_ID>", PRIMARY_PEM or "-----BEGIN...END")
        return

    # Try primary
    logging.info("Checking primary key: org=%s kid=%s", PRIMARY_ORG, PRIMARY_KID)
    ok, data, dbg = try_key(PRIMARY_ORG, PRIMARY_KID, PRIMARY_PEM)
    if ok:
        logging.info("✅ Primary key validated. You can fetch accounts and trade (if permissions present).")
        logging.info("Primary key permissions: %s", json.dumps(data) if data else "no-json")
        # Proceed to start your app/trading flow here if desired
        print("\nPrimary key validated. Bot is connected to Coinbase Advanced.\n")
        return

    # Primary failed — show debug
    logging.warning("Primary key validation failed: %s", dbg)
    # If fallback configured, try fallback
    if FALLBACK_ORG and FALLBACK_KID and FALLBACK_PEM:
        logging.info("Trying fallback key: org=%s kid=%s", FALLBACK_ORG, FALLBACK_KID)
        ok2, data2, dbg2 = try_key(FALLBACK_ORG, FALLBACK_KID, FALLBACK_PEM)
        if ok2:
            logging.info("✅ Fallback key validated. Note: fallback should have no IP restriction for reliability.")
            print("\nFallback key validated. Bot connected using fallback key.\n")
            return
        else:
            logging.error("Fallback key validation also failed: %s", dbg2)
    else:
        logging.info("No fallback key configured. To add one, set COINBASE_FALLBACK_ORG_ID, COINBASE_FALLBACK_API_KEY_ID, COINBASE_FALLBACK_PEM_CONTENT")

    # Both failed (or primary failed and no fallback) -> print exact instructions
    logging.error("❌ Coinbase key validation failed. See instructions below to fix.")
    print("\nACTIONABLE FIXES (copy-paste):\n")
    # If outbound IP known, print whitelist line
    if outbound:
        ip, _ = outbound
        print("1) Whitelist the container outbound IP in Coinbase Advanced (edit the API key and add this IP):")
        print(f"   {ip}\n")
    print("2) If you cannot whitelist, create a new Advanced API key with NO IP restrictions and add these env vars to Railway/Render (or your PaaS):")
    print_railway_env_lines(FALLBACK_ORG or PRIMARY_ORG, FALLBACK_KID or PRIMARY_KID, FALLBACK_PEM or PRIMARY_PEM)
    print("3) Ensure the COINBASE_ORG_ID matches the org that owns the API key (sub must equal /organizations/<ORG>/apiKeys/<KID>).")
    print("4) After updating env or whitelist, restart your container and check logs again.\n")
    logging.info("Done diagnostics. Resolve the above and re-run the container.")

if __name__ == "__main__":
    main()
