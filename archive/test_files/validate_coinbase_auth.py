# validate_coinbase_auth.py
import os, time, json
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.backends import default_backend
import base64
import hashlib

logger.remove()
logger.add(lambda msg: print(msg, end=""))

ORG = os.environ.get("COINBASE_ORG_ID")
API_KEY = os.environ.get("COINBASE_API_KEY")
PEM_RAW = os.environ.get("COINBASE_PEM_CONTENT")

if not (ORG and API_KEY and PEM_RAW):
    logger.error("Missing one or more env vars: COINBASE_ORG_ID / COINBASE_API_KEY / COINBASE_PEM_CONTENT")
    raise SystemExit(1)

# Fix literal "\n" -> actual newlines if needed
if "\\n" in PEM_RAW:
    PEM = PEM_RAW.replace("\\n", "\n")
else:
    PEM = PEM_RAW

# Ensure trailing newline
if not PEM.endswith("\n"):
    PEM = PEM + "\n"

logger.info(f"PEM length: {len(PEM)}\nAPI_KEY length: {len(API_KEY)}\nORG length: {len(ORG)}\n")

# Load private key (try PEM deserialization)
try:
    priv = serialization.load_pem_private_key(PEM.encode('utf-8'), password=None, backend=default_backend())
    logger.success("Loaded PEM private key OK.")
except Exception as e:
    logger.error(f"Failed to load PEM private key: {e}")
    raise

def sign_es256(message: bytes) -> str:
    # Use cryptography to sign and return base64url signature (r||s)
    signature = priv.sign(message, ec.ECDSA(hashes.SHA256()))
    # ECDSA signature is DER; convert to r|s raw then base64url
    # decode DER signature to (r, s)
    from asn1crypto import core as asn1core  # optional; if not available, use helper below
    try:
        # If asn1crypto available:
        class ECDSASignature(asn1core.Sequence):
            _fields = [('r', asn1core.Integer), ('s', asn1core.Integer)]
        parsed = ECDSASignature.load(signature)
        r = int(parsed['r'])
        s = int(parsed['s'])
    except Exception:
        # fallback parse DER manually (works in many cases)
        from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
        r, s = decode_dss_signature(signature)

    r_bytes = r.to_bytes(32, 'big')
    s_bytes = s.to_bytes(32, 'big')
    raw = r_bytes + s_bytes
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')

def make_jwt(payload: dict, kid_header: str):
    header = {"alg": "ES256", "typ": "JWT", "kid": kid_header}
    header_b = base64.urlsafe_b64encode(json.dumps(header, separators=(',',':')).encode()).rstrip(b'=')
    payload_b = base64.urlsafe_b64encode(json.dumps(payload, separators=(',',':')).encode()).rstrip(b'=')
    signing_input = header_b + b'.' + payload_b
    signature = sign_es256(signing_input)
    token = signing_input.decode() + "." + signature
    return token

# Try both payload variants: sub=ORG and sub=API_KEY
now = int(time.time())
payloads = [
    {"sub": ORG, "iat": now, "exp": now + 300, "jti": str(now)},
    {"sub": API_KEY, "iat": now, "exp": now + 300, "jti": str(now)}
]

endpoints = [
    ("v2_accounts", "https://api.coinbase.com/v2/accounts"),
    ("brokerage_org_accounts", f"https://api.coinbase.com/api/v3/brokerage/organizations/{ORG}/accounts")
]

for p in payloads:
    label = "sub=ORG" if p["sub"]==ORG else "sub=API_KEY"
    logger.info(f"\n--- Trying JWT with {label} ---")
    try:
        token = make_jwt(p, kid_header=API_KEY)
        logger.info("JWT preview: " + token[:80] + "...\n")
    except Exception as e:
        logger.error("JWT creation failed: " + repr(e))
        continue

    headers = {"Authorization": f"Bearer {token}", "CB-VERSION": "2025-11-13", "User-Agent":"nija-validator/1.0"}
    for ep_name, url in endpoints:
        try:
            r = requests.get(url, headers=headers, timeout=10)
            logger.info(f"Endpoint: {ep_name} -> status {r.status_code}")
            # print a short version of body
            body = r.text[:800].replace("\n","\\n")
            logger.info("Body (truncated): " + body + "\n")
        except Exception as e:
            logger.error(f"HTTP request to {url} failed: {e}")

logger.info("Done. If all attempts returned 401, check API key permissions, key/PEM pairing, or rotate key in Coinbase dashboard.")
