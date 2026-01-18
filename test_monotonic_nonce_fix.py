#!/usr/bin/env python3
"""
Quick validation test for monotonic nonce generator fix.

This test demonstrates that the nonce generator now uses
simple +1 increment (NOT time-based) per Kraken requirements.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from global_kraken_nonce import get_global_kraken_nonce, get_global_nonce_manager

def test_monotonic_increment():
    """Verify that nonces use simple +1 increment, not time-based generation."""
    print("=" * 70)
    print("MONOTONIC NONCE GENERATOR VALIDATION")
    print("=" * 70)
    print()
    print("Testing that nonces use simple +1 increment (NOT time-based)")
    print()
    
    # Get manager and reset for clean test
    manager = get_global_nonce_manager()
    manager.reset_for_testing()
    
    # Get first nonce
    nonce1 = get_global_kraken_nonce()
    print(f"Nonce 1: {nonce1}")
    
    # Get several more nonces rapidly
    nonces = [nonce1]
    for i in range(2, 11):
        nonce = get_global_kraken_nonce()
        nonces.append(nonce)
        print(f"Nonce {i}: {nonce}")
    
    print()
    print("Analyzing increment pattern...")
    print()
    
    # Check increments
    all_increments_are_one = True
    for i in range(1, len(nonces)):
        increment = nonces[i] - nonces[i-1]
        is_one = (increment == 1)
        symbol = "✅" if is_one else "❌"
        print(f"{symbol} Nonce {i+1} - Nonce {i} = {increment} (expected: 1)")
        if not is_one:
            all_increments_are_one = False
    
    print()
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    print()
    
    if all_increments_are_one:
        print("✅ SUCCESS: All nonces use simple +1 increment")
        print("✅ NOT time-based (each nonce = previous + 1)")
        print("✅ TRULY MONOTONIC (guaranteed strictly increasing)")
        print("✅ Kraken requirement met: 'Use monotonic nonce generator'")
        print()
        print("The nonce generator is now CORRECT and compliant!")
        return True
    else:
        print("❌ FAILURE: Nonces are NOT using simple +1 increment")
        print("❌ Still time-based or using other logic")
        print("❌ Does not meet Kraken requirement")
        return False

if __name__ == "__main__":
    success = test_monotonic_increment()
    sys.exit(0 if success else 1)
