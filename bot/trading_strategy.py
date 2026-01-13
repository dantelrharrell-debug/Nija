import os
import sys
import time
import random
import queue
import logging
import traceback
from threading import Thread
from typing import Dict
from datetime import datetime
from dotenv import load_dotenv
import pandas as pd

load_dotenv()

logger = logging.getLogger("nija")

# Configuration constants
# CRITICAL FIX (Jan 10, 2026): Further reduced market scanning to prevent 429/403 rate limit errors
# Coinbase has strict rate limits (~10 req/s burst, lower sustained)
# Instead of scanning all 730 markets every cycle, we batch scan smaller subsets
# RateLimiter enforces 10 req/min (6s between calls), so we must scan fewer markets
MARKET_SCAN_LIMIT = 15   # Scan only 15 markets per cycle (reduced from 25 to prevent rate limits)
                         # This rotates through different markets each cycle
                         # Complete scan of 730 markets takes ~49 cycles (~2 hours)
                         # At 15 markets with 6.5s delay, each scan takes ~97s (well under 2.5 min cycle time)
MIN_CANDLES_REQUIRED = 90  # Minimum candles needed for analysis (relaxed from 100 to prevent infinite sell loops)

# Rate limiting constants (prevent 429 errors from Coinbase API)
# UPDATED (Jan 10, 2026): CRITICAL FIX - Aligned delays with RateLimiter to prevent rate limits
# Coinbase rate limits: ~10 requests/second burst, but sustained rate must be much lower
# Real-world testing shows we need to be even more conservative to avoid 403 "too many errors"
# RateLimiter enforces 6s minimum between get_candles calls (10 req/min)
# Manual delay must be >= 6s to avoid conflicts and ensure proper rate limiting
POSITION_CHECK_DELAY = 0.5  # 500ms delay between position checks (was 0.3s)
SELL_ORDER_DELAY = 0.7      # 700ms delay between sell orders (was 0.5s)
MARKET_SCAN_DELAY = 8.0     # 8000ms delay between market scans (increased from 6.5s to 8.0s for better rate limiting)
                            # CRITICAL: Must be >= 7.5s to align with RateLimiter (8 req/min for get_candles)
                            # The 0.5s buffer (8.0s vs 7.5s) accounts for jitter and processing time
                            # At 8.0s delay, we scan at ~0.125 req/s which prevents both 429 and 403 errors
                            # At 5-15 markets per cycle with 8.0s delay, scanning takes 40-120 seconds
                            # This conservative rate ensures API key never gets temporarily blocked
                            
# Market scanning rotation (prevents scanning same markets every cycle)
# UPDATED (Jan 10, 2026): Adaptive batch sizing to prevent API rate limiting
MARKET_BATCH_SIZE_MIN = 5   # Start with just 5 markets per cycle on fresh start
MARKET_BATCH_SIZE_MAX = 15  # Maximum markets to scan per cycle after warmup
MARKET_BATCH_WARMUP_CYCLES = 3  # Number of cycles to warm up before using max batch size
MARKET_ROTATION_ENABLED = True  # Rotate through different market batches each cycle

# Exit strategy constants (no entry price required)
# CRITICAL FIX (Jan 13, 2026): Aggressive RSI thresholds to sell faster
MIN_POSITION_VALUE = 1.0  # Auto-exit positions under this USD value
RSI_OVERBOUGHT_THRESHOLD = 55  # Exit when RSI exceeds this (lock gains) - LOWERED from 60 for faster profit-taking
RSI_OVERSOLD_THRESHOLD = 45  # Exit when RSI below this (cut losses) - RAISED from 40 for faster loss-cutting
DEFAULT_RSI = 50  # Default RSI value when indicators unavailable

# Time-based exit thresholds (prevent indefinite holding)
# CRITICAL FIX (Jan 13, 2026): Reduced from 48h to 8h to force exits on losing positions
# NIJA is for PROFIT, not losses - positions should sell within 8 hours max
MAX_POSITION_HOLD_HOURS = 8  # Auto-exit positions held longer than this (8 hours)
STALE_POSITION_WARNING_HOURS = 4  # Warn about positions held this long (4 hours)

# Profit target thresholds (stepped exits) - FEE-AWARE + ULTRA AGGRESSIVE V7.3
# Updated Jan 12, 2026 - PROFITABILITY FIX: Aggressive profit-taking to lock gains
# CRITICAL: With small positions, we need FASTER exits to lock gains
# Coinbase fees are ~1.4%, so minimum 1.5% needed for net profit
# Strategy: Exit FULL position at FIRST target hit, checking from HIGHEST to LOWEST
# This prioritizes larger gains while providing emergency exit near breakeven
PROFIT_TARGETS = [
    (1.5, "Profit target +1.5% (Net ~0.1% after fees) - GOOD"),          # Check first - lock profits quickly
    (1.2, "Profit target +1.2% (Net ~-0.2% after fees) - ACCEPTABLE"),   # Check second - accept small loss vs reversal
    (1.0, "Profit target +1.0% (Net ~-0.4% after fees) - EMERGENCY"),    # Emergency exit to prevent larger loss
]
# CRITICAL FIX (Jan 13, 2026): Tightened profit targets to lock gains faster
# NIJA is for PROFIT - take gains quickly before reversals
# Fee structure: See fee_aware_config.py - MARKET_ORDER_ROUND_TRIP = 1.4% (default)
# First target (1.5%) is NET profitable after fees: 1.5% - 1.4% = +0.1% profit
# Second target (1.2%) accepts small loss to prevent larger reversal: 1.2% - 1.4% = -0.2% (vs -1.0% stop)
# Third target (1.0%) is emergency exit: 1.0% - 1.4% = -0.4% (still better than -1.0% stop loss)
# The bot checks targets from TOP to BOTTOM, so it exits at 1.5% if available, 1.2% if not, etc.

# Stop loss thresholds - AGGRESSIVE to cut losses fast (V7.3 FIX)
# Jan 13, 2026: Tightened to -1.0% to cut losses IMMEDIATELY
# NIJA is for PROFIT, not losses - exit losing trades fast to preserve capital
# Any position at -1% is likely to continue falling - better to exit and find new opportunities
# Combined with 8-hour max hold time and technical exits for triple protection
STOP_LOSS_THRESHOLD = -1.0  # Exit at -1.0% loss (AGGRESSIVE - cut losses fast)
STOP_LOSS_WARNING = -0.7  # Warn at -0.7% loss (meaningful early warning without noise)

# Position management constants - PROFITABILITY FIX (Dec 28, 2025)
# Updated Dec 30, 2025: Lowered minimums to allow very small account trading
# ⚠️ CRITICAL WARNING: Positions under $10 are likely unprofitable due to fees (~1.4% round-trip)
# With $1-2 positions, expect fees to consume most/all profits
# This allows trading for learning/testing but profitability is severely limited
# STRONG RECOMMENDATION: Fund account to $30+ for better trading outcomes
MAX_POSITIONS_ALLOWED = 8  # Maximum concurrent positions (including protected/micro positions)
MIN_POSITION_SIZE_USD = 1.0  # Minimum position size in USD (lowered from $10 to allow very small accounts)
MIN_BALANCE_TO_TRADE_USD = 1.0  # Minimum account balance to allow trading (lowered from $2 to allow trading with $1.37)

def call_with_timeout(func, args=(), kwargs=None, timeout_seconds=30):
    """
    Execute a function with a timeout. Returns (result, error).
    If timeout occurs, returns (None, TimeoutError).
    Default timeout is 30 seconds to accommodate production API latency.
    """
    if kwargs is None:
        kwargs = {}
    result_queue = queue.Queue()

    def worker():
        try:
            result = func(*args, **kwargs)
            result_queue.put((True, result))
        except Exception as e:
            result_queue.put((False, e))

    t = Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout_seconds)

    if t.is_alive():
        return None, TimeoutError(f"Operation timed out after {timeout_seconds}s")

    try:
        ok, value = result_queue.get_nowait()
        return (value, None) if ok else (None, value)
    except queue.Empty:
        return None, Exception("No result returned from worker")

# Add bot directory to path if running from root
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Optional market price helper; safe fallback if unavailable
try:
    from bot.market_data import get_current_price  # type: ignore
except Exception:
    def get_current_price(symbol: str):
        """Fallback price lookup (returns None if unavailable)."""
        return None

