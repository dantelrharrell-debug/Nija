# check_coinbase_key.py
import os
import hashlib
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# 🔹 Load environment variables
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")   # short UUID
COINBASE_API_SUB = os.getenv("COINBASE_API_SUB")         # full path
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT") # PEM block

if not COINBASE_ORG_ID or not COINBASE_API_KEY_ID or not COINBASE_API_SUB or not COINBASE_PEM_CONTENT:
    raise SystemExit("❌ Missing required env vars: COINBASE_ORG_ID, COINBASE_API_KEY_ID, COINBASE_API_SUB, COINBASE_PEM_CONTENT")

# 🔹 Load PEM
pem_text = COINBASE_PEM_CONTENT.replace("\\n", "\n").strip()
try:
    private_key = serialization.load_pem_private_key(
        pem_text.encode(), password=None, backend=default_backend()
    )
    print("✅ PEM loaded successfully")
except Exception as e:
    raise SystemExit(f"❌ Failed to load PEM: {e}")

# 🔹 Compute PEM fingerprint (SHA256)
pem_bytes = private_key.private_bytes(
    encoding=serialization.Encoding.DER,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption()
)
fingerprint = hashlib.sha256(pem_bytes).hexdigest()
print(f"🔹 PEM SHA256 fingerprint: {fingerprint}")

# 🔹 Print key info
print(f"🔹 Coinbase Org ID: {COINBASE_ORG_ID}")
print(f"🔹 Short API Key ID (sub): {COINBASE_API_KEY_ID}")
print(f"🔹 Full API Key path (kid): {COINBASE_API_SUB}")

# 🔹 Quick validation
if not COINBASE_API_SUB.endswith(COINBASE_API_KEY_ID):
    print("⚠️ Warning: COINBASE_API_SUB does not end with short key ID — JWT will 401 if not corrected.")
else:
    print("✅ COINBASE_API_SUB matches short key ID")
