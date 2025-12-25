#!/usr/bin/env python3
"""
Helper script to update API keys in .env file
Run this after creating new API keys with proper permissions
"""
import os
from pathlib import Path

print("\n" + "="*80)
print("🔑 UPDATE COINBASE API KEYS")
print("="*80)

print("\n⚠️  You need to create new API keys first!")
print("\nFollow these steps:")
print("1. Go to: https://www.coinbase.com/settings/api")
print("2. Click 'New API Key' → 'Cloud API Trading Keys'")
print("3. Enable permissions: View, Trade, Transfer, Portfolio Management")
print("4. Select 'All portfolios' or specifically 'Nija' portfolio")
print("5. Download the key file")
print("\n" + "="*80)

print("\n📝 Enter your NEW API credentials:")
print("(Press Ctrl+C to cancel)\n")

try:
    api_key = input("API Key Name (looks like 'organizations/xxx/apiKeys/xxx'): ").strip()
    print("\nAPI Secret (PEM format):")
    print("Paste the FULL private key including:")
    print("  -----BEGIN EC PRIVATE KEY-----")
    print("  (your key content)")
    print("  -----END EC PRIVATE KEY-----")
    print("\nWhen done, press Enter twice:\n")
    
    pem_lines = []
    while True:
        line = input()
        if line == "" and len(pem_lines) > 0 and "END EC PRIVATE KEY" in pem_lines[-1]:
            break
        pem_lines.append(line)
    
    api_secret = "\n".join(pem_lines)
    
    # Validate
    if not api_key or 'apiKeys' not in api_key:
        print("\n❌ Invalid API key format!")
        exit(1)
    
    if "BEGIN EC PRIVATE KEY" not in api_secret or "END EC PRIVATE KEY" not in api_secret:
        print("\n❌ Invalid PEM format!")
        exit(1)
    
    # Backup existing .env
    env_path = Path('.env')
    if env_path.exists():
        backup_path = Path('.env.backup')
        import shutil
        shutil.copy(env_path, backup_path)
        print(f"\n✅ Backed up existing .env to .env.backup")
    
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
    env_content['COINBASE_API_KEY'] = api_key
    env_content['COINBASE_API_SECRET'] = api_secret.replace('\n', '\\n')
    
    # Write updated .env
    with open(env_path, 'w') as f:
        for key, val in env_content.items():
            f.write(f"{key}={val}\n")
    
    print("\n✅ Updated .env file successfully!")
    print("\n" + "="*80)
    print("🧪 TESTING NEW CREDENTIALS...")
    print("="*80 + "\n")
    
    # Test the new credentials
    os.system("python3 find_my_157.py")
    
except KeyboardInterrupt:
    print("\n\n❌ Cancelled")
    exit(1)
except Exception as e:
    print(f"\n❌ Error: {e}")
    exit(1)
