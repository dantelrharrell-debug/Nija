# main.py
import os
import time
import json
import logging
import requests
import datetime
import jwt

from typing import Optional, Tuple
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# -------- CONFIG --------
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
RETRY_DELAY = float(os.getenv("RETRY_DELAY", "1.0"))
CB_BASE = os.getenv("COINBASE_BASE_URL", "https://api.coinbase.com")
CB_VERSION = datetime.datetime.utcnow().strftime("%Y-%m-%d")

# -------- Logging --------
LOG_FMT = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FMT)
log = logging.getLogger("nija_coinbase_diag")

# -------- Helpers --------
def env(name: str) -> Optional[str]:
    v = os.getenv(name)
    return v if v and v.strip() != "" else None

def normalize_pem(raw: Optional[str]) -> Optional[str]:
    """Normalize PEM into multiline with newline characters. Returns None if empty."""
    if not raw:
        return None
    pem = raw.strip()
    # If escaped newlines present, convert them
    if "\\n" in pem and "\n" not in pem:
        pem = pem.replace("\\n", "\n")
    # Ensure header/footer on their own lines and no trailing garbage
    lines = [ln.rstrip() for ln in pem.splitlines() if ln.strip() != ""]
    if not lines:
        return None
    pem_text = "\n".join(lines)
    if not pem_text.endswith("\n"):
        pem_text += "\n"
    # quick sanity check for header/footer
    if ("-----BEGIN" not in pem_text) or ("-----END" not in pem_text):
        return None
    return pem_text

def load_private_key(pem_text: str):
    """Attempt to parse PEM. Returns True if parse ok, otherwise raises."""
    try:
        serialization.load_pem_private_key(pem_text.encode("utf-8"), password=None, backend=default_backend())
        return True
    except Exception as e:
        raise

def get_outbound_ip() -> Tuple[Optional[str], Optional[str]]:
    """Try multiple public IP providers and return (ip, provider)"""
    probes = [
        ("https://api.ipify.org?format=json", "ipify"),
        ("https://ifconfig.co/json", "ifconfig.co"),
        ("https://ifconfig.me/all.json", "ifconfig.me")
    ]
    for url, name in probes:
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
    return None, None

def build_sub(org: str, kid: str) -> str:
    return f"/organizations/{org}/apiKeys/{kid}"

def generate_jwt_for(pem_text: str, kid: str, sub: str, path: str, method: str="GET") -> str:
    iat = int(time.time())
    payload = {"iat": iat, "exp": iat + 120, "sub": sub, "request_path": path, "method": method.upper(), "jti": f"nija-{iat}"}
    headers = {"alg": "ES256", "kid": kid}
    # Use the PEM text bytes (PyJWT accepts PEM)
    token = jwt.encode(payload, pem_text.encode("utf-8"), algorithm="ES256", headers=headers)
    return token, payload, headers

def call_key_permissions(token: str, org: str) -> Tuple[int, str, Optional[requests.Response]]:
    path = f"/api/v3/brokerage/organizations/{org}/key_permissions"
    url = CB_BASE + path
    headers = {"Authorization": f"Bearer {token}", "CB-VERSION": CB_VERSION, "Content-Type": "application/json"}
    try:
        r = requests.get(url, headers=headers, timeout=8)
        return r.status_code, r.text, r
    except Exception as e:
        return -1, str(e), None

# -------- Core validation routine --------
def test_key(org: str, kid: str, raw_pem: Optional[str]) -> dict:
    info = {"org": org, "kid": kid}
    if not org or not kid or not raw_pem:
        info["error"] = "Missing env var (org/kid/pem)"
        return info

    pem = normalize_pem(raw_pem)
    if not pem:
        info["error"] = "PEM normalization failed (missing header/footer or empty)."
        return info

    # Validate parsing
    try:
        load_private_key(pem)
    except Exception as e:
        info["error"] = f"Unable to parse PEM: {e}"
        return info

    sub = build_sub(org, kid)
    path = f"/api/v3/brokerage/organizations/{org}/key_permissions"
    token, payload, headers = generate_jwt_for(pem, kid, sub, path, method="GET")
    info["jwt_preview"] = str(token)[:200]
    info["jwt_payload_unverified"] = payload
    info["jwt_header_unverified"] = headers

    # Try call with retries
    last_status = None
    for attempt in range(1, MAX_RETRIES + 1):
        status, text, resp = call_key_permissions(token, org)
        last_status = {"status": status, "body_text": text}
        log.info(f"[Attempt {attempt}] /key_permissions -> {status}")
        if status == 200:
            try:
                info["response_json"] = resp.json()
            except Exception:
                info["response_text"] = text
            info["http_status"] = 200
            return info
        elif status == 401:
            info["http_status"] = 401
            info["body"] = text
            # stop retrying on 401 (likely credentials/whitelist)
            return info
        else:
            # try again after delay
            time.sleep(RETRY_DELAY)
    # exhausted retries
    info["last_status"] = last_status
    return info

