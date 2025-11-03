#!/usr/bin/env python3
"""
Generate a Coinbase Wallet JWT for NIJA bot authentication.
Uses environment variables:
  - COINBASE_API_KEY
  - COINBASE_API_SECRET
"""

import os
import time
import jwt  # PyJWT

# --- Load credentials ---
api_key = os.getenv("COINBASE_API_KEY")
api_secret = os.getenv("COINBASE_API_SECRET")

if not api_key or not api_secret:
    raise SystemExit("❌ Missing COINBASE_API_KEY or COINBASE_API_SECRET environment variables.")

# --- Build JWT payload ---
now = int(time.time())
payload = {
    "sub": api_key,       # Coinbase API key ID
    "iss": "coinbase-python",  # Issuer (optional label)
    "iat": now,           # Issued at
    "exp": now + 300,     # Expiration (5 minutes)
}

# --- Generate JWT ---
try:
    token = jwt.encode(payload, api_secret, algorithm="HS256")
    print(token)
except Exception as e:
    raise SystemExit(f"❌ Error generating JWT: {e}")
