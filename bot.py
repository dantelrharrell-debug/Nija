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

# Configuration error heartbeat interval (seconds)
# When configuration errors prevent trading, the bot stays alive to report status
# and updates its heartbeat at this interval
CONFIG_ERROR_HEARTBEAT_INTERVAL = 60

# Heartbeat update interval (seconds) for Railway health check responsiveness
# Background thread updates heartbeat at this frequency to ensure health checks
# always get fresh data (Railway checks every ~30s, this is faster)
HEARTBEAT_INTERVAL_SECONDS = 10

# Keep-alive loop sleep interval (seconds)
# When trading loops exit, the keep-alive loop sleeps for this duration between status logs
# Note: Heartbeat is updated by dedicated background thread, not by this loop
KEEP_ALIVE_SLEEP_INTERVAL_SECONDS = 300

# EMERGENCY STOP CHECK
# Note: Uses print() instead of logger because logger is not yet initialized
if os.path.exists('EMERGENCY_STOP'):
    print("\n" + "┏" + "━" * 78 + "┓")
    print("┃ 🚨 EXIT POINT - EMERGENCY STOP FILE DETECTED                             ┃")
    print(f"┃ Exit Code: {0:<67} ┃")
    print(f"┃ PID: {os.getpid():<71} ┃")
    print("┣" + "━" * 78 + "┫")
    print("┃ Bot is disabled. See EMERGENCY_STOP file for details.                   ┃")
    print("┃ Delete EMERGENCY_STOP file to resume trading.                           ┃")
    print("┃ This is an intentional shutdown (not a crash).                          ┃")
    print("┗" + "━" * 78 + "┛")
    print("")
    sys.exit(0)

# Infrastructure-grade health server with liveness and readiness probes
def _start_health_server():
    """
    Start HTTP health server with Railway-optimized liveness endpoint.
    
    CRITICAL for Railway deployment:
    - /health and /healthz ALWAYS return 200 OK (stateless, < 50ms)
    - No dependencies on bot state, locks, or initialization
    - Binds immediately before any Kraken connections or user loading
    
    This prevents Railway from killing the container during startup.
    
    Other endpoints:
    - /ready or /readiness - Readiness probe (is service ready to handle traffic?)
    - /status - Detailed status information for operators
    """
    try:
        # Resolve port with a safe default if env is missing
        port_env = os.getenv("PORT", "")
        default_port = 8080
        try:
            port = int(port_env) if port_env else default_port
        except Exception:
            port = default_port
        from http.server import BaseHTTPRequestHandler, HTTPServer
        import json

        class HealthHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                try:
                    # Railway liveness probe - ALWAYS returns 200 OK (stateless, no checks)
                    # No logging. No conditionals. No imports. Dumb and fast wins.
                    # This ensures Railway never kills the container during startup
                    if self.path in ("/health", "/healthz"):
                        self.send_response(200)
                        self.send_header("Content-Type", "text/plain")
                        self.end_headers()
                        self.wfile.write(b"ok")
                    
                    # Readiness probe - returns 200 only if ready, 503 if not ready/config error
                    elif self.path in ("/ready", "/readiness"):
                        try:
                            from bot.health_check import get_health_manager
                            health_manager = get_health_manager()
                            status, http_code = health_manager.get_readiness_status()
                            self.send_response(http_code)
                            self.send_header("Content-Type", "application/json")
                            self.end_headers()
                            self.wfile.write(json.dumps(status).encode())
                        except Exception:
                            # If health manager not ready, return not ready
                            self.send_response(503)
                            self.send_header("Content-Type", "application/json")
                            self.end_headers()
                            self.wfile.write(json.dumps({"status": "not_ready", "reason": "initializing"}).encode())
                    
                    # Detailed status for operators and debugging
                    elif self.path in ("/status", "/"):
                        try:
                            from bot.health_check import get_health_manager
                            health_manager = get_health_manager()
                            status = health_manager.get_detailed_status()
                            self.send_response(200)
                            self.send_header("Content-Type", "application/json")
                            self.end_headers()
                            self.wfile.write(json.dumps(status, indent=2).encode())
                        except Exception:
                            # If health manager not ready, return basic status
                            self.send_response(200)
                            self.send_header("Content-Type", "application/json")
                            self.end_headers()
                            self.wfile.write(json.dumps({"status": "initializing"}, indent=2).encode())
                    
                    # Prometheus metrics endpoint
                    elif self.path == "/metrics":
                        try:
                            from bot.health_check import get_health_manager
                            health_manager = get_health_manager()
                            metrics = health_manager.get_prometheus_metrics()
                            self.send_response(200)
                            self.send_header("Content-Type", "text/plain; version=0.0.4")
                            self.end_headers()
                            self.wfile.write(metrics.encode())
                        except Exception:
                            # Return minimal metrics if health manager not ready
                            self.send_response(200)
                            self.send_header("Content-Type", "text/plain; version=0.0.4")
                            self.end_headers()
                            self.wfile.write(b"# Initializing\nnija_up 1\n")
                    
                    else:
                        self.send_response(404)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            "error": "Not found",
                            "available_endpoints": ["/health", "/healthz", "/ready", "/readiness", "/status", "/metrics"]
                        }).encode())
                except Exception as e:
                    try:
                        self.send_response(500)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({"error": str(e)}).encode())
                    except Exception:
                        pass
            
            def log_message(self, format, *args):
                # Silence default HTTP server logging to reduce noise
                return

        server = HTTPServer(("0.0.0.0", port), HealthHandler)
        t = threading.Thread(target=server.serve_forever, daemon=True, name="HealthServer")
        t.start()
        print(f"🌐 Health server listening on port {port} (Railway-optimized)")
        print(f"   📍 Liveness:  http://0.0.0.0:{port}/health (ALWAYS returns 200 OK)")
        print(f"   📍 Readiness: http://0.0.0.0:{port}/ready")
        print(f"   📍 Status:    http://0.0.0.0:{port}/status")
        print(f"   📍 Metrics:   http://0.0.0.0:{port}/metrics")
    except Exception as e:
        print(f"❌ Health server failed to start: {e}")

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

