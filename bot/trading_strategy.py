import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
import os
import logging
import json
from logging.handlers import RotatingFileHandler

# Safe alias to avoid function-scope shadowing of os
_os = os

# Add bot directory to path if running from root
if os.path.basename(os.getcwd()) != 'bot':
    sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

# Setup logging (shared with live_trading.py)
LOG_FILE = os.path.join(os.path.dirname(__file__), '..', 'nija.log')
LOG_FILE = os.path.abspath(LOG_FILE)
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

from broker_manager import CoinbaseBroker
from mock_broker import MockBroker
from nija_apex_strategy_v71 import NIJAApexStrategyV71
from adaptive_growth_manager import AdaptiveGrowthManager
from trade_analytics import TradeAnalytics
from position_manager import PositionManager
from retry_handler import retry_handler
from indicators import calculate_vwap, calculate_ema, calculate_rsi, calculate_macd, calculate_atr, calculate_adx

# Unique build signature for deployment verification
STRATEGY_BUILD_ID = "TradingStrategy v7.1 init-hardened _os alias - 2025-12-24T17:40Z"

class TradingStrategy:
    """
    NIJA Ultimate Trading Strategy with APEX v7.1
    
    **ACTIVE PROFITABILITY MODE**: 5-8 quality trades continuously across 700+ markets
    - Smart filters: Avoid obvious losers, catch solid momentum
    - Score >= 60, RSI < 80 (allows strong trends, blocks parabolic)
    - 700+ markets scanned every 15s → Always finding opportunities
    - Continuous cycle: Fill 8 positions → TP → Refill → Repeat 24/7
    
    Features:
    - APEX v7.1 strategy engine with dual RSI indicators
    - Multi-market scanning (700+ cryptocurrency pairs)
    - Balanced profitability filters: Quality + Activity
    - Advanced entry/exit logic with trailing systems
    - Risk management and position sizing
    - Trade journal logging and performance tracking
    
    **PROFITABILITY FILTERS (BALANCED)**
    - ❌ Block RSI > 80 (parabolic/extreme)
    - ❌ Block score < 60 (weak setups)
    - ✅ Allow RSI 70-80 if score >= 75 (strong momentum)
    - ✅ 700+ markets = Always 5-8 quality opportunities available
    """
    
    def __init__(self):
        """Initialize trading strategy with broker and APEX strategy"""
        logger.info("Initializing NIJA Trading Strategy...")
        logger.info(f"BUILD SIGNATURE: {STRATEGY_BUILD_ID}")
        
        # Initialize broker connection (supports PAPER_MODE)
        paper_mode = str(_os.getenv("PAPER_MODE", "")).lower() in ("1", "true", "yes")
        if paper_mode:
            logger.info("PAPER_MODE enabled — using MockBroker")
            self.broker = MockBroker()
        else:
            self.broker = CoinbaseBroker()

        # Try connecting with limited retries for live mode
        if not paper_mode:
            max_attempts = 3
            delay = 2
            for attempt in range(1, max_attempts + 1):
                if self.broker.connect():
                    break
                logger.error(f"Coinbase connect failed (attempt {attempt}/{max_attempts})")
                if attempt < max_attempts:
                    time.sleep(delay)
                    delay = min(delay * 2, 15)
            else:
                logger.error("Failed to connect to Coinbase broker")
                logger.error("======================================================================")
                logger.error("❌ BROKER CONNECTION FAILED")
                logger.error("======================================================================")
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
                logger.error("======================================================================")
                raise RuntimeError("Broker connection failed")

            # One-time guard to prevent repeated rebalances per process
            self.rebalanced_once = False
        else:
            # Paper mode path: ensure MockBroker connects
            if not self.broker.connect():
                logger.error("MockBroker failed to initialize")
                raise RuntimeError("Mock broker initialization failed")
        
        logger.info("🔥 Broker connected, about to fetch balance...")
        print("🔥 BROKER CONNECTED, CALLING get_account_balance() NEXT", flush=True)
        
        # Initialize analytics tracker with correct path
        data_dir = _os.path.join(_os.path.dirname(__file__), '..', 'data')
        self.analytics = TradeAnalytics(data_dir=data_dir)
        logger.info("📊 Trade analytics initialized")
        
        # Initialize position manager
        self.position_manager = PositionManager()
        logger.info("💾 Position manager initialized")
        
        # Price cache to reduce API calls (cache expires after 30 seconds)
        # CRITICAL: Initialize BEFORE position syncing which needs price data
        self._price_cache = {}
        self._cache_timestamp = {}
        self._cache_ttl = 30  # seconds
        
        # Get account balance
        logger.info("🔥 Starting balance fetch...")
        print("🔥 ABOUT TO CALL self.broker.get_account_balance()", flush=True)
        try:
            balance = self.broker.get_account_balance()
            logger.info(f"🔥 Balance fetch returned: {balance} (type: {type(balance).__name__})")
            if isinstance(balance, dict):
                self.account_balance = float(balance.get("trading_balance", 0.0))
                logger.info(
                    f"🔥 Parsed USDC=${balance.get('usdc', 0.0):.2f} USD=${balance.get('usd', 0.0):.2f} "
                    f"→ trading_balance=${self.account_balance:.2f}"
                )
            else:
                self.account_balance = float(balance) if balance else 0.0
                logger.info(f"🔥 Balance converted to float: {self.account_balance}")
            logger.info(f"Account balance: ${self.account_balance:,.2f}")
            
            # EMERGENCY CHECK: Warn if balance is critically low
            MINIMUM_TRADING_BALANCE = float(_os.getenv("MINIMUM_TRADING_BALANCE", "25.0"))
            
            # Get total account value including crypto
            balance_dict = self.broker.get_account_balance()
            crypto_holdings = balance_dict.get('crypto', {}) if isinstance(balance_dict, dict) else {}
            total_crypto_value = sum(
                qty for qty in crypto_holdings.values() if isinstance(qty, (int, float)) and qty > 0
            )
            total_account_value = self.account_balance + total_crypto_value
            
            if total_account_value < MINIMUM_TRADING_BALANCE:
                logger.error("=" * 80)
                logger.error("🚨 CRITICAL WARNING: ACCOUNT BALANCE SEVERELY DEPLETED")
                logger.error("=" * 80)
                logger.error(f"   USD Cash: ${self.account_balance:.2f}")
                logger.error(f"   Crypto Value: ${total_crypto_value:.2f}")
                logger.error(f"   Total Account: ${total_account_value:.2f}")
                logger.error(f"   Minimum Required: ${MINIMUM_TRADING_BALANCE:.2f}")
                logger.error("")
                logger.error("   ⚠️  BUYING IS DISABLED - SELL-ONLY MODE ACTIVE")
                logger.error("   ⚠️  Bot will manage existing positions but NOT open new ones")
                logger.error("   ⚠️  Add funds to resume normal trading")
                logger.error("=" * 80)
            
            # Circuit breaker will prevent trading if balance < $25
            # No need for startup capital guard - let bot initialize and monitor
            
            # If initial balance is zero, print a clear banner with guidance
            if self.account_balance <= 0:
                logger.warning("""
==================== BALANCE NOTICE ====================
No USD/USDC trading balance detected via Advanced Trade API.
To enable trading:
- Move funds into your Advanced Trade portfolio: https://www.coinbase.com/advanced-portfolio
========================================================
""")
                # One-time USD/USDC inventory dump using broker helper so logs
                # go through the configured 'nija' logger/handlers.
                try:
                    if hasattr(self.broker, "get_usd_usdc_inventory"):
                        inv_lines = self.broker.get_usd_usdc_inventory()
                        if inv_lines:
                            logger.info("USD/USDC account inventory (Advanced Trade):")
                            for line in inv_lines:
                                logger.info(line)
                except Exception as inv_err:
                    logger.warning(f"USD/USDC inventory dump failed: {inv_err}")
        except Exception as e:
            logger.exception(f"🔥 CRITICAL: Failed to fetch/convert balance")
            logger.warning(f"Continuing with 0.0 balance")
            self.account_balance = 0.0
        
        # Initialize Adaptive Growth Manager
        self.growth_manager = AdaptiveGrowthManager()
        
        logger.info("🔥 Initializing APEX strategy with adaptive growth management...")
        try:
            # Get initial config based on current balance
            growth_config = self.growth_manager.get_current_config()
            logger.info(f"🧠 Growth Stage: {growth_config['description']}")
            
            tuned_min_adx = growth_config['min_adx'] + 5 if 'min_adx' in growth_config else 25
            tuned_volume = growth_config['volume_threshold'] * 1.15 if 'volume_threshold' in growth_config else 1.0
            self.strategy = NIJAApexStrategyV71(
                broker_client=self.broker.client,
                config={
                    'min_adx': tuned_min_adx,
                    'volume_threshold': tuned_volume,
                    'ai_momentum_enabled': True  # ENABLED for 15-day goal
                }
            )
            logger.info("🔥 APEX strategy initialized successfully")
        except Exception as e:
            logger.exception("🔥 CRITICAL: Failed to initialize APEX strategy")
            raise
        
        # Trading configuration - SCAN ALL MARKETS
        self.trading_pairs = []  # Will be populated dynamically from Coinbase
        self.all_markets_mode = True  # Trade ALL available crypto pairs (fetched dynamically)
        self.timeframe = '5m'
        self.min_candles_required = 80
        self.max_consecutive_losses = 3
        
        # Track open positions and trade history
        self.open_positions = {}
        # ACTIVE TRADING MODE: configurable cap to stop runaway accumulation
        try:
            self.max_concurrent_positions = int(_os.getenv("MAX_CONCURRENT_POSITIONS", "8") or 8)
        except Exception:
            self.max_concurrent_positions = 8
        self.total_trades_executed = 0
        # Risk/exit tuning - CONSERVATIVE MODE TO STOP BLEEDING
        self.stop_loss_pct = 0.03  # 3% stop loss (WIDER protection, less whipsaws)
        self.base_take_profit_pct = 0.05  # 5% initial TP (higher targets)
        self.stepped_take_profit_pct = 0.08  # 8% stepped TP (strong profit lock)
        self.take_profit_step_trigger = 0.03  # step TP at 3% move (gives room to breathe)
        # Lock 90% of peak gains when trailing - only give back 1% of profits
        self.trailing_lock_ratio = 0.90  # TIGHTER TRAILING
        # Sizing controls
        self.max_position_cap_usd = 15.0  # cap per-trade size (tighter to support 8 concurrent positions on small balances)
        # Loss streak cooldown - REDUCED FOR ACTIVE TRADING
        self.loss_cooldown_seconds = 180  # 3 minute cooldown (was 1 minute - pause after losses)
        self.last_loss_time = None
        # Market selection controls
        # ULTRA AGGRESSIVE: Scan all 50 markets for maximum opportunities
        self.limit_to_top_liquidity = False
        
        # EMERGENCY FIX: Track recently sold positions to prevent immediate re-buying
        self.recently_sold_positions = {}  # {symbol: timestamp}
        self.recently_sold_cooldown_minutes = 60  # 1 hour cooldown
        
        # Manual-sell reentry protection
        try:
            self.reentry_cooldown_minutes = int(_os.getenv("REENTRY_COOLDOWN_MINUTES", "60") or 60)
        except Exception:
            self.reentry_cooldown_minutes = 60
        self.recent_manual_sells = {}  # symbol -> iso timestamp of last detected manual sell
        self._last_holdings_snapshot = {}

        # Load saved positions from previous session
        loaded_positions = self.position_manager.load_positions()
        if loaded_positions:
            logger.info(f"💾 Found {len(loaded_positions)} saved positions from previous session")
            # DON'T validate yet - validation can remove positions if market data fails
            # Just load them directly
            self.open_positions = loaded_positions
            logger.info(f"✅ Loaded {len(self.open_positions)} positions from file")
        
        # 🔥 CRITICAL: Sync any orphaned Coinbase positions into tracking
        # This catches losing positions that aren't in open_positions.json
        # This runs AFTER loading saved positions, so it ADDS to them (doesn't replace)
        # DEFER heavy work (position sync + liquidation) to AFTER initialization completes
        # Railway kills containers that take >7s to init - sync can take 15s+
        self._startup_sync_pending = False
        if not paper_mode:
            try:
                logger.info("🔄 Syncing actual Coinbase holdings into position tracker...")
                synced = self.sync_positions_from_coinbase()
                # After syncing, prune dust-sized positions so they don't count toward caps
                try:
                    self._prune_dust_positions()
                except Exception as prune_err:
                    logger.warning(f"Dust prune failed: {prune_err}")
                if synced > 0:
                    logger.info("=" * 70)
                    logger.info(f"✅ POSITION SYNC COMPLETE")
                    logger.info(f"📊 NIJA now tracking {len(self.open_positions)} total positions")
                    logger.info(f"🛡️  Will auto-exit at stop loss ({self.stop_loss_pct*100}%) or take profit ({self.base_take_profit_pct*100}%)")
                    logger.info(f"⏰ Checks every 2.5 minutes")
                    logger.info("=" * 70)
                elif len(self.open_positions) == 0:
                    logger.info("✅ No positions to sync - portfolio is clean")
                else:
                    logger.info(f"✅ No new positions to sync - tracking {len(self.open_positions)} from file")

                # DEFER overage liquidation to first run_cycle() call to avoid Railway startup timeout
                # Railway expects app to signal "ready" quickly - long blocking operations during
                # __init__ cause Railway to kill container after ~7 seconds
                current_count = len(self.open_positions)
                if current_count > self.max_concurrent_positions:
                    lock_path = _os.path.join(_os.path.dirname(__file__), '..', 'TRADING_EMERGENCY_STOP.conf')
                    emergency_locked = _os.path.exists(lock_path)
                    if emergency_locked:
                        logger.info("⏭️  Overage detected at startup, but EMERGENCY STOP is active — not liquidating.")
                        logger.info("🔄 Deferring and suppressing startup liquidation while in sell-only mode.")
                        # Still set the pending flag so run_cycle can re-check and avoid long init work
                        self._startup_sync_pending = True
                    else:
                        logger.warning("=" * 80)
                        logger.warning(
                            f"⚠️  OVERAGE DETECTED: {current_count} positions open, max is {self.max_concurrent_positions}"
                        )
                        logger.warning("   Liquidating {0} weakest positions for profit...".format(
                            current_count - self.max_concurrent_positions
                        ))
                        logger.warning("=" * 80)
                        # Auto-enable SELL-ONLY lock to prevent re-entries during cleanup
                        try:
                            if not _os.path.exists(lock_path):
                                with open(lock_path, 'w') as f:
                                    f.write('AUTO-LOCK: Over-cap at startup')
                                logger.error("🔒 Enabled SELL-ONLY mode during startup overage cleanup")
                        except Exception as lock_err:
                            logger.warning(f"Failed to set SELL-ONLY lock: {lock_err}")
                        # Set flag to trigger liquidation in first run_cycle() call
                        self._startup_sync_pending = True
                        logger.info("🔄 Deferring overage liquidation to first trading cycle (Railway startup timeout workaround)")
            except Exception as sync_err:
                logger.error(f"⚠️ Position sync failed: {sync_err}")
                import traceback
                logger.error(traceback.format_exc())
        
        # Export trade history daily
        self._last_export_day = datetime.now().day
        self.winning_trades = 0
        self.trade_history = []
        self.consecutive_losses = 0
        self.consecutive_trades = 0  # Track consecutive trades in same direction
        self.max_consecutive_trades = 3  # Stop after 3 consecutive trades (was 8 - too aggressive)
        self.last_trade_side = None  # Track last trade direction (BUY/SELL)
        self.last_trade_time = None
        self.min_time_between_trades = 10.0  # CONSERVATIVE: 10s cooldown (was 0.5s - reduce over-trading)

        # Optional hard guard: max hold time for any position (minutes). 0 disables.
        try:
            self.max_hold_minutes = int(_os.getenv("MAX_HOLD_MINUTES", "0") or 0)
            if self.max_hold_minutes < 0:
                self.max_hold_minutes = 0
        except Exception:
            self.max_hold_minutes = 0
        
        # Trade journal file
        self.trade_journal_file = _os.path.join(_os.path.dirname(__file__), '..', 'trade_journal.jsonl')

        # 🚨 CRITICAL EMERGENCY CHECK: If lockfile exists, set flag to block NEW entries only
        emergency_lock_file = _os.path.join(_os.path.dirname(__file__), '..', 'TRADING_EMERGENCY_STOP.conf')
        self.emergency_stop_active = _os.path.exists(emergency_lock_file)
        
        if self.emergency_stop_active:
            logger.error("=" * 80)
            logger.error("🚨 EMERGENCY STOP FILE DETECTED")
            logger.error("=" * 80)
            logger.error("File: TRADING_EMERGENCY_STOP.conf")
            logger.error("Status: SELL-ONLY MODE ACTIVE")
            logger.error("Effect: NO NEW BUY ENTRIES ALLOWED")
            logger.error("Action: Existing positions WILL be managed (can exit via SL/TP/trailing)")
            logger.error("To resume: Delete TRADING_EMERGENCY_STOP.conf and restart bot")
            logger.error("=" * 80)
            logger.error(f"🔒 BUYING DISABLED: New entries blocked by emergency stop")

    # Alias to align with README wording
    def get_usd_balance(self) -> float:
        """Fetch current USD/USDC trading balance."""
        try:
            bal = self.broker.get_account_balance()
            if isinstance(bal, dict):
                return float(bal.get("trading_balance", 0.0))
            return float(bal) if bal else 0.0
        except Exception:
            return 0.0

    def sync_positions_from_coinbase(self):
        """
        Sync crypto holdings from Coinbase to NIJA position tracking.
        
        This fetches all crypto holdings from Coinbase and adds them to NIJA's
        position tracker so it can auto-sell them when stop loss or take profit is hit.
        
        CRITICAL: This is called on EVERY startup to ensure bot knows about all positions.
        Without this, the bot can't manage positions it doesn't know about.
        
        Returns:
            int: Number of NEW positions synced (doesn't count existing tracked positions)
        """
        logger.info("=" * 70)
        logger.info("🔄 SYNCING COINBASE POSITIONS TO NIJA TRACKER")
        logger.info("=" * 70)
        
        try:
            # Get current balance info which includes crypto holdings
            balance_info = self.broker.get_account_balance()
            crypto_holdings = balance_info.get('crypto', {}) if isinstance(balance_info, dict) else {}
            
            if not crypto_holdings:
                logger.info("✅ No crypto holdings found in Coinbase - portfolio is clean")
                return 0
            
            logger.info(f"📊 Found {len(crypto_holdings)} crypto holdings in Coinbase")
            
            # Check which ones are already tracked
            already_tracked = []
            for currency in crypto_holdings.keys():
                symbol = f"{currency}-USD"
                if symbol in self.open_positions:
                    already_tracked.append(symbol)
            
            if already_tracked:
                logger.info(f"   ✅ Already tracking {len(already_tracked)} positions: {', '.join(already_tracked)}")
            
            if already_tracked:
                logger.info(f"   ✅ Already tracking {len(already_tracked)} positions: {', '.join(already_tracked)}")
            
            synced_count = 0
            for currency, usd_value in crypto_holdings.items():
                # CRITICAL FIX: crypto_holdings contains USD VALUES, not crypto quantities!
                # Example: {'BTC': 17.70} means $17.70 worth of BTC, not 17.7 BTC
                if usd_value < 0.00000001:  # Skip dust
                    continue
                
                symbol = f"{currency}-USD"
                
                # Skip if already tracked
                if symbol in self.open_positions:
                    existing = self.open_positions[symbol]
                    logger.info(f"   ⏭️  {symbol}: Already tracked @ ${existing.get('entry_price', 0):.2f}")
                    continue
                
                # Get current market price using broker directly (simpler than analyze_symbol)
                try:
                    # Fetch candles directly from broker to get current price
                    candles = self.broker.get_candles(symbol, '5m', 10)
                    if not candles or len(candles) == 0:
                        logger.warning(f"   ⚠️ {symbol}: Cannot get price data, skipping")
                        continue
                    
                    # Get current price from latest candle
                    latest_candle = candles[-1]
                    current_price = float(latest_candle.get('close', latest_candle.get('price', 0)))
                    
                    if not current_price or current_price <= 0:
                        logger.warning(f"   ⚠️ {symbol}: Invalid price {current_price}, skipping")
                        continue
                    
                    # CRITICAL FIX: Calculate actual crypto quantity from USD value
                    # crypto_holdings gives us USD value, we need to convert to quantity
                    quantity = usd_value / current_price  # e.g., $17.70 / $87,000 = 0.0002034 BTC
                    position_value = usd_value  # Use the USD value we already have
                    
                    # Skip very small positions (< $0.50 - too small to manage)
                    if position_value < 0.50:
                        logger.info(f"   ⏭️  {symbol}: Position too small (${position_value:.4f}), skipping")
                        continue
                    
                    # Since we don't know original entry price, use current price as entry
                    # This means stop loss will trigger on ANY further decline
                    entry_price = current_price
                    
                    # Set CONSERVATIVE exits for immediate protection
                    stop_loss = entry_price * (1 - self.stop_loss_pct)  # 3% below current
                    take_profit = entry_price * (1 + self.base_take_profit_pct)  # 5% above current
                    trailing_stop = stop_loss  # Start trailing at SL level
                    
                    # Add to position tracking
                    position = {
                        'symbol': symbol,
                        'side': 'BUY',  # Holding crypto = long position
                        'entry_price': entry_price,
                        'current_price': current_price,
                        'size_usd': position_value,
                        'crypto_quantity': quantity,
                        'stop_loss': stop_loss,
                        'take_profit': take_profit,
                        'trailing_stop': trailing_stop,
                        'highest_price': current_price,
                        'tp_stepped': False,
                        'entry_time': datetime.now().isoformat(),
                        'timestamp': datetime.now().isoformat(),
                        'synced_from_coinbase': True,  # Mark as synced vs. traded by bot
                        'note': 'Auto-synced from Coinbase holdings'
                    }
                    
                    # Add to open positions
                    self.open_positions[symbol] = position
                    synced_count += 1
                    
                    logger.info(f"   ✅ {symbol}: {quantity:.8f} {currency} @ ${current_price:.4f} = ${position_value:.2f}")
                    logger.info(f"      Stop Loss: ${stop_loss:.4f} (-{self.stop_loss_pct*100}%) | Take Profit: ${take_profit:.4f} (+{self.base_take_profit_pct*100}%)")
                    
                except Exception as e:
                    logger.error(f"   ❌ {symbol}: Failed to sync - {e}")
                    continue
            
            # Save ALL positions to persistent storage (both synced and previously tracked)
            if len(self.open_positions) > 0:
                saved = self.position_manager.save_positions(self.open_positions)
                if saved:
                    logger.info("=" * 70)
                    if synced_count > 0:
                        logger.info(f"✅ SYNCED {synced_count} NEW POSITIONS FROM COINBASE")
                    logger.info(f"💾 Total positions tracked: {len(self.open_positions)}")
                    logger.info(f"🛡️  NIJA will auto-exit when SL/TP hit (checks every 2.5 min)")
                    logger.info("=" * 70)
                else:
                    logger.error("❌ Failed to save positions to file!")
            
            return synced_count
            
        except Exception as e:
            logger.error(f"❌ Position sync failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return 0

    def _estimate_position_value_usd(self, symbol: str, position: dict, fallback_price: float = None) -> float:
        """Estimate current USD value for a tracked position.

        Uses stored `crypto_quantity` if present; otherwise attempts to read live holdings.
        Falls back to provided price or cached/latest price fetch.
        """
        try:
            qty = float(position.get('crypto_quantity') or 0.0)
            price = None
            if fallback_price and fallback_price > 0:
                price = float(fallback_price)
            if (qty <= 0) or (price is None):
                # Try to fill missing qty from live holdings
                try:
                    bal = self.broker.get_account_balance()
                    holdings = bal.get('crypto', {}) if isinstance(bal, dict) else {}
                    base = symbol.split('-')[0]
                    if qty <= 0:
                        qty = float(holdings.get(base, 0.0) or 0.0)
                except Exception:
                    pass
            if price is None:
                try:
                    price = self._get_price_with_retry(symbol) or 0.0
                except Exception:
                    price = 0.0
            return max(0.0, float(qty) * float(price or 0.0))
        except Exception:
            return 0.0

    def _prune_dust_positions(self):
        """Remove or mark dust positions so they don't count against caps.

        Any position with estimated USD value < MIN_SELL_USD is treated as dust
        and removed from tracking (can't be sold due to Coinbase min order size).
        """
        try:
            try:
                min_sell_usd = float(os.getenv('MIN_SELL_USD', os.getenv('MIN_CASH_TO_BUY', '5.0')))
            except Exception:
                min_sell_usd = 5.0
            dust_threshold = max(0.0, min_sell_usd - 0.01)

            if not getattr(self, 'open_positions', None):
                return
            to_remove = []
            for symbol, pos in self.open_positions.items():
                est = self._estimate_position_value_usd(symbol, pos)
                if est < dust_threshold:
                    to_remove.append((symbol, est))

            if to_remove:
                logger.warning("🧹 Pruning dust positions below sell minimum:")
                for symbol, est in to_remove:
                    logger.warning(f"   • {symbol}: est ${est:.2f} < ${dust_threshold:.2f} → removing from tracker")
                    self.open_positions.pop(symbol, None)
                # Persist
                try:
                    self.position_manager.save_positions(self.open_positions)
                except Exception as e:
                    logger.warning(f"Failed to save after dust prune: {e}")
        except Exception as e:
            logger.warning(f"Dust prune error: {e}")

    def _update_manual_sell_snapshot(self):
        """
        Detect manual sells by comparing current Coinbase holdings to the last snapshot.
        When a previously-held symbol's quantity drops below dust threshold without a bot-driven exit,
        record a cooldown to prevent immediate re-entry.

        Cooldown duration is controlled by REENTRY_COOLDOWN_MINUTES.
        """
        try:
            balance_info = self.broker.get_account_balance()
            crypto_holdings = balance_info.get('crypto', {}) if isinstance(balance_info, dict) else {}

            # Housekeeping: remove expired cooldowns
            now = datetime.now()
            expired = []
            for sym, ts in self.recent_manual_sells.items():
                try:
                    t = datetime.fromisoformat(ts)
                except Exception:
                    expired.append(sym)
                    continue
                if (now - t) > timedelta(minutes=self.reentry_cooldown_minutes):
                    expired.append(sym)
            for sym in expired:
                self.recent_manual_sells.pop(sym, None)

            # Compare snapshot to current
            DUST = 0.00000001
            for currency, prev_qty in (self._last_holdings_snapshot or {}).items():
                if prev_qty > DUST:
                    current_qty = float(crypto_holdings.get(currency, 0.0) or 0.0)
                    if current_qty <= DUST:
                        symbol = f"{currency}-USD"
                        # If bot still tracks the position, skip (it will manage the exit)
                        if symbol in self.open_positions:
                            continue
                        # Record manual sell cooldown
                        self.recent_manual_sells[symbol] = now.isoformat()
                        logger.warning(
                            f"🛡️ Manual sell detected for {symbol}. Blocking re-entry for {self.reentry_cooldown_minutes} minutes."
                        )

            # Update snapshot with current holdings
            self._last_holdings_snapshot = {k: float(v) for k, v in crypto_holdings.items()}
        except Exception as e:
            logger.debug(f"Manual sell snapshot update failed: {e}")

    
    def _fetch_all_markets(self) -> list:
        """
        Fetch ALL cryptocurrency trading pairs from Coinbase API dynamically.
        Implements pagination to handle 700+ markets without timeouts.
        
        Returns:
            List of trading pair symbols (e.g., ['BTC-USD', 'ETH-USD', ...])
        """
        try:
            # Try to fetch from Coinbase API first (all 700+ pairs)
            logger.info("🔍 Fetching all available markets from Coinbase API (target: 700+)...")
            
            # Call broker's method to get all products (uses pagination internally)
            if hasattr(self.broker, 'get_all_products'):
                all_markets = self.broker.get_all_products()
                if all_markets and len(all_markets) > 50:
                    logger.info(f"✅ Successfully fetched {len(all_markets)} markets from Coinbase API! 🚀")
                    return all_markets
                elif all_markets:
                    logger.warning(f"⚠️  API returned only {len(all_markets)} markets (expected 700+), using returned list")
                    return all_markets
            
            # Fallback: If API fails, use comprehensive 700+ market list
            logger.warning("⚠️  API fetch failed, falling back to comprehensive 700+ market list...")
            
        except Exception as e:
            logger.warning(f"⚠️  Failed to fetch markets from API: {e}")
            logger.info("Falling back to comprehensive 700+ market list...")
        
        # FALLBACK: Comprehensive list of 700+ crypto pairs (all USD/USDC pairs from Coinbase)
        # This is the full market list to use when API is unavailable
        fallback_markets = [
            'BTC-USD', 'ETH-USD', 'SOL-USD', 'XRP-USD', 'ADA-USD',
            'AVAX-USD', 'DOGE-USD', 'DOT-USD', 'LINK-USD', 'UNI-USD',
            'ATOM-USD', 'LTC-USD', 'NEAR-USD', 'BCH-USD', 'APT-USD',
            'FIL-USD', 'ARB-USD', 'OP-USD', 'ICP-USD', 'ALGO-USD',
            'VET-USD', 'HBAR-USD', 'AAVE-USD', 'GRT-USD', 'ETC-USD',
            'SAND-USD', 'MANA-USD', 'AXS-USD', 'XLM-USD', 'EOS-USD',
            'FLOW-USD', 'XTZ-USD', 'CHZ-USD', 'IMX-USD', 'LRC-USD',
            'CRV-USD', 'COMP-USD', 'SNX-USD', 'MKR-USD', 'SUSHI-USD',
            '1INCH-USD', 'BAT-USD', 'ZRX-USD', 'YFI-USD', 'SHIB-USD',
            'PEPE-USD', 'FET-USD', 'INJ-USD', 'RENDER-USD', 'WLD-USD',
            'BLUR-USD', 'DYDX-USD', 'SAFE-USD', 'PYTH-USD', 'JTO-USD',
            'RONIN-USD', 'ONDO-USD', 'VIRTUAL-USD', 'STACKS-USD', 'MEME-USD',
            'TURBO-USD', 'BRETT-USD', 'ETHFI-USD', 'BNSOL-USD', 'PIXL-USD',
            'SLERF-USD', 'ZK-USD', 'SCRT-USD', 'TRX-USD', 'TON-USD',
            'POLKADOT-USD', 'POLYGON-USD', 'FANTOM-USD', 'CELO-USD', 'HEDERA-USD'
        ]
        
        # NOTE: This is just a sample. The full 700+ list will be fetched from Coinbase API.
        # When API is working, actual markets are returned (836 total).
        logger.info(f"📝 Using fallback list with {len(fallback_markets)} sample markets (API preferred)")
        logger.info(f"💡 Tip: Improve market coverage by ensuring Coinbase API connectivity")
        return fallback_markets
    
    def fetch_candles(self, symbol: str) -> pd.DataFrame:
        """
        Fetch OHLCV candles for a symbol with caching to reduce API calls
        
        Args:
            symbol: Trading symbol (e.g., 'BTC-USD')
            
        Returns:
            DataFrame with OHLCV data or None if fetch fails
        """
        try:
            # Check cache first
            current_time = time.time()
            if symbol in self._price_cache:
                cache_age = current_time - self._cache_timestamp.get(symbol, 0)
                if cache_age < self._cache_ttl:
                    logger.debug(f"Using cached data for {symbol} (age: {cache_age:.1f}s)")
                    return self._price_cache[symbol]
            
            # Fetch from API
            raw_candles = self.broker.get_candles(symbol, self.timeframe, self.min_candles_required)
            if not raw_candles or len(raw_candles) < self.min_candles_required:
                return None
            
            # CRITICAL: Normalize candles to ensure numeric types at ingest
            candles = self._normalize_candles(raw_candles)
            df = pd.DataFrame(candles)
            
            # Ensure required columns exist
            required_cols = ['open', 'high', 'low', 'close', 'volume']
            if not all(col in df.columns for col in required_cols):
                logger.warning(f"Missing required columns for {symbol}")
                return None

            # Sort by time to ensure proper order
            if 'time' in df.columns:
                df = df.sort_values('time').reset_index(drop=True)
            
            # Update cache
            self._price_cache[symbol] = df
            self._cache_timestamp[symbol] = current_time
            logger.debug(f"Cached price data for {symbol}")
            
            return df
        except Exception as e:
            logger.warning(f"Failed to fetch candles for {symbol}: {e}")
            return None
    
    def _normalize_candles(self, raw_candles):
        """
        Normalize raw candle data to ensure numeric types at ingest.
        CRITICAL: Coinbase returns strings for OHLCV - must convert immediately.
        
        Args:
            raw_candles: Raw candle data from broker
            
        Returns:
            List of normalized candle dictionaries with numeric types
            
        Raises:
            AssertionError: If candles are not properly converted to floats
        """
        clean = []
        for c in raw_candles:
            clean.append({
                "time": int(c["start"]),
                "open": float(c["open"]),
                "high": float(c["high"]),
                "low": float(c["low"]),
                "close": float(c["close"]),
                "volume": float(c["volume"]),
            })
        
        # MANDATORY: Verify numeric conversion succeeded
        assert isinstance(clean[-1]["close"], float), "CANDLES STILL STRINGS - NORMALIZATION FAILED"
        assert isinstance(clean[-1]["open"], float), "OPEN PRICE NOT FLOAT"
        assert isinstance(clean[-1]["volume"], float), "VOLUME NOT FLOAT"
        
        return clean
    
    def calculate_indicators(self, df: pd.DataFrame) -> dict:
        """
        Calculate technical indicators for analysis
        
        Args:
            df: OHLCV DataFrame
            
        Returns:
            Dictionary of calculated indicators
        """
        try:
            # HARD GUARD: Ensure numeric OHLCV before any indicator math
            required_cols = ['open', 'high', 'low', 'close', 'volume']
            if not all(col in df.columns for col in required_cols):
                logger.warning("Missing OHLCV columns; cannot calculate indicators")
                return {}
            df[required_cols] = df[required_cols].astype(float)
            logger.info(
                f"DEBUG candle types → close={type(df['close'].iloc[-1])}, "
                f"open={type(df['open'].iloc[-1])}, volume={type(df['volume'].iloc[-1])}"
            )
            indicators = {
                'vwap': calculate_vwap(df),
                'ema_9': calculate_ema(df, 9),
                'ema_21': calculate_ema(df, 21),
                'ema_50': calculate_ema(df, 50),
                'rsi': calculate_rsi(df, 14),
                'macd_line': None,
                'signal_line': None,
                'histogram': None,
                'atr': calculate_atr(df),
                'adx': None
            }
            
            # Calculate MACD (returns tuple)
            macd_line, signal_line, histogram = calculate_macd(df)
            indicators['macd_line'] = macd_line
            indicators['signal_line'] = signal_line
            indicators['histogram'] = histogram
            
            # Calculate ADX (returns tuple)
            adx, plus_di, minus_di = calculate_adx(df)
            indicators['adx'] = adx
            
            return indicators
        except Exception as e:
            logger.warning(f"Error calculating indicators: {e}")
            return None
    
    def analyze_symbol(self, symbol: str) -> dict:
        """
        Analyze a symbol for trading opportunities
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Analysis dictionary with signal, direction, and reasoning
        """
        try:
            # Fetch candle data
            df = self.fetch_candles(symbol)
            if df is None or len(df) < self.min_candles_required:
                return {
                    'symbol': symbol,
                    'signal': 'SKIP',
                    'reason': 'Insufficient candle data'
                }
            
            # Calculate indicators
            indicators = self.calculate_indicators(df)
            if not indicators:
                return {
                    'symbol': symbol,
                    'signal': 'SKIP',
                    'reason': 'Failed to calculate indicators'
                }
            
            # Check market filter
            allow_trade, direction, filter_reason = self.strategy.check_market_filter(df, indicators)
            
            if not allow_trade:
                return {
                    'symbol': symbol,
                    'signal': 'HOLD',
                    'direction': 'none',
                    'reason': f'Market filter: {filter_reason}'
                }
            
            # Check entry signals based on direction
            if direction == 'uptrend':
                long_signal, long_score, long_reason = self.strategy.check_long_entry(df, indicators)
                if long_signal:
                    # PROFITABILITY FILTER: Don't buy if RSI is overbought (> 70)
                    # This prevents buying at tops that will immediately reverse
                    rsi_14 = indicators.get('rsi_14', 50)
                    if rsi_14 > 70:
                        return {
                            'symbol': symbol,
                            'signal': 'HOLD',
                            'direction': 'uptrend',
                            'reason': f'RSI overbought ({rsi_14:.1f} > 70) - waiting for pullback'
                        }
                    
                    # PROFITABILITY FILTER: Require minimum score for entry
                    # Only buy trades with score >= 70 (high probability)
                    if long_score < 70:
                        return {
                            'symbol': symbol,
                            'signal': 'HOLD',
                            'direction': 'uptrend',
                            'reason': f'Score too low ({long_score:.1f} < 70) - waiting for stronger signal'
                        }
                    
                    # PROFITABILITY FILTER: Check price is not at recent high
                    # Don't buy if price is within 2% of 20-candle high (avoid chasing)
                    recent_high = df['high'].tail(20).max()
                    current_price = df['close'].iloc[-1]
                    if current_price >= recent_high * 0.98:
                        return {
                            'symbol': symbol,
                            'signal': 'HOLD',
                            'direction': 'uptrend',
                            'reason': f'Too close to recent high (${current_price:.4f} vs ${recent_high:.4f}) - waiting for dip'
                        }
                    
                    return {
                        'symbol': symbol,
                        'signal': 'BUY',
                        'direction': 'uptrend',
                        'score': long_score,
                        'price': current_price,
                        'reason': f'{long_reason} | RSI:{rsi_14:.1f} | Score:{long_score:.1f}'
                    }
            elif direction == 'downtrend':
                # DISABLED: Coinbase Advanced Trade doesn't support short selling on spot markets
                # short_signal, short_score, short_reason = self.strategy.check_short_entry(df, indicators)
                # if short_signal:
                #     return {
                #         'symbol': symbol,
                #         'signal': 'SELL',
                #         'direction': 'downtrend',
                #         'score': short_score,
                #         'price': df['close'].iloc[-1],
                #         'reason': short_reason
                #     }
                pass  # Only BUY signals supported on Coinbase spot trading
            
            return {
                'symbol': symbol,
                'signal': 'HOLD',
                'direction': direction,
                'reason': 'No entry conditions met'
            }
            
        except Exception as e:
            logger.error(f"Error analyzing {symbol}: {e}")
            return {
                'symbol': symbol,
                'signal': 'SKIP',
                'reason': f'Analysis error: {str(e)}'
            }
    
    def execute_trade(self, analysis: dict) -> bool:
        """
        Execute a trade based on analysis
        
        Args:
            analysis: Trade analysis dictionary
            
        Returns:
            True if trade executed, False otherwise
        """
        try:
            symbol = analysis['symbol']
            signal = analysis['signal']

            # 🚨 CRITICAL EMERGENCY STOP: BLOCK ALL BUY TRADES IMMEDIATELY
            # Check for emergency stop file FIRST before any other logic
            emergency_lock_file = os.path.join(os.path.dirname(__file__), '..', 'TRADING_EMERGENCY_STOP.conf')
            if signal == 'BUY' and os.path.exists(emergency_lock_file):
                logger.error("=" * 80)
                logger.error("🛑 EMERGENCY STOP: BUY BLOCKED - SELL-ONLY MODE ACTIVE")
                logger.error(f"   Symbol: {symbol}")
                logger.error(f"   Lockfile: TRADING_EMERGENCY_STOP.conf exists")
                logger.error(f"   Action: Delete lockfile to resume buying")
                logger.error("=" * 80)
                return False

            # EMERGENCY FIX: Prevent re-buying positions that were just sold within cooldown period
            if signal == 'BUY' and symbol in self.recently_sold_positions:
                try:
                    from datetime import datetime, timedelta
                    last_sell_time = self.recently_sold_positions[symbol]
                    cooldown_expires = last_sell_time + timedelta(minutes=self.recently_sold_cooldown_minutes)
                    now = datetime.now()
                    
                    if now < cooldown_expires:
                        remaining_minutes = int((cooldown_expires - now).total_seconds() / 60)
                        logger.error("=" * 80)
                        logger.error(f"🚨 BUY BLOCKED: {symbol} was just sold - COOLDOWN ACTIVE")
                        logger.error(f"   Last sold: {last_sell_time.strftime('%Y-%m-%d %H:%M:%S')}")
                        logger.error(f"   Cooldown: {self.recently_sold_cooldown_minutes} minutes")
                        logger.error(f"   Time remaining: {remaining_minutes} minutes")
                        logger.error(f"   This prevents immediate re-buying (bleeding fix)")
                        logger.error("=" * 80)
                        return False
                    else:
                        # Cooldown expired, remove from list
                        logger.info(f"✅ Sell cooldown expired for {symbol}, allowing new entry")
                        del self.recently_sold_positions[symbol]
                except Exception as e:
                    logger.error(f"⚠️ BUY blocked for {symbol}: recently sold cooldown active (error: {e})")
                    return False

            # Re-entry cooldown after manual sells
            if signal == 'BUY' and symbol in self.recent_manual_sells:
                try:
                    last = datetime.fromisoformat(self.recent_manual_sells[symbol])
                    remaining = self.reentry_cooldown_minutes - int((time.time() - last.timestamp())/60)
                    if remaining > 0:
                        logger.warning(
                            f"🛡️ BUY BLOCKED for {symbol}: Manual sell cooldown active ({remaining} min remaining of {self.reentry_cooldown_minutes}m)"
                        )
                        logger.warning(f"   Last manual sell: {last.strftime('%Y-%m-%d %H:%M:%S')}")
                        return False
                    else:
                        # Cooldown expired, remove from list
                        logger.info(f"✅ Cooldown expired for {symbol}, allowing re-entry")
                        del self.recent_manual_sells[symbol]
                except Exception as e:
                    # If parsing fails, be safe and block this cycle
                    logger.warning(f"⏸️ BUY blocked for {symbol}: manual sell cooldown active (parse error: {e})")
                    return False
            
            # Optional: previously protected positions. Allow trading unless explicitly disabled via env
            disable_protected = str(os.getenv("DISABLE_PROTECTED_POSITIONS", "1")).lower() in ("1", "true", "yes")
            if not disable_protected:
                protected_symbols = ['BTC-USD', 'XRP-USD', 'ETH-USD', 'SOL-USD', 'DOGE-USD', 'ATOM-USD']
                if symbol in protected_symbols:
                    logger.warning(f"🚫 PROTECTED POSITION ACTIVE: {symbol} - Trade blocking enabled (set DISABLE_PROTECTED_POSITIONS=1 to allow)")
                    return False
            
            if signal not in ['BUY', 'SELL']:
                return False
            
            # PROFITABILITY FILTER: Only execute quality BUY signals
            # Score >= 60 balances quality with activity (700+ markets should have 5-8)
            if signal == 'BUY':
                score = analysis.get('score', 0)
                if score < 60:
                    logger.warning(
                        f"🛑 BUY blocked for {symbol}: Quality score {score:.1f} < 60. "
                        "Need better setup."
                    )
                    return False
            
            # Check time between trades
            if self.last_trade_time:
                time_since_last = time.time() - self.last_trade_time
                if time_since_last < self.min_time_between_trades:
                    logger.info(f"Skipping {symbol}: Too soon since last trade ({time_since_last:.1f}s)")
                    return False

            # Cooldown after loss streaks
            if self.consecutive_losses >= 2 and self.last_loss_time:
                since_loss = time.time() - self.last_loss_time
                if since_loss < self.loss_cooldown_seconds:
                    logger.info(
                        f"Skipping {symbol}: Cooling down after {self.consecutive_losses} losses; {self.loss_cooldown_seconds - since_loss:.1f}s remaining"
                    )
                    return False
            
            # Check max concurrent positions limit (double-check before each trade)
            # Using >= so we reject at exactly max_concurrent_positions
            if len(self.open_positions) >= self.max_concurrent_positions:
                logger.error(
                    f"❌ POSITION LIMIT EXCEEDED: {len(self.open_positions)}/{self.max_concurrent_positions} positions open. "
                    f"Rejecting trade for {symbol}"
                )
                return False
            
            # CRITICAL: Stop buying after 8 consecutive trades - force sell cycle
            if self.consecutive_trades >= self.max_consecutive_trades and signal == 'BUY':
                logger.warning(f"⚠️ Max consecutive trades ({self.max_consecutive_trades}) reached - skipping buy until positions close")
                logger.info(f"   Current open positions: {len(self.open_positions)}")
                logger.info(f"   Waiting for sells to reset counter...")
                return False
            
            # Skip if THIS symbol already has a position
            if symbol in self.open_positions:
                logger.info(f"Skipping {symbol}: Position already open for this symbol")
                return False
            
            # CRITICAL POSITION LIMIT ENFORCEMENT (BUYs only)
            # Count ACTUAL crypto holdings on Coinbase, not just in-memory tracker
            # This prevents the bot from buying when user manually sold positions
            # IMPORTANT: Block when count would EXCEED limit after the buy (>= check, not >)
            if signal == 'BUY':
                try:
                    balance_info = self.broker.get_account_balance()
                    actual_crypto_holdings = balance_info.get('crypto', {}) if isinstance(balance_info, dict) else {}
                    # Count holdings with non-dust quantities
                    actual_position_count = sum(1 for qty in actual_crypto_holdings.values() if qty > 0.00000001)
                    
                    # Block if we're AT or ABOVE the limit (don't allow buying the 8th position)
                    # This means we allow up to 7 positions, block when trying to buy #8
                    if actual_position_count >= self.max_concurrent_positions:
                        logger.warning(
                            f"🛑 BUY BLOCKED: {actual_position_count} actual crypto positions on Coinbase, "
                            f"max is {self.max_concurrent_positions}. Waiting for sells."
                        )
                        return False
                    
                    # ADDITIONAL CHECK: Don't buy if we're at max-1 (one away from limit)
                    # This prevents buying the position that would take us TO the limit
                    if actual_position_count >= (self.max_concurrent_positions - 1):
                        logger.warning(
                            f"🛑 BUY BLOCKED: {actual_position_count} positions (max-1 safety guard). "
                            f"Keeping 1 slot free for better entries. Max is {self.max_concurrent_positions}."
                        )
                        return False
                except Exception as e:
                    logger.error(f"⚠️ Could not verify position count from Coinbase: {e}")
                    # If we can't verify, block the buy to be safe
                    return False
            
            # Refresh balance right before sizing to avoid using stale consumer funds
            live_balance = self.get_usd_balance()
            self.account_balance = live_balance

            # BUY GUARD: Require a minimum USD cash threshold before allowing any BUY
            # $6 allows faster rotation while preventing dust trades
            try:
                min_cash_to_buy = float(os.getenv("MIN_CASH_TO_BUY", "6.0"))
            except Exception:
                min_cash_to_buy = 6.0
            if signal == 'BUY' and live_balance < min_cash_to_buy:
                logger.info(
                    f"⏸️  BUY blocked: USD balance ${live_balance:.2f} < min ${min_cash_to_buy:.2f}. "
                    f"Waiting to accumulate."
                )
                return False
            
            # Calculate position size using Adaptive Growth Manager
            position_size_pct = self.growth_manager.get_position_size_pct()
            calculated_size = live_balance * position_size_pct
            
            # Get hard position limits (in USD, not %)
            coinbase_minimum = 5.00
            min_position_hard_floor = self.growth_manager.get_min_position_usd()  # $2.00 minimum
            max_position_hard_cap = self.growth_manager.get_max_position_usd()    # $100 maximum
            effective_cap = min(max_position_hard_cap, self.max_position_cap_usd)
            
            # CIRCUIT BREAKER: Stop all trading if balance drops below minimum viable for profitable trading
            # CRITICAL: Check TOTAL account value (USD + crypto value), not just cash
            # This prevents bot from "unlocking" just because user manually liquidated crypto
            MINIMUM_TRADING_BALANCE = float(os.getenv("MINIMUM_TRADING_BALANCE", "25.0"))
            
            # Get full balance info including crypto
            balance_info = self.broker.get_account_balance()
            crypto_holdings = balance_info.get('crypto', {})
            
            # Calculate total crypto value
            total_crypto_value = 0.0
            for currency, quantity in crypto_holdings.items():
                if quantity > 0.00000001:
                    try:
                        analysis = self.analyze_symbol(f"{currency}-USD")
                        price = float(analysis.get('price', 0))
                        total_crypto_value += quantity * price
                    except:
                        pass  # Ignore pricing errors, use what we have
            
            # Total account value = USD cash + crypto value
            total_account_value = live_balance + total_crypto_value
            
            # Apply the minimum-account-value circuit breaker ONLY to BUYs; allow SELLs to always proceed
            # EMERGENCY FIX: Hard stop at $25 to prevent bleeding
            if total_account_value < MINIMUM_TRADING_BALANCE and signal == 'BUY':
                logger.error("="*80)
                logger.error(
                    f"⛔ BUY HALTED: Total account value (${total_account_value:.2f}) below minimum "
                    f"(${MINIMUM_TRADING_BALANCE:.2f})"
                )
                logger.error(f"   USD Cash: ${live_balance:.2f} | Crypto Value: ${total_crypto_value:.2f}")
                logger.error(f"   BUYs paused to avoid fee drag; waiting for additional funds")
                logger.error(f"   🚨 EMERGENCY STOP: Account severely depleted - NO BUYING until funded")
                logger.error("="*80)
                return False
            
            # ADDITIONAL EMERGENCY CHECK: Block buying if USD cash alone is below $6
            if signal == 'BUY' and live_balance < 6.0:
                logger.error("="*80)
                logger.error(f"🚨 EMERGENCY: USD cash ${live_balance:.2f} < $6.00 - BUY BLOCKED")
                logger.error("   Waiting for funds or position liquidation to free up cash")
                logger.error("="*80)
                return False
            
            # CRITICAL: Dynamic minimum balance reserve - scales with account growth
            # This ensures bot always has capital to continue trading as account grows
            reserve_floor = 20.0

            if live_balance < 100:
                # Small account: ensure at least one minimum-sized trade is possible
                # Keep 50% as safety buffer on tiny accounts to avoid rapid depletion
                MINIMUM_RESERVE = live_balance * 0.5
            elif live_balance < 500:
                # Growing account ($100-500): Keep 30% reserve
                MINIMUM_RESERVE = live_balance * 0.30
            elif live_balance < 2000:
                # Medium account ($500-2000): Keep 20% reserve
                MINIMUM_RESERVE = live_balance * 0.20
            else:
                # Large account ($2000+): Keep 10% reserve
                MINIMUM_RESERVE = live_balance * 0.10
            
            # Enforce a $20 floor reserve once balance is at least $100, but never exceed available minus the $5 minimum tradable requirement.
            if live_balance >= 100:
                MINIMUM_RESERVE = max(MINIMUM_RESERVE, reserve_floor)

            # Guard against over-reserving so at least the minimum position size is possible
            MINIMUM_RESERVE = min(MINIMUM_RESERVE, max(0.0, live_balance - min_position_hard_floor))

            tradable_balance = max(0, live_balance - MINIMUM_RESERVE)
            
            if tradable_balance < min_position_hard_floor:
                logger.warning(
                    f"🚫 Not enough tradable balance (${tradable_balance:.2f}) for minimum position (${min_position_hard_floor:.2f}) - "
                    f"keeping ${MINIMUM_RESERVE:.2f} minimum reserve ({MINIMUM_RESERVE/live_balance*100:.1f}%). "
                    f"Total balance: ${live_balance:.2f}"
                )
                return False
            
            logger.info(f"💰 Dynamic reserve: ${MINIMUM_RESERVE:.2f} ({MINIMUM_RESERVE/live_balance*100:.1f}%) | Tradable: ${tradable_balance:.2f}")
            
            # ENFORCE: min_position_hard_floor <= position_size <= effective cap and tradable balance
            # This ensures positions are:
            # 1. Large enough to profit after Coinbase fees
            # 2. Small enough to fit within account growth stage
            # 3. Small enough to fit within remaining tradable balance
            position_size_usd = max(min_position_hard_floor, calculated_size)
            position_size_usd = min(position_size_usd, effective_cap, tradable_balance)

            # If we can't meet the minimum position size, skip this trade
            if position_size_usd < min_position_hard_floor:
                logger.warning(
                    f"🚫 Cannot achieve minimum position size (${min_position_hard_floor:.2f}). "
                    f"Calculated: ${calculated_size:.2f}, Available: ${tradable_balance:.2f} — skipping {symbol}"
                )
                return False
            
            # Final sanity check: ensure we have funds for the position
            if position_size_usd > tradable_balance:
                logger.warning(
                    f"🚫 Position size (${position_size_usd:.2f}) exceeds tradable balance (${tradable_balance:.2f}) — skipping {symbol}"
                )
                return False
            
            logger.info(f"🔄 Executing {signal} for {symbol}")
            logger.info(f"   Price: ${analysis.get('price', 'N/A')}")
            logger.info(f"   Position size: ${position_size_usd:.2f} (min: ${min_position_hard_floor:.2f}, max: ${effective_cap:.2f})")
            logger.info(f"   Percentage of balance: {(position_size_usd/live_balance)*100:.1f}%")
            logger.info(f"   Open positions BEFORE trade: {len(self.open_positions)}/{self.max_concurrent_positions}")
            logger.info(f"   Reason: {analysis['reason']}")
            
            # Place market order with retry handling
            try:
                expected_price = analysis.get('price')
                
                # Place order with manual retry logic
                order = None
                for attempt in range(1, 4):  # 3 attempts
                    try:
                        if signal == 'BUY':
                            result = self.broker.place_market_order(symbol, 'buy', position_size_usd)
                        else:
                            # For sell, we need quantity not USD
                            quantity = position_size_usd / expected_price
                            result = self.broker.place_market_order(symbol, 'sell', quantity)
                        
                        # Check if order succeeded (broker returns dict with status)
                        if result and isinstance(result, dict) and result.get('status') == 'filled':
                            order = result
                            break
                        elif result and isinstance(result, dict) and result.get('status') == 'unfilled':
                            # Order was rejected by exchange (insufficient funds, etc.)
                            error_code = result.get('error', 'UNKNOWN_ERROR')
                            error_msg = result.get('message', 'Unknown error')
                            logger.error(f"❌ Order rejected for {symbol}: {error_msg}")
                            
                            # Don't retry if insufficient funds or other permanent errors
                            if error_code in ['INSUFFICIENT_FUND', 'INVALID_PRODUCT_ID', 'INVALID_SIZE']:
                                logger.error(f"   Permanent error ({error_code}), skipping retries")
                                break
                            elif attempt < 3:
                                logger.warning(f"Order attempt {attempt}/3 failed, retrying...")
                                time.sleep(2 * attempt)
                            else:
                                logger.error(f"Order failed after 3 attempts for {symbol}")
                        elif result and isinstance(result, dict) and result.get('status') == 'error':
                            error_msg = result.get('error', 'Unknown error')
                            if attempt < 3:
                                logger.warning(f"Order attempt {attempt}/3 failed for {symbol}: {error_msg}")
                                time.sleep(2 * attempt)  # Exponential backoff
                            else:
                                logger.error(f"Order failed after 3 attempts for {symbol}: {error_msg}")
                        else:
                            # Unexpected result format
                            if attempt < 3:
                                logger.warning(f"Order attempt {attempt}/3 returned unexpected result for {symbol}")
                                time.sleep(2 * attempt)
                            
                    except Exception as retry_err:
                        if attempt < 3:
                            logger.warning(f"Order attempt {attempt}/3 failed for {symbol}: {retry_err}")
                            time.sleep(2 * attempt)  # Exponential backoff
                        else:
                            logger.error(f"All order attempts failed for {symbol}: {retry_err}")
                            raise
                
                # Check for partial fills if order succeeded
                if order:
                    expected_size = position_size_usd if signal == 'BUY' else (position_size_usd / expected_price)
                    order = retry_handler.handle_partial_fill(order, expected_size)
                
                if order and order.get('status') in ['filled', 'partial']:
                    # Get actual fill price (use expected if not available)
                    actual_fill_price = expected_price  # TODO: Extract from order response
                    
                    # Log trade to journal
                    self.log_trade(symbol, signal, actual_fill_price, position_size_usd)
                    
                    # Calculate stop loss and take profit levels
                    entry_price = actual_fill_price
                    stop_loss_pct = self.stop_loss_pct
                    take_profit_pct = self.base_take_profit_pct
                    
                    if signal == 'BUY':
                        stop_loss = entry_price * (1 - stop_loss_pct)
                        take_profit = entry_price * (1 + take_profit_pct)
                        trailing_stop = stop_loss  # Initialize trailing stop at stop loss
                        tp_stepped = False
                    else:  # SELL
                        stop_loss = entry_price * (1 + stop_loss_pct)
                        take_profit = entry_price * (1 - take_profit_pct)
                        trailing_stop = stop_loss
                        tp_stepped = False
                    
                    # Record entry with analytics (includes fee tracking)
                    trade_id = self.analytics.record_entry(
                        symbol=symbol,
                        side=signal,
                        price=entry_price,
                        size_usd=position_size_usd,
                        expected_price=expected_price,
                        actual_fill_price=actual_fill_price,
                        stop_loss=stop_loss,
                        take_profit=take_profit
                    )
                    
                    # Calculate actual crypto quantity received (accounting for fees)
                    # For BUY orders: we spent position_size_usd and received crypto
                    # The order response should contain filled_size, but if not available, estimate
                    crypto_quantity = order.get('filled_size', position_size_usd / entry_price)
                    
                    # Track consecutive trades in same direction
                    if self.last_trade_side == signal:
                        self.consecutive_trades += 1
                    else:
                        self.consecutive_trades = 1
                        self.last_trade_side = signal
                    
                    # Track position with risk management levels
                    self.open_positions[symbol] = {
                        'side': signal,
                        'entry_price': entry_price,
                        'size_usd': position_size_usd,
                        'crypto_quantity': float(crypto_quantity),  # CRITICAL: Store actual amount of crypto
                        'timestamp': datetime.now(),
                        'stop_loss': stop_loss,
                        'take_profit': take_profit,
                        'consecutive_count': self.consecutive_trades,  # Track which consecutive trade this is
                        'trailing_stop': trailing_stop,
                        'highest_price': entry_price if signal == 'BUY' else None,
                        'lowest_price': entry_price if signal == 'SELL' else None,
                        'trade_id': trade_id,
                        'tp_stepped': tp_stepped
                    }
                    
                    self.last_trade_time = time.time()
                    
                    # Save positions to file (crash recovery)
                    self.position_manager.save_positions(self.open_positions)
                    
                    logger.info(f"✅ Trade executed: {symbol} {signal}")
                    logger.info(f"   Entry: ${entry_price:.2f}")
                    logger.info(f"   Stop Loss: ${stop_loss:.2f} (-{stop_loss_pct*100}%)")
                    logger.info(f"   Take Profit: ${take_profit:.2f} (+{take_profit_pct*100}%)")
                    return True
                else:
                    # Extract and log detailed error message
                    if order and isinstance(order, dict):
                        error_detail = order.get('error', 'Unknown error from broker')
                        order_status = order.get('status', 'unknown')
                        logger.error(f"❌ Trade failed for {symbol}:")
                        logger.error(f"   Status: {order_status}")
                        logger.error(f"   Error: {error_detail}")
                        logger.error(f"   Full order response: {order}")
                    else:
                        logger.error(f"❌ Trade failed for {symbol}: Order returned None")
                    return False
            except Exception as e:
                logger.error(f"Error placing order for {symbol}: {e}")
                return False
            
        except Exception as e:
            logger.error(f"Error executing trade: {e}")
            return False
    
    def manage_open_positions(self):
        """
        Monitor all open positions and close them when:
        1. Stop loss hit
        2. Trailing stop hit
        3. Take profit hit
        4. Exit signal from strategy
        """
        if not self.open_positions:
            return
        
        logger.info(f"📊 Managing {len(self.open_positions)} open position(s)...")
        
        positions_to_close = []
        
        for symbol, position in self.open_positions.items():
            try:
                # Get current price
                analysis = self.analyze_symbol(symbol)
                current_price = analysis.get('price')
                
                if not current_price:
                    logger.warning(f"⚠️ Could not get price for {symbol}, skipping")
                    continue
                
                side = position['side']
                entry_price = position['entry_price']
                stop_loss = position['stop_loss']
                take_profit = position['take_profit']
                trailing_stop = position['trailing_stop']
                
                # Calculate current P&L
                if side == 'BUY':
                    pnl_pct = ((current_price - entry_price) / entry_price) * 100
                    pnl_usd = position['size_usd'] * (pnl_pct / 100)
                else:  # SELL
                    pnl_pct = ((entry_price - current_price) / entry_price) * 100
                    pnl_usd = position['size_usd'] * (pnl_pct / 100)
                
                logger.info(f"   {symbol}: {side} @ ${entry_price:.2f} | Current: ${current_price:.2f} | P&L: {pnl_pct:+.2f}% (${pnl_usd:+.2f})")
                logger.info(f"      Exit Levels: SL=${stop_loss:.2f}, Trail=${trailing_stop:.2f}, TP=${position['take_profit']:.2f}")
                
                # Log exit condition checks for debugging
                if side == 'BUY':
                    logger.debug(f"      Exit checks: price={current_price:.2f}, SL={stop_loss:.2f}, Trail={trailing_stop:.2f}, TP={position['take_profit']:.2f}")
                    if current_price >= position['take_profit']:
                        logger.info(f"      ✅ TAKE PROFIT TRIGGERED: ${current_price:.2f} >= ${position['take_profit']:.2f}")
                    elif current_price <= stop_loss:
                        logger.info(f"      🛑 STOP LOSS TRIGGERED: ${current_price:.2f} <= ${stop_loss:.2f}")
                    elif current_price <= trailing_stop:
                        logger.info(f"      🔻 TRAILING STOP TRIGGERED: ${current_price:.2f} <= ${trailing_stop:.2f}")
                
                exit_reason = None

                # Optional max-hold-time auto-exit
                if self.max_hold_minutes and self.max_hold_minutes > 0:
                    try:
                        ts = position.get('timestamp') or position.get('entry_time')
                        if isinstance(ts, str):
                            try:
                                ts_dt = datetime.fromisoformat(ts)
                            except Exception:
                                ts_dt = datetime.now()
                        else:
                            ts_dt = ts if ts else datetime.now()
                        age_minutes = (datetime.now() - ts_dt).total_seconds() / 60.0
                        if age_minutes >= self.max_hold_minutes:
                            exit_reason = f"Max hold time exceeded ({age_minutes:.1f}m ≥ {self.max_hold_minutes}m)"
                    except Exception:
                        pass
                
                if side == 'BUY':
                    # Update highest price for trailing stop
                    if current_price > position.get('highest_price', entry_price):
                        position['highest_price'] = current_price
                        # Update trailing stop to lock in part of the move
                        new_trailing = entry_price + (current_price - entry_price) * self.trailing_lock_ratio
                        if new_trailing > trailing_stop:
                            position['trailing_stop'] = new_trailing
                            locked_profit_pct = ((new_trailing - entry_price) / entry_price) * 100
                            logger.info(f"   📈 Trailing stop updated: ${new_trailing:.2f} (locks in {locked_profit_pct:.2f}% profit)")

                        # Step take-profit once price moves sufficiently in our favor
                        if (not position.get('tp_stepped')) and current_price >= entry_price * (1 + self.take_profit_step_trigger):
                            stepped_tp = entry_price * (1 + self.stepped_take_profit_pct)
                            position['take_profit'] = stepped_tp
                            position['tp_stepped'] = True
                            logger.info(
                                f"   🎯 TP stepped up to ${stepped_tp:.2f} after move ≥ {self.take_profit_step_trigger*100:.1f}%"
                            )
                        
                        # PROFITABILITY_UPGRADE_V7.2: Check for stepped profit-taking exits
                        # Exits portions at: 0.5%, 1%, 2%, 3% profit targets
                        # This reduces hold time from 8+ hours to 15-30 minutes per position
                        if pnl_pct >= 0.5 and not exit_reason:  # Only if profit and not already exiting
                            stepped_exit_info = self._check_stepped_exit(symbol, current_price, pnl_pct, entry_price, position)
                            if stepped_exit_info:
                                # Execute partial exit
                                exit_signal = 'SELL'
                                try:
                                    exit_quantity = position.get('crypto_quantity', position['size_usd'] / entry_price) * stepped_exit_info['exit_pct']
                                    order = self.broker.place_market_order(
                                        symbol, 
                                        exit_signal.lower(), 
                                        exit_quantity,
                                        size_type='base'
                                    )
                                    if order and order.get('status') == 'filled':
                                        logger.info(f"   ✅ Stepped exit {stepped_exit_info['exit_pct']*100:.0f}% @ {stepped_exit_info['profit_level']} profit filled")
                                        # Don't remove position, just mark that portion as exited
                                        position['size_usd'] *= (1.0 - stepped_exit_info['exit_pct'])
                                except Exception as e:
                                    logger.warning(f"   ⚠️ Stepped exit order failed: {e}")
                    
                    # Check stop loss
                    if current_price <= stop_loss:
                        exit_reason = f"Stop loss hit @ ${stop_loss:.2f}"
                    # Check trailing stop
                    elif current_price <= trailing_stop:
                        exit_reason = f"Trailing stop hit @ ${trailing_stop:.2f}"
                    # Check take profit
                    elif current_price >= position['take_profit']:
                        exit_reason = f"Take profit hit @ ${position['take_profit']:.2f}"
                        logger.info(f"      💰 PROFIT TARGET HIT: Closing {symbol} with {pnl_pct:+.2f}% gain")
                    # Check for opposite signal
                    elif analysis.get('signal') == 'SELL':
                        exit_reason = f"Opposite signal detected: {analysis.get('reason')}"
                        logger.info(f"      🔄 REVERSAL SIGNAL: Closing {symbol} on opposite signal")
                
                else:  # SELL position
                    # Update lowest price for trailing stop
                    if current_price < position.get('lowest_price', entry_price):
                        position['lowest_price'] = current_price
                        # Update trailing stop to lock in part of the move
                        new_trailing = entry_price - (entry_price - current_price) * self.trailing_lock_ratio
                        if new_trailing < trailing_stop:
                            position['trailing_stop'] = new_trailing
                            locked_profit_pct = ((entry_price - new_trailing) / entry_price) * 100
                            logger.info(f"   📉 Trailing stop updated: ${new_trailing:.2f} (locks in {locked_profit_pct:.2f}% profit)")
                    
                    # PROFITABILITY_UPGRADE_V7.2: Check for stepped profit-taking exits
                    # Exits portions at: 0.5%, 1%, 2%, 3% profit targets
                    # This reduces hold time from 8+ hours to 15-30 minutes per position
                    if pnl_pct >= 0.5 and not exit_reason:  # Only if profit and not already exiting
                        stepped_exit_info = self._check_stepped_exit(symbol, current_price, pnl_pct, entry_price, position)
                        if stepped_exit_info:
                            # Execute partial exit
                            exit_signal = 'BUY'
                            try:
                                exit_quantity = position.get('crypto_quantity', position['size_usd'] / entry_price) * stepped_exit_info['exit_pct']
                                order = self.broker.place_market_order(
                                    symbol, 
                                    exit_signal.lower(), 
                                    exit_quantity,
                                    size_type='base'
                                )
                                if order and order.get('status') == 'filled':
                                    logger.info(f"   ✅ Stepped exit {stepped_exit_info['exit_pct']*100:.0f}% @ {stepped_exit_info['profit_level']} profit filled")
                                    # Don't remove position, just mark that portion as exited
                                    position['size_usd'] *= (1.0 - stepped_exit_info['exit_pct'])
                            except Exception as e:
                                logger.warning(f"   ⚠️ Stepped exit order failed: {e}")
                    
                    # Check stop loss
                    if current_price >= stop_loss:
                        exit_reason = f"Stop loss hit @ ${stop_loss:.2f}"
                    # Check trailing stop
                    elif current_price >= trailing_stop:
                        exit_reason = f"Trailing stop hit @ ${trailing_stop:.2f}"
                    # Check take profit
                    elif current_price <= take_profit:
                        exit_reason = f"Take profit hit @ ${take_profit:.2f}"
                        logger.info(f"      💰 PROFIT TARGET HIT: Closing {symbol} with {pnl_pct:+.2f}% gain")
                    # Check for opposite signal
                    elif analysis.get('signal') == 'BUY':
                        exit_reason = f"Opposite signal detected: {analysis.get('reason')}"
                        logger.info(f"      🔄 REVERSAL SIGNAL: Closing {symbol} on opposite signal")
                
                # Execute exit if conditions met
                if exit_reason:
                    logger.info(f"🔄 Closing {symbol} position: {exit_reason}")
                    logger.info(f"   Exit price: ${current_price:.2f} | P&L: {pnl_pct:+.2f}% (${pnl_usd:+.2f})")
                    
                    # Close position with retry handling
                    exit_signal = 'SELL' if side == 'BUY' else 'BUY'
                    try:
                        # Use the ACTUAL crypto quantity from when we opened the position
                        # This accounts for fees paid during entry
                        quantity = position.get('crypto_quantity', position['size_usd'] / entry_price)
                        
                        logger.info(f"   🔄 Executing {exit_signal} order for {symbol}")
                        logger.info(f"   Position size: ${position['size_usd']:.2f}")
                        logger.info(f"   Crypto amount: {quantity:.8f}")
                        logger.info(f"   Current price: ${current_price:.2f}")
                        logger.info(f"   Estimated exit value: ${quantity * current_price:.2f}")
                        
                        # Place exit order with manual retry
                        order = None
                        for attempt in range(1, 4):  # 3 attempts
                            try:
                                # CRITICAL: When SELLING crypto, use base_size (crypto amount), not quote_size (USD)
                                result = self.broker.place_market_order(
                                    symbol, 
                                    exit_signal.lower(), 
                                    quantity,
                                    size_type='base' if exit_signal == 'SELL' else 'quote'
                                )
                                
                                # CRITICAL FIX: Check for both 'filled' and 'unfilled' status
                                if result and isinstance(result, dict):
                                    status = result.get('status', 'unknown')
                                    logger.info(f"   Attempt {attempt}/3: Order status = {status}")
                                    
                                    if status == 'filled':
                                        order = result
                                        logger.info(f"   ✅ Order filled successfully on attempt {attempt}")
                                        break
                                    elif status in ['error', 'unfilled']:
                                        error_msg = result.get('error', result.get('message', 'Unknown error'))
                                        if attempt < 3:
                                            logger.warning(f"   Exit order attempt {attempt}/3 failed for {symbol}: {error_msg}")
                                            time.sleep(2 * attempt)
                                        else:
                                            logger.error(f"   ❌ Exit order failed after 3 attempts for {symbol}: {error_msg}")
                                    else:
                                        logger.warning(f"   Unexpected status '{status}' on attempt {attempt}/3")
                                        if attempt < 3:
                                            time.sleep(2 * attempt)
                                        
                            except Exception as retry_err:
                                if attempt < 3:
                                    logger.warning(f"Exit order attempt {attempt}/3 failed for {symbol}: {retry_err}")
                                    time.sleep(2 * attempt)
                                else:
                                    logger.error(f"All exit attempts failed for {symbol}: {retry_err}")
                                    raise
                        
                        # Check for partial fills if order succeeded
                        if order:
                            order = retry_handler.handle_partial_fill(order, quantity)
                        
                        # CRITICAL: ONLY close position if order ACTUALLY filled on Coinbase
                        # Do NOT remove tracking if order failed - keep retrying until it fills
                        position_closed_successfully = order and order.get('status') in ['filled', 'partial']
                        
                        if position_closed_successfully:
                            # Record exit with analytics (includes fee calculation)
                            self.analytics.record_exit(
                                symbol=symbol,
                                exit_price=current_price,
                                exit_reason=exit_reason
                            )
                            
                            # Log closing trade
                            self.log_trade(symbol, exit_signal, current_price, position['size_usd'])
                            
                            # Update stats
                            if pnl_usd > 0:
                                self.winning_trades += 1
                                self.consecutive_losses = 0
                                logger.info(f"✅ Position closed with PROFIT: ${pnl_usd:+.2f}")
                            else:
                                self.consecutive_losses += 1
                                self.last_loss_time = time.time()
                                logger.info(f"❌ Position closed with LOSS: ${pnl_usd:+.2f}")
                            
                            # Add to close list (remove from tracking ONLY if order filled)
                            positions_to_close.append(symbol)
                            self.total_trades_executed += 1
                            
                            # Warn if partial fill
                            if order and order.get('partial_fill'):
                                logger.warning(
                                    f"⚠️  Partial exit: {order.get('filled_pct', 0):.1f}% filled - will retry remaining {100 - order.get('filled_pct', 0):.1f}%"
                                )
                        else:
                            # Order failed or did not execute
                            if order:
                                error_msg = order.get('error', order.get('message', 'Unknown error'))
                                logger.error(f"❌ Failed to close {symbol}: {error_msg}")
                                logger.error(f"   Will retry on next cycle - position NOT removed from tracking")
                            else:
                                logger.error(f"❌ No order returned for {symbol} exit")
                                logger.error(f"   Will retry on next cycle - position NOT removed from tracking")
                            
                            # DO NOT add to positions_to_close - keep retrying

                    
                    except Exception as e:
                        logger.error(f"Error closing {symbol} position: {e}")
            
            except Exception as e:
                logger.error(f"Error managing position {symbol}: {e}")
        
        # Remove closed positions and reset consecutive counter on sells
        for symbol in positions_to_close:
            closed_position = self.open_positions[symbol]
            # Reset consecutive counter when we sell (close a position)
            if closed_position.get('side') == 'BUY':
                logger.info(f"   Resetting consecutive trade counter (was {self.consecutive_trades})")
                self.consecutive_trades = 0
                self.last_trade_side = 'SELL'
            del self.open_positions[symbol]
        
        if positions_to_close:
            # Save updated positions to file (crash recovery)
            self.position_manager.save_positions(self.open_positions)
            logger.info(f"✅ Closed {len(positions_to_close)} position(s)")

    def force_exit_all_positions(self):
        """Force-close all tracked positions immediately at market, regardless of signals/levels."""
        if not self.open_positions:
            logger.info("Force-exit requested, but no open positions are tracked.")
            return

        logger.error("=" * 80)
        logger.error("🚨 FORCE EXIT ALL POSITIONS - MARKET ORDERS")
        logger.error("=" * 80)

        symbols = list(self.open_positions.keys())
        closed = 0
        for symbol in symbols:
            position = self.open_positions.get(symbol)
            if not position:
                continue
            try:
                analysis = self.analyze_symbol(symbol)
                current_price = analysis.get('price')
                side = position.get('side', 'BUY')
                exit_signal = 'SELL' if side == 'BUY' else 'BUY'
                quantity = position.get('crypto_quantity', 0.0) or (position.get('size_usd', 0.0) / max(position.get('entry_price', 0.0), 1e-9))

                logger.info(f"   Forcing exit {symbol}: side={side} -> {exit_signal}, qty={quantity:.8f}, px≈{current_price}")

                order = None
                for attempt in range(1, 4):
                    try:
                        result = self.broker.place_market_order(
                            symbol,
                            exit_signal.lower(),
                            quantity,
                            size_type='base' if exit_signal == 'SELL' else 'quote'
                        )
                        if result and isinstance(result, dict):
                            status = result.get('status', 'unknown')
                            if status in ['filled', 'partial']:
                                order = result
                                break
                        time.sleep(1 * attempt)
                    except Exception as e:
                        if attempt >= 3:
                            logger.error(f"Force-exit failed for {symbol}: {e}")

                if order:
                    self.analytics.record_exit(symbol=symbol, exit_price=current_price, exit_reason='FORCE_EXIT_ALL')
                    self.log_trade(symbol, exit_signal, current_price, position.get('size_usd', 0.0))
                    closed += 1
                else:
                    logger.error(f"Force-exit order did not confirm for {symbol}")

                # Remove from tracking regardless to prevent lingering bags
                del self.open_positions[symbol]
            except Exception as e:
                logger.error(f"Error during force-exit for {symbol}: {e}")

        self.position_manager.save_positions(self.open_positions)
        logger.error(f"✅ Force-exit complete: closed {closed} position(s)")
    
    def rebalance_existing_holdings(self, max_positions: int = 8, target_cash: float = 15.0):
        """
        Rebuild a view of actual holdings from the broker and liquidate excess positions
        to ensure we keep at most `max_positions` and have at least `target_cash` USD.

        This is essential when the bot restarts without a saved `open_positions` file
        but there are stray holdings on the account (e.g., 13+ assets).
        """
        try:
            # Fetch real holdings from broker (Advanced Trade accounts only)
            positions = []
            try:
                positions = self.broker.get_positions()  # [{'symbol': 'BTC-USD', 'quantity': 0.001, 'currency': 'BTC'}]
            except Exception as e:
                logger.error(f"Error fetching live positions for rebalance: {e}")
                positions = []

            # Nothing to do if no crypto holdings
            if not positions:
                logger.info("Rebalance check: no live crypto holdings found — skipping.")
                return

            # Compute USD value per holding using current price
            valued = []
            for p in positions:
                symbol = p.get('symbol')
                qty = float(p.get('quantity', 0) or 0)
                if not symbol or qty <= 0:
                    continue
                try:
                    analysis = self.analyze_symbol(symbol)
                    price = float(analysis.get('price') or 0)
                except Exception:
                    price = 0.0
                usd_value = qty * price if price > 0 else 0.0
                valued.append({
                    'symbol': symbol,
                    'quantity': qty,
                    'usd_value': usd_value,
                    'price': price
                })

            if not valued:
                logger.info("Rebalance check: holdings valuation yielded no entries — skipping.")
                return

            # Sort by USD value descending (largest first)
            valued.sort(key=lambda x: x['usd_value'], reverse=True)

            # Determine what to keep and what to sell
            keep = valued[:max_positions]
            sell_list = valued[max_positions:]

            # If we already have enough cash, we may skip liquidation
            current_cash = float(self.account_balance or 0)
            need_cash = current_cash < target_cash

            to_sell = []
            if sell_list:
                to_sell.extend(sell_list)
            # If we still need cash, sell from the tail of the 'keep' (smallest keeps)
            if need_cash:
                # Evaluate from the smallest of the kept positions
                tail_kept = list(reversed(keep))
                for item in tail_kept:
                    if current_cash >= target_cash:
                        break
                    to_sell.append(item)
                    current_cash += item.get('usd_value', 0.0)

            if not to_sell:
                logger.info(
                    f"Rebalance not required: keep={len(keep)} (≤{max_positions}) and cash=${float(self.account_balance or 0):.2f} "
                    f"(target ${target_cash:.2f})."
                )
                return

            logger.warning(f"⚠️ Rebalancing holdings: selling {len(to_sell)} position(s) to enforce max {max_positions} and reach ${target_cash:.2f} cash")
            logger.info(
                f"Rebalance plan: keep={len(keep)}, sell_list={len(sell_list)}, need_cash={need_cash}, "
                f"starting_cash=${float(self.account_balance or 0):.2f}"
            )

            sold = 0
            for item in to_sell:
                symbol = item['symbol']
                qty = item['quantity']
                if qty <= 0:
                    continue
                try:
                    # Sell full crypto amount (base size)
                    result = self.broker.place_market_order(
                        symbol,
                        'sell',
                        qty,
                        size_type='base'
                    )
                    status = (result or {}).get('status', 'unknown')
                    if status == 'filled':
                        sold += 1
                        logger.info(f"✅ Rebalance SELL filled: {symbol} qty={qty}")
                    else:
                        logger.error(f"❌ Rebalance SELL failed: {symbol} qty={qty} result={result}")
                except Exception as e:
                    logger.error(f"Error selling {symbol} during rebalance: {e}")

            if sold:
                logger.info(f"✅ Rebalance complete: sold {sold} position(s)")
                # Refresh cash balance after liquidation
                try:
                    self.account_balance = self.get_usd_balance()
                except Exception:
                    pass
            # Ensure we don't run this repeatedly in the same process
            self.rebalanced_once = True

        except Exception as e:
            logger.error(f"Rebalance error: {e}")
            self.rebalanced_once = True

    def _get_price_with_retry(self, symbol: str, attempts: int = 2, base_delay: float = 0.5):
        """Lean price fetch for emergency liquidation paths.

        Only uses broker.get_current_price to avoid heavy candle analysis during
        Railway-constrained startup. Returns None if all attempts fail.
        """
        last_error = None
        for attempt in range(1, attempts + 1):
            try:
                price = float(self.broker.get_current_price(symbol) or 0)
                if price > 0:
                    return price
            except Exception as e:
                last_error = e
                logger.debug(
                    f"Price fetch via broker failed for {symbol} (attempt {attempt}/{attempts}): {e}"
                )

            if attempt < attempts:
                time.sleep(base_delay)

        if last_error:
            logger.warning(f"⚠️ Unable to fetch price for {symbol} after {attempts} attempts: {last_error}")
        else:
            logger.warning(f"⚠️ Unable to fetch price for {symbol} after {attempts} attempts (no error raised)")
        return None

    def close_excess_positions(self, max_positions=8, timeout_seconds=5):
        """
        Close excess positions if we exceed the max concurrent limit.
        Sells positions in order: lowest P&L first (weakest performers)
        
        NOTE: This method is designed to NOT crash the bot even if API errors occur.
        It will skip positions with API failures and continue with the next.
        
        CRITICAL: Railway has platform timeouts. This function limits itself to
        a short timeout to avoid being killed mid-execution.
        
        Args:
            max_positions: Maximum concurrent positions allowed
            timeout_seconds: Maximum time to spend liquidating (default 5s for startup safety)
        """
        import time as time_module
        liquidation_start = time_module.time()
        MAX_LIQUIDATION_TIME = timeout_seconds  # Use parameter, default to 5 seconds
        
        try:
            # FIRST: Clean up any stale positions with zero crypto_quantity
            # This prevents trying to fetch prices for positions that don't actually exist
            stale_positions = []
            for symbol, position in list(self.open_positions.items()):
                quantity = float(position.get('crypto_quantity') or 0.0)
                if quantity <= 0:
                    stale_positions.append(symbol)
            
            if stale_positions:
                logger.warning(f"🧹 Removing {len(stale_positions)} stale positions with zero quantity before overage check")
                for symbol in stale_positions:
                    logger.warning(f"   🗑️  {symbol} (quantity: 0)")
                    del self.open_positions[symbol]
                self.position_manager.save_positions(self.open_positions)
            
            MAX_CONCURRENT = max_positions
            current_count = len(self.open_positions)
            
            if current_count <= MAX_CONCURRENT:
                logger.info(f"✅ Position count OK: {current_count}/{MAX_CONCURRENT}")
                return  # No overage to close
            
            excess_count = current_count - MAX_CONCURRENT
            logger.warning(f"⚠️  OVERAGE DETECTED: {current_count} positions open, max is {MAX_CONCURRENT}")
            logger.warning(f"   Liquidating {excess_count} weakest positions for profit...")
            
            # Sort positions by current P&L (lowest first)
            positions_by_pnl = []
            
            for symbol, position in self.open_positions.items():
                try:
                    current_price = self._get_price_with_retry(symbol)
                    price_known = current_price is not None and current_price > 0
                    
                    entry_price = position['entry_price']
                    side = position['side']
                    
                    # Calculate P&L %
                    if price_known:
                        if side == 'BUY':
                            pnl_pct = ((current_price - entry_price) / entry_price) * 100
                        else:
                            pnl_pct = ((entry_price - current_price) / entry_price) * 100
                    else:
                        # If price is unknown, force-close these first by treating P&L as very low
                        pnl_pct = -999.0
                        current_price = None
                    
                    positions_by_pnl.append({
                        'symbol': symbol,
                        'position': position,
                        'current_price': current_price,
                        'pnl_pct': pnl_pct,
                        'price_known': price_known
                    })
                except Exception as e:
                    logger.warning(f"⚠️  Skipping price check for {symbol}: {e}")
                    # Add with worst P&L to close later if possible
                    positions_by_pnl.append({
                        'symbol': symbol,
                        'position': position,
                        'current_price': None,
                        'pnl_pct': -999.0,
                        'price_known': False
                    })
            
            # Sort by P&L (lowest first - we want to close the worst performers)
            positions_by_pnl.sort(key=lambda x: x['pnl_pct'])
            
            # Close the worst performers first
            successfully_closed = 0
            for i in range(excess_count):
                # Timeout protection: Stop liquidation if we're approaching platform limits
                elapsed = time_module.time() - liquidation_start
                if elapsed > MAX_LIQUIDATION_TIME:
                    logger.warning(f"⏰ Liquidation timeout after {elapsed:.1f}s - pausing to avoid Railway kill")
                    logger.warning(f"   Closed {successfully_closed}/{excess_count} positions this cycle")
                    logger.warning(f"   Remaining {excess_count - successfully_closed} will be handled in next run")
                    break
                
                if i >= len(positions_by_pnl):
                    break
                
                p = positions_by_pnl[i]
                symbol = p['symbol']
                position = p['position']
                current_price = p['current_price']
                pnl_pct = p['pnl_pct']
                price_known = p.get('price_known', False)
                
                if price_known:
                    logger.info(f"🔴 CLOSING EXCESS: {symbol} (P&L: {pnl_pct:+.2f}%)")
                else:
                    logger.warning(f"🔴 CLOSING EXCESS WITHOUT PRICE: {symbol} (P&L unknown; proceeding with market exit)")
                
                # EMERGENCY FIX: Add to recently sold list to prevent immediate re-buying
                from datetime import datetime
                self.recently_sold_positions[symbol] = datetime.now()
                logger.info(f"⏸️  {symbol} added to cooldown list (1 hour) - will not re-buy immediately")
                
                try:
                    # Get the crypto quantity we actually hold
                    side = position['side']
                    # Prefer stored crypto_quantity; if missing or zero, fetch from Coinbase holdings
                    quantity = float(position.get('crypto_quantity') or 0.0)
                    if quantity <= 0:
                        try:
                            bal = self.broker.get_account_balance()
                            holdings = bal.get('crypto', {}) if isinstance(bal, dict) else {}
                            base = symbol.split('-')[0]
                            quantity = float(holdings.get(base, 0.0) or 0.0)
                        except Exception as qerr:
                            logger.warning(f"⚠️ Could not resolve quantity for {symbol} from holdings: {qerr}")
                    # If still zero, this is likely a stale tracked position — drop it from tracking
                    if quantity <= 0:
                        logger.warning(f"🧹 Removing stale tracked position with zero holdings: {symbol}")
                        del self.open_positions[symbol]
                        self.position_manager.save_positions(self.open_positions)
                        successfully_closed += 1
                        continue

                    # DUST-SAFE GUARD: Skip selling if est value < minimum sell USD
                    try:
                        min_sell_usd = float(os.getenv('MIN_SELL_USD', os.getenv('MIN_CASH_TO_BUY', '5.0')))
                    except Exception:
                        min_sell_usd = 5.0
                    est_value = (current_price or 0.0) * quantity if price_known else self._estimate_position_value_usd(symbol, position)
                    if est_value < (min_sell_usd - 0.01):
                        logger.warning(
                            f"⏭️  Skipping sell for dust: {symbol} est ${est_value:.2f} < ${min_sell_usd:.2f} (min). Removing from tracker."
                        )
                        self.open_positions.pop(symbol, None)
                        self.position_manager.save_positions(self.open_positions)
                        successfully_closed += 1
                        continue
                    
                    # Exit: opposite of entry side
                    exit_signal = 'SELL' if side == 'BUY' else 'BUY'

                    # Pre-order debug logging for visibility
                    logger.info(
                        f"   🔄 Placing market {exit_signal} for {symbol} | qty={quantity:.8f} (base)"
                    )
                    
                    # Place market exit order with LIMITED retries to avoid Railway timeout
                    # During startup liquidation, speed is critical - don't hang on slow API
                    result = None
                    for attempt in range(1, 3):  # Reduced to 2 attempts max
                        try:
                            result = self.broker.place_market_order(
                                symbol,
                                exit_signal.lower(),
                                quantity,
                                size_type='base' if exit_signal == 'SELL' else 'quote'
                            )
                            status = (result or {}).get('status', 'unknown')
                            logger.info(f"   Attempt {attempt}/2 → order status: {status}")
                            if status in ['filled', 'partial']:
                                break
                            logger.warning(
                                f"⚠️ Excess close attempt {attempt}/2 for {symbol} returned status={status}; retrying..."
                            )
                        except Exception as e:
                            logger.warning(
                                f"⚠️ Excess close attempt {attempt}/2 for {symbol} failed: {e}"
                            )
                        if attempt < 2:
                            time.sleep(0.5)  # Reduced delay: 0.5s instead of scaling
                    
                    if result and result.get('status') in ['filled', 'partial']:
                        pnl_usd = None
                        if price_known:
                            pnl_usd = position['size_usd'] * (pnl_pct / 100)
                            logger.info(f"✅ Excess position closed: {symbol} | P&L: {pnl_pct:+.2f}% (${pnl_usd:+.2f})")
                        else:
                            logger.info(f"✅ Excess position closed: {symbol} | P&L unknown (price unavailable)")
                        
                        # Remove from tracking
                        del self.open_positions[symbol]
                        self.position_manager.save_positions(self.open_positions)
                        successfully_closed += 1
                    else:
                        logger.error(f"❌ Failed to close excess position: {symbol}")
                
                except Exception as e:
                    logger.error(f"Error closing excess position {symbol}: {e}")
                    # Continue with next position instead of crashing
                    continue
            
            logger.warning(f"🔄 Liquidation cycle complete: {successfully_closed}/{excess_count} positions closed")

            # One-shot summary banner for clarity in constrained startup logs
            try:
                current_after = len(self.open_positions)
                if current_after > MAX_CONCURRENT:
                    over = current_after - MAX_CONCURRENT
                    logger.error("=" * 80)
                    logger.error(
                        f"🚨 Liquidation summary: {successfully_closed}/{excess_count} closed; still {over} over limit."
                    )
                    logger.error(f"   Positions now: {current_after}/{MAX_CONCURRENT}")
                    logger.error("   Remaining will be handled in next run.")
                    logger.error("=" * 80)
                else:
                    logger.info("=" * 80)
                    logger.info(
                        f"✅ Liquidation summary: {successfully_closed}/{excess_count} closed."
                    )
                    logger.info(f"   Positions now: {current_after}/{MAX_CONCURRENT} (within limit)")
                    logger.info("=" * 80)
            except Exception:
                pass
        
        except Exception as e:
            # Catch-all to prevent entire bot crash
            logger.error(f"🚨 CRITICAL: Error in close_excess_positions: {e}", exc_info=True)
            logger.error("⚠️  Bot will continue despite liquidation error")
    
    def _auto_unlock_sell_only_if_safe(self) -> bool:
        """Remove SELL-only lock when it's safe to resume entries.

        Conditions required:
        - Tracked positions are at/below `max_concurrent_positions`
        - USD cash balance is at least `MIN_CASH_TO_BUY`

        Returns:
            bool: True if the lock was removed this call, else False.
        """
        try:
            lock_path = os.path.join(os.path.dirname(__file__), '..', 'TRADING_EMERGENCY_STOP.conf')
            if not os.path.exists(lock_path):
                return False

            within_cap = len(self.open_positions) <= self.max_concurrent_positions

            try:
                min_cash_to_buy = float(os.getenv("MIN_CASH_TO_BUY", "6.0"))
            except Exception:
                min_cash_to_buy = 6.0
            live_balance = self.get_usd_balance()
            cash_ok = live_balance >= min_cash_to_buy

            if within_cap and cash_ok:
                os.remove(lock_path)
                logger.info(
                    f"🔓 SELL-only lock removed: positions within cap ({len(self.open_positions)}/" \
                    f"{self.max_concurrent_positions}) and cash ${live_balance:.2f} ≥ min ${min_cash_to_buy:.2f}"
                )
                return True
            else:
                if not within_cap:
                    logger.info(
                        f"🔒 SELL-only remains: positions {len(self.open_positions)}/" \
                        f"{self.max_concurrent_positions} exceed cap"
                    )
                if not cash_ok:
                    logger.info(
                        f"🔒 SELL-only remains: cash ${live_balance:.2f} < min ${min_cash_to_buy:.2f}"
                    )
        except Exception as e:
            logger.warning(f"Failed to auto-unlock SELL-only mode: {e}")
        return False
    
    def _check_stepped_exit(self, symbol: str, current_price: float, pnl_pct: float, 
                            entry_price: float, position: dict) -> dict:
        """
        PROFITABILITY_UPGRADE_V7.2: Check if position should take stepped profit exit
        
        Stepped exit schedule:
        - Exit 10% at 0.5% profit
        - Exit 15% at 1.0% profit  
        - Exit 25% at 2.0% profit
        - Exit 50% at 3.0% profit (remaining 25% on trailing stop)
        
        Args:
            symbol: Trading symbol
            current_price: Current market price
            pnl_pct: Current profit percentage
            entry_price: Entry price
            position: Position dictionary
        
        Returns:
            Dictionary with exit_pct and profit_level if triggered, None otherwise
        """
        # Define exit thresholds in order: (profit_threshold, exit_percentage, flag_name)
        exit_thresholds = [
            (0.005, 0.10, 'stepped_exit_0_5pct'),   # Exit 10% at 0.5%
            (0.010, 0.15, 'stepped_exit_1_0pct'),   # Exit 15% at 1.0%
            (0.020, 0.25, 'stepped_exit_2_0pct'),   # Exit 25% at 2.0%
            (0.030, 0.50, 'stepped_exit_3_0pct'),   # Exit 50% at 3.0%
        ]
        
        # Check each threshold in order
        for profit_threshold, exit_pct, flag_name in exit_thresholds:
            # Skip if already executed
            if position.get(flag_name, False):
                continue
            
            # Check if profit target met
            if pnl_pct >= (profit_threshold * 100):
                # Mark as executed
                position[flag_name] = True
                
                # Return exit info
                return {
                    'exit_pct': exit_pct,
                    'profit_level': f"{profit_threshold*100:.1f}%"
                }
        
        return None

    def log_trade(self, symbol: str, side: str, price: float, size_usd: float):
        """
        Log trade to journal file
        
        Args:
            symbol: Trading symbol
            side: 'BUY' or 'SELL'
            price: Entry price
            size_usd: Position size in USD
        """
        try:
            trade_entry = {
                'timestamp': datetime.now().isoformat(),
                'symbol': symbol,
                'side': side,
                'price': price,
                'size_usd': size_usd
            }
            
            # Append to trade journal
            with open(self.trade_journal_file, 'a') as f:
                f.write(json.dumps(trade_entry) + '\n')
            
            self.trade_history.append(trade_entry)
        except Exception as e:
            logger.warning(f"Failed to log trade: {e}")

    def run_cycle(self):
        """Run lightweight trading cycle - manage positions and scan for signals."""
        try:
            logger.info("🔁 Running trading cycle...")
            
            # Update balance
            self.account_balance = self.get_usd_balance()
            logger.info(f"USD Balance: ${self.account_balance:,.2f}")
            
            # CRITICAL: Manage existing positions FIRST (this was blocked before)
            # Position management MUST run even during emergency stop
            self.manage_open_positions()
            
            # Check emergency stop status
            emergency_lock_file = os.path.join(os.path.dirname(__file__), '..', 'TRADING_EMERGENCY_STOP.conf')
            trading_locked = os.path.exists(emergency_lock_file)
            
            if trading_locked:
                logger.info("🔒 Emergency stop active - sell-only mode")
                logger.info("   ✅ Existing positions managed (can exit via SL/TP)")
                logger.info("   ❌ NO new entries allowed")
                return  # Skip new trade scanning when locked
            
            # Normal trading mode - scan for new opportunities
            logger.info(f"🎯 Scanning {len(self.trading_pairs)} markets...")
            
        except Exception as e:
            logger.error(f"run_cycle error: {e}", exc_info=True)

    
    def run_trading_cycle(self):
        """
        Execute one complete trading cycle:
        1. Fetch ALL available markets dynamically
        2. Analyze each pair with APEX strategy
        3. Execute trades based on signals
        4. Monitor open positions
        """
        try:
            logger.info("=" * 60)
            logger.info(f"🔄 Running trading cycle at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f"   USD balance (get_usd_balance): ${self.account_balance:,.2f}")
            logger.info(f"   Open positions: {len(self.open_positions)}")
            
            # Refresh account balance
            self.account_balance = self.get_usd_balance()

            # Update manual sell snapshot to enforce re-entry cooldowns
            self._update_manual_sell_snapshot()
            
            # 🔥 CRITICAL: Re-sync positions every 10 cycles to catch orphaned positions
            # This ensures positions opened manually or lost during restarts are tracked
            if not hasattr(self, '_cycle_sync_counter'):
                self._cycle_sync_counter = 0
            self._cycle_sync_counter += 1
            
            if self._cycle_sync_counter >= 10:  # Every 10 cycles (25 minutes)
                logger.info("🔄 Periodic position sync (every 10 cycles)...")
                try:
                    synced = self.sync_positions_from_coinbase()
                    if synced > 0:
                        logger.info(f"🎯 Found and synced {synced} orphaned positions!")
                except Exception as e:
                    logger.error(f"Periodic sync failed: {e}")
                self._cycle_sync_counter = 0

            # SELL-ONLY mode support (same semantics as run_cycle)
            emergency_lock_file = _os.path.join(_os.path.dirname(__file__), '..', 'TRADING_EMERGENCY_STOP.conf')
            trading_locked = _os.path.exists(emergency_lock_file)
            # FORCE EXIT ALL support with emergency override protection
            force_exit_flag = _os.path.join(_os.path.dirname(__file__), '..', 'FORCE_EXIT_ALL.conf')
            override_flag = _os.path.join(_os.path.dirname(__file__), '..', 'FORCE_EXIT_OVERRIDE.conf')
            allow_force_exit = (_os.getenv('ALLOW_FORCE_EXIT_DURING_EMERGENCY', '0') == '1') or _os.path.exists(override_flag)
            if _os.path.exists(force_exit_flag):
                if trading_locked and not allow_force_exit:
                    logger.error("="*80)
                    logger.error("🛑 FORCE_EXIT_ALL suppressed — EMERGENCY STOP active (sell-only mode)")
                    logger.error("   Set ALLOW_FORCE_EXIT_DURING_EMERGENCY=1 or create FORCE_EXIT_OVERRIDE.conf to proceed.")
                    logger.error("="*80)
                    # Keep the flag for later processing once emergency ends or override set
                    return
                logger.error("="*80)
                logger.error("🛑 FORCE_EXIT_ALL flag detected — closing all positions now")
                logger.error("="*80)
                self.force_exit_all_positions()
                try:
                    os.remove(force_exit_flag)
                except Exception:
                    pass
                return
            if trading_locked:
                logger.error("="*80)
                logger.error("🔒 EMERGENCY STOP ACTIVE - SELL-ONLY MODE ENABLED")
                logger.error("="*80)
                logger.error("Managing open positions only; new entries are blocked.")
                # Manage/exit existing positions using current rules
                self.manage_open_positions()
                # In sell-only mode, do NOT liquidate due to cap; only auto-unlock when safe
                if self._auto_unlock_sell_only_if_safe():
                    logger.info("🔓 SELL-only auto-unlock engaged: resuming normal entries.")
                else:
                    return
            
            # Check if account has grown to new stage and update strategy
            stage_changed, new_config = self.growth_manager.update_stage(self.account_balance)
            if stage_changed:
                # Reinitialize strategy with new parameters
                logger.info("🔄 Reinitializing strategy with new growth stage parameters...")
                self.strategy = NIJAApexStrategyV71(
                    broker_client=self.broker.client,
                    config={
                        'min_adx': new_config['min_adx'],
                        'volume_threshold': new_config['volume_threshold'],
                        'ai_momentum_enabled': True  # ENABLED for 15-day goal
                    }
                )
                logger.info("✅ Strategy updated for new growth stage!")
            
            # Show progress to next milestone
            progress = self.growth_manager.get_progress_to_next_milestone(self.account_balance)
            if progress['next_milestone']:
                logger.info(f"📈 Progress: {progress['progress_pct']:.1f}% to ${progress['next_milestone']:.0f} ({progress['message']})")
            
            # Fetch ALL available trading pairs dynamically
            if self.all_markets_mode:
                self.trading_pairs = self._fetch_all_markets()
                logger.info(f"🌍 ALL MARKETS MODE: Scanning {len(self.trading_pairs)} crypto pairs")
            
            # Scan all trading pairs
            logger.info(f"📊 Scanning {len(self.trading_pairs)} trading pairs...")
            analyses = []
            
            for symbol in self.trading_pairs:
                analysis = self.analyze_symbol(symbol)
                analyses.append(analysis)
                
                if analysis['signal'] in ['BUY', 'SELL']:
                    logger.info(f"   ✅ {symbol}: {analysis['signal']} (Score: {analysis.get('score', 'N/A')})")
                    # Execute the trade
                    self.execute_trade(analysis)
                else:
                    logger.debug(f"   ⏸️ {symbol}: {analysis['signal']}")
            
            # ✅ CRITICAL FIX: Manage open positions (close stops/takes/exits)
            logger.info("📊 Checking open positions for exit conditions...")
            self.manage_open_positions()
            
            logger.info(f"✅ Trading cycle complete. Open positions: {len(self.open_positions)}")
            
            # Print performance report every 10 cycles (or after first trade)
            if hasattr(self, '_cycle_count'):
                self._cycle_count += 1
            else:
                self._cycle_count = 1
            
            if self._cycle_count % 10 == 0 or self.total_trades_executed > 0:
                self.analytics.print_session_report()
            
            # Export trade history daily
            current_day = datetime.now().day
            if current_day != self._last_export_day:
                try:
                    export_path = self.analytics.export_to_csv()
                    logger.info(f"📄 Daily export completed: {export_path}")
                    self._last_export_day = current_day
                except Exception as e:
                    logger.warning(f"Daily export failed: {e}")
            logger.info("=" * 60)
            
        except Exception as e:
            logger.error(f"Error in trading cycle: {e}", exc_info=True)
