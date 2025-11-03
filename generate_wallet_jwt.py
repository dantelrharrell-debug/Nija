#!/usr/bin/env python3
"""
Generate a Coinbase Wallet JWT (wallet-auth) safely with helpful errors.

Expects environment variables:
 - WALLET_SECRET       (base64 DER private key string)
 - REQUEST_METHOD      (e.g. "POST")
 - REQUEST_HOST        (e.g. "api.cdp.coinbase.com")
 - REQUEST_PATH        (e.g. "/platform/v2/evm/.../sign/transaction")
 - REQUEST_BODY        (JSON string or empty)

This script will print a single JWT string on success or
print a clear error and exit(1) on failure.
"""

import os
import sys
import time
import jwt
import uuid
import json
import hashlib
import base64
from cryptography.hazmat.primitives import serialization

def fatal(msg):
    print("ERROR:", msg, file=sys.stderr)
    sys.exit(1)

# Load env vars
wallet_secret = os.getenv("WALLET_SECRET")
request_method = os.getenv("REQUEST_METHOD", "").strip()
request_host = os.getenv("REQUEST_HOST", "").strip()
request_path = os.getenv("REQUEST_PATH", "").strip()
request_body_raw = os.getenv("REQUEST_BODY")  # may be None or a JSON string

# Validate required values
if not wallet_secret:
    fatal("WALLET_SECRET not set. Export WALLET_SECRET with the base64 DER private key.")

if not request_method or not request_host or not request_path:
    fatal("REQUEST_METHOD, REQUEST_HOST, and REQUEST_PATH must be set and non-empty.")

# Parse request body if present
request_body = None
if request_body_raw:
    try:
        # Allow REQUEST_BODY to be a JSON string (single quotes or double)
        request_body = json.loads(request_body_raw)
    except json.JSONDecodeError:
        fatal("REQUEST_BODY is not valid JSON. Example: export REQUEST_BODY='{\"transaction\":\"0x...\"}'")
    except TypeError:
        # this happens if request_body_raw is not a str/bytes
        fatal("REQUEST_BODY environment variable has invalid type (expected JSON string).")

# Build payload
now = int(time.time())
uri = f"{request_method} {request_host}{request_path}"
payload = {
    "iat": now,
    "nbf": now,
    "jti": str(uuid.uuid4()),
    "uris": [uri],
}

def sort_keys(obj):
    if obj is None or not isinstance(obj, (dict, list)):
        return obj
    if isinstance(obj, list):
        return [sort_keys(i) for i in obj]
    # dict
    return {k: sort_keys(obj[k]) for k in sorted(obj.keys())}

# If body present, compute reqHash
if request_body is not None:
    try:
        sorted_body = sort_keys(request_body)
        json_bytes = json.dumps(sorted_body, separators=(",", ":"), sort_keys=True).encode("utf-8")
        payload["reqHash"] = hashlib.sha256(json_bytes).hexdigest()
    except Exception as e:
        fatal(f"Failed to hash REQUEST_BODY: {e}")

# Load private key (expecting base64-encoded DER by default)
try:
    der_bytes = base64.b64decode(wallet_secret)
except Exception as e:
    fatal(f"WALLET_SECRET is not valid base64: {e}")

if not der_bytes:
    fatal("Decoded WALLET_SECRET is empty. Ensure WALLET_SECRET contains base64 DER content.")

try:
    private_key = serialization.load_der_private_key(der_bytes, password=None)
except Exception as e:
    fatal(f"Failed to load private key from WALLET_SECRET (DER). Error: {e}")

# Create JWT. PyJWT can accept a cryptography key object for ES256 signing.
try:
    token = jwt.encode(payload, private_key, algorithm="ES256", headers={"typ": "JWT"})
    # On PyJWT >= 2, encode returns str; ensure str
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    print(token)
except Exception as e:
    fatal(f"Failed to sign JWT: {e}")