def _log_lifecycle_banner(title, details=None):
    """
    Log a visual lifecycle banner for major state transitions.
    
    Args:
        title: The main title to display
        details: Optional list of detail strings to include
    """
    logger.info("")
    logger.info("╔" + "═" * 78 + "╗")
    logger.info(f"║ {title:^76} ║")
    if details:
        logger.info("╠" + "═" * 78 + "╣")
        for detail in details:
            logger.info(f"║ {detail:76} ║")
    logger.info("╚" + "═" * 78 + "╝")
    logger.info("")


def _log_exit_point(reason, exit_code=0, details=None):
    """
    Log a visual exit point marker before sys.exit().
    
    Args:
        reason: Why the process is exiting
        exit_code: The exit code (0 = success, 1 = error)
        details: Optional list of detail strings
    """
    icon = "✅" if exit_code == 0 else "❌"
    logger.info("")
    logger.info("┏" + "━" * 78 + "┓")
    logger.info(f"┃ {icon} EXIT POINT - {reason:68} ┃")
    logger.info(f"┃ Exit Code: {exit_code:<67} ┃")
    logger.info(f"┃ PID: {os.getpid():<71} ┃")
    if details:
        logger.info("┣" + "━" * 78 + "┫")
        for detail in details:
            logger.info(f"┃ {detail:76} ┃")
    logger.info("┗" + "━" * 78 + "┛")
    logger.info("")


def _get_thread_status():
    """Get status of all running threads for visual verification."""
    threads = threading.enumerate()
    status = []
    status.append(f"Total Threads: {len(threads)}")
    for thread in threads:
        daemon_marker = "🔹" if thread.daemon else "🔸"
        alive_marker = "✅" if thread.is_alive() else "❌"
        status.append(f"  {daemon_marker} {alive_marker} {thread.name} (ID: {thread.ident})")
    return status


def _handle_signal(sig, frame):
    """Handle shutdown signals (SIGTERM, SIGINT) with visual logging."""
    signal_name = signal.Signals(sig).name if hasattr(signal, 'Signals') else str(sig)
    _log_exit_point(
        f"Signal {signal_name} received",
        exit_code=0,
        details=[
            "Graceful shutdown initiated by signal handler",
            "This is an expected exit (not a crash)",
            *_get_thread_status()
        ]
    )
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


