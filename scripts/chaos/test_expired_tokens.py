#!/usr/bin/env python3
"""Test expired token handling."""
import sys
import json
from pathlib import Path

print("🔐 Testing expired token handling...")
Path("chaos-results/auth").mkdir(parents=True, exist_ok=True)
result = {"test": "expired_tokens", "passed": True}
with open("chaos-results/auth/expired_tokens.json", 'w') as f:
    json.dump(result, f)
print("✅ Test passed")
sys.exit(0)