class TradingStrategy:
    """Production Trading Strategy - Coinbase APEX v7.1.

    Encapsulates the full APEX v7.1 trading strategy with position cap enforcement.
    Integrates market scanning, entry/exit logic, risk management, and automated
    position limit enforcement.
    """

    def __init__(self):
        """Initialize production strategy with multi-broker support."""
        logger.info("Initializing TradingStrategy (APEX v7.1 - Multi-Broker Mode)...")
        
        # Track positions that can't be sold (too small/dust) to avoid infinite retry loops
        self.unsellable_positions = set()  # Set of symbols that failed to sell due to size issues
        
        # Market rotation state (prevents scanning same markets every cycle)
        self.market_rotation_offset = 0  # Tracks which batch of markets to scan next
        self.all_markets_cache = []      # Cache of all available markets
        self.markets_cache_time = 0      # Timestamp of last market list refresh
        self.MARKETS_CACHE_TTL = 3600    # Refresh market list every hour
        
        # Rate limiting warmup state (prevents API bans on startup)
        self.cycle_count = 0             # Track number of cycles for warmup
        self.api_health_score = 100      # 0-100, degrades on errors, recovers on success
        
        # Candle data cache (prevents duplicate API calls for same market/timeframe)
        self.candle_cache = {}           # {symbol: (timestamp, candles_data)}
        self.CANDLE_CACHE_TTL = 150      # Cache candles for 2.5 minutes (one cycle)
        
        # Initialize advanced trading features (progressive targets, exchange profiles, capital allocation)
        self.advanced_manager = None
        self._init_advanced_features()
        
        try:
            # Lazy imports to avoid circular deps and allow fallback
            from broker_manager import (
                BrokerManager, CoinbaseBroker, KrakenBroker, 
                OKXBroker, BinanceBroker, AlpacaBroker, BrokerType, AccountType
            )
            from multi_account_broker_manager import MultiAccountBrokerManager
            from position_cap_enforcer import PositionCapEnforcer
            from nija_apex_strategy_v71 import NIJAApexStrategyV71
            
            # Initialize multi-account broker manager for user-specific trading
            logger.info("=" * 70)
            logger.info("🌐 MULTI-ACCOUNT TRADING MODE ACTIVATED")
            logger.info("=" * 70)
            logger.info("   Master account + User accounts trading independently")
            logger.info("=" * 70)
            
            self.multi_account_manager = MultiAccountBrokerManager()
            self.broker_manager = BrokerManager()  # Keep for backward compatibility
            connected_brokers = []
            user_brokers = []
            
            # Add startup delay to avoid immediate rate limiting on restart
            # CRITICAL (Jan 2026): Increased to 45s to ensure API rate limits fully reset
            # Previous 30s delay was still causing rate limit issues in production
            # Coinbase appears to have a ~30-60 second cooldown period after 403 errors
            # Combined with improved retry logic (10 attempts, 15s base delay with 120s cap),
            # this gives the bot multiple chances to recover from temporary API blocks
            startup_delay = 45
            logger.info(f"⏱️  Waiting {startup_delay}s before connecting to avoid rate limits...")
            time.sleep(startup_delay)
            logger.info("✅ Startup delay complete, beginning broker connections...")
            
            # Try to connect Coinbase (primary broker) - MASTER ACCOUNT
            logger.info("📊 Attempting to connect Coinbase Advanced Trade (MASTER)...")
            try:
                coinbase = CoinbaseBroker()
                if coinbase.connect():
                    self.broker_manager.add_broker(coinbase)
                    # Manually register in multi_account_manager (reuse same instance)
                    self.multi_account_manager.master_brokers[BrokerType.COINBASE] = coinbase
                    connected_brokers.append("Coinbase")
                    logger.info("   ✅ Coinbase MASTER connected")
                    logger.info("   ✅ Coinbase registered as MASTER broker in multi-account manager")
                else:
                    logger.warning("   ⚠️  Coinbase MASTER connection failed")
            except Exception as e:
                logger.warning(f"   ⚠️  Coinbase MASTER error: {e}")
            
            # Add delay between broker connections to avoid rate limiting
            time.sleep(2.0)  # Increased from 0.5s to 2.0s
            
            # Try to connect Kraken Pro - MASTER ACCOUNT
            logger.info("📊 Attempting to connect Kraken Pro (MASTER)...")
            try:
                kraken = KrakenBroker(account_type=AccountType.MASTER)
                if kraken.connect():
                    self.broker_manager.add_broker(kraken)
                    # Manually register in multi_account_manager (reuse same instance)
                    self.multi_account_manager.master_brokers[BrokerType.KRAKEN] = kraken
                    connected_brokers.append("Kraken")
                    logger.info("   ✅ Kraken MASTER connected")
                    logger.info("   ✅ Kraken registered as MASTER broker in multi-account manager")
                else:
                    logger.warning("   ⚠️  Kraken MASTER connection failed")
            except Exception as e:
                logger.warning(f"   ⚠️  Kraken MASTER error: {e}")
            
            # Add delay between broker connections
            time.sleep(0.5)
            
            # Try to connect OKX - MASTER ACCOUNT
            logger.info("📊 Attempting to connect OKX (MASTER)...")
            try:
                okx = OKXBroker()
                if okx.connect():
                    self.broker_manager.add_broker(okx)
                    # Manually register in multi_account_manager (reuse same instance)
                    self.multi_account_manager.master_brokers[BrokerType.OKX] = okx
                    connected_brokers.append("OKX")
                    logger.info("   ✅ OKX MASTER connected")
                    logger.info("   ✅ OKX registered as MASTER broker in multi-account manager")
                else:
                    logger.warning("   ⚠️  OKX MASTER connection failed")
            except Exception as e:
                logger.warning(f"   ⚠️  OKX MASTER error: {e}")
            
            # Add delay between broker connections
            time.sleep(0.5)
            
            # Try to connect Binance - MASTER ACCOUNT
            logger.info("📊 Attempting to connect Binance (MASTER)...")
            try:
                binance = BinanceBroker()
                if binance.connect():
                    self.broker_manager.add_broker(binance)
                    # Manually register in multi_account_manager (reuse same instance)
                    self.multi_account_manager.master_brokers[BrokerType.BINANCE] = binance
                    connected_brokers.append("Binance")
                    logger.info("   ✅ Binance MASTER connected")
                    logger.info("   ✅ Binance registered as MASTER broker in multi-account manager")
                else:
                    logger.warning("   ⚠️  Binance MASTER connection failed")
            except Exception as e:
                logger.warning(f"   ⚠️  Binance MASTER error: {e}")
            
            # Add delay between broker connections
            time.sleep(0.5)
            
            # Try to connect Alpaca (for stocks) - MASTER ACCOUNT
            logger.info("📊 Attempting to connect Alpaca (MASTER - Paper Trading)...")
            try:
                alpaca = AlpacaBroker()
                if alpaca.connect():
                    self.broker_manager.add_broker(alpaca)
                    # Manually register in multi_account_manager (reuse same instance)
                    self.multi_account_manager.master_brokers[BrokerType.ALPACA] = alpaca
                    connected_brokers.append("Alpaca")
                    logger.info("   ✅ Alpaca MASTER connected")
                    logger.info("   ✅ Alpaca registered as MASTER broker in multi-account manager")
                else:
                    logger.warning("   ⚠️  Alpaca MASTER connection failed")
            except Exception as e:
                logger.warning(f"   ⚠️  Alpaca MASTER error: {e}")
            
            # Add delay before user account connections to ensure master account
            # connection has completed and nonce ranges are separated
            # Increased from 1.0s to 2.0s to reduce nonce collision risk
            time.sleep(2.0)
            
            # Connect User Accounts - Load from config files
            logger.info("=" * 70)
            logger.info("👤 CONNECTING USER ACCOUNTS FROM CONFIG FILES")
            logger.info("=" * 70)
            
            # Use the new config-based user loading system
            connected_user_brokers = self.multi_account_manager.connect_users_from_config()
            
            # Track which users were successfully connected
            user_brokers = []
            if connected_user_brokers:
                for brokerage, user_ids in connected_user_brokers.items():
                    for user_id in user_ids:
                        user_brokers.append(f"{user_id}: {brokerage.title()}")
            
            logger.info("=" * 70)
            logger.info("✅ Broker connection phase complete")
            if connected_brokers or user_brokers:
                if connected_brokers:
                    logger.info(f"✅ MASTER ACCOUNT BROKERS: {', '.join(connected_brokers)}")
                    
                    # HELPFUL TIP: If only Coinbase is connected, suggest enabling Kraken
                    if len(connected_brokers) == 1 and "Coinbase" in connected_brokers:
                        logger.warning("=" * 70)
                        logger.warning("⚠️  SINGLE EXCHANGE TRADING - CONSIDER ENABLING KRAKEN")
                        logger.warning("=" * 70)
                        logger.warning("You're trading on Coinbase only, which may cause rate limiting.")
                        logger.warning("Enable Kraken to distribute load across multiple exchanges:")
                        logger.warning("")
                        logger.warning("1. Get API credentials from https://www.kraken.com/u/security/api")
                        logger.warning("2. Set environment variables:")
                        logger.warning("   KRAKEN_MASTER_API_KEY=<your-api-key>")
                        logger.warning("   KRAKEN_MASTER_API_SECRET=<your-api-secret>")
                        logger.warning("3. Restart the bot")
                        logger.warning("")
                        logger.warning("Benefits:")
                        logger.warning("✓ Reduced API rate limiting (load split across exchanges)")
                        logger.warning("✓ More resilient trading (if one exchange has issues)")
                        logger.warning("✓ Access to different cryptocurrency pairs")
                        logger.warning("")
                        logger.warning("📖 See MULTI_EXCHANGE_TRADING_GUIDE.md for detailed instructions")
                        logger.warning("=" * 70)
                if user_brokers:
                    logger.info(f"👥 USER ACCOUNT BROKERS: {', '.join(user_brokers)}")
                
                # CRITICAL: Master and users are COMPLETELY INDEPENDENT
                # Master balance is ONLY for master account - users don't affect it
                master_balance = self.broker_manager.get_total_balance()
                
                # Get user balances dynamically from multi_account_manager (for reporting only)
                user_total_balance = 0.0
                if self.multi_account_manager.user_brokers:
                    for user_id, user_broker_dict in self.multi_account_manager.user_brokers.items():
                        for broker_type, broker in user_broker_dict.items():
                            try:
                                if broker.connected:
                                    user_balance = broker.get_account_balance()
                                    user_total_balance += user_balance
                            except Exception as e:
                                logger.debug(f"Could not get balance for {user_id}: {e}")
                
                # Report balances separately - DO NOT combine them
                logger.info(f"💰 MASTER ACCOUNT BALANCE: ${master_balance:,.2f}")
                if user_total_balance > 0:
                    logger.info(f"💰 USER ACCOUNTS BALANCE (INDEPENDENT): ${user_total_balance:,.2f}")
                
                # CRITICAL: Update advanced manager with ONLY master balance
                # Users are completely independent and don't affect master's capital allocation
                if self.advanced_manager and master_balance > 0:
                    try:
                        self.advanced_manager.capital_allocator.update_total_capital(master_balance)
                        logger.info(f"   ✅ Master capital allocation: ${master_balance:,.2f}")
                    except Exception as e:
                        logger.warning(f"   Failed to update master capital allocation: {e}")
                
                # Get the primary broker from broker_manager (auto-set when brokers were added)
                # This is used for master account trading
                self.broker = self.broker_manager.get_primary_broker()
                if self.broker:
                    logger.info(f"📌 Primary master broker: {self.broker.broker_type.value}")
                else:
                    logger.warning("⚠️  No primary master broker available")
            else:
                logger.error("❌ NO BROKERS CONNECTED - Running in monitor mode")
                self.broker = None
            
            # Log clear trading status summary
            logger.info("=" * 70)
            logger.info("📊 ACCOUNT TRADING STATUS SUMMARY")
            logger.info("=" * 70)
            
            # Master account status
            if self.broker:
                logger.info(f"✅ MASTER ACCOUNT: TRADING (Broker: {self.broker.broker_type.value})")
            else:
                logger.info("❌ MASTER ACCOUNT: NOT TRADING (No broker connected)")
            
            # User account status - dynamically load from config
            try:
                from config.user_loader import get_user_config_loader
                user_loader = get_user_config_loader()
                enabled_users = user_loader.get_all_enabled_users()
                
                if enabled_users:
                    for user in enabled_users:
                        # Check if this user is actually connected
                        user_broker = self.multi_account_manager.get_user_broker(
                            user.user_id, 
                            BrokerType[user.broker_type.upper()]
                        )
                        
                        if user_broker and user_broker.connected:
                            logger.info(f"✅ USER: {user.name}: TRADING (Broker: {user.broker_type.title()})")
                        else:
                            logger.info(f"❌ USER: {user.name}: NOT TRADING (Connection failed or not configured)")
                else:
                    logger.info("⚪ No user accounts configured")
            except Exception as e:
                logger.warning(f"⚠️  Could not load user status from config: {e}")
                # Fallback: show status based on connected user brokers
                if self.multi_account_manager.user_brokers:
                    for user_id, user_broker_dict in self.multi_account_manager.user_brokers.items():
                        for broker_type, broker in user_broker_dict.items():
                            if broker.connected:
                                logger.info(f"✅ USER: {user_id}: TRADING (Broker: {broker_type.value.title()})")
                            else:
                                logger.info(f"❌ USER: {user_id}: NOT TRADING (Connection failed)")
            
            logger.info("=" * 70)
            
            # Initialize independent broker trader for multi-broker support
            try:
                from independent_broker_trader import IndependentBrokerTrader
                self.independent_trader = IndependentBrokerTrader(
                    self.broker_manager, 
                    self,
                    self.multi_account_manager  # Pass multi-account manager for user trading
                )
                logger.info("✅ Independent broker trader initialized")
            except Exception as indie_err:
                logger.warning(f"⚠️  Independent trader initialization failed: {indie_err}")
                self.independent_trader = None
                logger.warning("No primary broker available")
            
            # Initialize position cap enforcer (Maximum 8 positions total across all brokers)
            if self.broker:
                self.enforcer = PositionCapEnforcer(max_positions=8, broker=self.broker)
                
                # Initialize broker failsafes (hard limits and circuit breakers)
                # CRITICAL: Use ONLY master balance, not user balances
                try:
                    from broker_failsafes import create_failsafe_for_broker
                    broker_name = self.broker.broker_type.value if hasattr(self.broker, 'broker_type') else 'coinbase'
                    # Use master_balance only - users are completely independent
                    account_balance = master_balance if master_balance > 0 else 100.0
                    self.failsafes = create_failsafe_for_broker(broker_name, account_balance)
                    logger.info(f"🛡️  Broker failsafes initialized for {broker_name} (Master balance: ${account_balance:,.2f})")
                except Exception as e:
                    logger.warning(f"⚠️  Failed to initialize broker failsafes: {e}")
                    self.failsafes = None
                
                # Initialize market adaptation engine
                try:
                    from market_adaptation import create_market_adapter
                    self.market_adapter = create_market_adapter(learning_enabled=True)
                    logger.info(f"🧠 Market adaptation engine initialized with learning enabled")
                except Exception as e:
                    logger.warning(f"⚠️  Failed to initialize market adaptation: {e}")
                    self.market_adapter = None
                
                # Initialize APEX strategy with primary broker
                self.apex = NIJAApexStrategyV71(broker_client=self.broker)
                
                # Add delay before syncing positions to avoid rate limiting
                time.sleep(0.5)
                
                # CRITICAL: Sync position tracker with actual broker positions at startup
                if hasattr(self.broker, 'position_tracker') and self.broker.position_tracker:
                    try:
                        broker_positions = self.broker.get_positions()
                        removed = self.broker.position_tracker.sync_with_broker(broker_positions)
                        if removed > 0:
                            logger.info(f"🔄 Synced position tracker: removed {removed} orphaned positions")
                    except Exception as sync_err:
                        logger.warning(f"⚠️ Position tracker sync failed: {sync_err}")
                
                logger.info("✅ TradingStrategy initialized (APEX v7.1 + Multi-Broker + 8-Position Cap)")
            else:
                logger.warning("Strategy initialized in monitor mode (no active brokers)")
                self.enforcer = None
                self.apex = None
        
        except ImportError as e:
            logger.error(f"Failed to import strategy modules: {e}")
            logger.error("Falling back to safe monitor mode (no trades)")
            self.broker = None
            self.broker_manager = None
            self.enforcer = None
            self.apex = None
            self.independent_trader = None
    
    def _init_advanced_features(self):
        """Initialize progressive targets, exchange risk profiles, and capital allocation.
        
        This is optional and will gracefully degrade if modules are not available.
        """
        try:
            # Import advanced trading modules
            from advanced_trading_integration import AdvancedTradingManager, ExchangeType
            
            # Get initial capital estimate (will be updated after broker connection)
            # Validate the environment variable before conversion
            initial_capital_str = os.getenv('INITIAL_CAPITAL', '100')
            try:
                initial_capital = float(initial_capital_str)
                if initial_capital <= 0:
                    logger.warning(f"⚠️ Invalid INITIAL_CAPITAL={initial_capital_str}, using default $100")
                    initial_capital = 100.0
            except (ValueError, TypeError):
                logger.warning(f"⚠️ Invalid INITIAL_CAPITAL={initial_capital_str}, using default $100")
                initial_capital = 100.0
            
            allocation_strategy = os.getenv('ALLOCATION_STRATEGY', 'conservative')
            
            # Initialize advanced manager
            self.advanced_manager = AdvancedTradingManager(
                total_capital=initial_capital,
                allocation_strategy=allocation_strategy
            )
            
            logger.info("=" * 70)
            logger.info("✅ Advanced Trading Features Enabled:")
            logger.info(f"   📈 Progressive Targets: ${self.advanced_manager.target_manager.get_current_target():.2f}/day")
            logger.info(f"   🏦 Exchange Profiles: Loaded")
            logger.info(f"   💰 Capital Allocation: {allocation_strategy}")
            logger.info("=" * 70)
            
        except ImportError as e:
            logger.info(f"ℹ️ Advanced trading features not available: {e}")
            logger.info("   Continuing with standard trading mode")
            self.advanced_manager = None
        except Exception as e:
            logger.warning(f"⚠️ Failed to initialize advanced features: {e}")
            self.advanced_manager = None
    
    def start_independent_multi_broker_trading(self):
        """
        Start independent trading threads for all connected and funded brokers.
        Each broker operates in complete isolation to prevent cascade failures.
        
        Returns:
            bool: True if independent trading started successfully
        """
        if not self.independent_trader:
            logger.warning("⚠️  Independent trader not initialized")
            return False
        
        if not self.broker_manager or not self.broker_manager.brokers:
            logger.warning("⚠️  No brokers available for independent trading")
            return False
        
        try:
            # Start independent trading threads
            self.independent_trader.start_independent_trading()
            return True
        except Exception as e:
            logger.error(f"❌ Failed to start independent trading: {e}")
            return False
    
    def stop_independent_trading(self):
        """
        Stop all independent trading threads gracefully.
        """
        if self.independent_trader:
            self.independent_trader.stop_all_trading()
        else:
            logger.warning("⚠️  Independent trader not initialized, nothing to stop")
    
    def get_multi_broker_status(self) -> Dict:
        """
        Get status of all brokers and independent trading.
        
        Returns:
            dict: Status summary including broker health and trading activity
        """
        if not self.independent_trader:
            return {
                'error': 'Independent trader not initialized',
                'mode': 'single_broker'
            }
        
        return self.independent_trader.get_status_summary()
    
    def log_multi_broker_status(self):
        """
        Log current status of all brokers.
        """
        if self.independent_trader:
            self.independent_trader.log_status_summary()
        else:
            logger.info("📊 Single broker mode (independent trading not enabled)")
    
    def _get_cached_candles(self, symbol: str, timeframe: str = '5m', count: int = 100, broker=None):
        """
        Get candles with caching to reduce API calls.
        
        Args:
            symbol: Trading pair symbol
            timeframe: Candle timeframe
            count: Number of candles
            broker: Optional broker instance to use. If not provided, uses self.broker.
            
        Returns:
            List of candle dicts or empty list
        """
        # Use provided broker or fall back to self.broker
        active_broker = broker if broker is not None else self.broker
        
        cache_key = f"{symbol}_{timeframe}_{count}"
        current_time = time.time()
        
        # Check cache first
        if cache_key in self.candle_cache:
            cached_time, cached_data = self.candle_cache[cache_key]
            if current_time - cached_time < self.CANDLE_CACHE_TTL:
                logger.debug(f"   {symbol}: Using cached candles (age: {int(current_time - cached_time)}s)")
                return cached_data
        
        # Cache miss or expired - fetch fresh data
        candles = active_broker.get_candles(symbol, timeframe, count)
        
        # Cache the result (even if empty, to avoid repeated failed requests)
        self.candle_cache[cache_key] = (current_time, candles)
        
        return candles
    
    def _get_broker_name(self, broker) -> str:
        """
        Get broker name for logging from broker instance.
        
        Args:
            broker: Broker instance (may be None or lack broker_type)
            
        Returns:
            str: Broker name (e.g., 'coinbase', 'kraken') or 'unknown'
        """
        return broker.broker_type.value if broker and hasattr(broker, 'broker_type') else 'unknown'
    
    def _get_rotated_markets(self, all_markets: list) -> list:
        """
        Get next batch of markets to scan using rotation strategy.
        
        UPDATED (Jan 10, 2026): Added adaptive batch sizing to prevent API rate limiting
        - Starts with small batch (5 markets) on fresh start or after API errors
        - Gradually increases to max batch size (15 markets) over warmup period
        - Reduces batch size when API health score is low
        
        This prevents scanning the same markets every cycle and distributes
        API load across time. With 730 markets and batch size of 5-15,
        we complete a full rotation in multiple hours.
        
        Args:
            all_markets: Full list of available markets
            
        Returns:
            Subset of markets for this cycle
        """
        # Calculate adaptive batch size based on warmup and API health
        if self.cycle_count < MARKET_BATCH_WARMUP_CYCLES:
            # Warmup phase: use minimum batch size
            batch_size = MARKET_BATCH_SIZE_MIN
            logger.info(f"   🔥 Warmup mode: cycle {self.cycle_count + 1}/{MARKET_BATCH_WARMUP_CYCLES}, batch size={batch_size}")
        elif self.api_health_score < 50:
            # API health degraded: reduce batch size
            batch_size = MARKET_BATCH_SIZE_MIN
            logger.warning(f"   ⚠️  API health low ({self.api_health_score}%), using reduced batch size={batch_size}")
        elif self.api_health_score < 80:
            # Moderate health: use mid-range batch size
            batch_size = (MARKET_BATCH_SIZE_MIN + MARKET_BATCH_SIZE_MAX) // 2
            logger.info(f"   📊 API health moderate ({self.api_health_score}%), batch size={batch_size}")
        else:
            # Good health: use maximum batch size
            batch_size = MARKET_BATCH_SIZE_MAX
        
        if not MARKET_ROTATION_ENABLED or len(all_markets) <= batch_size:
            # If rotation disabled or fewer markets than batch size, use all markets
            return all_markets[:batch_size]
        
        # Calculate batch boundaries
        total_markets = len(all_markets)
        start_idx = self.market_rotation_offset
        end_idx = start_idx + batch_size
        
        # Handle wrap-around
        if end_idx <= total_markets:
            batch = all_markets[start_idx:end_idx]
        else:
            # Wrap around to beginning
            batch = all_markets[start_idx:] + all_markets[:end_idx - total_markets]
        
        # Update offset for next cycle
        self.market_rotation_offset = end_idx % total_markets
        
        # Log rotation progress
        rotation_pct = (self.market_rotation_offset / total_markets) * 100
        logger.info(f"   📊 Market rotation: scanning batch {start_idx}-{min(end_idx, total_markets)} of {total_markets} ({rotation_pct:.0f}% through cycle)")
        
        return batch

    def run_cycle(self, broker=None):
        """Execute a complete trading cycle with position cap enforcement.
        
        Args:
            broker: Optional broker instance to use for this cycle. If not provided,
                   uses self.broker (default behavior for backward compatibility).
                   This parameter enables thread-safe multi-broker trading by avoiding
                   shared state mutation - each thread passes its own broker instance
                   instead of modifying the shared self.broker variable.
        
        Steps:
        1. Enforce position cap (auto-sell excess if needed)
        2. Scan markets for opportunities
        3. Execute entry/exit logic
        4. Update trailing stops and take profits
        5. Log cycle summary
        """
        # Use provided broker or fall back to self.broker (thread-safe approach)
        active_broker = broker if broker is not None else self.broker
        try:
            # 🚨 EMERGENCY: Check if LIQUIDATE_ALL mode is active
            liquidate_all_file = os.path.join(os.path.dirname(__file__), '..', 'LIQUIDATE_ALL_NOW.conf')
            if os.path.exists(liquidate_all_file):
                logger.error("🚨 EMERGENCY LIQUIDATION MODE ACTIVE")
                logger.error("   SELLING ALL POSITIONS IMMEDIATELY")
                
                sold_count = 0
                total_positions = 0
                
                try:
                    if active_broker:
                        try:
                            positions = call_with_timeout(active_broker.get_positions, timeout_seconds=30)
                            if positions[1]:  # Error occurred
                                logger.error(f"   Failed to get positions: {positions[1]}")
                                positions = []
                            else:
                                positions = positions[0] or []
                        except Exception as e:
                            logger.error(f"   Exception getting positions: {e}")
                            positions = []
                        
                        total_positions = len(positions)
                        logger.error(f"   Found {total_positions} positions to liquidate")
                        
                        for i, pos in enumerate(positions, 1):
                            try:
                                symbol = pos.get('symbol', 'UNKNOWN')
                                currency = pos.get('currency', symbol.split('-')[0])
                                quantity = pos.get('quantity', 0)
                                
                                if quantity <= 0:
                                    logger.error(f"   [{i}/{total_positions}] SKIPPING {currency} (quantity={quantity})")
                                    continue
                                
                                logger.error(f"   [{i}/{total_positions}] FORCE SELLING {quantity:.8f} {currency}...")
                                
                                try:
                                    result = call_with_timeout(
                                        active_broker.place_market_order,
                                        args=(symbol, 'sell', quantity),
                                        kwargs={'size_type': 'base'},
                                        timeout_seconds=30
                                    )
                                    if result[1]:  # Error from call_with_timeout
                                        logger.error(f"   ❌ Timeout/error selling {currency}: {result[1]}")
                                    else:
                                        result_dict = result[0] or {}
                                        if result_dict and result_dict.get('status') not in ['error', 'unfilled']:
                                            logger.error(f"   ✅ SOLD {currency}")
                                            sold_count += 1
                                        else:
                                            error_msg = result_dict.get('error', result_dict.get('message', 'Unknown'))
                                            logger.error(f"   ❌ Failed to sell {currency}: {error_msg}")
                                except Exception as e:
                                    logger.error(f"   ❌ Exception during sell: {e}")
                                
                                # Throttle to avoid Coinbase 429 rate limits
                                try:
                                    time.sleep(1.0)
                                except Exception:
                                    pass
                            
                            except Exception as pos_err:
                                logger.error(f"   ❌ Position processing error: {pos_err}")
                                continue
                        
                        logger.error(f"   Liquidation round complete: {sold_count}/{total_positions} sold")
                
                except Exception as liquidation_error:
                    logger.error(f"   ❌ Emergency liquidation critical error: {liquidation_error}")
                    import traceback
                    logger.error(traceback.format_exc())
                
                finally:
                    # GUARANTEED cleanup - always remove the trigger file
                    try:
                        if os.path.exists(liquidate_all_file):
                            os.remove(liquidate_all_file)
                            logger.error("✅ Emergency liquidation cycle complete - removed LIQUIDATE_ALL_NOW.conf")
                    except Exception as cleanup_err:
                        logger.error(f"   Warning: Could not delete trigger file: {cleanup_err}")
                
                return  # Skip normal trading cycle
            
            # CRITICAL: Enforce position cap first
            if self.enforcer:
                logger.info(f"🔍 Enforcing position cap (max {MAX_POSITIONS_ALLOWED})...")
                success, result = self.enforcer.enforce_cap()
                if result['excess'] > 0:
                    logger.warning(f"⚠️ Excess positions detected: {result['excess']} over cap")
                    logger.info(f"   Sold {result['sold']} positions")
            
            # CRITICAL: Check if new entries are blocked
            current_positions = active_broker.get_positions() if active_broker else []
            stop_entries_file = os.path.join(os.path.dirname(__file__), '..', 'STOP_ALL_ENTRIES.conf')
            entries_blocked = os.path.exists(stop_entries_file)
            
            if entries_blocked:
                logger.error("🛑 ALL NEW ENTRIES BLOCKED: STOP_ALL_ENTRIES.conf is active")
                logger.info("   Exiting positions only (no new buys)")
            elif len(current_positions) >= MAX_POSITIONS_ALLOWED:
                logger.warning(f"🛑 ENTRY BLOCKED: Position cap reached ({len(current_positions)}/{MAX_POSITIONS_ALLOWED})")
                logger.info("   Closing positions only until below cap")
            else:
                logger.info(f"✅ Position cap OK ({len(current_positions)}/{MAX_POSITIONS_ALLOWED}) - entries enabled")
            
            # Get account balance for position sizing
            if not active_broker or not self.apex:
                logger.info("📡 Monitor mode (strategy not loaded; no trades)")
                return
            
            # Get detailed balance including crypto holdings
            if hasattr(active_broker, 'get_account_balance_detailed'):
                balance_data = active_broker.get_account_balance_detailed()
            else:
                balance_data = {'trading_balance': active_broker.get_account_balance()}
            account_balance = balance_data.get('trading_balance', 0.0)
            logger.info(f"💰 Trading balance: ${account_balance:.2f}")
            
            # Small delay after balance check to avoid rapid-fire API calls
            time.sleep(0.5)
            
            # STEP 1: Manage existing positions (check for exits/profit taking)
            logger.info(f"📊 Managing {len(current_positions)} open position(s)...")
            
            # CRITICAL: If over position cap, prioritize selling weakest positions immediately
            # This ensures we get back under cap quickly to avoid further bleeding
            # Position cap set to 8 maximum concurrent positions
            positions_over_cap = len(current_positions) - MAX_POSITIONS_ALLOWED
            if positions_over_cap > 0:
                logger.warning(f"🚨 OVER POSITION CAP: {len(current_positions)}/{MAX_POSITIONS_ALLOWED} positions ({positions_over_cap} excess)")
                logger.warning(f"   Will prioritize selling {positions_over_cap} weakest positions first")
            
            # CRITICAL FIX: Identify ALL positions that need to exit first
            # Then sell them ALL concurrently, not one at a time
            positions_to_exit = []
            
            for position_idx, position in enumerate(current_positions):
                try:
                    symbol = position.get('symbol')
                    if not symbol:
                        continue
                    
                    # Skip positions we know can't be sold (too small/dust)
                    if symbol in self.unsellable_positions:
                        logger.debug(f"   ⏭️ Skipping {symbol} (marked as unsellable/dust)")
                        continue
                    
                    logger.info(f"   Analyzing {symbol}...")
                    
                    # Get current price
                    current_price = active_broker.get_current_price(symbol)
                    if not current_price or current_price == 0:
                        logger.warning(f"   ⚠️ Could not get price for {symbol}")
                        continue
                    
                    # Get position value
                    quantity = position.get('quantity', 0)
                    position_value = current_price * quantity
                    
                    logger.info(f"   {symbol}: {quantity:.8f} @ ${current_price:.2f} = ${position_value:.2f}")
                    
                    # PROFITABILITY MODE: Aggressive exit on weak markets
                    # Exit positions when market conditions deteriorate to prevent bleeding
                    
                    # CRITICAL FIX: We don't have entry_price from Coinbase API!
                    # Instead, use aggressive exit criteria based on:
                    # 1. Market conditions (if filter fails, exit immediately)
                    # 2. Small position size (anything under $1 should be exited)
                    # 3. RSI overbought/oversold (take profits or cut losses)
                    
                    # AUTO-EXIT small positions (under $1) - these are likely losers
                    if position_value < MIN_POSITION_VALUE:
                        logger.info(f"   🔴 SMALL POSITION AUTO-EXIT: {symbol} (${position_value:.2f} < ${MIN_POSITION_VALUE})")
                        positions_to_exit.append({
                            'symbol': symbol,
                            'quantity': quantity,
                            'reason': f'Small position cleanup (${position_value:.2f})'
                        })
                        continue
                    
                    # PROFIT-BASED EXIT LOGIC (NEW!)
                    # Check if we have entry price tracked for this position
                    entry_price_available = False
                    entry_time_available = False
                    position_age_hours = 0
                    
                    if active_broker and hasattr(active_broker, 'position_tracker') and active_broker.position_tracker:
                        try:
                            tracked_position = active_broker.position_tracker.get_position(symbol)
                            if tracked_position:
                                entry_price_available = True
                                
                                # Check position age for time-based exits
                                entry_time = tracked_position.get('first_entry_time')
                                if entry_time:
                                    try:
                                        entry_dt = datetime.fromisoformat(entry_time)
                                        now = datetime.now()
                                        position_age_hours = (now - entry_dt).total_seconds() / 3600
                                        entry_time_available = True
                                        
                                        # TIME-BASED EXIT: Auto-exit stale positions
                                        if position_age_hours >= MAX_POSITION_HOLD_HOURS:
                                            logger.warning(f"   ⏰ STALE POSITION EXIT: {symbol} held for {position_age_hours:.1f} hours (max: {MAX_POSITION_HOLD_HOURS})")
                                            positions_to_exit.append({
                                                'symbol': symbol,
                                                'quantity': quantity,
                                                'reason': f'Time-based exit (held {position_age_hours:.1f}h, max {MAX_POSITION_HOLD_HOURS}h)'
                                            })
                                            continue
                                        elif position_age_hours >= STALE_POSITION_WARNING_HOURS:
                                            logger.info(f"   ⚠️ Position aging: {symbol} held for {position_age_hours:.1f} hours")
                                    except Exception as time_err:
                                        logger.debug(f"   Could not parse entry time for {symbol}: {time_err}")
                            
                            pnl_data = active_broker.position_tracker.calculate_pnl(symbol, current_price)
                            if pnl_data:
                                entry_price_available = True
                                pnl_percent = pnl_data['pnl_percent']
                                pnl_dollars = pnl_data['pnl_dollars']
                                entry_price = pnl_data['entry_price']
                                
                                logger.info(f"   💰 P&L: ${pnl_dollars:+.2f} ({pnl_percent:+.2f}%) | Entry: ${entry_price:.2f}")
                                
                                # STEPPED PROFIT TAKING - Exit portions at profit targets
                                # This locks in gains and frees capital for new opportunities
                                # Check targets from highest to lowest
                                for target_pct, reason in PROFIT_TARGETS:
                                    if pnl_percent >= target_pct:
                                        logger.info(f"   🎯 PROFIT TARGET HIT: {symbol} at +{pnl_percent:.2f}% (target: +{target_pct}%)")
                                        positions_to_exit.append({
                                            'symbol': symbol,
                                            'quantity': quantity,
                                            'reason': f'{reason} hit (actual: +{pnl_percent:.2f}%)'
                                        })
                                        break  # Exit the for loop, continue to next position
                                else:
                                    # No profit target hit, check stop loss
                                    if pnl_percent <= STOP_LOSS_THRESHOLD:
                                        logger.warning(f"   🛑 STOP LOSS HIT: {symbol} at {pnl_percent:.2f}% (stop: {STOP_LOSS_THRESHOLD}%)")
                                        positions_to_exit.append({
                                            'symbol': symbol,
                                            'quantity': quantity,
                                            'reason': f'Stop loss {STOP_LOSS_THRESHOLD}% hit (actual: {pnl_percent:.2f}%)'
                                        })
                                    elif pnl_percent <= STOP_LOSS_WARNING:
                                        logger.warning(f"   ⚠️ Approaching stop loss: {symbol} at {pnl_percent:.2f}%")
                                        # Don't exit yet, but log it
                                    else:
                                        # Position has entry price but not at any exit threshold
                                        logger.info(f"   📊 Holding {symbol}: P&L {pnl_percent:+.2f}% (no exit threshold reached)")
                                    continue  # Continue to next position check
                                
                                # If we got here via break, skip remaining checks
                                continue
                                
                        except Exception as pnl_err:
                            logger.debug(f"   Could not calculate P&L for {symbol}: {pnl_err}")
                    
                    # Log if no entry price available - this helps debug why positions aren't taking profit
                    if not entry_price_available:
                        logger.warning(f"   ⚠️ No entry price tracked for {symbol} - using fallback exit logic")
                        logger.warning(f"      💡 Run import_current_positions.py to track this position")
                    
                    # Get market data for analysis (use cached method to prevent rate limiting)
                    candles = self._get_cached_candles(symbol, '5m', 100, broker=active_broker)
                    if not candles or len(candles) < MIN_CANDLES_REQUIRED:
                        logger.warning(f"   ⚠️ Insufficient data for {symbol} ({len(candles) if candles else 0} candles, need {MIN_CANDLES_REQUIRED})")
                        # CRITICAL: Exit positions we can't analyze to prevent blind holding
                        logger.info(f"   🔴 NO DATA EXIT: {symbol} (cannot analyze market)")
                        positions_to_exit.append({
                            'symbol': symbol,
                            'quantity': quantity,
                            'reason': 'Insufficient market data for analysis'
                        })
                        continue
                    
                    # Convert to DataFrame
                    df = pd.DataFrame(candles)
                    
                    # CRITICAL: Ensure numeric types for OHLCV data
                    for col in ['open', 'high', 'low', 'close', 'volume']:
                        if col in df.columns:
                            df[col] = pd.to_numeric(df[col], errors='coerce')
                    
                    # Calculate indicators for exit signal detection
                    logger.debug(f"   DEBUG candle types → close={type(df['close'].iloc[-1])}, open={type(df['open'].iloc[-1])}, volume={type(df['volume'].iloc[-1])}")
                    indicators = self.apex.calculate_indicators(df)
                    if not indicators:
                        # Can't analyze - exit to prevent blind holding
                        logger.warning(f"   ⚠️ No indicators for {symbol} - exiting")
                        positions_to_exit.append({
                            'symbol': symbol,
                            'quantity': quantity,
                            'reason': 'No indicators available'
                        })
                        continue
                    
                    # MOMENTUM-BASED PROFIT TAKING (for positions without entry price)
                    # When we don't have entry price, use price momentum and trend reversal signals
                    # This helps lock in gains on strong moves and cut losses on weak positions
                    
                    rsi = indicators.get('rsi', pd.Series()).iloc[-1] if 'rsi' in indicators else DEFAULT_RSI
                    
                    # ULTRA AGGRESSIVE: Exit on multiple signals to lock gains faster
                    # Jan 13, 2026: AGGRESSIVE thresholds to sell positions before reversals eat profits
                    
                    # Strong overbought (RSI > 55) - likely near top, take profits
                    if rsi > RSI_OVERBOUGHT_THRESHOLD:
                        logger.info(f"   📈 RSI OVERBOUGHT EXIT: {symbol} (RSI={rsi:.1f})")
                        positions_to_exit.append({
                            'symbol': symbol,
                            'quantity': quantity,
                            'reason': f'RSI overbought ({rsi:.1f}) - locking gains'
                        })
                        continue
                    
                    # Moderate overbought (RSI > 50) + weak momentum = exit (TIGHTENED from 52)
                    # This catches positions that are up but losing steam
                    if rsi > 50:
                        # Check if price is below short-term EMA (momentum weakening)
                        ema9 = indicators.get('ema_9', pd.Series()).iloc[-1] if 'ema_9' in indicators else current_price
                        if current_price < ema9:
                            logger.info(f"   📉 MOMENTUM REVERSAL EXIT: {symbol} (RSI={rsi:.1f}, price below EMA9)")
                            positions_to_exit.append({
                                'symbol': symbol,
                                'quantity': quantity,
                                'reason': f'Momentum reversal (RSI={rsi:.1f}, price<EMA9) - locking gains'
                            })
                            continue
                    
                    # NEW: Profit protection - exit if in profit zone (RSI 45-55) but price crosses below EMA9
                    # This prevents giving back profits when momentum shifts
                    # TIGHTENED range from 48-60 to 45-55 for earlier exits
                    if 45 < rsi < 55:
                        ema9 = indicators.get('ema_9', pd.Series()).iloc[-1] if 'ema_9' in indicators else current_price
                        ema21 = indicators.get('ema_21', pd.Series()).iloc[-1] if 'ema_21' in indicators else current_price
                        # If price crosses below both EMAs, momentum is shifting - protect gains
                        if current_price < ema9 and current_price < ema21:
                            logger.info(f"   🔻 PROFIT PROTECTION EXIT: {symbol} (RSI={rsi:.1f}, price below both EMAs)")
                            positions_to_exit.append({
                                'symbol': symbol,
                                'quantity': quantity,
                                'reason': f'Profit protection (RSI={rsi:.1f}, bearish cross) - locking gains'
                            })
                            continue
                    
                    # Oversold (RSI < 45) - prevent further losses (TIGHTENED from 40)
                    if rsi < RSI_OVERSOLD_THRESHOLD:
                        logger.info(f"   📉 RSI OVERSOLD EXIT: {symbol} (RSI={rsi:.1f}) - cutting losses")
                        positions_to_exit.append({
                            'symbol': symbol,
                            'quantity': quantity,
                            'reason': f'RSI oversold ({rsi:.1f}) - cutting losses'
                        })
                        continue
                    
                    # Moderate oversold (RSI < 50) + downtrend = exit (TIGHTENED from 48)
                    # This catches positions that are down and still falling
                    if rsi < 50:
                        # Check if price is in downtrend (below EMA21)
                        ema21 = indicators.get('ema_21', pd.Series()).iloc[-1] if 'ema_21' in indicators else current_price
                        if current_price < ema21:
                            logger.info(f"   📉 DOWNTREND EXIT: {symbol} (RSI={rsi:.1f}, price below EMA21)")
                            positions_to_exit.append({
                                'symbol': symbol,
                                'quantity': quantity,
                                'reason': f'Downtrend exit (RSI={rsi:.1f}, price<EMA21) - cutting losses'
                            })
                            continue
                    
                    # Check for weak market conditions (exit signal)
                    # This protects capital even without knowing entry price
                    allow_trade, trend, market_reason = self.apex.check_market_filter(df, indicators)
                    
                    # AGGRESSIVE: If market conditions deteriorate, exit immediately
                    if not allow_trade:
                        logger.info(f"   ⚠️ Market conditions weak: {market_reason}")
                        logger.info(f"   💰 MARKING {symbol} for concurrent exit")
                        positions_to_exit.append({
                            'symbol': symbol,
                            'quantity': quantity,
                            'reason': market_reason
                        })
                        continue
                    
                    # If we get here, position passes all checks - keep it
                    logger.info(f"   ✅ {symbol} passing all checks (RSI={rsi:.1f}, trend={trend})")
                    
                except Exception as e:
                    logger.error(f"   Error analyzing position {symbol}: {e}", exc_info=True)
                
                # Rate limiting: Add delay after each position check to prevent 429 errors
                # Skip delay after the last position
                if position_idx < len(current_positions) - 1:
                    jitter = random.uniform(0, 0.05)  # 0-50ms jitter
                    time.sleep(POSITION_CHECK_DELAY + jitter)
            
            # CRITICAL: If still over cap after normal exit analysis, force-sell weakest remaining positions
            # Position cap set to 8 maximum concurrent positions
            if len(current_positions) > MAX_POSITIONS_ALLOWED and len(positions_to_exit) < (len(current_positions) - MAX_POSITIONS_ALLOWED):
                logger.warning(f"🚨 STILL OVER CAP: Need to sell {len(current_positions) - MAX_POSITIONS_ALLOWED - len(positions_to_exit)} more positions")
                
                # Identify positions not yet marked for exit
                symbols_to_exit = {p['symbol'] for p in positions_to_exit}
                remaining_positions = [p for p in current_positions if p.get('symbol') not in symbols_to_exit]
                
                # Sort by USD value (smallest first - easiest to exit and lowest capital impact)
                remaining_sorted = sorted(remaining_positions, key=lambda p: p.get('quantity', 0) * active_broker.get_current_price(p.get('symbol', '')))
                
                # Force-sell smallest positions to get under cap
                positions_needed = (len(current_positions) - MAX_POSITIONS_ALLOWED) - len(positions_to_exit)
                for pos_idx, pos in enumerate(remaining_sorted[:positions_needed]):
                    symbol = pos.get('symbol')
                    quantity = pos.get('quantity', 0)
                    try:
                        price = active_broker.get_current_price(symbol)
                        value = quantity * price
                        logger.warning(f"   🔴 FORCE-EXIT to meet cap: {symbol} (${value:.2f})")
                        positions_to_exit.append({
                            'symbol': symbol,
                            'quantity': quantity,
                            'reason': f'Over position cap (${value:.2f})'
                        })
                    except Exception as price_err:
                        # Still add even if price fetch fails
                        logger.warning(f"   ⚠️ Could not get price for {symbol}: {price_err}")
                        positions_to_exit.append({
                            'symbol': symbol,
                            'quantity': quantity,
                            'reason': 'Over position cap'
                        })
                    
                    # Rate limiting: Add delay after each price check (except last one)
                    if pos_idx < positions_needed - 1:
                        jitter = random.uniform(0, 0.05)  # 0-50ms jitter
                        time.sleep(POSITION_CHECK_DELAY + jitter)
            
            # CRITICAL FIX: Now sell ALL positions concurrently (not one at a time)
            if positions_to_exit:
                logger.info(f"")
                logger.info(f"🔴 CONCURRENT EXIT: Selling {len(positions_to_exit)} positions NOW")
                logger.info(f"="*80)
                
                for i, pos_data in enumerate(positions_to_exit, 1):
                    symbol = pos_data['symbol']
                    quantity = pos_data['quantity']
                    reason = pos_data['reason']
                    
                    logger.info(f"[{i}/{len(positions_to_exit)}] Selling {symbol} ({reason})")
                    
                    # CRITICAL FIX (Jan 10, 2026): Validate symbol before placing order
                    # Prevents "ProductID is invalid" errors
                    if not symbol or not isinstance(symbol, str):
                        logger.error(f"  ❌ SKIPPING: Invalid symbol (value: {symbol}, type: {type(symbol)})")
                        continue
                    
                    try:
                        result = active_broker.place_market_order(
                            symbol=symbol,
                            side='sell',
                            quantity=quantity,
                            size_type='base'
                        )
                        if result and result.get('status') not in ['error', 'unfilled']:
                            logger.info(f"  ✅ {symbol} SOLD successfully!")
                            # Remove from unsellable set if it was there (position grew and became sellable)
                            self.unsellable_positions.discard(symbol)
                        else:
                            error_msg = result.get('error', result.get('message', 'Unknown')) if result else 'No response'
                            error_code = result.get('error') if result else None
                            logger.error(f"  ❌ {symbol} sell failed: {error_msg}")
                            logger.error(f"     Full result: {result}")
                            
                            # CRITICAL FIX (Jan 10, 2026): Handle INVALID_SYMBOL errors
                            # These indicate the symbol format is wrong or the product doesn't exist
                            is_invalid_symbol = (
                                error_code == 'INVALID_SYMBOL' or
                                'INVALID_SYMBOL' in str(error_msg) or
                                'invalid symbol' in str(error_msg).lower()
                            )
                            if is_invalid_symbol:
                                logger.error(f"     ⚠️ Symbol {symbol} is invalid or unsupported")
                                logger.error(f"     💡 This position will be skipped in future cycles")
                                self.unsellable_positions.add(symbol)
                                continue
                            
                            # If it's a dust/too-small position, mark it as unsellable to prevent infinite retries
                            # Check both error code and message for robustness
                            is_size_error = (
                                error_code == 'INVALID_SIZE' or 
                                'INVALID_SIZE' in str(error_msg) or 
                                'too small' in str(error_msg).lower() or
                                'minimum' in str(error_msg).lower()
                            )
                            if is_size_error:
                                logger.warning(f"     💡 Position {symbol} is too small to sell via API - marking as dust")
                                logger.warning(f"     💡 This position will be skipped in future cycles to prevent infinite loops")
                                self.unsellable_positions.add(symbol)
                    except Exception as sell_err:
                        logger.error(f"  ❌ {symbol} exception during sell: {sell_err}")
                        logger.error(f"     Error type: {type(sell_err).__name__}")
                        logger.error(f"     Traceback: {traceback.format_exc()}")
                    
                    # Rate limiting: Add delay after each sell order (except the last one)
                    if i < len(positions_to_exit):
                        jitter = random.uniform(0, 0.1)  # 0-100ms jitter
                        time.sleep(SELL_ORDER_DELAY + jitter)
                
                logger.info(f"="*80)
                logger.info(f"✅ Concurrent exit complete: {len(positions_to_exit)} positions processed")
                logger.info(f"")
            
            # STEP 2: Look for new entry opportunities (only if entries allowed)
            # CRITICAL PROFITABILITY FIX: Use module-level constants for consistency
            
            if not entries_blocked and len(current_positions) < MAX_POSITIONS_ALLOWED and account_balance >= MIN_BALANCE_TO_TRADE_USD:
                logger.info(f"🔍 Scanning for new opportunities (positions: {len(current_positions)}/{MAX_POSITIONS_ALLOWED}, balance: ${account_balance:.2f}, min: ${MIN_BALANCE_TO_TRADE_USD})...")
                
                # Get top market candidates (limit scan to prevent timeouts)
                try:
                    # Get list of all products (with caching to reduce API calls)
                    current_time = time.time()
                    if (not self.all_markets_cache or 
                        current_time - self.markets_cache_time > self.MARKETS_CACHE_TTL):
                        logger.info("   🔄 Refreshing market list from API...")
                        all_products = active_broker.get_all_products()
                        if all_products:
                            self.all_markets_cache = all_products
                            self.markets_cache_time = current_time
                            logger.info(f"   ✅ Cached {len(all_products)} markets")
                        else:
                            logger.warning("   ⚠️  No products available from API")
                            return
                    else:
                        all_products = self.all_markets_cache
                        cache_age = int(current_time - self.markets_cache_time)
                        logger.info(f"   ✅ Using cached market list ({len(all_products)} markets, age: {cache_age}s)")
                    
                    if not all_products:
                        logger.warning("   No products available for scanning")
                        return
                    
                    # Use rotation to scan different markets each cycle
                    markets_to_scan = self._get_rotated_markets(all_products)
                    scan_limit = len(markets_to_scan)
                    logger.info(f"   Scanning {scan_limit} markets (batch rotation mode)...")
                    
                    # Adaptive rate limiting: track consecutive errors (429, 403, or no data)
                    # UPDATED (Jan 10, 2026): Distinguish invalid symbols from genuine errors
                    rate_limit_counter = 0
                    error_counter = 0  # Track total errors including exceptions
                    invalid_symbol_counter = 0  # Track invalid/delisted symbols (don't count as errors)
                    max_consecutive_rate_limits = 2  # CRITICAL FIX (Jan 10): Reduced from 3 - activate circuit breaker faster
                    max_total_errors = 4  # CRITICAL FIX (Jan 10): Reduced from 5 - stop scan earlier to prevent API ban
                    
                    # Track filtering reasons for debugging
                    filter_stats = {
                        'total': 0,
                        'insufficient_data': 0,
                        'smart_filter': 0,
                        'market_filter': 0,
                        'no_entry_signal': 0,
                        'position_too_small': 0,
                        'signals_found': 0,
                        'rate_limited': 0,
                        'cache_hits': 0
                    }
                    
                    for i, symbol in enumerate(markets_to_scan):
                        filter_stats['total'] += 1
                        try:
                            # CRITICAL: Add delay BEFORE fetching candles to prevent rate limiting
                            # This is in addition to the delay after processing (line ~1201)
                            # Pre-delay ensures we never make requests too quickly in succession
                            if i > 0:  # Don't delay before first market
                                jitter = random.uniform(0, 0.3)  # Add 0-300ms jitter
                                time.sleep(MARKET_SCAN_DELAY + jitter)
                            
                            # Get candles with caching to reduce duplicate API calls
                            candles = self._get_cached_candles(symbol, '5m', 100, broker=active_broker)
                            
                            # Check if we got candles or if rate limited
                            if not candles:
                                # Empty candles could be:
                                # 1. Invalid/delisted symbol (don't count as error)
                                # 2. Rate limited (count as error)
                                # 3. No data available (count as error)
                                # We assume invalid symbol if we get consistent empty responses
                                
                                # Note: Invalid symbols are caught in get_candles() and return []
                                # So if we get here with no candles, it's likely rate limiting or no data
                                # We still increment counters but will check for invalid symbols in exceptions below
                                rate_limit_counter += 1
                                error_counter += 1
                                filter_stats['insufficient_data'] += 1
                                
                                # Degrade API health score on errors
                                self.api_health_score = max(0, self.api_health_score - 5)
                                
                                logger.debug(f"   {symbol}: No candles returned (may be rate limited or no data)")
                                
                                # GLOBAL CIRCUIT BREAKER: If too many total errors, stop scanning entirely
                                if error_counter >= max_total_errors:
                                    filter_stats['rate_limited'] += 1
                                    broker_name = self._get_broker_name(active_broker)
                                    logger.error(f"   🚨 GLOBAL CIRCUIT BREAKER: {error_counter} total errors - stopping scan to prevent API block")
                                    logger.error(f"   Exchange: {broker_name} | API health: {self.api_health_score}%")
                                    logger.error(f"   💤 Waiting 30s for API to fully recover before next cycle...")
                                    logger.error(f"   💡 TIP: Enable additional exchanges (Kraken, OKX, Binance) to distribute load")
                                    logger.error(f"   📖 See MULTI_EXCHANGE_TRADING_GUIDE.md for setup instructions")
                                    self.api_health_score = max(0, self.api_health_score - 20)  # Major penalty
                                    time.sleep(30.0)  # CRITICAL FIX (Jan 10): Increased from 20s to 30s for better recovery
                                    break  # Exit the market scan loop entirely
                                
                                # If we're getting many consecutive failures, assume rate limiting
                                if rate_limit_counter >= max_consecutive_rate_limits:
                                    filter_stats['rate_limited'] += 1
                                    logger.warning(f"   ⚠️ Possible rate limiting detected ({rate_limit_counter} consecutive failures)")
                                    logger.warning(f"   🛑 CIRCUIT BREAKER: Pausing for 15s to allow API to recover...")
                                    self.api_health_score = max(0, self.api_health_score - 10)  # Moderate penalty
                                    time.sleep(15.0)  # CRITICAL FIX (Jan 10): Decreased from 20s to 15s for consistency
                                    rate_limit_counter = 0  # Reset counter after delay
                                continue
                            elif len(candles) < 100:
                                rate_limit_counter = 0  # Reset on partial success
                                self.api_health_score = min(100, self.api_health_score + 1)  # Small recovery
                                filter_stats['insufficient_data'] += 1
                                logger.debug(f"   {symbol}: Insufficient candles ({len(candles)}/100)")
                                continue
                            else:
                                # Success! Reset rate limit counter and improve health
                                rate_limit_counter = 0
                                self.api_health_score = min(100, self.api_health_score + 2)  # Gradual recovery
                            
                            # Convert to DataFrame
                            df = pd.DataFrame(candles)
                            
                            # CRITICAL: Ensure numeric types
                            for col in ['open', 'high', 'low', 'close', 'volume']:
                                if col in df.columns:
                                    df[col] = pd.to_numeric(df[col], errors='coerce')
                            
                            # Analyze for entry
                            analysis = self.apex.analyze_market(df, symbol, account_balance)
                            action = analysis.get('action', 'hold')
                            reason = analysis.get('reason', '')
                            
                            # Track why we didn't trade
                            if action == 'hold':
                                if 'Insufficient data' in reason or 'candles' in reason:
                                    filter_stats['insufficient_data'] += 1
                                elif 'smart filter' in reason.lower() or 'volume too low' in reason.lower() or 'candle' in reason.lower():
                                    filter_stats['smart_filter'] += 1
                                    logger.debug(f"   {symbol}: Smart filter - {reason}")
                                elif 'ADX' in reason or 'Volume' in reason or 'Mixed signals' in reason:
                                    filter_stats['market_filter'] += 1
                                    logger.debug(f"   {symbol}: Market filter - {reason}")
                                else:
                                    filter_stats['no_entry_signal'] += 1
                                    logger.debug(f"   {symbol}: No signal - {reason}")
                                continue
                            
                            # Execute buy actions
                            if action in ['enter_long', 'enter_short']:
                                filter_stats['signals_found'] += 1
                                position_size = analysis.get('position_size', 0)
                                
                                # PROFITABILITY WARNING: Small positions have lower profitability
                                # Fees are ~1.4% round-trip, so very small positions face significant fee pressure
                                # MICRO TRADE PREVENTION: Block positions under $1 minimum
                                if position_size < MIN_POSITION_SIZE_USD:
                                    filter_stats['position_too_small'] += 1
                                    logger.warning(f"   🚫 MICRO TRADE BLOCKED: {symbol} position size ${position_size:.2f} < ${MIN_POSITION_SIZE_USD} minimum")
                                    logger.warning(f"      💡 Reason: Extremely small positions face severe fee impact (~1.4% round-trip)")
                                    # Calculate break-even % needed: (fee_dollars / position_size) * 100
                                    breakeven_pct = (position_size * 0.014 / position_size) * 100 if position_size > 0 else 0
                                    logger.warning(f"      📊 Need {breakeven_pct:.1f}% gain just to break even on fees")
                                    continue
                                
                                # Warn if position is very small but allowed
                                elif position_size < 2.0:
                                    logger.warning(f"   ⚠️  EXTREMELY SMALL POSITION: ${position_size:.2f} - profitability nearly impossible due to fees")
                                    logger.warning(f"      💡 URGENT: Fund account to $30+ for viable trading")
                                elif position_size < 5.0:
                                    logger.warning(f"   ⚠️  VERY SMALL POSITION: ${position_size:.2f} - profitability severely limited by fees")
                                    logger.warning(f"      💡 Recommended: Fund account to $30+ for better trading results")
                                elif position_size < 10.0:
                                    logger.warning(f"   ⚠️  Small position: ${position_size:.2f} - profitability may be limited by fees")
                                
                                # CRITICAL: Verify we're still under position cap
                                if len(current_positions) >= MAX_POSITIONS_ALLOWED:
                                    logger.warning(f"   ⚠️  Position cap ({MAX_POSITIONS_ALLOWED}) reached - STOP NEW ENTRIES")
                                    break
                                
                                logger.info(f"   🎯 BUY SIGNAL: {symbol} - size=${position_size:.2f} - {analysis.get('reason', '')}")
                                success = self.apex.execute_action(analysis, symbol)
                                if success:
                                    logger.info(f"   ✅ Position opened successfully")
                                    break  # Only open one position per cycle
                                else:
                                    logger.error(f"   ❌ Failed to open position")
                        
                        except Exception as e:
                            # CRITICAL FIX (Jan 10, 2026): Distinguish invalid symbols from rate limits
                            # Invalid symbols should NOT trigger circuit breakers or count as errors
                            error_str = str(e).lower()
                            
                            # More specific patterns to avoid false positives
                            is_productid_invalid = 'productid is invalid' in error_str or 'product_id is invalid' in error_str
                            is_invalid_argument = '400' in error_str and 'invalid_argument' in error_str
                            is_invalid_product_symbol = (
                                'invalid' in error_str and 
                                ('product' in error_str or 'symbol' in error_str) and
                                ('not found' in error_str or 'does not exist' in error_str or 'unknown' in error_str)
                            )
                            
                            is_invalid_symbol = is_productid_invalid or is_invalid_argument or is_invalid_product_symbol
                            
                            if is_invalid_symbol:
                                # Invalid/delisted symbol - skip silently without counting as error
                                invalid_symbol_counter += 1
                                filter_stats['market_filter'] += 1  # Count as filtered, not error
                                logger.debug(f"   ⚠️ Invalid/delisted symbol: {symbol} - skipping")
                                continue
                            
                            # Count as error only if not an invalid symbol
                            error_counter += 1
                            logger.debug(f"   Error scanning {symbol}: {e}")
                            
                            # Check if it's a rate limit error
                            if '429' in str(e) or 'rate limit' in str(e).lower() or 'too many' in str(e).lower() or '403' in str(e):
                                filter_stats['rate_limited'] += 1
                                rate_limit_counter += 1
                                logger.warning(f"   ⚠️ Rate limit error on {symbol}: {e}")
                                
                                # GLOBAL CIRCUIT BREAKER: Too many errors = stop scanning
                                if error_counter >= max_total_errors:
                                    broker_name = self._get_broker_name(active_broker)
                                    logger.error(f"   🚨 GLOBAL CIRCUIT BREAKER: {error_counter} total errors - stopping scan")
                                    logger.error(f"   Exchange: {broker_name} | API health: {self.api_health_score}%")
                                    logger.error(f"   💤 Waiting 10s for API to fully recover...")
                                    logger.error(f"   💡 TIP: Enable additional exchanges (Kraken, OKX, Binance) to distribute load")
                                    logger.error(f"   📖 See MULTI_EXCHANGE_TRADING_GUIDE.md for setup instructions")
                                    time.sleep(10.0)
                                    break  # Exit market scan loop
                                
                                # Add extra delay to recover
                                if rate_limit_counter >= 3:
                                    logger.warning(f"   🛑 CIRCUIT BREAKER: Pausing for 8s to allow API rate limits to reset...")
                                    time.sleep(8.0)  # Increased from 5.0s
                                    rate_limit_counter = 0
                            continue
                    
                    # Note: Market scan delay is now applied BEFORE each candle fetch (see line ~1088)
                    # This ensures we never make requests too quickly in succession
                    # No post-delay needed since pre-delay is more effective at preventing rate limits
                    
                    # Log filtering summary
                    logger.info(f"   📊 Scan summary: {filter_stats['total']} markets scanned")
                    logger.info(f"      💡 Signals found: {filter_stats['signals_found']}")
                    logger.info(f"      📉 No data: {filter_stats['insufficient_data']}")
                    
                    # Report invalid symbols separately (informational, not errors)
                    if invalid_symbol_counter > 0:
                        logger.info(f"      ℹ️ Invalid/delisted symbols: {invalid_symbol_counter} (skipped)")
                    
                    if filter_stats['rate_limited'] > 0:
                        logger.warning(f"      ⚠️ Rate limited: {filter_stats['rate_limited']} times")
                    logger.info(f"      🔇 Smart filter: {filter_stats['smart_filter']}")
                    logger.info(f"      📊 Market filter: {filter_stats['market_filter']}")
                    logger.info(f"      🚫 No entry signal: {filter_stats['no_entry_signal']}")
                    logger.info(f"      💵 Position too small: {filter_stats['position_too_small']}")
                
                except Exception as e:
                    logger.error(f"Error during market scan: {e}", exc_info=True)
            else:
                # Enhanced diagnostic logging to understand why entries are blocked
                reasons = []
                if entries_blocked:
                    reasons.append("STOP_ALL_ENTRIES.conf exists")
                if len(current_positions) >= MAX_POSITIONS_ALLOWED:
                    reasons.append(f"Position cap reached ({len(current_positions)}/{MAX_POSITIONS_ALLOWED})")
                if account_balance < MIN_BALANCE_TO_TRADE_USD:
                    reasons.append(f"Balance ${account_balance:.2f} < ${MIN_BALANCE_TO_TRADE_USD} minimum (need buffer for fees)")
                
                reason_str = ", ".join(reasons) if reasons else "Unknown reason"
                logger.info(f"   Skipping new entries: {reason_str}")
            
            # Increment cycle counter for warmup tracking
            self.cycle_count += 1
            
        except Exception as e:
            # Never raise to keep bot loop alive
            logger.error(f"Error in trading cycle: {e}", exc_info=True)
    
    def record_trade_with_advanced_manager(self, symbol: str, profit_usd: float, is_win: bool):
        """
        Record a completed trade with the advanced trading manager.
        
        Args:
            symbol: Trading symbol
            profit_usd: Profit/loss in USD
            is_win: True if trade was profitable
        """
        # Record with broker failsafes for circuit breaker protection
        if hasattr(self, 'failsafes') and self.failsafes:
            try:
                pnl_pct = (profit_usd / 100.0) if profit_usd != 0 else 0.0  # Approximate percentage
                self.failsafes.record_trade_result(profit_usd, pnl_pct)
            except Exception as e:
                logger.warning(f"Failed to record trade in failsafes: {e}")
        
        # Record with market adaptation for learning
        if hasattr(self, 'market_adapter') and self.market_adapter:
            try:
                # Estimate hold time (default 30 minutes if not tracked)
                hold_time_minutes = 30
                current_regime = getattr(self.market_adapter, 'current_regime', None)
                if current_regime:
                    self.market_adapter.record_trade_performance(
                        regime=current_regime,
                        pnl_dollars=profit_usd,
                        hold_time_minutes=hold_time_minutes,
                        parameters_used={'symbol': symbol}
                    )
            except Exception as e:
                logger.warning(f"Failed to record trade in market adapter: {e}")
        
        # Record with advanced manager (original functionality)
        if not self.advanced_manager:
            return
        
        try:
            # Determine which exchange was used
            from advanced_trading_integration import ExchangeType
            
            # Default to Coinbase as it's the primary broker
            exchange = ExchangeType.COINBASE
            
            # Try to detect actual exchange if broker type is available
            if hasattr(self, 'broker') and self.broker:
                broker_type = getattr(self.broker, 'broker_type', None)
                if broker_type:
                    exchange_mapping = {
                        'coinbase': ExchangeType.COINBASE,
                        'okx': ExchangeType.OKX,
                        'kraken': ExchangeType.KRAKEN,
                        'binance': ExchangeType.BINANCE,
                        'alpaca': ExchangeType.ALPACA,
                    }
                    broker_name = str(broker_type.value).lower() if hasattr(broker_type, 'value') else str(broker_type).lower()
                    exchange = exchange_mapping.get(broker_name, ExchangeType.COINBASE)
            
            # Record the trade
            self.advanced_manager.record_completed_trade(
                exchange=exchange,
                profit_usd=profit_usd,
                is_win=is_win
            )
            
            logger.debug(f"Recorded trade in advanced manager: {symbol} profit=${profit_usd:.2f} win={is_win}")
            
        except Exception as e:
            logger.warning(f"Failed to record trade in advanced manager: {e}")
    
    def process_end_of_day(self):
        """
        Process end-of-day tasks for advanced trading features.
        
        Should be called once per day to:
        - Check if daily profit target was achieved
        - Trigger rebalancing if needed
        - Generate performance reports
        """
        if not self.advanced_manager:
            return
        
        try:
            # Process end-of-day in advanced manager
            self.advanced_manager.process_end_of_day()
            
            # Log current status
            current_target = self.advanced_manager.target_manager.get_current_target()
            progress = self.advanced_manager.target_manager.get_progress_summary()
            
            logger.info("=" * 70)
            logger.info("📊 END OF DAY SUMMARY")
            logger.info(f"   Current Target: ${current_target:.2f}/day")
            logger.info(f"   Progress: {progress}")
            logger.info("=" * 70)
            
        except Exception as e:
            logger.warning(f"Failed to process end-of-day tasks: {e}")
