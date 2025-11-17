# main.py
"""
Coinbase Advanced diagnostics utility (single-file).
- Detects outbound IP and prints CIDR/whitelist line
- Normalizes & saves PEM from env (handles escaped \n)
- Attempts JWT preview (no remote call by default)
- Optionally can call /key_permissions (uncomment call below)
- Prints copy-paste Railway/Render env export lines (populated with your provided keys)
Save as main.py and run in your container / PaaS. Inspect logs for the whitelist line.
"""

import os
import sys
import time
import json
import requests
import logging
import datetime

from typing import Optional, Tuple

# crypto libs for JWT preview
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("coinbase_diag")

CB_VERSION = datetime.datetime.utcnow().strftime("%Y-%m-%d")

# -------------------------
# Replace these with your env keys if you want them hard-coded here.
# (Better: set them as environment variables in Railway/Render.)
# The values below were provided by you and are included in the exported lines
# printed at the end of this script so you can copy them to your PaaS env editor.
# -------------------------
# (The script will prefer real env vars at runtime; these are only fallbacks for the printed export lines.)
FALLBACK_PRINT_ONLY = {
    "COINBASE_API_KEY_ID": "d3c4f66b-809e-4ce4-9d6c-1a8d31b777d5",
    # PEM as single-line escaped (as you provided earlier). Use multiline in PaaS if possible.
    "COINBASE_PEM_ESCAPED": "-----BEGIN EC PRIVATE KEY-----\\nMHcCAQEEIB7MOrFbx1Kfc/DxXZZ3Gz4Y2hVY9SbcfUHPiuQmLSPxoAoGCCqGSM49\\nAwEHoUQDQgAEiFR+zABGG0DB0HFgjo69cg3tY1Wt41T1gtQp3xrMnvWwio96ifmk\\nAh1eXfBIuinsVEJya4G9DZ01hzaF/edTIw==\\n-----END EC PRIVATE KEY-----",
    "COINBASE_JWT_KID": "d3c4f66b-809e-4ce4-9d6c-1a8d31b777d5",
    "COINBASE_JWT_ISSUER": "organizations/ce77e4ea-ecca-42ec-912a-b6b4455ab9d5/apiKeys/d3c4f66b-809e-4ce4-9d6c-1a8d31b777d5",
    # Provide the ORG you intend to use; logs from your runs showed ce77e4ea... as active orgs,
    # but in earlier messages you also listed 14f3af21... Confirm which org you want in the PaaS env.
    "COINBASE_ORG_ID": "14f3af21-7544-412c-8409-98dc92cd2eec"
}

# -------------------------
# Helpers
# -------------------------
def env(name: str, fallback: Optional[str] = None) -> Optional[str]:
    v = os.getenv(name)
    if v and v.strip() != "":
        return v
    return fallback

def normalize_pem(raw: Optional[str]) -> str:
    """
    Convert escaped single-line PEM (with literal '\n') into real multiline PEM.
    Also trims/normalizes header/footer and removes stray leading/trailing whitespace.
    """
    if not raw:
        return ""
    s = raw.strip()
    # If it contains literal \n sequences but no real newlines, convert
    if "\\n" in s and "\n" not in s:
        s = s.replace("\\n", "\n")
    # Ensure header/footer on own lines and no extra spaces
    lines = [ln.rstrip() for ln in s.splitlines()]
    # Remove any empty lines at start/end
    while lines and lines[0].strip() == "":
        lines.pop(0)
    while lines and lines[-1].strip() == "":
        lines.pop()
    return "\n".join(lines) + ("\n" if lines else "")

def save_pem_debug(pem_text: str, path: str = "/tmp/coinbase_pem_debug.pem"):
    try:
        with open(path, "w") as f:
            f.write(pem_text)
        log.info("Saved normalized PEM to %s (inspect this file in the container)", path)
    except Exception as e:
        log.error("Failed to save PEM to %s: %s", path, e)

