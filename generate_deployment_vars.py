#!/usr/bin/env python3
"""
Generate Deployment Environment Variables

This script reads the locked credentials and outputs them in a format
ready for copy-paste into deployment platforms (Railway, Render, etc.)

Usage:
    python3 generate_deployment_vars.py           # Show for Railway/Render
    python3 generate_deployment_vars.py --docker  # Show for Docker
    python3 generate_deployment_vars.py --json    # Show as JSON
"""

import os
import sys
import json

# Try to load from locked credentials file
try:
    from dotenv import dotenv_values
    
    if os.path.exists('.env.kraken_users_locked'):
        env_vars = dotenv_values('.env.kraken_users_locked')
        print("✅ Loaded from .env.kraken_users_locked\n")
    else:
        print("❌ Error: .env.kraken_users_locked not found")
        print("   This file should contain the locked Kraken credentials")
        sys.exit(1)
        
except ImportError:
    print("❌ Error: python-dotenv not installed")
    print("   Install with: pip install python-dotenv")
    sys.exit(1)

# Extract only the Kraken user credentials
kraken_vars = {
    k: v for k, v in env_vars.items() 
    if k.startswith('KRAKEN_USER_')
}

if not kraken_vars:
    print("❌ Error: No KRAKEN_USER_* variables found in .env.kraken_users_locked")
    sys.exit(1)

# Check for required variables
required_vars = [
    'KRAKEN_USER_DAIVON_API_KEY',
    'KRAKEN_USER_DAIVON_API_SECRET',
    'KRAKEN_USER_TANIA_API_KEY',
    'KRAKEN_USER_TANIA_API_SECRET'
]

missing_vars = [v for v in required_vars if v not in kraken_vars]
if missing_vars:
    print(f"⚠️  Warning: Missing variables: {', '.join(missing_vars)}\n")

# Determine output format
use_docker = '--docker' in sys.argv
use_json = '--json' in sys.argv

if use_json:
    # JSON format (for API deployments)
    print("=" * 80)
    print("JSON FORMAT (for API deployments)")
    print("=" * 80)
    print()
    print(json.dumps(kraken_vars, indent=2))
    print()
    
elif use_docker:
    # Docker ENV format
    print("=" * 80)
    print("DOCKER ENV FORMAT")
    print("=" * 80)
    print()
    print("# Add to docker-compose.yml under 'environment:' or to Dockerfile ENV")
    print()
    for key, value in kraken_vars.items():
        print(f"{key}={value}")
    print()
    
else:
    # Railway/Render format (default)
    print("=" * 80)
    print("DEPLOYMENT ENVIRONMENT VARIABLES")
    print("Copy-paste these into Railway or Render")
    print("=" * 80)
    print()
    
    # Group by user
    daivon_vars = {k: v for k, v in kraken_vars.items() if 'DAIVON' in k}
    tania_vars = {k: v for k, v in kraken_vars.items() if 'TANIA' in k}
    
    if daivon_vars:
        print("# Daivon Frazier Credentials")
        print("-" * 80)
        for key, value in daivon_vars.items():
            print(f"{key}={value}")
        print()
    
    if tania_vars:
        print("# Tania Gilbert Credentials")
        print("-" * 80)
        for key, value in tania_vars.items():
            print(f"{key}={value}")
        print()

# Print instructions
print("=" * 80)
print("DEPLOYMENT INSTRUCTIONS")
print("=" * 80)
print()

if use_json:
    print("For API-based deployments:")
    print("  1. Use this JSON in your deployment API calls")
    print("  2. Or convert to platform-specific format")
    
elif use_docker:
    print("For Docker deployments:")
    print("  1. Add these to docker-compose.yml under 'environment:'")
    print("  2. Or use a .env file with these values")
    print("  3. Start with: docker-compose up")
    
else:
    print("For Railway:")
    print("  1. Go to https://railway.app/dashboard")
    print("  2. Select your NIJA project → service")
    print("  3. Click 'Variables' tab")
    print("  4. Click 'New Variable' for each variable above")
    print("  5. Copy the name and value exactly as shown")
    print("  6. Railway will auto-deploy")
    print()
    print("For Render:")
    print("  1. Go to https://dashboard.render.com")
    print("  2. Select your NIJA service")
    print("  3. Click 'Environment' tab")
    print("  4. Click 'Add Environment Variable' for each")
    print("  5. Copy the name and value exactly as shown")
    print("  6. Click 'Save Changes' → 'Manual Deploy'")

print()
print("=" * 80)

# Print verification
print()
print("✅ Credentials ready for deployment!")
print(f"   Total variables: {len(kraken_vars)}")
print(f"   Daivon variables: {len([k for k in kraken_vars if 'DAIVON' in k])}")
print(f"   Tania variables: {len([k for k in kraken_vars if 'TANIA' in k])}")
print()
