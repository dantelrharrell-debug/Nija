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

# Import broker types for error reporting
try:
    from bot.broker_manager import BrokerType
except ImportError:
    # Fallback if running from different directory
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))
    from broker_manager import BrokerType

# Constants for error formatting
# Separator length of 63 matches the width of the error message
# "🚨 KRAKEN MASTER CREDENTIALS ARE SET BUT CONNECTION FAILED" (61 chars + 2 spaces padding)
ERROR_SEPARATOR = "═" * 63

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
    # Ensure immediate flushing to prevent log message interleaving
    console_handler.flush = lambda: sys.stdout.flush()
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

def _handle_signal(sig, frame):
    logger.info(f"Received signal {sig}, shutting down gracefully")
    sys.exit(0)


def _log_kraken_connection_error_header(error_msg):
    """
    Log Kraken Master connection error header with consistent formatting.

    Args:
        error_msg: The error message to display, or None if no specific error
    """
    logger.error("")
    logger.error(f"      {ERROR_SEPARATOR}")
    logger.error(f"      🚨 KRAKEN PLATFORM CREDENTIALS ARE SET BUT CONNECTION FAILED")
    logger.error(f"      {ERROR_SEPARATOR}")
    if error_msg:
        logger.error(f"      ❌ Error: {error_msg}")
    else:
        logger.error("      ❌ No specific error message was captured")
    logger.error("")


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

    # Check Kraken Platform (with enhanced validation)
    kraken_master_configured = False
    kraken_platform_key_raw = os.getenv("KRAKEN_PLATFORM_API_KEY", "")
    kraken_platform_secret_raw = os.getenv("KRAKEN_PLATFORM_API_SECRET", "")
    kraken_platform_key = kraken_platform_key_raw.strip()
    kraken_platform_secret = kraken_platform_secret_raw.strip()

    # Check for whitespace-only credentials (common configuration error)
    kraken_platform_key_malformed = (kraken_platform_key_raw != "" and kraken_platform_key == "")
    kraken_platform_secret_malformed = (kraken_platform_secret_raw != "" and kraken_platform_secret == "")

    if kraken_platform_key_malformed or kraken_platform_secret_malformed:
        exchange_status.append("⚠️ Kraken (Platform - MALFORMED)")
        logger.warning("⚠️  Kraken Platform credentials ARE SET but CONTAIN ONLY WHITESPACE")
        logger.warning("   This is a common error when copying/pasting credentials!")
        if kraken_platform_key_malformed:
            logger.warning("   → KRAKEN_PLATFORM_API_KEY: SET but empty after removing whitespace")
        if kraken_platform_secret_malformed:
            logger.warning("   → KRAKEN_PLATFORM_API_SECRET: SET but empty after removing whitespace")
        logger.warning("")
        logger.warning("   🔧 FIX in Railway/Render dashboard:")
        logger.warning("      1. Check for leading/trailing spaces or newlines in the values")
        logger.warning("      2. Re-paste the credentials without extra whitespace")
        logger.warning("      3. Click 'Save' and restart the deployment")
    elif kraken_platform_key and kraken_platform_secret:
        exchanges_configured += 1
        exchange_status.append("✅ Kraken (Platform)")
        logger.info("✅ Kraken Platform credentials detected")
        kraken_master_configured = True
    else:
        exchange_status.append("❌ Kraken (Platform)")
        logger.warning("⚠️  Kraken Platform credentials NOT SET")
        logger.warning("   → Kraken will NOT connect without these environment variables:")
        logger.warning("      KRAKEN_PLATFORM_API_KEY")
        logger.warning("      KRAKEN_PLATFORM_API_SECRET")

    # Check Kraken User accounts (with enhanced validation)
    kraken_users_configured = 0

    # User #1: Daivon
    daivon_key_raw = os.getenv("KRAKEN_USER_DAIVON_API_KEY", "")
    daivon_secret_raw = os.getenv("KRAKEN_USER_DAIVON_API_SECRET", "")
    daivon_key = daivon_key_raw.strip()
    daivon_secret = daivon_secret_raw.strip()
    daivon_key_malformed = (daivon_key_raw != "" and daivon_key == "")
    daivon_secret_malformed = (daivon_secret_raw != "" and daivon_secret == "")

    if daivon_key_malformed or daivon_secret_malformed:
        logger.warning("⚠️  Kraken User #1 (Daivon) credentials ARE SET but CONTAIN ONLY WHITESPACE")
        if daivon_key_malformed:
            logger.warning("   → KRAKEN_USER_DAIVON_API_KEY: SET but empty after stripping")
        if daivon_secret_malformed:
            logger.warning("   → KRAKEN_USER_DAIVON_API_SECRET: SET but empty after stripping")
    elif daivon_key and daivon_secret:
        logger.info("✅ Kraken User #1 (Daivon) credentials detected")
        kraken_users_configured += 1
    else:
        logger.warning("⚠️  Kraken User #1 (Daivon) credentials NOT SET")

    # User #2: Tania
    tania_key_raw = os.getenv("KRAKEN_USER_TANIA_API_KEY", "")
    tania_secret_raw = os.getenv("KRAKEN_USER_TANIA_API_SECRET", "")
    tania_key = tania_key_raw.strip()
    tania_secret = tania_secret_raw.strip()
    tania_key_malformed = (tania_key_raw != "" and tania_key == "")
    tania_secret_malformed = (tania_secret_raw != "" and tania_secret == "")

    if tania_key_malformed or tania_secret_malformed:
        logger.warning("⚠️  Kraken User #2 (Tania) credentials ARE SET but CONTAIN ONLY WHITESPACE")
        if tania_key_malformed:
            logger.warning("   → KRAKEN_USER_TANIA_API_KEY: SET but empty after stripping")
        if tania_secret_malformed:
            logger.warning("   → KRAKEN_USER_TANIA_API_SECRET: SET but empty after stripping")
    elif tania_key and tania_secret:
        logger.info("✅ Kraken User #2 (Tania) credentials detected")
        kraken_users_configured += 1
    else:
        logger.warning("⚠️  Kraken User #2 (Tania) credentials NOT SET")

    # Update Kraken status if users are configured but master isn't
    if not kraken_master_configured and kraken_users_configured > 0:
        # Remove only the "❌ Kraken (Master)" status (keep MALFORMED if present)
        exchange_status = [s for s in exchange_status if s != "❌ Kraken (Master)"]
        # Add updated status showing user accounts
        exchanges_configured += 1
        exchange_status.append(f"✅ Kraken (Users: {kraken_users_configured})")

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
    logger.info("=" * 70)

    # Add specific Kraken help if it's not configured
    if not kraken_master_configured and kraken_users_configured == 0:
        logger.info("")
        logger.info("💡 KRAKEN NOT CONNECTED - To enable Kraken trading:")
        logger.info("")
        logger.info("   📋 REQUIRED ENVIRONMENT VARIABLES:")
        logger.info("      • KRAKEN_PLATFORM_API_KEY=<your-api-key>")
        logger.info("      • KRAKEN_PLATFORM_API_SECRET=<your-api-secret>")
        logger.info("      • KRAKEN_USER_DAIVON_API_KEY=<user-api-key>  (optional)")
        logger.info("      • KRAKEN_USER_DAIVON_API_SECRET=<user-api-secret>  (optional)")
        logger.info("      • KRAKEN_USER_TANIA_API_KEY=<user-api-key>  (optional)")
        logger.info("      • KRAKEN_USER_TANIA_API_SECRET=<user-api-secret>  (optional)")
        logger.info("")
        logger.info("   🔧 HOW TO ADD IN RAILWAY:")
        logger.info("      1. Dashboard → Your Service → 'Variables' tab")
        logger.info("      2. Click '+ New Variable' for each variable above")
        logger.info("      3. Railway auto-restarts after saving")
        logger.info("")
        logger.info("   🔧 HOW TO ADD IN RENDER:")
        logger.info("      1. Dashboard → Your Service → 'Environment' tab")
        logger.info("      2. Add each variable above")
        logger.info("      3. Click 'Save Changes'")
        logger.info("      4. Click 'Manual Deploy' → 'Deploy latest commit'")
        logger.info("")
        logger.info("   🔑 GET API CREDENTIALS:")
        logger.info("      1. Go to https://www.kraken.com/u/security/api")
        logger.info("      2. Create API key with these permissions:")
        logger.info("         ✅ Query Funds")
        logger.info("         ✅ Query Open Orders & Trades")
        logger.info("         ✅ Query Closed Orders & Trades")
        logger.info("         ✅ Create & Modify Orders")
        logger.info("         ✅ Cancel/Close Orders")
        logger.info("      3. Copy the API Key and Private Key")
        logger.info("")
        logger.info("   📖 DETAILED GUIDES:")
        logger.info("      • KRAKEN_RAILWAY_RENDER_SETUP.md (step-by-step for platforms)")
        logger.info("      • KRAKEN_NOT_CONNECTING_DIAGNOSIS.md (troubleshooting)")
        logger.info("      • Run: python3 test_kraken_connection_live.py (test credentials)")
        logger.info("      • Run: python3 diagnose_kraken_connection.py (diagnose issues)")
        logger.info("=" * 70)

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
        # Can be suppressed by setting SUPPRESS_SINGLE_EXCHANGE_WARNING=true
        suppress_warning = os.getenv("SUPPRESS_SINGLE_EXCHANGE_WARNING", "false").lower() in ("true", "1", "yes")
        if not suppress_warning:
            logger.warning("=" * 70)
            logger.warning("⚠️  SINGLE EXCHANGE TRADING")
            logger.warning("=" * 70)
            logger.warning(f"Only {exchanges_configured} exchange configured. Consider enabling more for:")
            logger.warning("  • Better diversification")
            logger.warning("  • Reduced API rate limiting")
            logger.warning("  • More resilient trading")
            logger.warning("")
            logger.warning("See MULTI_EXCHANGE_TRADING_GUIDE.md for setup instructions")
            logger.warning("To suppress this warning, set SUPPRESS_SINGLE_EXCHANGE_WARNING=true")
            logger.warning("=" * 70)
        logger.warning(f"⚠️  Single exchange trading ({exchanges_configured} exchange configured). Consider enabling more exchanges for better diversification and resilience.")
        logger.info("📖 See MULTI_EXCHANGE_TRADING_GUIDE.md for setup instructions")

    try:
        logger.info("Initializing trading strategy...")
        # Start health server if PORT is provided by platform (e.g., Railway)
        logger.info("PORT env: %s", os.getenv("PORT") or "<unset>")
        _start_health_server()
        strategy = TradingStrategy()

        # AUDIT USER BALANCES - Show all user balances regardless of trading status
        # This runs BEFORE trading starts to ensure visibility even if users aren't actively trading
        logger.info("=" * 70)
        logger.info("🔍 AUDITING USER ACCOUNT BALANCES")
        logger.info("=" * 70)
        if hasattr(strategy, 'multi_account_manager') and strategy.multi_account_manager:
            strategy.multi_account_manager.audit_user_accounts()
        else:
            logger.warning("   ⚠️  Multi-account manager not available - skipping balance audit")

        # STARTUP BALANCE CONFIRMATION - Display live capital for legal/operational protection
        logger.info("")
        logger.info("=" * 70)
        logger.info("💰 LIVE CAPITAL CONFIRMED:")
        logger.info("=" * 70)
        if hasattr(strategy, 'multi_account_manager') and strategy.multi_account_manager:
            try:
                manager = strategy.multi_account_manager

                # Get all balances
                all_balances = manager.get_all_balances()

                # Platform account total
                platform_total = sum(all_balances.get('platform', {}).values())
                logger.info(f"   Platform: ${platform_total:,.2f}")

                # User accounts - specifically Daivon and Tania
                users_balances = all_balances.get('users', {})

                # Find Daivon's balance
                daivon_total = 0.0
                for user_id, balances in users_balances.items():
                    if 'daivon' in user_id.lower():
                        daivon_total = sum(balances.values())
                        break
                logger.info(f"   Daivon: ${daivon_total:,.2f}")

                # Find Tania's balance
                tania_total = 0.0
                for user_id, balances in users_balances.items():
                    if 'tania' in user_id.lower():
                        tania_total = sum(balances.values())
                        break
                logger.info(f"   Tania: ${tania_total:,.2f}")

                # Show grand total
                grand_total = platform_total + daivon_total + tania_total
                logger.info("")
                logger.info(f"   🏦 TOTAL CAPITAL UNDER MANAGEMENT: ${grand_total:,.2f}")
            except Exception as e:
                logger.error(f"   ⚠️  Error fetching balances: {e}")
                logger.error("   ⚠️  Continuing with startup - balances will be shown in trade logs")
        else:
            logger.warning("   ⚠️  Multi-account manager not available - cannot confirm balances")
        logger.info("=" * 70)

        # Independent trading mode - all accounts trade using same logic
        logger.info("=" * 70)
        logger.info("🔄 INDEPENDENT TRADING MODE ENABLED")
        logger.info("=" * 70)
        logger.info("   ✅ Each account trades independently")
        logger.info("   ✅ Same NIJA strategy logic for all accounts")
        logger.info("   ✅ Same risk management rules for all accounts")
        logger.info("   ✅ Position sizing scaled by account balance")
        logger.info("   ℹ️  No trade copying or mirroring between accounts")
        logger.info("=" * 70)

        # Log clear trading readiness status
        logger.info("=" * 70)
        logger.info("📊 TRADING READINESS STATUS")
        logger.info("=" * 70)

        # Check which master brokers are connected
        connected_platform_brokers = []
        failed_platform_brokers = []

        if hasattr(strategy, 'multi_account_manager') and strategy.multi_account_manager:
            for broker_type, broker in strategy.multi_account_manager.platform_brokers.items():
                if broker and broker.connected:
                    connected_platform_brokers.append(broker_type.value.upper())

        # CRITICAL FIX: Check for brokers with credentials configured but failed to connect
        # This catches cases where credentials are set but connection failed due to:
        # - SDK not installed (krakenex/pykrakenapi missing)
        # - Permission errors (API key lacks required permissions)
        # - Nonce errors (timing issues)
        # - Network errors
        # Check if Kraken was expected but didn't connect
        if kraken_master_configured and 'KRAKEN' not in connected_platform_brokers:
            failed_platform_brokers.append('KRAKEN')

        # Track if Kraken credentials were not configured at all
        kraken_not_configured = not kraken_master_configured

        if connected_platform_brokers:
            logger.info("✅ NIJA IS READY TO TRADE!")
            logger.info("")
            logger.info("Active Platform Exchanges:")
            for exchange in connected_platform_brokers:
                logger.info(f"   ✅ {exchange}")

            # Show failed brokers if any were expected to connect
            if failed_platform_brokers:
                logger.info("")
                logger.warning("⚠️  Expected but NOT Connected:")
                for exchange in failed_platform_brokers:
                    logger.warning(f"   ❌ {exchange}")
                    if exchange == 'KRAKEN':
                        # Try to get the specific error from the failed broker instance
                        error_msg = None
                        if hasattr(strategy, 'failed_brokers') and BrokerType.KRAKEN in strategy.failed_brokers:
                            failed_broker = strategy.failed_brokers[BrokerType.KRAKEN]
                            if hasattr(failed_broker, 'last_connection_error') and failed_broker.last_connection_error:
                                error_msg = failed_broker.last_connection_error

                        if error_msg:
                            _log_kraken_connection_error_header(error_msg)
                            # Provide specific guidance based on error type
                            # Check for SDK import errors (Kraken-specific patterns to avoid false positives)
                            is_sdk_error = any(pattern in error_msg.lower() for pattern in [
                                "sdk import error",  # Set by KrakenBroker.connect() ImportError handler
                                "modulenotfounderror",  # Python exception when module not found
                                "no module named 'krakenex'",  # Specific krakenex import failure
                                "no module named 'pykrakenapi'",  # Specific pykrakenapi import failure
                                "no module named \"krakenex\"",  # Alternative quote style
                                "no module named \"pykrakenapi\"",  # Alternative quote style
                            ])
                            if is_sdk_error:
                                logger.error("")
                                logger.error("      ❌ KRAKEN SDK NOT INSTALLED")
                                logger.error("      The Kraken libraries (krakenex/pykrakenapi) are missing!")
                                logger.error("")
                                logger.error("      🔧 IMMEDIATE FIX REQUIRED:")
                                logger.error("      1. Verify your deployment platform is using the Dockerfile")
                                logger.error("         Railway: Should auto-detect Dockerfile")
                                logger.error("         Render: Check 'Docker' is selected as environment")
                                logger.error("")
                                logger.error("      2. If using Railway/Render without Docker:")
                                logger.error("         Add to your start command:")
                                logger.error("         pip install krakenex pykrakenapi")
                                logger.error("")
                                logger.error("      3. Trigger a fresh deployment (not just restart):")
                                logger.error("         Railway: Settings → 'Redeploy'")
                                logger.error("         Render: Manual Deploy → 'Clear build cache & deploy'")
                                logger.error("")
                                logger.error("      📖 See SOLUTION_KRAKEN_LIBRARY_NOT_INSTALLED.md for details")
                                logger.error("")
                            elif "permission" in error_msg.lower():
                                logger.error("      → Fix: Enable required permissions at https://www.kraken.com/u/security/api")
                                logger.error("      → Required: Query Funds, Query/Create/Cancel Orders")
                            elif "nonce" in error_msg.lower():
                                logger.error("      → Fix: Wait 1-2 minutes and restart the bot")
                            elif "lockout" in error_msg.lower():
                                logger.error("      → Fix: Wait 5-10 minutes before restarting")
                            elif "whitespace" in error_msg.lower():
                                logger.error("      → Fix: Remove spaces/newlines from credentials in Railway/Render")
                            else:
                                logger.error("      → Verify credentials at https://www.kraken.com/u/security/api")
                        else:
                            # No error message was captured - this shouldn't happen but handle gracefully
                            _log_kraken_connection_error_header(None)
                            logger.error("      📋 POSSIBLE CAUSES:")
                            logger.error("         1. Kraken SDK not installed (krakenex/pykrakenapi)")
                            logger.error("         2. API key permissions insufficient")
                            logger.error("         3. Network connectivity issues")
                            logger.error("         4. Nonce synchronization errors")
                            logger.error("         5. API key expired or invalid")
                            logger.error("")
                            logger.error("      🔧 TROUBLESHOOTING STEPS:")
                            logger.error("         1. Check logs above for 'Kraken connection' errors")
                            logger.error("         2. Verify SDK installation:")
                            logger.error("            python3 -c 'import krakenex; import pykrakenapi; print(\"OK\")'")
                            logger.error("         3. Test credentials:")
                            logger.error("            python3 test_kraken_connection_live.py")
                            logger.error("         4. Verify API permissions at:")
                            logger.error("            https://www.kraken.com/u/security/api")
                            logger.error("            Required: Query Funds, Query/Create/Cancel Orders")
                            logger.error("")
                            logger.error("      📖 DETAILED GUIDES:")
                            logger.error("         • SOLUTION_KRAKEN_LIBRARY_NOT_INSTALLED.md")
                            logger.error("         • KRAKEN_PERMISSION_ERROR_FIX.md")
                            logger.error("         • KRAKEN_NOT_CONNECTING_DIAGNOSIS.md")
                            logger.error(f"      {ERROR_SEPARATOR}")
                            logger.error("")

            # Show warning if Kraken Platform credentials are not configured
            if kraken_not_configured:
                logger.info("")
                logger.warning("💡 PLATFORM KRAKEN NOT CONFIGURED")
                logger.warning("   ⚠️  Kraken Platform credentials are not set")
                logger.warning("   ℹ️  This is OPTIONAL - only set if you want PLATFORM Kraken trading")
                logger.warning("")
                logger.warning("   To enable PLATFORM Kraken trading, set in your deployment platform:")
                logger.warning("      KRAKEN_PLATFORM_API_KEY=<your-platform-api-key>")
                logger.warning("      KRAKEN_PLATFORM_API_SECRET=<your-platform-api-secret>")
                logger.warning("")
                logger.warning("   📖 Get credentials: https://www.kraken.com/u/security/api")
                logger.warning("   📖 Setup guide: SOLUTION_MASTER_KRAKEN_NOT_TRADING.md")
                logger.warning("   🔍 Diagnostic tool: python3 diagnose_master_kraken_live.py")

            logger.info("")
            logger.info(f"📈 Trading will occur on {len(connected_platform_brokers)} exchange(s)")
            logger.info("💡 Each exchange operates independently")
            logger.info("🛡️  Failures on one exchange won't affect others")
        else:
            logger.warning("⚠️  NO PLATFORM EXCHANGES CONNECTED")
            logger.warning("Bot is running in MONITOR MODE (no trades will execute)")
            logger.warning("")
            logger.warning("To enable trading:")
            logger.warning("   1. Run: python3 validate_all_env_vars.py")
            logger.warning("   2. Configure at least one platform exchange")
            logger.warning("   3. Restart the bot")

        logger.info("=" * 70)

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
