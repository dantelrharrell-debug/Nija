#!/usr/bin/env python3
"""
Test what format the credentials are in
"""
import os

# Load .env
if os.path.isfile(".env"):
    with open(".env") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key not in os.environ:
                os.environ[key] = value

api_key = os.getenv("COINBASE_API_KEY", "")
api_secret = os.getenv("COINBASE_API_SECRET", "")

print("API Key format check:")
print(f"  Length: {len(api_key)}")
print(f"  Starts with: {api_key[:30]}..." if len(api_key) > 30 else f"  Full: {api_key}")
print()
print("API Secret format check:")
print(f"  Length: {len(api_secret)}")
print(f"  First 50 chars: {api_secret[:50]}")
print(f"  Contains 'BEGIN': {'BEGIN' in api_secret}")
print(f"  Contains 'END': {'END' in api_secret}")
print(f"  Contains '\\n': {'\\n' in api_secret}")
print()

if "BEGIN" in api_secret:
    print("⚠️  API_SECRET looks like a PEM key!")
    print("    For Advanced Trade, this should be a simple secret string")
    print("    NOT a PEM-formatted private key")
else:
    print("✅ API_SECRET looks correct (not PEM format)")
