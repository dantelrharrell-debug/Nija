#!/usr/bin/env python3
# validate_coinbase_env.py
"""
Validate Coinbase Advanced (CDP) env vars, PEM, JWT, and produce exact
commands / whitelist lines for Railway/Render and Coinbase Advanced.
Run: python validate_coinbase_env.py
"""

import os
import sys
import time
import json
import datetime
import logging
from typing import Tuple, Optional
import requests
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("validate_coinbase_env")

CB_VERSION = datetime.datetime.utcnow().strftime("%Y-%m-%d")


# -------------------------
# Helpers
# -------------------------
def env(name: str) -> Optional[str]:
    v = os.getenv(name)
    return v if v and v.strip() != "" else None


def normalize_pem(raw: str) -> str:
    """
    Normalize PEM content:
    - convert escaped \\n to real newlines if necessary
    - trim surrounding whitespace
    - collapse accidental empty lines while preserving header/footer structure
    """
    if raw is None:
        return ""
    pem = raw.strip()
    if "\\n" in pem and "\n" not in pem:
        pem = pem.replace("\\n", "\n")
    # Remove lines that are purely whitespace but preserve real structure
    lines = [line.rstrip() for line in pem.splitlines()]
    # Reconstruct ensuring header/footer remain intact
    pem_norm = "\n".join(lines).strip() + "\n"
    return pem_norm


def load_private_key(pem_text: str):
    try:
        key = serialization.load_pem_private_key(pem_text.encode("utf-8"), password=None, backend=default_backend())
        return key
    except Exception as e:
        logger.error("Failed to parse PEM: %s", e)
        return None


def make_sub(org: str, key: str) -> str:
    return f"/organizations/{org}/apiKeys/{key}"


def generate_jwt_preview(key_obj, kid: str, sub: str, path: str, method: str = "GET"):
    iat = int(time.time())
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
        logger.error("Failed to encode JWT with provided key object: %s", e)
        token = None
    return token, payload, headers


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


def cb_time_drift_seconds() -> Optional[int]:
    try:
        r = requests.get("https://api.coinbase.com/v2/time", timeout=5)
        cb_epoch = int(r.json()["data"]["epoch"])
        return int(time.time()) - cb_epoch
    except Exception as e:
        logger.debug("Coinbase time check failed: %s", e)
        return None


def call_key_permissions(token: str, org_id: str):
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


def print_export_lines(org: str, key: str, pem: str, prefix: str = "COINBASE"):
    print("\n--- Copy-paste this to Railway/Render env editor (multiline PEM preferred) ---")
    print(f"{prefix}_ORG_ID={org}")
    print(f"{prefix}_API_KEY_ID={key}")
    print(f"{prefix}_PEM_CONTENT= (paste full PEM as MULTILINE value including header/footer)")
    print("Example PEM value (paste as multiline exactly):")
    print("-----BEGIN EC PRIVATE KEY-----")
    print("MHcCAQEE...")
    print("...rest of key...")
    print("-----END EC PRIVATE KEY-----")
    print("\nIf your UI only supports single-line, use this escaped form instead:")
    escaped = pem.replace("\n", "\\n")
    print(f"{prefix}_PEM_CONTENT='{escaped}'")


# -------------------------
# Validate primary & optional fallback
# -------------------------
PRIMARY_ORG = env("COINBASE_ORG_ID")
PRIMARY_KEY = env("COINBASE_API_KEY_ID")
PRIMARY_PEM_RAW = env("COINBASE_PEM_CONTENT")

FALLBACK_ORG = env("COINBASE_FALLBACK_ORG_ID")
FALLBACK_KEY = env("COINBASE_FALLBACK_API_KEY_ID")
FALLBACK_PEM_RAW = env("COINBASE_FALLBACK_PEM_CONTENT")


