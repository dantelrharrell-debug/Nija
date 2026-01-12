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
import threading
import subprocess

# EMERGENCY STOP CHECK
if os.path.exists('EMERGENCY_STOP'):
    print("\n" + "="*80)
    print("🚨 EMERGENCY STOP ACTIVE")
    print("="*80)
    print("Bot is disabled. See EMERGENCY_STOP file for details.")
    print("Delete EMERGENCY_STOP file to resume trading.")
    print("="*80 + "\n")
    sys.exit(0)

# EMERGENCY STOP CHECK
if os.path.exists('EMERGENCY_STOP'):
    print("\n" + "="*80)
    print("🚨 EMERGENCY STOP ACTIVE")
    print("="*80)
    print("Bot is disabled. See EMERGENCY_STOP file for details.")
    print("Delete EMERGENCY_STOP file to resume trading.")
    print("="*80 + "\n")
    sys.exit(0)

# Minimal HTTP health server to satisfy platforms expecting $PORT
def _start_health_server():
    try:
        # Resolve port with a safe default if env is missing
        port_env = os.getenv("PORT", "")
        default_port = 8080
        try:
            port = int(port_env) if port_env else default_port
        except Exception:
            port = default_port
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class HealthHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                try:
                    # Simple health endpoint
                    if self.path in ("/", "/health", "/healthz", "/status"):
                        self.send_response(200)
                        self.send_header("Content-Type", "text/plain")
                        self.end_headers()
                        self.wfile.write(b"OK")
                    else:
                        self.send_response(404)
                        self.end_headers()
                except Exception:
                    try:
                        self.send_response(500)
                        self.end_headers()
                    except Exception:
                        pass
            def log_message(self, format, *args):
                # Silence default HTTP server logging
                return

        server = HTTPServer(("0.0.0.0", port), HealthHandler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        logger.info(f"🌐 Health server listening on port {port}")
    except Exception as e:
        logger.warning(f"Health server failed to start: {e}")

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

# Setup logging - configure ONCE to prevent duplicates
LOG_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), 'nija.log'))

# Remove any existing handlers first
root = logging.getLogger()
if root.handlers:
    for handler in list(root.handlers):
        root.removeHandler(handler)

# Get nija logger
logger = logging.getLogger("nija")
logger.setLevel(logging.INFO)
logger.propagate = False  # Prevent propagation to root logger

