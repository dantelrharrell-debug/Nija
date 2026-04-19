#!/usr/bin/env python3
"""
NIJA State Transition Grep Filter
==================================
Runs the heartbeat trade and filters logs for state transitions only.
"""

import os
import sys
import subprocess
import threading
import queue
import time

# Enable heartbeat trade and limit output
os.environ['HEARTBEAT_TRADE'] = 'true'

# Keywords we're watching for
STATE_KEYWORDS = [
    'LIVE_ACTIVE',
    'CA_READY',
    'WAIT_PLATFORM',
    'READY',
    'ORDER',
    'FILLED',
    'REJECTED',
    'HEARTBEAT',
    'payload_hydrated',
]

print("\n" + "="*70)
print("🔍 NIJA HEARTBEAT DIAGNOSTIC - State Transitions Only")
print("="*70)
print("\nMonitoring for state transitions:")
for kw in STATE_KEYWORDS:
    print(f"  • {kw}")
print("\n" + "="*70 + "\n")

# Start bot process
proc = subprocess.Popen(
    [sys.executable, 'bot.py'],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    bufsize=1
)

# Queue for output lines
output_queue = queue.Queue()

def stream_output():
    """Stream bot output and filter for state transitions"""
    transition_count = 0
    
    for line in proc.stdout:
        line = line.rstrip('\n')
        
        # Check if line contains any state keyword
        has_transition = any(kw in line for kw in STATE_KEYWORDS)
        
        if has_transition:
            transition_count += 1
            print(f"\n[TRANSITION #{transition_count}] {line}")
        elif any(kw in line.upper() for kw in ['ERROR', 'CRITICAL', 'FAILED']):
            # Also show errors
            print(f"\n[ERROR] {line}")
    
    proc.wait()
    print(f"\n📊 Total transitions captured: {transition_count}")
    return transition_count

try:
    stream_output()
    print("\n✅ Heartbeat diagnostic complete")
except KeyboardInterrupt:
    print("\n\n✋ Diagnostic interrupted")
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    sys.exit(0)
