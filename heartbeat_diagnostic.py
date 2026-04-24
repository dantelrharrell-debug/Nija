#!/usr/bin/env python3
"""
NIJA Heartbeat Trade Diagnostic
================================
Minimal script to run heartbeat trade with detailed state transition logging.

This bypasses startup banners and logs only state transitions:
- LIVE_ACTIVE
- CA_READY
- WAIT_PLATFORM
- READY
- ORDER / FILLED / REJECTED
"""

import os
import sys
import logging
import time

# Enable heartbeat trade
os.environ['HEARTBEAT_TRADE'] = 'true'

# Configure minimal logging - state transitions only
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger('heartbeat')

# Pre-flight checks
print("\n" + "="*70)
print("🔍 HEARTBEAT TRADE DIAGNOSTIC - State Transition Logging Only")
print("="*70 + "\n")

# Check environment
required_env = ['COINBASE_API_KEY', 'COINBASE_API_SECRET', 'COINBASE_PEM_CONTENT']
missing = [e for e in required_env if not os.getenv(e)]

if missing:
    print(f"❌ Missing environment variables: {', '.join(missing)}")
    print("   Ensure .env file is loaded")
    sys.exit(1)

print("✅ Environment variables: OK")
print("✅ Heartbeat trade: ENABLED")
print("\n" + "="*70)
print("State Transitions Being Monitored:")
print("="*70)
print("  • LIVE_ACTIVE         ← trading state machine")
print("  • CA_READY            ← capital authority hydrated")
print("  • WAIT_PLATFORM       ← broker connection waiting")
print("  • READY               ← capital flow bootstrap complete")
print("  • ORDER / FILLED / REJECTED  ← order execution states")
print("="*70 + "\n")

# Monkey-patch logging to highlight transitions
_original_info = logger.info
_original_debug = logger.debug

def _log_info(msg, *args, **kwargs):
    # Highlight state transitions
    if any(x in str(msg) for x in ['LIVE_ACTIVE', 'CA_READY', 'WAIT_PLATFORM', 'READY', 'ORDER', 'FILLED', 'REJECTED']):
        print(f"\n>>> STATE TRANSITION <<<")
        _original_info(msg, *args, **kwargs)
        print(">>> <<<\n")
    else:
        _original_info(msg, *args, **kwargs)

def _log_debug(msg, *args, **kwargs):
    if any(x in str(msg) for x in ['LIVE_ACTIVE', 'CA_READY', 'WAIT_PLATFORM', 'READY', 'ORDER', 'FILLED', 'REJECTED']):
        _original_info(f"[DEBUG] {msg}", *args, **kwargs)

logger.info = _log_info
logger.debug = _log_debug

# Import and run bot
try:
    logger.info("Importing NIJA bot module...")
    from bot import main
    
    logger.info("Starting heartbeat trade diagnostic...")
    logger.info("")
    
    main()
    
except KeyboardInterrupt:
    logger.info("\n✋ Heartbeat diagnostic interrupted by user")
    sys.exit(0)
except Exception as e:
    logger.error(f"💥 Heartbeat diagnostic failed: {e}", exc_info=True)
    sys.exit(1)
