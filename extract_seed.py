from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# Paste your PEM here as a multi-line string
pem_data = b"""
-----BEGIN EC PRIVATE KEY-----
MHcCAQEEIB7MOrFbx1Kfc/DxXZZ3Gz4Y2hVY9SbcfUHPiuQmLSPxoAoGCCqGSM49
AwEHoUQDQgAEiFR+zABGG0DB0HFgjo69cg3tY1Wt41T1gtQp3xrMnvWwio96ifmk
Ah1eXfBIuinsVEJya4G9DZ01hzaF/edTIw==
-----END EC PRIVATE KEY-----
"""

# Load the EC private key
private_key = serialization.load_pem_private_key(
    pem_data,
    password=None,
    backend=default_backend()
)

# Extract the raw private numbers (this is your 32-byte seed)
private_numbers = private_key.private_numbers()
raw_seed = private_numbers.private_value.to_bytes(32, "big")

print("Raw 32-byte seed (base64):", raw_seed.hex())  # or use base64.b64encode(raw_seed)