# Single formatter with consistent timestamp format
formatter = logging.Formatter(
    '%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Add handlers only if not already present
if not logger.hasHandlers():
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=2*1024*1024, backupCount=2)
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler(sys.stdout)
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

    # Get git metadata - try env vars first, then git commands
    git_branch = os.getenv("GIT_BRANCH", "")
    git_commit = os.getenv("GIT_COMMIT", "")
    
    # Fallback to git commands if env vars not set
    if not git_branch:
        try:
            git_branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=os.path.dirname(__file__),
                stderr=subprocess.DEVNULL,
                timeout=5
            ).decode().strip()
        except Exception:
            git_branch = "unknown"
    
    if not git_commit:
        try:
            git_commit = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=os.path.dirname(__file__),
                stderr=subprocess.DEVNULL,
                timeout=5
            ).decode().strip()
        except Exception:
            git_commit = "unknown"

    logger.info("=" * 70)
    logger.info("NIJA TRADING BOT - APEX v7.1")
    logger.info("Branch: %s", git_branch)
    logger.info("Commit: %s", git_commit)
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

    # Pre-flight check: Verify at least one exchange is configured
    logger.info("=" * 70)
    logger.info("🔍 PRE-FLIGHT: Checking Exchange Credentials")
    logger.info("=" * 70)
    
    exchanges_configured = 0
    exchange_status = []
    
    # Check Coinbase
    if os.getenv("COINBASE_API_KEY") and os.getenv("COINBASE_API_SECRET"):
        exchanges_configured += 1
        exchange_status.append("✅ Coinbase")
        logger.info("✅ Coinbase credentials detected")
    else:
        exchange_status.append("❌ Coinbase")
        logger.warning("⚠️  Coinbase credentials not configured")
    
    # Check Kraken Master
    if os.getenv("KRAKEN_MASTER_API_KEY") and os.getenv("KRAKEN_MASTER_API_SECRET"):
        exchanges_configured += 1
        exchange_status.append("✅ Kraken (Master)")
        logger.info("✅ Kraken Master credentials detected")
    else:
        exchange_status.append("❌ Kraken (Master)")
        logger.warning("⚠️  Kraken Master credentials not configured")
    
    # Check Kraken User accounts
    if os.getenv("KRAKEN_USER_DAIVON_API_KEY") and os.getenv("KRAKEN_USER_DAIVON_API_SECRET"):
        logger.info("✅ Kraken User #1 (Daivon) credentials detected")
    else:
        logger.warning("⚠️  Kraken User #1 (Daivon) credentials not configured")
    
    if os.getenv("KRAKEN_USER_TANIA_API_KEY") and os.getenv("KRAKEN_USER_TANIA_API_SECRET"):
        logger.info("✅ Kraken User #2 (Tania) credentials detected")
    else:
        logger.warning("⚠️  Kraken User #2 (Tania) credentials not configured")
    
    # Check OKX
    if os.getenv("OKX_API_KEY") and os.getenv("OKX_API_SECRET") and os.getenv("OKX_PASSPHRASE"):
        exchanges_configured += 1
        exchange_status.append("✅ OKX")
        logger.info("✅ OKX credentials detected")
    else:
        exchange_status.append("❌ OKX")
        logger.warning("⚠️  OKX credentials not configured")
    
    # Check Binance
    if os.getenv("BINANCE_API_KEY") and os.getenv("BINANCE_API_SECRET"):
        exchanges_configured += 1
        exchange_status.append("✅ Binance")
        logger.info("✅ Binance credentials detected")
    else:
        exchange_status.append("❌ Binance")
        logger.warning("⚠️  Binance credentials not configured")
    
    # Check Alpaca
    if os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_API_SECRET"):
        exchanges_configured += 1
        exchange_status.append("✅ Alpaca")
        logger.info("✅ Alpaca credentials detected")
    else:
        exchange_status.append("❌ Alpaca")
        logger.warning("⚠️  Alpaca credentials not configured")
    
    logger.info("=" * 70)
    logger.info(f"📊 EXCHANGE CREDENTIAL SUMMARY: {exchanges_configured} configured")
    logger.info("   " + " | ".join(exchange_status))
    logger.info("=" * 41)
    
    if exchanges_configured == 0:
        logger.error("=" * 70)
        logger.error("❌ CRITICAL: NO EXCHANGE CREDENTIALS CONFIGURED")
        logger.error("=" * 70)
        logger.error("The bot cannot trade without exchange API credentials.")
        logger.error("")
        logger.error("If you've added credentials to Railway/Render but they're not")
        logger.error("showing up here, you need to RESTART the deployment:")
        logger.error("")
        logger.error("Railway: Dashboard → Service → '...' menu → 'Restart Deployment'")
        logger.error("Render:  Dashboard → Service → 'Manual Deploy' → 'Deploy latest commit'")
        logger.error("")
        logger.error("For detailed help, see:")
        logger.error("  • SOLUTION_ENABLE_EXCHANGES.md")
        logger.error("  • RESTART_DEPLOYMENT.md")
        logger.error("  • Run: python3 diagnose_env_vars.py")
        logger.error("=" * 70)
        logger.error("Exiting - No trading possible without credentials")
        sys.exit(1)
    elif exchanges_configured < 2:
        logger.warning("=" * 70)
        logger.warning("⚠️  SINGLE EXCHANGE TRADING")
        logger.warning("=" * 70)
        logger.warning(f"Only {exchanges_configured} exchange configured. Consider enabling more for:")
        logger.warning("  • Better diversification")
        logger.warning("  • Reduced API rate limiting")
        logger.warning("  • More resilient trading")
        logger.warning("")
        logger.warning("See MULTI_EXCHANGE_TRADING_GUIDE.md for setup instructions")
        logger.warning("=" * 70)

    try:
        logger.info("Initializing trading strategy...")
        # Start health server if PORT is provided by platform (e.g., Railway)
        logger.info("PORT env: %s", os.getenv("PORT") or "<unset>")
        _start_health_server()
        strategy = TradingStrategy()

        # Check if we should use independent multi-broker trading mode
        use_independent_trading = os.getenv("MULTI_BROKER_INDEPENDENT", "true").lower() in ["true", "1", "yes"]
        
        if use_independent_trading and strategy.independent_trader:
            logger.info("=" * 70)
            logger.info("🚀 STARTING INDEPENDENT MULTI-BROKER TRADING MODE")
            logger.info("=" * 70)
            logger.info("Each broker will trade independently in isolated threads.")
            logger.info("Failures in one broker will NOT affect other brokers.")
            logger.info("=" * 70)
            
            # Start independent trading for all funded brokers
            if strategy.start_independent_multi_broker_trading():
                logger.info("✅ Independent multi-broker trading started successfully")
                
                # Main loop just monitors status and keeps process alive
                cycle_count = 0
                while True:
                    try:
                        cycle_count += 1
                        
                        # Log status every 10 cycles (25 minutes)
                        if cycle_count % 10 == 0:
                            logger.info(f"🔄 Status check #{cycle_count // 10}")
                            strategy.log_multi_broker_status()
                        
                        # Sleep for 2.5 minutes
                        time.sleep(150)
                        
                    except KeyboardInterrupt:
                        logger.info("Received shutdown signal, stopping all trading...")
                        strategy.stop_independent_trading()
                        break
                    except Exception as e:
                        logger.error(f"Error in monitoring loop: {e}", exc_info=True)
                        time.sleep(10)
            else:
                logger.error("❌ Failed to start independent multi-broker trading")
                logger.info("Falling back to single-broker mode...")
                use_independent_trading = False
        
        if not use_independent_trading:
            # Single broker mode (original behavior)
            logger.info("🚀 Starting single-broker trading loop (2.5 minute cadence)...")
            cycle_count = 0

            while True:
                try:
                    cycle_count += 1
                    logger.info(f"🔁 Main trading loop iteration #{cycle_count}")
                    strategy.run_cycle()
                    time.sleep(150)  # 2.5 minutes
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
