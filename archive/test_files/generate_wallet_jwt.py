#!/usr/bin/env python3
"""
Robust wallet JWT generator that accepts:
 - WALLET_SECRET as base64 DER string (single-line)
 - WALLET_SECRET as PEM text (-----BEGIN PRIVATE KEY-----...-----END PRIVATE KEY-----)

Other env vars:
 - REQUEST_METHOD
 - REQUEST_HOST
 - REQUEST_PATH
 - REQUEST_BODY (optional, JSON string)
"""

import os, sys, time, jwt, uuid, json, hashlib, base64, re
from cryptography.hazmat.primitives import serialization

def fatal(msg):
    print("ERROR:", msg, file=sys.stderr)
    sys.exit(1)

wallet_secret = os.getenv("WALLET_SECRET")
request_method = os.getenv("REQUEST_METHOD", "").strip()
request_host = os.getenv("REQUEST_HOST", "").strip()
request_path = os.getenv("REQUEST_PATH", "").strip()
request_body_raw = os.getenv("REQUEST_BODY")

if not wallet_secret:
    fatal("WALLET_SECRET not set. Provide base64 DER or PEM text in WALLET_SECRET.")

if not request_method or not request_host or not request_path:
    fatal("REQUEST_METHOD, REQUEST_HOST, and REQUEST_PATH must be set and non-empty.")

# parse REQUEST_BODY
request_body = None
if request_body_raw:
    try:
        request_body = json.loads(request_body_raw)
    except Exception as e:
        fatal(f"REQUEST_BODY is not valid JSON: {e}")

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
    return {k: sort_keys(obj[k]) for k in sorted(obj.keys())}

if request_body is not None:
    try:
        sorted_body = sort_keys(request_body)
        json_bytes = json.dumps(sorted_body, separators=(",", ":"), sort_keys=True).encode("utf-8")
        payload["reqHash"] = hashlib.sha256(json_bytes).hexdigest()
    except Exception as e:
        fatal(f"Failed to hash REQUEST_BODY: {e}")

def try_load_private_key_from_base64(s: str):
    # normalize + pad
    s2 = re.sub(r"\s+", "", s)
    pad = (-len(s2)) % 4
    if pad:
        s2 += "=" * pad
    try:
        der = base64.b64decode(s2)
    except Exception as e:
        raise RuntimeError(f"base64 decode failed: {e}")
    if not der:
        raise RuntimeError("base64 decoded to empty bytes")
    try:
        return serialization.load_der_private_key(der, password=None)
    except Exception as e:
        raise RuntimeError(f"load_der_private_key failed: {e}")

def try_load_private_key_from_pem(s: str):
    try:
        # cryptography can load PEM directly if bytes
        return serialization.load_pem_private_key(s.encode("utf-8"), password=None)
    except Exception as e:
        raise RuntimeError(f"load_pem_private_key failed: {e}")

# Decide: is this PEM?
s = wallet_secret.strip()
private_key = None
if "-----BEGIN" in s and "PRIVATE KEY-----" in s:
    try:
        private_key = try_load_private_key_from_pem(s)
    except Exception as e:
        # fallback: maybe user pasted PEM but line endings/extra spaces caused issue; try cleaning
        cleaned = "\n".join([line.strip() for line in s.splitlines() if line.strip()])
        try:
            private_key = try_load_private_key_from_pem(cleaned)
        except Exception as e2:
            fatal(f"WALLET_SECRET appears to be PEM but failed to load as PEM: {e2}")
else:
    # try base64 DER
    try:
        private_key = try_load_private_key_from_base64(s)
    except Exception as e:
        # last-ditch: maybe they pasted PEM but without headers (just base64 body). Try to add padding and decode:
        body = re.sub(r"-----.*-----", "", s)
        try:
            private_key = try_load_private_key_from_base64(body)
        except Exception as e2:
            fatal(f"WALLET_SECRET base64/DER load failed: {e2}\nOriginal error: {e}")

if not private_key:
    fatal("Failed to obtain a private key from WALLET_SECRET.")

# Create JWT
try:
    token = jwt.encode(payload, private_key, algorithm="ES256", headers={"typ": "JWT"})
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    print(token)
except Exception as e:
    fatal(f"Failed to sign JWT: {e}")