# -------------------------
# Start checks
# -------------------------
def main():
    if not PRIMARY_ORG or not PRIMARY_KEY or not PRIMARY_PEM_RAW:
        logger.error("Primary key environment variables are missing. Set COINBASE_ORG_ID, COINBASE_API_KEY_ID, COINBASE_PEM_CONTENT.")
        print_export_lines(PRIMARY_ORG or "<ORG_ID>", PRIMARY_KEY or "<KEY_ID>", PRIMARY_PEM_RAW or "-----BEGIN...END")
        sys.exit(1)

    print("\n=== Coinbase Advanced Env Validator ===\n")
    print("Primary key found in environment. Validating...")

    PEM = normalize_pem(PRIMARY_PEM_RAW)
    key_obj = load_private_key(PEM)
    if not key_obj:
        logger.error("Primary PEM failed to parse. Re-copy the PEM exactly from Coinbase (include header/footer).")
        print_export_lines(PRIMARY_ORG, PRIMARY_KEY, PRIMARY_PEM_RAW)
        sys.exit(1)
    else:
        logger.info("Primary PEM parsed successfully.")

    SUB = make_sub(PRIMARY_ORG, PRIMARY_KEY)
    print(f"Primary SUB (constructed): {SUB}")

    # show coinbase time drift
    drift = cb_time_drift_seconds()
    if drift is not None:
        print(f"Coinbase time drift (local - coinbase) seconds: {drift}")
        if abs(drift) > 10:
            print("WARNING: drift >10s. Sync server clock.")
    else:
        print("Could not determine Coinbase time drift (network error).")

    # generate JWT preview
    request_path = f"/api/v3/brokerage/organizations/{PRIMARY_ORG}/key_permissions"
    token, payload, headers = generate_jwt_preview(key_obj, PRIMARY_KEY, SUB, request_path, method="GET")
    if not token:
        logger.error("JWT generation failed with primary key. Check PEM and key.")
        sys.exit(1)

    print("\n--- JWT preview (first 200 chars) ---")
    print(f"{str(token)[:200]}")
    print("\nJWT payload (unverified) ->")
    print(json.dumps(payload, indent=2))
    print("\nJWT header (unverified) ->")
    print(json.dumps(headers, indent=2))

    # detect outbound IP
    ip, src = get_outbound_ip()
    if ip:
        print(f"\nDetected outbound IP via {src}: {ip}")
        print("Exact whitelist line for Coinbase Advanced (one line):")
        print(ip)
    else:
        print("\nCould not detect outbound IP. You may need to find your container's egress IP via your PaaS dashboard or run 'curl https://api.ipify.org' from the server.")

    # show railway export lines for ease
    print("\n\n--- Railway / Render env export lines (PRIMARY) ---")
    print(f"export COINBASE_ORG_ID={PRIMARY_ORG}")
    print(f"export COINBASE_API_KEY_ID={PRIMARY_KEY}")
    print("export COINBASE_PEM_CONTENT='(multiline PEM or escaped \\n form)'")
    print("\nPreferred: paste PEM as multiline in the env editor.")
    print("\nEscaped-one-line example (if UI requires it):")
    print("export COINBASE_PEM_CONTENT='{}'".format(PEM.replace("\n", "\\n")))

    # Offer to call Coinbase /key_permissions now (gives 401 or 200)
    print("\nWould you like me to attempt a live call to Coinbase /key_permissions with the primary key now? (recommended) [y/N]")
    try:
        resp = input().strip().lower()
    except Exception:
        resp = "n"

    if resp == "y":
        print("Calling /key_permissions ...")
        status, text, raw_resp = call_key_permissions(token, PRIMARY_ORG)
        if status is None:
            print(f"Request failed: {text}")
        else:
            print(f"HTTP {status}")
            try:
                j = raw_resp.json()
                print(json.dumps(j, indent=2))
            except Exception:
                print(text)

        if status == 200:
            print("\n✅ Primary key validated successfully! You can now fetch accounts.")
        elif status == 401:
            print("\n❌ Received 401 Unauthorized from Coinbase.")
            print("Likely causes (in order):")
            print("  1) API key has IP whitelist and current outbound IP is not allowed.")
            print("  2) COINBASE_ORG_ID or COINBASE_API_KEY_ID do not match this PEM/key.")
            print("  3) PEM formatting issue (but key parsed correctly so less likely).")
            if ip:
                print(f"\nAction A (fast): Add this IP to Coinbase key whitelist: {ip}")
                print("\nAction B (if you cannot whitelist dynamic IPs): Create a new Advanced API key with NO IP restrictions and update env vars.")
            else:
                print("\nAction: If you cannot whitelist, create a new key with no IP restrictions and test that.")
    else:
        print("Skipped live /key_permissions call.")

    # If optional fallback env provided, print fallback exports and validation
    if FALLBACK_ORG and FALLBACK_KEY and FALLBACK_PEM_RAW:
        print("\n\nDetected fallback env values. Validating fallback key...")
        f_pem = normalize_pem(FALLBACK_PEM_RAW)

        if not f_key_obj:
            print("Fallback PEM failed to parse. Please re-check COINBASE_FALLBACK_PEM_CONTENT.")
        else:
            f_sub = make_sub(FALLBACK_ORG, FALLBACK_KEY)
            print("Fallback SUB:", f_sub)
            # generate jwt for fallback preview
            f_token, f_payload, f_headers = generate_jwt_preview(f_key_obj, FALLBACK_KEY, f_sub, request_path)
            print("\nFallback JWT preview (first 160 chars):")
            print(str(f_token)[:160])
            print("\nFallback JWT payload (unverified):")
            print(json.dumps(f_payload, indent=2))
            print("\nFallback JWT header (unverified):")
            print(json.dumps(f_headers, indent=2))
            print("\nRailway export lines for fallback (copy-paste):")
            print(f"export COINBASE_FALLBACK_ORG_ID={FALLBACK_ORG}")
            print(f"export COINBASE_FALLBACK_API_KEY_ID={FALLBACK_KEY}")
            print("export COINBASE_FALLBACK_PEM_CONTENT='(multiline PEM or escaped \\n form)'")
            print("Escaped-one-line example:")
            print(f"export COINBASE_FALLBACK_PEM_CONTENT='{f_pem.replace('\\n','\\\\n')}'")
    else:
        print("\nNo fallback key env variables detected. If you want auto-fallback, set COINBASE_FALLBACK_ORG_ID, COINBASE_FALLBACK_API_KEY_ID, COINBASE_FALLBACK_PEM_CONTENT (temp key with no IP restriction).")

    print("\n\nValidation script finished. If you see 401 from Coinbase, the quickest fix is to whitelist the detected outbound IP in Coinbase Advanced or create a new key with no IP restriction and use it as the fallback to verify connectivity.")


if __name__ == "__main__":
    main()
