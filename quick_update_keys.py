#!/usr/bin/env python3
"""
Simple .env updater - paste your credentials here directly
"""
import os
from pathlib import Path
import shutil

# ============================================================================
# PASTE YOUR NEW CREDENTIALS HERE:
# ============================================================================

NEW_API_KEY = "organizations/ce77e4ea-ecca-42ec-912a-b6b4455ab9d0/apiKeys/05067708-2a5d-43a5-a4c6-732176c05e7c"

NEW_API_SECRET = """-----BEGIN EC PRIVATE KEY-----
MHcCAQEEIIpbqWDgEUayl0/GuwoWe04zjdwyliPABAzHTRlzhJbFoAoGCCqGSM49
AwEHoUQDQgAEqoQqw6ZbWDfB1ElbpHfYAJCBof7ala7v5e3TqqiWiYqtprUajjD+
mqoVbKN6pqHMcnFwC86rM/jRId+1rgf31A==
-----END EC PRIVATE KEY-----"""

# ============================================================================
# Script will update .env automatically
# ============================================================================

print("\n" + "="*80)
print("🔑 UPDATING API KEYS IN .ENV")
print("="*80)

# Validate
if not NEW_API_KEY or 'apiKeys' not in NEW_API_KEY:
    print("\n❌ Invalid API key!")
    print(f"   Got: {NEW_API_KEY}")
    exit(1)

if "BEGIN EC PRIVATE KEY" not in NEW_API_SECRET:
    print("\n❌ Invalid PEM format!")
    exit(1)

print(f"\n✅ API Key: {NEW_API_KEY[:50]}...")
print(f"✅ Secret: (PEM format validated)")

# Backup .env
env_path = Path('.env')
if env_path.exists():
    backup_path = Path('.env.backup')
    shutil.copy(env_path, backup_path)
    print(f"\n✅ Backed up .env → .env.backup")

# Read current .env
env_content = {}
if env_path.exists():
    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                env_content[key.strip()] = val.strip()

# Update keys
env_content['COINBASE_API_KEY'] = NEW_API_KEY
env_content['COINBASE_API_SECRET'] = NEW_API_SECRET.replace('\n', '\\n')

# Write .env
with open(env_path, 'w') as f:
    for key, val in env_content.items():
        f.write(f"{key}={val}\n")

print(f"\n✅ Updated .env file!")

print("\n" + "="*80)
print("🧪 TESTING NEW CREDENTIALS...")
print("="*80 + "\n")

# Test
import sys
sys.exit(os.system("python3 find_my_157.py"))
