#!/usr/bin/env python3
"""
NIJA Trading Bot - Main Entry Point
Runs the complete APEX v7.1 strategy with Coinbase Advanced Trade API
Railway deployment: Force redeploy with position size fix ($5 minimum)
"""

import os
import sys
import time
import logging
from logging.handlers import RotatingFileHandler
import signal

# Try to load dotenv if available, but don't fail if not
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not available, env vars should be set externally

# Setup paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

# Import after path setup
from trading_strategy import TradingStrategy

# Setup logging
LOG_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), 'nija.log'))
logger = logging.getLogger("nija")
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')

if not logger.hasHandlers():
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=2*1024*1024, backupCount=2)
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

def _handle_signal(sig, frame):
    logger.info(f"Received signal {sig}, shutting down gracefully")
    sys.exit(0)


def main():
    """Main entry point for NIJA trading bot"""
    # Graceful shutdown handlers to avoid non-zero exits on platform terminations
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info("=" * 70)
    logger.info("NIJA TRADING BOT - APEX v7.1")
    logger.info("Branch: %s", os.getenv("GIT_BRANCH", "unknown"))
    logger.info("Commit: %s", os.getenv("GIT_COMMIT", "unknown"))
    logger.info("=" * 70)
    logger.info(f"Python version: {sys.version.split()[0]}")
    logger.info(f"Log file: {LOG_FILE}")
    logger.info(f"Working directory: {os.getcwd()}")

    # Portfolio override visibility at startup
    portfolio_id = os.environ.get("COINBASE_RETAIL_PORTFOLIO_ID")
    if portfolio_id:
        logger.info("🔧 Portfolio override in use: %s", portfolio_id)
    else:
        logger.info("🔧 Portfolio override in use: <none>")

    try:
        logger.info("Initializing trading strategy...")
        strategy = TradingStrategy()

        logger.info("🚀 Starting trading loop (2.5 minute cadence - EMERGENCY BLEEDING FIX)...")
        cycle_count = 0

        while True:
            try:
                cycle_count += 1
                logger.info(f"🔁 Main trading loop iteration #{cycle_count}")
                strategy.run_cycle()
                time.sleep(150)  # 2.5 minutes - EMERGENCY FIX: Prevent overtrading and immediate re-buying
            except KeyboardInterrupt:
                logger.info("Trading bot stopped by user (Ctrl+C)")
                break
            except Exception as e:
                logger.error(f"Error in trading cycle: {e}", exc_info=True)
                time.sleep(10)

    except RuntimeError as e:
        if "Broker connection failed" in str(e):
            logger.error("=" * 70)
            logger.error("❌ BROKER CONNECTION FAILED")
            logger.error("=" * 70)
            logger.error("")
            logger.error("Coinbase credentials not found or invalid. Check and set ONE of:")
            logger.error("")
            logger.error("1. PEM File (mounted):")
            logger.error("   - COINBASE_PEM_PATH=/path/to/file.pem (file must exist)")
            logger.error("")
            logger.error("2. PEM Content (as env var):")
            logger.error("   - COINBASE_PEM_CONTENT='-----BEGIN PRIVATE KEY-----\\n...'")
            logger.error("")
            logger.error("3. Base64-Encoded PEM:")
            logger.error("   - COINBASE_PEM_BASE64='<base64-encoded-pem>'")
            logger.error("")
            logger.error("4. API Key + Secret (JWT):")
            logger.error("   - COINBASE_API_KEY='<key>'")
            logger.error("   - COINBASE_API_SECRET='<secret>'")
            logger.error("")
            logger.error("=" * 70)
            sys.exit(1)
        else:
            logger.error(f"Fatal error initializing bot: {e}", exc_info=True)
            sys.exit(1)
    except Exception as e:
        logger.error(f"Unhandled fatal error: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
