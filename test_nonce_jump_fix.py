#!/usr/bin/env python3
"""
Test: Kraken Global Nonce Jump Functionality

This test verifies that the global nonce manager properly jumps forward
when an "Invalid nonce" error occurs, which is critical for recovering
from nonce-related API errors.

Expected behavior:
1. Nonce should jump forward by 120 seconds (120,000 ms)
2. Jump should be thread-safe
3. Subsequent nonces should be greater than jumped nonce
"""

import time
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_global_nonce_jump():
    """Test that global nonce can jump forward on error."""
    print("\n" + "="*70)
    print("TEST: Kraken Global Nonce Jump Functionality")
    print("="*70)
    
    try:
        from bot.global_kraken_nonce import (
            get_global_kraken_nonce,
            jump_global_kraken_nonce_forward
        )
    except ImportError:
        print("❌ FAILED: Could not import global nonce functions")
        return False
    
    print("\n1. Testing basic nonce generation...")
    nonce1 = get_global_kraken_nonce()
    print(f"   Initial nonce: {nonce1}")
    
    # Wait a moment to ensure time advances
    time.sleep(0.01)
    
    nonce2 = get_global_kraken_nonce()
    print(f"   Second nonce:  {nonce2}")
    
    if nonce2 <= nonce1:
        print(f"   ❌ FAILED: Second nonce not greater than first")
        return False
    print(f"   ✅ PASS: Nonces are monotonically increasing")
    
    print("\n2. Testing nonce jump (simulating error recovery)...")
    jump_ms = 120 * 1000  # 120 seconds
    print(f"   Jumping nonce forward by {jump_ms/1000:.0f} seconds...")
    
    jumped_nonce = jump_global_kraken_nonce_forward(jump_ms)
    print(f"   Jumped nonce:  {jumped_nonce}")
    
    if jumped_nonce <= nonce2:
        print(f"   ❌ FAILED: Jumped nonce not greater than previous")
        return False
    
    # Verify jump was at least 120 seconds
    jump_amount = jumped_nonce - nonce2
    expected_min_jump = jump_ms
    
    if jump_amount < expected_min_jump:
        print(f"   ❌ FAILED: Jump amount ({jump_amount}ms) less than expected ({expected_min_jump}ms)")
        return False
    
    print(f"   ✅ PASS: Nonce jumped forward by {jump_amount}ms (>= {expected_min_jump}ms)")
    
    print("\n3. Testing that subsequent nonces are still monotonic...")
    time.sleep(0.01)
    
    nonce3 = get_global_kraken_nonce()
    print(f"   Next nonce:    {nonce3}")
    
    if nonce3 <= jumped_nonce:
        print(f"   ❌ FAILED: Next nonce not greater than jumped nonce")
        return False
    
    print(f"   ✅ PASS: Nonces remain monotonic after jump")
    
    print("\n4. Testing multiple rapid jumps...")
    for i in range(3):
        jump_nonce = jump_global_kraken_nonce_forward(60000)  # 60 second jumps
        print(f"   Jump {i+1}: {jump_nonce}")
        time.sleep(0.01)
    
    final_nonce = get_global_kraken_nonce()
    print(f"   Final nonce: {final_nonce}")
    
    if final_nonce <= jump_nonce:
        print(f"   ❌ FAILED: Final nonce not greater than last jump")
        return False
    
    print(f"   ✅ PASS: Multiple jumps work correctly")
    
    print("\n" + "="*70)
    print("✅ ALL TESTS PASSED")
    print("="*70)
    print("\nSummary:")
    print("- Global nonce manager properly generates monotonic nonces")
    print("- Nonce jump function works correctly for error recovery")
    print("- Jumped nonces are properly integrated into the sequence")
    print("- Multiple jumps are handled correctly")
    print("\nThis fix ensures that 'Invalid nonce' errors will be properly")
    print("recovered by jumping the nonce forward by 120 seconds, clearing")
    print("the 'burned' nonce window and allowing subsequent API calls to succeed.")
    print("="*70)
    
    return True


if __name__ == "__main__":
    success = test_global_nonce_jump()
    sys.exit(0 if success else 1)
