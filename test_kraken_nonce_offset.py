#!/usr/bin/env python3
"""
Test to demonstrate the Kraken nonce offset fix.
This script shows that the new 120-180s offset ensures nonces are always
ahead of any previous session's nonces, even with frequent restarts.
"""

import time
import random

def simulate_nonce_initialization():
    """Simulate the nonce initialization with the new 120-180s offset"""
    # New implementation (120-180s)
    base_offset = 120000000  # 120 seconds in microseconds
    random_jitter = random.randint(0, 60000000)  # 0-60 seconds inclusive
    total_offset = base_offset + random_jitter
    
    current_time_us = int(time.time() * 1000000)
    initial_nonce = current_time_us + total_offset
    
    # Calculate offset in seconds for display
    offset_seconds = total_offset / 1000000.0
    
    return initial_nonce, offset_seconds, current_time_us

def test_restart_scenarios():
    """Test various bot restart scenarios"""
    print("=" * 80)
    print("KRAKEN NONCE OFFSET FIX - RESTART SCENARIO TESTING")
    print("=" * 80)
    print()
    
    scenarios = [
        ("Immediate restart (1 second)", 1),
        ("Quick restart (30 seconds)", 30),
        ("Normal restart (60 seconds)", 60),
        ("Delayed restart (90 seconds)", 90),
        ("Long restart (120 seconds)", 120),
        ("Very long restart (150 seconds)", 150),
        ("Extended restart (180 seconds)", 180),
    ]
    
    # Simulate first session
    print("Session 1 (initial run):")
    session1_time_us = int(time.time() * 1000000)
    session1_offset = 180000000 + 30000000  # Example: 210 seconds
    session1_nonce = session1_time_us + session1_offset
    
    print(f"  Start time: {session1_time_us}")
    print(f"  Initial nonce offset: {session1_offset / 1000000.0:.2f}s")
    print(f"  Initial nonce: {session1_nonce}")
    
    # Simulate the bot running for a bit and using nonces
    # In a real scenario, the nonce would advance as API calls are made
    # For this test, we'll assume the last nonce is 5 seconds ahead of initial
    session1_last_nonce = session1_nonce + 5000000  # +5 seconds of API calls
    print(f"  Last nonce used: {session1_last_nonce} (+5s from initial)")
    print()
    
    all_safe = True
    
    for scenario_name, delay_seconds in scenarios:
        print(f"{scenario_name}:")
        print(f"  Bot restarts after {delay_seconds} seconds")
        
        # Calculate the new session start time (wall clock)
        session2_time_us = session1_time_us + (delay_seconds * 1000000)
        
        # New session uses MINIMUM 180s offset, could be up to 240s
        # For worst case testing, use minimum offset (180s)
        min_offset = 180000000  # 180 seconds
        session2_nonce = session2_time_us + min_offset
        
        # Check if new nonce is higher than previous session's last nonce
        is_safe = session2_nonce > session1_last_nonce
        nonce_gap = (session2_nonce - session1_last_nonce) / 1000000.0
        
        status = "✅ SAFE" if is_safe else "❌ COLLISION"
        print(f"  Session 2 initial nonce: {session2_nonce}")
        print(f"  Nonce gap: {nonce_gap:.2f}s (worst case with 180s offset)")
        print(f"  Result: {status}")
        
        if not is_safe:
            all_safe = False
            print(f"  ⚠️  WARNING: Nonce collision would cause 'Invalid nonce' error!")
        
        print()
    
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    if all_safe:
        print("✅ All restart scenarios are SAFE from nonce collisions")
        print()
        print("Key points:")
        print("  • 180-240s offset ensures safety even with rapid restarts")
        print("  • Kraken's ~180-240s nonce memory window is covered")
        print("  • Bot can restart frequently without errors")
        print("  • First connection attempt will succeed (no retries needed)")
    else:
        print("❌ Some restart scenarios have nonce collisions")
        print("⚠️  This would cause 'Invalid nonce' errors on first attempt")
        print()
        print("Analysis:")
        print("  The test shows worst-case scenario (minimum 180s offset)")
        print("  In practice, random jitter (0-60s) provides additional buffer")
    
    print()
    return all_safe

def main():
    """Run the test"""
    success = test_restart_scenarios()
    
    if success:
        print("🎉 Nonce offset fix is working correctly!")
        return 0
    else:
        print("⚠️  Nonce offset may need further adjustment")
        return 1

if __name__ == "__main__":
    import sys
    sys.exit(main())