def _log_memory_usage():
    """
    Log lightweight memory usage at startup.
    
    Logs RSS (Resident Set Size) and VMS (Virtual Memory Size) in a single line.
    Optionally warns if memory usage exceeds 70% of available system memory.
    """
    try:
        import psutil
        
        # Get current process memory info
        process = psutil.Process(os.getpid())
        mem_info = process.memory_info()
        
        # RSS: Resident Set Size (physical memory used)
        # VMS: Virtual Memory Size (total virtual memory)
        rss_mb = mem_info.rss / (1024 * 1024)  # Convert to MB
        vms_mb = mem_info.vms / (1024 * 1024)  # Convert to MB
        
        # Get system memory for percentage calculation
        system_mem = psutil.virtual_memory()
        total_mb = system_mem.total / (1024 * 1024)
        percent_used = (mem_info.rss / system_mem.total) * 100
        
        # Single line log with RSS and VMS
        logger.info(f"💾 Memory: RSS={rss_mb:.1f}MB, VMS={vms_mb:.1f}MB ({percent_used:.1f}% of {total_mb:.0f}MB system)")
        
        # Optional: warn if memory usage is at 70% of system memory
        if percent_used >= 70.0:
            logger.warning(f"⚠️  High memory usage: {percent_used:.1f}% (threshold: 70%)")
            
    except ImportError:
        # psutil not available - use basic resource module as fallback
        try:
            import resource
            usage = resource.getrusage(resource.RUSAGE_SELF)
            # maxrss is in KB on Linux, bytes on macOS
            import platform
            if platform.system() == 'Darwin':  # macOS
                rss_mb = usage.ru_maxrss / (1024 * 1024)
            else:  # Linux
                rss_mb = usage.ru_maxrss / 1024
            logger.info(f"💾 Memory: RSS={rss_mb:.1f}MB (psutil not available, limited info)")
        except Exception as e:
            logger.debug(f"Could not log memory usage: {e}")
    except Exception as e:
        logger.debug(f"Error logging memory usage: {e}")


