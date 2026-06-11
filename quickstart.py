#!/usr/bin/env python3
"""
NIJA Quick Start Script
=======================

Run this to start the bot with proper environment setup and timeout increases.

Usage:
    python quickstart.py

Environment variables set:
    - NIJA_BOOTSTRAP_BROKERS_READY_TIMEOUT_S=120 (extended timeout)
    - NIJA_BOOTSTRAP_STRATEGY_READY_TIMEOUT_S=120
    - NIJA_BOOTSTRAP_RUNNING_SUPERVISED_TIMEOUT_S=120
    - LIVE_CAPITAL_VERIFIED=true (if set)
"""

import os
import sys
import subprocess
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger("quickstart")

# Ensure extended timeouts for all bootstrap phases
env = os.environ.copy()
env.update({
    "NIJA_BOOTSTRAP_PRECHECK_TIMEOUT_S": "120",
    "NIJA_BOOTSTRAP_LOCK_ACQUIRED_TIMEOUT_S": "120",
    "NIJA_BOOTSTRAP_HEARTBEATS_READY_TIMEOUT_S": "120",
    "NIJA_BOOTSTRAP_FSM_READY_TIMEOUT_S": "120",
    "NIJA_BOOTSTRAP_BROKERS_READY_TIMEOUT_S": "120",
    "NIJA_BOOTSTRAP_STRATEGY_READY_TIMEOUT_S": "120",
    "NIJA_BOOTSTRAP_RUNNING_SUPERVISED_TIMEOUT_S": "120",
    "PYTHONUNBUFFERED": "1",
})

logger.info("🚀 NIJA Quick Start")
logger.info("=" * 60)
logger.info("Bootstrap timeouts set to 120s (extended)")
logger.info("Starting bot...")
logger.info("=" * 60)

# Start the bot
cmd = [sys.executable, "-m", "bot.bot_main"]
logger.info(f"Running: {' '.join(cmd)}")

try:
    result = subprocess.run(cmd, env=env, check=False)
    sys.exit(result.returncode)
except KeyboardInterrupt:
    logger.info("🛑 Shutdown requested")
    sys.exit(0)
except Exception as e:
    logger.error(f"❌ Error: {e}")
    sys.exit(1)
