#!/usr/bin/env python3
"""
Quick verification script to check if Kraken nonce isolation is working correctly.

This script can be run in production to verify:
1. Each account has its own nonce file
2. Nonce files exist and contain valid values
3. MASTER account was migrated from legacy file (if applicable)

Run this AFTER deploying the nonce isolation fix.
"""

import os
import sys
from pathlib import Path

def check_nonce_isolation():
    """Verify that Kraken accounts use isolated nonce files."""
    print()
    print("=" * 70)
    print("🔍 KRAKEN NONCE ISOLATION VERIFICATION")
    print("=" * 70)
    print()
    
    # Check data directory exists
    data_dir = Path(__file__).parent / "data"
    if not data_dir.exists():
        print("❌ FAIL: Data directory not found")
        print(f"   Expected: {data_dir}")
        return False
    
    print(f"✅ Data directory exists: {data_dir}")
    print()
    
    # Expected nonce files
    expected_files = {
        "MASTER": "kraken_nonce_master.txt",
        "Daivon": "kraken_nonce_user_daivon_frazier.txt",
        "Tania": "kraken_nonce_user_tania_gilbert.txt"
    }
    
    # Check each expected file
    print("Checking nonce files...")
    print("-" * 70)
    
    all_files_ok = True
    nonce_values = {}
    
    for account_name, filename in expected_files.items():
        file_path = data_dir / filename
        
        if file_path.exists():
            print(f"✅ {account_name:10s}: {filename}")
            
            # Read and validate nonce value
            try:
                with open(file_path, 'r') as f:
                    nonce_str = f.read().strip()
                    nonce = int(nonce_str)
                    nonce_values[account_name] = nonce
                    print(f"   Nonce value: {nonce}")
                    
                    # Validate nonce is reasonable (should be recent microseconds timestamp)
                    import time
                    current_us = int(time.time() * 1000000)
                    age_seconds = (current_us - nonce) / 1000000.0
                    
                    if abs(age_seconds) > 3600:  # More than 1 hour difference
                        print(f"   ⚠️  WARNING: Nonce age: {age_seconds:.1f}s (might be stale or too far in future)")
                    else:
                        print(f"   ✅ Nonce age: {age_seconds:.1f}s (looks good)")
                        
            except (ValueError, IOError) as e:
                print(f"   ❌ ERROR reading nonce: {e}")
                all_files_ok = False
        else:
            print(f"⚠️  {account_name:10s}: {filename} NOT FOUND")
            print(f"   This is OK if {account_name} account hasn't initialized yet")
    
    print()
    
    # Check for legacy file (should not be used anymore)
    print("Checking for legacy nonce file...")
    print("-" * 70)
    legacy_file = data_dir / "kraken_nonce.txt"
    
    if legacy_file.exists():
        print(f"⚠️  Legacy file exists: {legacy_file}")
        print(f"   This file is no longer used (replaced by kraken_nonce_master.txt)")
        print(f"   It's safe to delete after confirming MASTER migrated successfully")
        
        # Read legacy nonce for comparison
        try:
            with open(legacy_file, 'r') as f:
                legacy_nonce = int(f.read().strip())
                print(f"   Legacy nonce value: {legacy_nonce}")
                
                if "MASTER" in nonce_values:
                    if nonce_values["MASTER"] >= legacy_nonce:
                        print(f"   ✅ MASTER nonce >= legacy nonce (migration successful)")
                    else:
                        print(f"   ❌ MASTER nonce < legacy nonce (migration may have failed!)")
                        all_files_ok = False
        except (ValueError, IOError) as e:
            print(f"   ⚠️  Could not read legacy nonce: {e}")
    else:
        print(f"✅ No legacy file found (clean state)")
    
    print()
    
    # Check for nonce collisions (all nonce values should be different)
    if len(nonce_values) > 1:
        print("Checking for nonce collisions...")
        print("-" * 70)
        
        unique_nonces = set(nonce_values.values())
        if len(unique_nonces) == len(nonce_values):
            print(f"✅ All {len(nonce_values)} accounts have unique nonce values")
        else:
            print(f"❌ COLLISION DETECTED: {len(nonce_values)} accounts but only {len(unique_nonces)} unique nonces")
            all_files_ok = False
        
        print()
    
    # Summary
    print("=" * 70)
    if all_files_ok:
        print("✅ VERIFICATION PASSED")
        print()
        print("Kraken nonce isolation is working correctly:")
        print(f"  • {len(nonce_values)} account(s) have valid nonce files")
        print(f"  • All nonce values are unique")
        print(f"  • No collisions detected")
        print()
        print("Expected behavior:")
        print("  • Each Kraken account uses its own nonce file")
        print("  • No 'Invalid nonce' errors should occur")
        print("  • Copy trading should work for all enabled users")
        print()
        return True
    else:
        print("❌ VERIFICATION FAILED")
        print()
        print("Issues detected - see messages above.")
        print("If USER accounts haven't initialized yet, this is expected.")
        print("Run this script again after the bot fully starts up.")
        print()
        return False

def main():
    """Run the verification."""
    try:
        success = check_nonce_isolation()
        return 0 if success else 1
    except Exception as e:
        print()
        print("=" * 70)
        print("❌ VERIFICATION ERROR")
        print("=" * 70)
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        print()
        return 1

if __name__ == "__main__":
    sys.exit(main())