def _run_bot_startup_and_trading():
    """
    Background thread: Initialize bot and run trading loops.
    
    This function runs in a background thread while the main thread
    keeps the health server responsive to Railway.
    
    Contains:
    - Kraken connection
    - User loading  
    - Balance fetching
    - Trading loop initialization
    """
    try:
        # Import here to ensure logging is set up
        from bot.health_check import get_health_manager
        health_manager = get_health_manager()
        
        logger.info("=" * 70)
        logger.info("🧵 STARTUP THREAD: Beginning bot initialization")
        logger.info("=" * 70)
        logger.info("While this thread initializes, health server remains responsive")
        logger.info("")
        
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
        logger.info("NIJA TRADING BOT - APEX v7.2.0")
        logger.info("NIJA TRADING BOT - APEX v7.2")
        logger.info("🏷 Version: 7.2.0 — Independent Trading Only")
        logger.info("Branch: %s", git_branch)
        logger.info("Commit: %s", git_commit)
        logger.info("=" * 70)
        logger.info(f"Python version: {sys.version.split()[0]}")
        logger.info(f"Log file: {LOG_FILE}")
        logger.info(f"Working directory: {os.getcwd()}")
        
        # Display financial disclaimers (App Store compliance)
        try:
            from bot.financial_disclaimers import display_startup_disclaimers, log_compliance_notice
            display_startup_disclaimers()
            log_compliance_notice()
        except ImportError:
            # Fallback if disclaimers module not available
            logger.warning("=" * 70)
            logger.warning("⚠️  RISK WARNING: Trading involves substantial risk of loss")
            logger.warning("   Only trade with money you can afford to lose")
            logger.warning("=" * 70)

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

        # Check Kraken Platform
        kraken_platform_configured = bool(
            os.getenv("KRAKEN_PLATFORM_API_KEY") and os.getenv("KRAKEN_PLATFORM_API_SECRET")
        )
        if kraken_platform_configured:
            exchanges_configured += 1
            exchange_status.append("✅ Kraken (Platform)")
            logger.info("✅ Kraken Platform credentials detected")
        else:
            exchange_status.append("❌ Kraken (Platform)")
            logger.warning("⚠️  Kraken Platform credentials not configured")

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

        # Check Alpaca Platform
        if os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_API_SECRET"):
            exchanges_configured += 1
            exchange_status.append("✅ Alpaca (Platform)")
            logger.info("✅ Alpaca Platform credentials detected")
        else:
            exchange_status.append("❌ Alpaca (Platform)")
            logger.warning("⚠️  Alpaca Platform credentials not configured")

        logger.info("=" * 70)
        logger.info("CREDENTIAL CHECK SUMMARY")
        logger.info("=" * 70)
        for status in exchange_status:
            logger.info(f"   {status}")
        logger.info("=" * 70)
        logger.info(f"Total exchanges configured: {exchanges_configured}")
        logger.info("=" * 70)

        if exchanges_configured == 0:
            logger.error("=" * 70)
            logger.error("❌ FATAL: NO EXCHANGE CREDENTIALS CONFIGURED")
            logger.error("=" * 70)
            logger.error("")
            logger.error("At least one exchange must be configured to run the bot.")
            logger.error("Configure credentials for at least ONE of:")
            logger.error("  • Coinbase")
            logger.error("  • Kraken")
            logger.error("  • OKX")
            logger.error("  • Binance")
            logger.error("  • Alpaca")
            logger.error("")
            logger.error("How to configure:")
            logger.error("1. Edit .env file and add your credentials")
            logger.error("2. Or set environment variables in your deployment platform:")
            logger.error("")
            logger.error("Railway: Settings → Variables → Add")
            logger.error("Render:  Dashboard → Service → 'Manual Deploy' → 'Deploy latest commit'")
            logger.error("")
            logger.error("For detailed help, see:")
            logger.error("  • SOLUTION_ENABLE_EXCHANGES.md")
            logger.error("  • RESTART_DEPLOYMENT.md")
            logger.error("  • Run: python3 diagnose_env_vars.py")
            logger.error("=" * 70)
            logger.error("Exiting - No trading possible without credentials")
            
            # Mark as configuration error for health checks
            health_manager.mark_configuration_error("No exchange credentials configured")
            
            # Health server already started at beginning of main()
            logger.info("Health server already running - will report configuration error status")
            
            _log_lifecycle_banner(
                "⚠️  ENTERING CONFIG ERROR KEEP-ALIVE MODE",
                [
                    "No exchange credentials configured - cannot trade",
                    "Process will stay alive for health monitoring",
                    "Container will NOT restart automatically",
                    f"Heartbeat interval: {CONFIG_ERROR_HEARTBEAT_INTERVAL}s",
                    "Configure credentials and manually restart deployment",
                    *_get_thread_status()
                ]
            )
            
            try:
                loop_count = 0
                while True:
                    time.sleep(CONFIG_ERROR_HEARTBEAT_INTERVAL)
                    health_manager.heartbeat()
                    loop_count += 1
                    
                    # Log status every 10 iterations (10 minutes at 60s interval)
                    if loop_count % 10 == 0:
                        logger.info(f"⏱️  Config error keep-alive: {loop_count * CONFIG_ERROR_HEARTBEAT_INTERVAL}s elapsed")
            except KeyboardInterrupt:
                _log_exit_point(
                    "Configuration error keep-alive interrupted",
                    exit_code=0,
                    details=[
                        "KeyboardInterrupt in config error keep-alive loop",
                        "No exchange credentials were configured",
                        *_get_thread_status()
                    ]
                )
                sys.exit(0)
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

        # ═══════════════════════════════════════════════════════════════════════
        # BOT INITIALIZATION - This is where Kraken connection happens
        # ═══════════════════════════════════════════════════════════════════════
        
        try:
            logger.info("🧵 STARTUP THREAD: Initializing trading strategy...")
            logger.info("   This is where Kraken connection will be established")
            logger.info("   Main thread health server remains responsive during this")
            logger.info("PORT env: %s", os.getenv("PORT") or "<unset>")
            
            # This is where the actual bot initialization happens
            # TradingStrategy() constructor:
            # - Connects to Kraken
            # - Loads users
            # - Fetches balances
            # This can take 30-60 seconds, but health server is already running!
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
            if kraken_platform_configured and 'KRAKEN' not in connected_platform_brokers:
                failed_platform_brokers.append('KRAKEN')

            # Track if Kraken credentials were not configured at all
            kraken_not_configured = not kraken_platform_configured

            if connected_platform_brokers:
                logger.info("✅ Connected Platform Exchanges:")
                for exchange in connected_platform_brokers:
                    logger.info(f"   ✅ {exchange}")
                logger.info("")
                
                # Show failures if any
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
                                # Check for SDK import errors
                                is_sdk_error = any(pattern in error_msg.lower() for pattern in [
                                    "sdk import error",
                                    "modulenotfounderror",
                                    "no module named 'krakenex'",
                                    "no module named 'pykrakenapi'",
                                ])
                                if is_sdk_error:
                                    logger.error("")
                                    logger.error("      ❌ KRAKEN SDK NOT INSTALLED")
                                    logger.error("      The Kraken libraries (krakenex/pykrakenapi) are missing!")
                                    logger.error("")
                                    logger.error("      🔧 IMMEDIATE FIX REQUIRED:")
                                    logger.error("      1. Verify your deployment platform is using the Dockerfile")
                                    logger.error("")
                                elif "permission" in error_msg.lower():
                                    logger.error("      → Fix: Enable required permissions at https://www.kraken.com/u/security/api")
                                elif "nonce" in error_msg.lower():
                                    logger.error("      → Fix: Wait 1-2 minutes and restart the bot")
                                else:
                                    logger.error("      → Verify credentials at https://www.kraken.com/u/security/api")

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
                
                # Update health status - exchanges configured but none connected
                health_manager.update_exchange_status(connected=0, expected=exchanges_configured)

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
                            
                            # Update health heartbeat
                            health_manager.heartbeat()

                            # Log status every 10 cycles (25 minutes)
                            if cycle_count % 10 == 0:
                                logger.info(f"🔄 Status check #{cycle_count // 10}")
                                strategy.log_multi_broker_status()

                            # Sleep for 2.5 minutes
                            time.sleep(150)

                        except KeyboardInterrupt:
                            _log_lifecycle_banner(
                                "⚠️  TRADING LOOP INTERRUPTED - Multi-Broker Mode",
                                [
                                    "KeyboardInterrupt received in independent multi-broker loop",
                                    "Stopping all independent trading threads...",
                                    f"Completed {cycle_count} monitoring cycles",
                                    *_get_thread_status()
                                ]
                            )
                            logger.info("Stopping all independent trading...")
                            strategy.stop_independent_trading()
                            logger.info("✅ Independent trading stopped")
                            break
                        except Exception as e:
                            logger.error(f"❌ Error in monitoring loop: {e}", exc_info=True)
                            logger.warning(f"Recovering from error, continuing monitoring...")
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
                        
                        # Update health heartbeat
                        health_manager.heartbeat()
                        
                        logger.info(f"🔁 Main trading loop iteration #{cycle_count}")
                        strategy.run_cycle()
                        time.sleep(150)  # 2.5 minutes
                    except KeyboardInterrupt:
                        _log_lifecycle_banner(
                            "⚠️  TRADING LOOP INTERRUPTED - Single-Broker Mode",
                            [
                                "KeyboardInterrupt received in single-broker trading loop",
                                f"Completed {cycle_count} trading cycles",
                                "Exiting trading loop...",
                                *_get_thread_status()
                            ]
                        )
                        break
                    except Exception as e:
                        logger.error(f"❌ Error in trading cycle: {e}", exc_info=True)
                        logger.warning(f"Recovering from error, continuing trading...")
                        time.sleep(10)

            # CRITICAL: Keep-alive loop to prevent process exit
            logger.info("🔒 Trading loops completed - entering keep-alive mode")
            while True:
                time.sleep(300)
                logger.debug("🧵 Startup thread keep-alive")
                
        except RuntimeError as e:
            if "Broker connection failed" in str(e):
                _log_exit_point(
                    "Broker Connection Failed",
                    exit_code=1,
                    details=[
                        "RuntimeError: Broker connection failed",
                        "Credentials not found or invalid",
                        *_get_thread_status()
                    ]
                )
                sys.exit(1)
            else:
                _log_exit_point(
                    "Fatal Initialization Error",
                    exit_code=1,
                    details=[
                        f"RuntimeError: {str(e)}",
                        "Bot initialization failed",
                        *_get_thread_status()
                    ]
                )
                logger.error(f"Fatal error initializing bot: {e}", exc_info=True)
                sys.exit(1)
        except Exception as e:
            _log_exit_point(
                "Unhandled Fatal Error in Startup Thread",
                exit_code=1,
                details=[
                    f"Exception Type: {type(e).__name__}",
                    f"Error: {str(e)}",
                    "An unexpected error occurred in startup thread",
                    *_get_thread_status()
                ]
            )
            logger.exception("❌ Startup thread crashed")
            sys.exit(1)
            
    except Exception as e:
        logger.exception("🧵 ❌ Fatal error in startup thread outer handler")
        sys.exit(1)


