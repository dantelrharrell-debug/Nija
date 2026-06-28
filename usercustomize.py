"""User-level startup defaults for NIJA runtime."""

import os

# US OKX accounts require the US regional API host. Keep an explicit Railway
# OKX_BASE_URL override if one is provided; otherwise default to us.okx.com.
os.environ.setdefault("OKX_BASE_URL", "https://us.okx.com")
os.environ.setdefault("OKX_US_REGION", "true")
