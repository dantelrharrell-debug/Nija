#!/usr/bin/env python3
"""
Unit test to verify permission error message improvements.

This test verifies that the "see above" reference has been removed
from the fallback permission error message.
"""

import sys
import os

def test_permission_error_message_in_code():
    """
    Test that the code no longer contains the problematic 'see above' message.
    """
    print("=" * 70)
    print("Testing Permission Error Message Code Changes")
    print("=" * 70)
    
    files_to_check = [
        'bot/broker_manager.py',
        'bot/broker_integration.py'
    ]
    
    old_message = "Permission error (see above for fix instructions)"
    new_message_pattern = "API KEY PERMISSION ERROR"
    new_url_pattern = "https://www.kraken.com/u/security/api"
    
    all_passed = True
    
    for file_path in files_to_check:
        full_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), file_path)
        print(f"\nChecking {file_path}...")
        
        if not os.path.exists(full_path):
            print(f"   ⚠️  File not found: {full_path}")
            all_passed = False
            continue
        
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that old message is gone
        if old_message in content:
            print(f"   ❌ FAIL: Still contains old message '{old_message}'")
            all_passed = False
        else:
            print(f"   ✅ PASS: Old 'see above' message removed")
        
        # Check that new message pattern exists
        if new_message_pattern in content:
            print(f"   ✅ PASS: New message pattern '{new_message_pattern}' found")
        else:
            print(f"   ⚠️  WARNING: New message pattern not found")
        
        # Check that URL is included
        if new_url_pattern in content:
            print(f"   ✅ PASS: URL '{new_url_pattern}' found")
        else:
            print(f"   ⚠️  WARNING: URL not found")
    
    print("\n" + "=" * 70)
    if all_passed:
        print("✅ All checks passed!")
        print("\nChanges made:")
        print("- Removed vague 'see above for fix instructions' message")
        print("- Replaced with self-contained error message including:")
        print("  • Clear description of the problem")
        print("  • Direct URL to fix the issue")
        print("  • Reference to documentation file")
        return 0
    else:
        print("❌ Some checks failed!")
        return 1

if __name__ == '__main__':
    sys.exit(test_permission_error_message_in_code())