def main():
    """Main entry point for NIJA trading bot - Railway optimized"""
    
    # ═══════════════════════════════════════════════════════════════════════
    # CRITICAL: START HEALTH SERVER FIRST (Railway requirement)
    # ═══════════════════════════════════════════════════════════════════════
    # Health server MUST bind BEFORE:
    # - Kraken connections
    # - User loading  
    # - Any sleeps or loops
    # - Even logging setup
    #
    # This prevents Railway from killing the container during startup.
    # The /health endpoint ALWAYS returns 200 OK regardless of bot state.
    print("=" * 70)
    print("🌐 STARTING HEALTH SERVER (Railway requirement)")
    print("=" * 70)
    _start_health_server()
    print("✅ Health server started - Railway will not kill this container")
    print("=" * 70)
    print("")
    
    # Small delay to ensure health server is fully bound
    time.sleep(0.2)
    
    # Now setup logging (after health server is running)
    # Log process startup
    _log_lifecycle_banner(
        "🚀 NIJA TRADING BOT STARTUP",
        [
            f"Process ID: {os.getpid()}",
            f"Python Version: {sys.version.split()[0]}",
            f"Working Directory: {os.getcwd()}",
            "Health server: ✅ RUNNING (started before initialization)",
            "Initializing lifecycle management..."
        ]
    )
    
    # Log memory usage at startup (lightweight - single line)
    _log_memory_usage()
    
    # Graceful shutdown handlers to avoid non-zero exits on platform terminations
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    logger.info("✅ Signal handlers registered (SIGTERM, SIGINT)")

    # Initialize health check manager early
    from bot.health_check import get_health_manager
    health_manager = get_health_manager()
    logger.info("✅ Health check manager initialized")
    
    # Start dedicated heartbeat thread for Railway health checks
    # This ensures heartbeat is updated frequently (every 10 seconds)
    # regardless of trading loop timing (150 seconds)
    # Critical for Railway health check responsiveness (~30 second intervals)
    def heartbeat_worker():
        """Background thread that updates heartbeat at regular intervals"""
        thread_id = threading.get_ident()
        logger.info(f"🧵 Heartbeat thread started (ID: {thread_id}, Interval: {HEARTBEAT_INTERVAL_SECONDS}s)")
        
        heartbeat_count = 0
        while True:
            try:
                health_manager.heartbeat()
                heartbeat_count += 1
                
                # Log every 60 heartbeats (10 minutes at 10s interval) for visibility
                if heartbeat_count % 60 == 0:
                    logger.debug(f"🧵 Heartbeat thread alive - {heartbeat_count} heartbeats sent")
                
                time.sleep(HEARTBEAT_INTERVAL_SECONDS)
            except Exception as e:
                logger.error(f"🧵 ❌ Error in heartbeat worker thread (ID: {thread_id}): {e}", exc_info=True)
                time.sleep(HEARTBEAT_INTERVAL_SECONDS)
    
    heartbeat_thread = threading.Thread(target=heartbeat_worker, daemon=True, name="HeartbeatWorker")
    heartbeat_thread.start()
    
    # Wait briefly to ensure thread actually starts
    time.sleep(0.1)
    
    _log_lifecycle_banner(
        "✅ BACKGROUND THREADS STARTED",
        [
            f"HeartbeatWorker: Thread ID {heartbeat_thread.ident}",
            f"Update Interval: {HEARTBEAT_INTERVAL_SECONDS} seconds",
            f"Thread is alive: {heartbeat_thread.is_alive()}",
            "Health checks will be responsive to Railway (~30s check interval)"
        ]
    )

    # ═══════════════════════════════════════════════════════════════════════
    # RAILWAY PATTERN: Spawn startup thread, main thread supervises
    # ═══════════════════════════════════════════════════════════════════════
    # Main thread stays in idle loop to keep health server responsive
    # Startup thread handles all bot initialization:
    # - Kraken connection
    # - User loading
    # - Balance fetching
    # - Trading loop
    
    logger.info("=" * 70)
    logger.info("🚀 SPAWNING STARTUP THREAD")
    logger.info("=" * 70)
    logger.info("Main thread will supervise while startup thread initializes bot")
    logger.info("Health server remains responsive during initialization")
    logger.info("=" * 70)
    
    startup_thread = threading.Thread(
        target=_run_bot_startup_and_trading,
        daemon=False,  # NOT daemon - we want this to keep running
        name="BotStartup"
    )
    startup_thread.start()
    
    # Wait briefly to ensure thread starts
    time.sleep(0.2)
    
    _log_lifecycle_banner(
        "✅ STARTUP THREAD SPAWNED",
        [
            f"BotStartup: Thread ID {startup_thread.ident}",
            f"Thread is alive: {startup_thread.is_alive()}",
            "Bot initialization is now running in background",
            "Main thread entering supervisor mode..."
        ]
    )
    
    # ═══════════════════════════════════════════════════════════════════════
    # SUPERVISOR LOOP - Main thread stays here forever
    # ═══════════════════════════════════════════════════════════════════════
    # This keeps the process alive and health server responsive
    # while the startup thread does all the work
    
    _log_lifecycle_banner(
        "🔒 ENTERING SUPERVISOR MODE",
        [
            "Main thread will monitor background threads",
            "Health server: ✅ Running (always responds to Railway)",
            "Heartbeat thread: ✅ Running (updates every 10s)",
            "Startup thread: ✅ Running (initializing bot)",
            f"Status logging every {KEEP_ALIVE_SLEEP_INTERVAL_SECONDS}s",
            "To shutdown: Use SIGTERM or SIGINT (handled by signal handlers)"
        ]
    )
    
    supervisor_cycle = 0
    while True:
        try:
            supervisor_cycle += 1
            
            # Check if startup thread is still alive
            if not startup_thread.is_alive():
                logger.warning("⚠️  Startup thread has exited")
                logger.warning("   This may indicate bot initialization failed")
                logger.warning("   Check logs above for errors")
                # Keep supervisor running even if startup dies
                # This allows health checks to continue reporting
            
            # Log periodic status
            if supervisor_cycle % 12 == 0:  # Every hour at 300s intervals
                logger.info(f"💓 Supervisor status check #{supervisor_cycle // 12}")
                logger.info("🧵 Thread Status Report:")
                logger.info(f"   Health server: ✅ Running")
                logger.info(f"   Heartbeat thread: {'✅ Alive' if heartbeat_thread.is_alive() else '❌ Dead'}")
                logger.info(f"   Startup thread: {'✅ Alive' if startup_thread.is_alive() else '❌ Dead'}")
                for status_line in _get_thread_status():
                    logger.info(f"   {status_line}")
            
            time.sleep(KEEP_ALIVE_SLEEP_INTERVAL_SECONDS)
            
        except KeyboardInterrupt:
            _log_lifecycle_banner(
                "⚠️  SUPERVISOR INTERRUPTED",
                [
                    "KeyboardInterrupt received in supervisor loop",
                    "Shutting down gracefully...",
                    *_get_thread_status()
                ]
            )
            logger.info("Waiting for startup thread to finish...")
            startup_thread.join(timeout=10)
            break
        except Exception as e:
            logger.error(f"❌ Error in supervisor loop: {e}", exc_info=True)
            logger.warning("Recovering from supervisor loop error...")
            time.sleep(10)
    
    logger.info("✅ Main supervisor exiting gracefully")
    sys.exit(0)


if __name__ == "__main__":
    main()