def load_private_key_from_pem_text(pem_text: str):
    try:
        key = serialization.load_pem_private_key(pem_text.encode("utf-8"), password=None, backend=default_backend())
        return key
    except Exception as e:
        # Return error for better diagnostics
        return e

def get_outbound_ip() -> Tuple[Optional[str], Optional[str]]:
    services = [
        ("https://api.ipify.org?format=json", "ipify"),
        ("https://ifconfig.co/json", "ifconfig.co"),
        ("https://ifconfig.me/all.json", "ifconfig.me")
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
    return None, None

def generate_jwt_preview_from_key(key_obj, kid: str, org_id: str, api_key_id: str, path: str, method: str = "GET"):
    iat = int(time.time())
    sub = f"/organizations/{org_id}/apiKeys/{api_key_id}"
    payload = {
        "iat": iat,
        "exp": iat + 120,
        "sub": sub,
        "request_path": path,
        "method": method.upper(),
        "jti": f"validate-{iat}"
    }
    headers = {"alg": "ES256", "kid": kid, "typ": "JWT"}
    try:
        token = jwt.encode(payload, key_obj, algorithm="ES256", headers=headers)
    except Exception as e:
        return None, payload, headers, str(e)
    return token, payload, headers, None

def call_key_permissions_with_token(token: str, org_id: str):
    path = f"/api/v3/brokerage/organizations/{org_id}/key_permissions"
    url = "https://api.coinbase.com" + path
    try:
        r = requests.get(url, headers={
            "Authorization": f"Bearer {token}",
            "CB-VERSION": CB_VERSION,
            "Content-Type": "application/json"
        }, timeout=10)
        return r.status_code, r.text, r
    except Exception as e:
        return None, str(e), None

# -------------------------
# Main diagnostics flow
# -------------------------
def run_diagnostics():
    log.info("🔥 Nija Trading Bot diagnostic bootstrap starting...")

    # Detect outbound IP
    ip, src = get_outbound_ip()
    if ip:
        log.info("⚡ Current outbound IP on this run: %s (via %s)", ip, src or "ip-service")
        print("\n--- Coinbase Advanced Whitelist line (paste this exact IP) ---")
        print(ip)
        print("---------------------------------------------------------------\n")
    else:
        log.warning("Could not detect outbound IP via external services. If your PaaS shows an egress IP, whitelist that instead.")

    # Gather env values (primary)
    ORG = env("COINBASE_ORG_ID", FALLBACK_PRINT_ONLY["COINBASE_ORG_ID"])
    KID = env("COINBASE_API_KEY_ID", FALLBACK_PRINT_ONLY["COINBASE_API_KEY_ID"])
    PEM_RAW = env("COINBASE_PEM_CONTENT", os.getenv("COINBASE_API_SECRET", FALLBACK_PRINT_ONLY["COINBASE_PEM_ESCAPED"]))  # some users stored under COINBASE_API_SECRET

    if not ORG or not KID or not PEM_RAW:
        log.error("Missing COINBASE_ORG_ID, COINBASE_API_KEY_ID, or COINBASE_PEM_CONTENT (or COINBASE_API_SECRET).")
        # Print copy-paste lines (populated with your supplied fallback keys)
        print_export_lines_hint()
        return

    # Normalize PEM
    PEM = normalize_pem(PEM_RAW)
    save_pem_debug(PEM)  # saves to /tmp/coinbase_pem_debug.pem for inspection

    # Try to load private key
    key_or_err = load_private_key_from_pem_text(PEM)
    if not hasattr(key_or_err, "sign"):  # in cryptography, private key objects have sign() method; if not, it's error
        log.error("Unable to load PEM file. See https://cryptography.io/en/latest/faq/#why-can-t-i-import-my-pem-file for details. Error: %s", key_or_err)
        # Attempt to suggest quick conversions (already attempted by normalize_pem)
        print_export_lines_hint()
        return

    log.info("Private key loaded successfully (PEM parsed). Building JWT preview...")

    # JWT preview
    path = f"/api/v3/brokerage/organizations/{ORG}/key_permissions"
    token, payload, headers, err = generate_jwt_preview_from_key(key_or_err, KID, ORG, KID, path)
    if err:
        log.error("Failed to generate JWT preview: %s", err)
        print_export_lines_hint()
        return

    log.info("✅ JWT preview generated (first 200 chars): %s", str(token)[:200])
    log.debug("JWT payload (unverified): %s", json.dumps(payload))
    log.debug("JWT header (unverified): %s", json.dumps(headers))

    # OPTIONAL: call Coinbase /key_permissions
    # You can enable the live call below by setting PERFORM_LIVE_CALL env var
    PERFORM_LIVE = os.getenv("PERFORM_LIVE_CALL", "0") == "1"
    if PERFORM_LIVE:
        log.info("Attempting live /key_permissions call to Coinbase to validate key...")
        status, text, raw = call_key_permissions_with_token(token, ORG)
        if status is None:
            log.error("Key permissions request failed: %s", text)
        else:
            log.info("Coinbase returned HTTP %s", status)
            if status == 200:
                log.info("✅ Primary key validated successfully! You can now fetch accounts.")
                try:
                    j = raw.json()
                    print(json.dumps(j, indent=2))
                except Exception:
                    print(text)
                return
            elif status == 401:
                log.error("❌ 401 Unauthorized! Check PEM, ORG_ID, API_KEY_ID, timestamps, and IP restrictions (whitelist container IP).")
                log.error("Coinbase response body: %s", text)
                print_export_lines_hint()
                return
            else:
                log.error("Unexpected HTTP %s: %s", status, text)
                print_export_lines_hint()
                return
    else:
        log.info("Live /key_permissions call is disabled (PERFORM_LIVE_CALL!=1). Enable to perform automatic validation.")

    # Final: print env export lines for Railway/Render (populated with your provided values)
    print("\n--- Railway / Render env export lines (copy & paste) ---")
    # Use the actual values from env if present, otherwise fallback print values
    print(f"export COINBASE_ORG_ID={ORG}")
    print(f"export COINBASE_API_KEY_ID={KID}")
    print("Preferred: paste PEM as MULTILINE in the PaaS env editor.")
    print("Example PEM (multiline) to paste into COINBASE_PEM_CONTENT:")
    # Print normalized PEM for convenience (but beware: this prints your private key into logs/console)
    print(PEM if PEM else "(PEM is empty or could not be normalized)")
    print("\nIf your PaaS requires single-line escaped env, use:")
    print("export COINBASE_PEM_CONTENT='{}'".format(PEM.replace("\n", "\\n") if PEM else "''"))
    print("------------------------------------------------------\n")

def print_export_lines_hint():
    # Use fallbacks from the user-provided block where available
    print("\n--- Quick env export hints (copy/paste into Railway/Render) ---")
    print(f"export COINBASE_ORG_ID={FALLBACK_PRINT_ONLY['COINBASE_ORG_ID']}")
    print(f"export COINBASE_API_KEY_ID={FALLBACK_PRINT_ONLY['COINBASE_API_KEY_ID']}")
    print("export COINBASE_PEM_CONTENT='(paste full PEM as MULTILINE value including header/footer)'")
    print("\nIf your PaaS only supports single-line envs, use escaped form:")
    print("export COINBASE_PEM_CONTENT='{}'".format(FALLBACK_PRINT_ONLY['COINBASE_PEM_ESCAPED']))
    print("---------------------------------------------------------------\n")

# -------------------------
# Run when executed
# -------------------------
if __name__ == "__main__":
    try:
        run_diagnostics()
    except Exception as e:
        log.exception("Diagnostic run failed: %s", e)
        sys.exit(1)
