import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
import os
import logging
import json
from logging.handlers import RotatingFileHandler

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

class TradingStrategy:
    """
    NIJA Ultimate Trading Strategy with APEX v7.1
    
    **15-DAY GOAL MODE**: $55 → $5,000 in 15 days
    - ULTRA AGGRESSIVE: 8-40% positions, 8 concurrent trades
    - 50 markets, 15-second scans, AI momentum filtering
    - Auto-adjusts risk as balance grows ($300, $1K, $3K milestones)
    
    Features:
    - APEX v7.1 strategy engine with dual RSI indicators
    - Multi-market scanning (Bitcoin, Ethereum, and 48+ altcoins)
    - Advanced entry/exit logic with trailing systems
    - Risk management and position sizing
    - Trade journal logging and performance tracking
    """
    
    def __init__(self):
        """Initialize trading strategy with broker and APEX strategy"""
        logger.info("Initializing NIJA Trading Strategy...")
        
        # Initialize broker connection (supports PAPER_MODE)
        paper_mode = str(os.getenv("PAPER_MODE", "")).lower() in ("1", "true", "yes")
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
        else:
            # Paper mode path: ensure MockBroker connects
            if not self.broker.connect():
                logger.error("MockBroker failed to initialize")
                raise RuntimeError("Mock broker initialization failed")
        
        logger.info("🔥 Broker connected, about to fetch balance...")
        print("🔥 BROKER CONNECTED, CALLING get_account_balance() NEXT", flush=True)
        
        # Initialize analytics tracker
        self.analytics = TradeAnalytics()
        logger.info("📊 Trade analytics initialized")
        
        # Initialize position manager
        self.position_manager = PositionManager()
        logger.info("💾 Position manager initialized")
        
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
            
            # CRITICAL: Enforce minimum capital for Coinbase fee structure
            MINIMUM_VIABLE_CAPITAL = 50.0  # $50 minimum for profitable trading
            
            if self.account_balance < MINIMUM_VIABLE_CAPITAL:
                logger.error("="*80)
                logger.error("🚨 INSUFFICIENT CAPITAL - BOT CANNOT TRADE")
                logger.error("="*80)
                logger.error(f"")
                logger.error(f"Current Balance: ${self.account_balance:.2f}")
                logger.error(f"Minimum Required: ${MINIMUM_VIABLE_CAPITAL:.2f}")
                logger.error(f"")
                logger.error("❌ WHY BOT WON'T START:")
                logger.error("   • Coinbase fees: 2-4% per trade")
                logger.error("   • Balance <$50 = positions too small to profit")
                logger.error("   • Even WINNING trades lose money to fees")
                logger.error("")
                logger.error("📊 EXAMPLE (with $10 capital):")
                logger.error("   • Position size: $5-8")
                logger.error("   • Buy fee: $0.15-0.30 (3%)")
                logger.error("   • Sell fee: $0.15-0.30 (3%)")
                logger.error("   • Total fees: 6% → Lose money on every trade!")
                logger.error("")
                logger.error("✅ THE FIX:")
                logger.error("   1. Deposit $100-200 to Coinbase Advanced Trade")
                logger.error("   2. Bot will trade $10-80 positions")
                logger.error("   3. Fees drop to <1% (profitable)")
                logger.error("   4. Strategy can work properly")
                logger.error("")
                logger.error("🔄 ALTERNATIVE:")
                logger.error("   • Switch to Binance/Kraken (0.1-0.5% fees)")
                logger.error("   • Can trade profitably with $50 capital")
                logger.error("")
                logger.error("="*80)
                raise RuntimeError(f"Insufficient capital: ${self.account_balance:.2f} (need ${MINIMUM_VIABLE_CAPITAL:.2f}+)")
            
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
        # Temporarily cap concurrent positions to limit fee drag while we stabilize PnL
        self.max_concurrent_positions = 3
        self.total_trades_executed = 0
        # Risk/exit tuning
        self.stop_loss_pct = 0.02  # 2% hard stop
        self.base_take_profit_pct = 0.05  # initial TP
        self.stepped_take_profit_pct = 0.08  # stepped TP after price moves in our favor
        self.take_profit_step_trigger = 0.03  # when price moves 3% in favor, step TP
        # Lock 55% of peak gains when trailing to reduce give-back on winners
        self.trailing_lock_ratio = 0.55
        # Sizing controls
        self.max_position_cap_usd = 75.0  # cap per-trade size until balance grows
        # Loss streak cooldown
        self.loss_cooldown_seconds = 180
        self.last_loss_time = None
        # Market selection controls
        self.limit_to_top_liquidity = True
        
        # Load saved positions from previous session
        loaded_positions = self.position_manager.load_positions()
        if loaded_positions:
            logger.info(f"💾 Validating {len(loaded_positions)} saved positions...")
            self.open_positions = self.position_manager.validate_positions(
                loaded_positions, self.broker
            )
            logger.info(f"✅ Restored {len(self.open_positions)} valid positions")
        
        # Export trade history daily
        self._last_export_day = datetime.now().day
        self.winning_trades = 0
        self.trade_history = []
        self.consecutive_losses = 0
        self.consecutive_trades = 0  # Track consecutive trades in same direction
        self.max_consecutive_trades = 8  # Stop after 8 consecutive trades (sell to reset)
        self.last_trade_side = None  # Track last trade direction (BUY/SELL)
        self.last_trade_time = None
        self.min_time_between_trades = 0.5  # ULTRA AGGRESSIVE: 0.5s cooldown for rapid 5-position fills
        
        # Trade journal file
        self.trade_journal_file = os.path.join(os.path.dirname(__file__), '..', 'trade_journal.jsonl')
        
        # Price cache to reduce API calls (cache expires after 30 seconds)
        self._price_cache = {}
        self._cache_timestamp = {}
        self._cache_ttl = 30  # seconds

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

    
    def _fetch_all_markets(self) -> list:
        """
        Fetch top cryptocurrency trading pairs from Coinbase
        Using curated list to avoid API timeout issues
        
        Returns:
            List of trading pair symbols (e.g., ['BTC-USD', 'ETH-USD', ...])
        """
        # ULTRA AGGRESSIVE: Top 50 verified Coinbase high-volume crypto pairs
        # Using curated list instead of API fetch to avoid timeout issues
        top_markets = [
            'BTC-USD', 'ETH-USD', 'SOL-USD', 'XRP-USD', 'ADA-USD',
            'AVAX-USD', 'DOGE-USD', 'DOT-USD', 'LINK-USD', 'UNI-USD',
            'ATOM-USD', 'LTC-USD', 'NEAR-USD', 'BCH-USD', 'APT-USD',
            'FIL-USD', 'ARB-USD', 'OP-USD', 'ICP-USD', 'ALGO-USD',
            'VET-USD', 'HBAR-USD', 'AAVE-USD', 'GRT-USD', 'ETC-USD',
            'SAND-USD', 'MANA-USD', 'AXS-USD', 'XLM-USD', 'EOS-USD',
            'FLOW-USD', 'XTZ-USD', 'CHZ-USD', 'IMX-USD', 'LRC-USD',
            'CRV-USD', 'COMP-USD', 'SNX-USD', 'MKR-USD', 'SUSHI-USD',
            '1INCH-USD', 'BAT-USD', 'ZRX-USD', 'YFI-USD', 'SHIB-USD',
            'PEPE-USD', 'FET-USD', 'INJ-USD', 'RENDER-USD'
        ]
        
        top_liquidity = [
            'BTC-USD', 'ETH-USD', 'SOL-USD', 'AVAX-USD', 'LINK-USD',
            'LTC-USD', 'ADA-USD', 'XRP-USD', 'DOGE-USD', 'DOT-USD',
            'ATOM-USD', 'NEAR-USD', 'BCH-USD', 'APT-USD', 'UNI-USD',
            'FIL-USD', 'ARB-USD', 'OP-USD', 'ICP-USD', 'ALGO-USD'
        ]
        
        if self.limit_to_top_liquidity:
            logger.info(f"✅ Using top-liquidity set of {len(top_liquidity)} markets")
            return top_liquidity
        
        logger.info(f"✅ Using curated list of {len(top_markets)} high-volume markets")
        return top_markets
    
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
                    return {
                        'symbol': symbol,
                        'signal': 'BUY',
                        'direction': 'uptrend',
                        'score': long_score,
                        'price': df['close'].iloc[-1],
                        'reason': long_reason
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
            
            if signal not in ['BUY', 'SELL']:
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
            
            # Check max concurrent positions limit
            if len(self.open_positions) >= self.max_concurrent_positions:
                logger.info(f"Skipping {symbol}: Max {self.max_concurrent_positions} positions already open")
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
            
            # CRITICAL: Verify sufficient balance before ANY trade
            MINIMUM_VIABLE_CAPITAL = 50.0  # $50 minimum for profitable trading

            # Refresh balance right before sizing to avoid using stale consumer funds
            live_balance = self.get_usd_balance()
            self.account_balance = live_balance

            if live_balance < MINIMUM_VIABLE_CAPITAL:
                logger.error("="*80)
                logger.error(f"🚨 TRADE BLOCKED: Insufficient capital (${live_balance:.2f})")
                logger.error("="*80)
                logger.error(f"")
                logger.error(f"Attempted to trade {symbol} but balance too low.")
                logger.error(f"")
                logger.error(f"Current Balance: ${live_balance:.2f}")
                logger.error(f"Minimum Required: ${MINIMUM_VIABLE_CAPITAL:.2f}")
                logger.error(f"")
                logger.error("❌ WHY THIS TRADE WON'T WORK:")
                logger.error(f"   • Position size would be: ${live_balance * 0.1:.2f}-${live_balance * 0.4:.2f}")
                logger.error("   • Coinbase fees: 2-4% per trade")
                logger.error("   • Fees will eat entire profit margin")
                logger.error("   • Even winning trades = net loss")
                logger.error("")
                logger.error("✅ SOLUTION:")
                logger.error("   1. Deposit $100-200 to Coinbase Advanced Trade")
                logger.error("   2. Bot will trade $10-80 positions (fees <1%)")
                logger.error("")
                logger.error("="*80)
                return False
            
            # Calculate position size using Adaptive Growth Manager
            # ULTRA AGGRESSIVE MODE: 8-40% positions for 15-day $5K goal
            position_size_pct = self.growth_manager.get_position_size_pct()
            calculated_size = live_balance * position_size_pct
            
            # Apply hard caps to position size
            coinbase_minimum = 5.00
            max_position_hard_cap = self.growth_manager.get_max_position_usd()  # $100 hard cap
            effective_cap = min(max_position_hard_cap, self.max_position_cap_usd)
            
            # Enforce: min($5) <= position_size <= effective cap and available balance
            position_size_usd = max(coinbase_minimum, calculated_size)
            position_size_usd = min(position_size_usd, effective_cap, live_balance)

            # If we don't have enough tradable balance for even the $5 minimum, stop quickly
            if position_size_usd < coinbase_minimum or live_balance < coinbase_minimum:
                logger.warning(
                    f"🚫 Insufficient Advanced Trade balance (${live_balance:.2f}) for Coinbase $5 minimum — skipping {symbol}"
                )
                return False
            
            logger.info(f"🔄 Executing {signal} for {symbol}")
            logger.info(f"   Price: ${analysis.get('price', 'N/A')}")
            logger.info(f"   Position size: ${position_size_usd:.2f} (capped at $100 max)")
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
                
                # Check exit conditions
                exit_reason = None
                
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
                    
                    # Check stop loss
                    if current_price <= stop_loss:
                        exit_reason = f"Stop loss hit @ ${stop_loss:.2f}"
                    # Check trailing stop
                    elif current_price <= trailing_stop:
                        exit_reason = f"Trailing stop hit @ ${trailing_stop:.2f}"
                    # Check take profit
                    elif current_price >= position['take_profit']:
                        exit_reason = f"Take profit hit @ ${position['take_profit']:.2f}"
                    # Check for opposite signal
                    elif analysis.get('signal') == 'SELL':
                        exit_reason = f"Opposite signal detected: {analysis.get('reason')}"
                
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
                    
                    # Check stop loss
                    if current_price >= stop_loss:
                        exit_reason = f"Stop loss hit @ ${stop_loss:.2f}"
                    # Check trailing stop
                    elif current_price >= trailing_stop:
                        exit_reason = f"Trailing stop hit @ ${trailing_stop:.2f}"
                    # Check take profit
                    elif current_price <= take_profit:
                        exit_reason = f"Take profit hit @ ${take_profit:.2f}"
                    # Check for opposite signal
                    elif analysis.get('signal') == 'BUY':
                        exit_reason = f"Opposite signal detected: {analysis.get('reason')}"
                
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
                        
                        if order and order.get('status') in ['filled', 'partial']:
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
                            positions_to_close.append(symbol)
                            self.total_trades_executed += 1
                            
                            # Warn if partial fill
                            if order.get('partial_fill'):
                                logger.warning(
                                    f"⚠️  Partial exit: {order.get('filled_pct', 0):.1f}% filled"
                                )
                        else:
                            logger.warning(f"Failed to close {symbol}: {order.get('error')}")
                    
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
        """Run a lightweight trading cycle used by the main loop with dynamic market fetching."""
        try:
            # Clear cache at start of each cycle for fresh data
            self._price_cache.clear()
            self._cache_timestamp.clear()
            
            logger.info("🔁 Running trading loop iteration")
            self.account_balance = self.get_usd_balance()
            logger.info(f"USD Balance (get_usd_balance): ${self.account_balance:,.2f}")
            
            # Fetch ALL available trading pairs dynamically if not set
            if self.all_markets_mode and not self.trading_pairs:
                logger.info("🔍 Fetching all available markets...")
                all_markets = self._fetch_all_markets()
                logger.info(f"✅ Market fetch complete: {len(all_markets)} markets returned")
                
                # ULTRA AGGRESSIVE: Scan top 50 markets for maximum opportunity
                # Filter for active USD/USDC pairs with good liquidity
                self.trading_pairs = all_markets[:50] if len(all_markets) > 50 else all_markets
                logger.info(f"📊 Scanning {len(self.trading_pairs)} markets for trading opportunities")
                logger.info(f"   Top 10 markets: {self.trading_pairs[:10]}")
            elif not self.trading_pairs:
                # Fallback to default pairs if market fetch fails
                self.trading_pairs = ['BTC-USD', 'ETH-USD', 'SOL-USD', 'AVAX-USD', 'XRP-USD']
                logger.warning(f"⚠️ Using fallback trading pairs: {len(self.trading_pairs)} pairs")

            # Check for growth stage changes
            stage_changed, new_config = self.growth_manager.update_stage(self.account_balance)
            if stage_changed:
                logger.info("🔄 Reinitializing strategy with new growth stage parameters...")
                tuned_min_adx = new_config['min_adx'] + 5 if 'min_adx' in new_config else 25
                tuned_volume = new_config['volume_threshold'] * 1.15 if 'volume_threshold' in new_config else 1.0
                self.strategy = NIJAApexStrategyV71(
                    broker_client=self.broker.client,
                    config={
                        'min_adx': tuned_min_adx,
                        'volume_threshold': tuned_volume,
                        'ai_momentum_enabled': True  # ENABLED for 15-day goal
                    }
                )
                logger.info("✅ Strategy updated for new growth stage!")

            # *** MANAGE OPEN POSITIONS FIRST ***
            # Check all open positions for exit conditions (stop loss, take profit, trailing stops)
            self.manage_open_positions()

            # Guard: if no trading balance, do not attempt orders
            if not self.account_balance or self.account_balance <= 0:
                logger.warning("🚫 No USD/USDC trading balance detected. Skipping trade execution this cycle.")
                logger.warning("👉 Move funds into your Advanced Trade portfolio: https://www.coinbase.com/advanced-portfolio")
                return

            logger.info(f"🎯 Analyzing {len(self.trading_pairs)} markets for signals...")
            signals_found = 0
            for symbol in self.trading_pairs:
                analysis = self.analyze_symbol(symbol)
                if analysis.get('signal') in ['BUY', 'SELL']:
                    signals_found += 1
                    logger.info(f"🔥 SIGNAL: {symbol}, Signal: {analysis.get('signal')}, Reason: {analysis.get('reason')}")
                    self.execute_trade(analysis)
            
            if signals_found == 0:
                logger.info(f"📭 No trade signals found in {len(self.trading_pairs)} markets this cycle")
        except Exception as exc:
            logger.error(f"run_cycle error: {exc}", exc_info=True)
    
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
