#!/usr/bin/env python3
"""
main.py

Single-file debug + JWT generator + accounts test for Coinbase Advanced (CDP) JWT auth.

Usage:
  - Put this file in your project root and run: python main.py
  - Make sure environment variables are set:
      COINBASE_ORG_ID
      COINBASE_API_KEY            (either full path or key id)
      COINBASE_PEM_CONTENT       (PEM private key; keep literal "\n" in env value)
      CB_API_HOST (optional; default api.coinbase.com)
"""

import os
import time
import base64
import json
import requests
import jwt  # PyJWT
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# --------- Config / env ----------
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")  # can be "organizations/.../apiKeys/<ID>" or "<ID>"
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT", "")  # keep literal \n in the env value
CB_API_HOST = os.getenv("CB_API_HOST", "api.coinbase.com")  # override if necessary

# minimal validation
missing = []
if not COINBASE_ORG_ID:
    missing.append("COINBASE_ORG_ID")
if not COINBASE_API_KEY:
    missing.append("COINBASE_API_KEY")
if not COINBASE_PEM_CONTENT:
    missing.append("COINBASE_PEM_CONTENT")

if missing:
    print("❌ Missing environment variables:", ", ".join(missing))
    print("Please set them and restart the service.")
    raise SystemExit(1)

# Extract API key id (last part) if user passed full path
API_KEY_ID = COINBASE_API_KEY.split("/")[-1]

# Convert literal "\n" sequences into real newlines (Railway/Render often stores multiline secrets like this)
pem_corrected = COINBASE_PEM_CONTENT.replace("\\n", "\n")

# Attempt to load PEM private key
try:
    private_key = serialization.load_pem_private_key(
        pem_corrected.encode("utf-8"),
        password=None,
        backend=default_backend(),
    )
    print("✅ PEM private key loaded successfully")
except Exception as e:
    print("❌ Failed to load PEM key:", e)
    # extra debug hints
    print("  - Ensure COINBASE_PEM_CONTENT contains the exact PEM with BEGIN/END lines.")
    print("  - If you pasted the PEM directly into .env, keep literal \\n instead of newlines.")
    print("  - Visit https://cryptography.io/en/latest/faq/#why-can-t-i-import-my-pem-file for PEM issues.")
    raise

# Build JWT claims (Coinbase examples include request_path + method in payload)
def generate_jwt_for_path(path: str, method: str = "GET", expires_in: int = 120) -> str:
    iat = int(time.time())
    payload = {
        "iat": iat,
        "exp": iat + int(expires_in),
        "sub": API_KEY_ID,          # must be the API key id
        "request_path": path,       # exactly match the API path you will call
        "method": method.upper(),   # uppercase HTTP method
    }
    headers = {
        "alg": "ES256",
        "kid": API_KEY_ID           # kid must match key id used in Coinbase portal
    }

    token = jwt.encode(
        payload,
        private_key,
        algorithm="ES256",
        headers=headers
    )

    return token

# Debug helper to print token header & payload (no signature verification)
def decode_no_verify(token: str):
    try:
        header = jwt.get_unverified_header(token)
        payload = jwt.decode(token, options={"verify_signature": False})
        return header, payload
    except Exception as e:
        return None, None

# Call Accounts endpoint to verify auth
def test_get_accounts():
    # IMPORTANT: request_path must match the path included in the JWT payload exactly
    path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
    url = f"https://{CB_API_HOST}{path}"

    token = generate_jwt_for_path(path, method="GET", expires_in=120)
    header, payload = decode_no_verify(token)

    print()
    print("JWT preview (first 80 chars):", token[:80])
    print("JWT header (unverified):", json.dumps(header, indent=2))
    print("JWT payload (unverified):", json.dumps(payload, indent=2))
    print("Request Path used in JWT:", path)
    print("Request URL:", url)

    # Extra debug: show curl command you can paste locally (token is short-lived)
    print("\n--- Example curl (paste locally) ---")
    print(f'curl -s -D - -H "Authorization: Bearer {token}" -H "CB-VERSION: 2025-11-12" "{url}"')
    print("-----------------------------------\n")

    # Make the request
    resp = requests.get(url, headers={
        "Authorization": f"Bearer {token}",
        "CB-VERSION": "2025-11-12",
        "Accept": "application/json"
    }, timeout=10)

    print("HTTP status:", resp.status_code)
    try:
        print("Response JSON / text:", resp.text)
    except Exception:
        print("Response (non-text)")

    if resp.status_code == 200:
        print("✅ Accounts fetched - AUTH successful")
    else:
        print("⚠️ Failed to fetch accounts. See above response and checklist.")

# Run the quick test once (not looped)
if __name__ == "__main__":
    print("🌟 Running Coinbase JWT test")
    print("  API_KEY_ID:", API_KEY_ID)
    print("  COINBASE_ORG_ID:", COINBASE_ORG_ID)
    print("  CB_API_HOST:", CB_API_HOST)
    test_get_accounts()