# -------- Entrypoint --------
def main():
    log.info("🔥 Nija Trading Bot bootstrap starting...")
    # Read primary env
    PRIMARY_ORG = env("COINBASE_ORG_ID")
    PRIMARY_KID = env("COINBASE_API_KEY_ID")
    PRIMARY_PEM_RAW = env("COINBASE_PEM_CONTENT")

    # Optional fallback env (unrestricted recommended)
    FALLBACK_ORG = env("COINBASE_FALLBACK_ORG_ID")
    FALLBACK_KID = env("COINBASE_FALLBACK_API_KEY_ID")
    FALLBACK_PEM_RAW = env("COINBASE_FALLBACK_PEM_CONTENT")

    ip, src = get_outbound_ip()
    if ip:
        log.info(f"⚡ Current outbound IP on this run: {ip} (via {src})")
        log.info("--- Coinbase Advanced Whitelist line (paste this exact IP) ---")
        log.info(ip)
        log.info("---------------------------------------------------------------")
    else:
        log.warning("Could not detect outbound IP. If your host/PaaS has a dashboard, find its egress IP and whitelist that.")

    # Quick sanity: ensure org/kid present
    if not PRIMARY_ORG or not PRIMARY_KID or not PRIMARY_PEM_RAW:
        log.error("Missing PRIMARY key env vars. Set COINBASE_ORG_ID, COINBASE_API_KEY_ID, COINBASE_PEM_CONTENT.")
        log.info("Railway/Render example exports:")
        log.info(f"export COINBASE_ORG_ID={PRIMARY_ORG or '<ORG_ID>'}")
        log.info(f"export COINBASE_API_KEY_ID={PRIMARY_KID or '<KID>'}")
        log.info("export COINBASE_PEM_CONTENT='(paste full PEM as MULTILINE value including header/footer)'")
        return

    # Test primary
    log.info(f"Checking primary key: org={PRIMARY_ORG} kid={PRIMARY_KID}")
    primary_result = test_key(PRIMARY_ORG, PRIMARY_KID, PRIMARY_PEM_RAW)
    if primary_result.get("http_status") == 200:
        log.info("✅ Primary key validated successfully. You are connected to Coinbase Advanced.")
        # Optionally fetch accounts or continue to trading here
        return
    else:
        log.warning("Primary key validation failed.")
        log.debug(json.dumps(primary_result, indent=2))
        # If fallback configured, test fallback
        if FALLBACK_ORG and FALLBACK_KID and FALLBACK_PEM_RAW:
            log.info(f"Trying fallback key: org={FALLBACK_ORG} kid={FALLBACK_KID}")
            fallback_result = test_key(FALLBACK_ORG, FALLBACK_KID, FALLBACK_PEM_RAW)
            if fallback_result.get("http_status") == 200:
                log.info("✅ Fallback key validated successfully. Use fallback key envs in your deployment.")
                return
            else:
                log.warning("Fallback key validation failed.")
                log.debug(json.dumps(fallback_result, indent=2))
        else:
            fallback_result = None
            log.info("No fallback configured. Add COINBASE_FALLBACK_* env vars for an unrestricted key.")

    # At this point, both primary (and optional fallback) failed
    log.error("❌ Coinbase key validation failed. Fix the following (copy/paste):")
    if ip:
        log.error("1) Whitelist the container outbound IP in Coinbase Advanced (edit the API key and add this IP):")
        log.error(f"   {ip}")
    log.error("2) Ensure these env vars match your Coinbase Advanced API key (copy/paste into Railway/Render):")
    log.error(f"   export COINBASE_ORG_ID={PRIMARY_ORG}")
    log.error(f"   export COINBASE_API_KEY_ID={PRIMARY_KID}")
    log.error("   export COINBASE_PEM_CONTENT='(paste full PEM as MULTILINE value including header/footer)'")
    log.error("")
    log.error("If you cannot whitelist dynamic container IPs, create a new Advanced API key with NO IP restrictions and set it as fallback:")
    log.error("   export COINBASE_FALLBACK_ORG_ID=<ORG_OF_FALLBACK_KEY>")
    log.error("   export COINBASE_FALLBACK_API_KEY_ID=<KID_OF_FALLBACK_KEY>")
    log.error("   export COINBASE_FALLBACK_PEM_CONTENT='(paste fallback PEM here)'")
    log.error("")
    log.error("After updating env or whitelist, restart your container.")
    # Print short diagnostic summary
    log.error("--- Primary details (short) ---")
    log.error(json.dumps({k: v for k, v in primary_result.items() if k in ("org", "kid", "http_status", "error", "body", "last_status")}, indent=2))
    if fallback_result is not None:
        log.error("--- Fallback details (short) ---")
        log.error(json.dumps({k: v for k, v in fallback_result.items() if k in ("org", "kid", "http_status", "error", "body", "last_status")}, indent=2))

if __name__ == "__main__":
    main()
