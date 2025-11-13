#!/usr/bin/env python3
# debug_deploy_decode.py
import os, time, base64, json
import jwt, requests
from loguru import logger
logger.remove()
logger.add(lambda msg: print(msg, end=""))

def fix_pem(pem_raw):
    if pem_raw is None:
        return None
    pem = pem_raw.strip().replace("\\n", "\n")
    if not pem.startswith("-----BEGIN EC PRIVATE KEY-----"):
        pem = "-----BEGIN EC PRIVATE KEY-----\n" + pem
    if not pem.strip().endswith("-----END EC PRIVATE KEY-----"):
        pem = pem + "\n-----END EC PRIVATE KEY-----"
    return pem

def generate_jwt(pem, kid, org_id):
    now = int(time.time())
    payload = {"iat": now, "exp": now + 300, "sub": org_id}
    headers = {"kid": kid}
    try:
        token = jwt.encode(payload, pem, algorithm="ES256", headers=headers)
        return token
    except Exception as e:
        print("JWT generation exception:", repr(e))
        return None

def decode_no_verify(token):
    try:
        # Use PyJWT to decode without verifying signature to inspect contents
        decoded = jwt.decode(token, options={"verify_signature": False})
        header = jwt.get_unverified_header(token)
        return header, decoded
    except Exception as e:
        print("Decode error:", repr(e))
        return None, None

def main():
    print("\n=== DEBUG DECODE START ===\n")
    org = os.environ.get("COINBASE_ORG_ID")
    kid = os.environ.get("COINBASE_API_KEY")
    pem_raw = os.environ.get("COINBASE_PEM_CONTENT")
    print("Env lengths:", "ORG", len(org) if org else "<MISSING>", "KID", len(kid) if kid else "<MISSING>", "PEM", len(pem_raw) if pem_raw else "<MISSING>")

    pem = fix_pem(pem_raw)
    token = generate_jwt(pem, kid, org)
    if not token:
        print("No JWT generated; stop.")
        return

    print("\nJWT preview (first 200 chars):", token[:200])
    header, payload = decode_no_verify(token)
    print("\n--- JWT HEADER ---")
    print(json.dumps(header, indent=2))
    print("\n--- JWT PAYLOAD ---")
    print(json.dumps(payload, indent=2))
    # Show human readable iat/exp and local time
    now = int(time.time())
    iat = payload.get("iat")
    exp = payload.get("exp")
    sub = payload.get("sub")
    print("\nTime check:")
    print("  now (unix):", now)
    print("  iat:", iat, " (", time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(iat)) if iat else None, ")")
    print("  exp:", exp, " (", time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(exp)) if exp else None, ")")
    print("  sub:", sub)
    print("  local clock drift (sec):", now - iat if iat else "N/A")

    # Optionally attempt the accounts call (you can skip by removing this)
    url = f"https://api.coinbase.com/api/v3/brokerage/organizations/{org}/accounts"
    headers = {"Authorization": f"Bearer {token}", "CB-VERSION": "2025-11-01"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        print("\nCoinbase call status:", resp.status_code)
        print("Coinbase response body (first 1000 chars):")
        print(resp.text[:1000])
    except Exception as e:
        print("HTTP exception:", repr(e))

    print("\n=== DEBUG DECODE END ===\n")

if __name__ == "__main__":
    main()
