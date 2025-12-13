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
from nija_apex_strategy_v71 import NIJAApexStrategyV71
from indicators import calculate_vwap, calculate_ema, calculate_rsi, calculate_macd, calculate_atr, calculate_adx

class TradingStrategy:
    """
    NIJA Ultimate Trading Strategy with APEX v7.1
    
    Features:
    - APEX v7.1 strategy engine with dual RSI indicators
    - Multi-market scanning (Bitcoin, Ethereum, and 730+ altcoins)
    - Advanced entry/exit logic with trailing systems
    - Risk management and position sizing
    - Trade journal logging and performance tracking
    """
    
    def __init__(self):
        """Initialize trading strategy with broker and APEX strategy"""
        logger.info("Initializing NIJA Trading Strategy...")
        
        # Initialize broker connection
        self.broker = CoinbaseBroker()
        if not self.broker.connect():
            logger.error("Failed to connect to Coinbase broker")
            raise RuntimeError("Broker connection failed")
        
        # Get account balance
        self.account_balance = self.broker.get_account_balance()
        logger.info(f"Account balance: ${self.account_balance:,.2f}")
        
        # Initialize APEX strategy
        self.strategy = NIJAApexStrategyV71(
            broker_client=self.broker.client,
            config={
                'min_adx': 20,
                'volume_threshold': 0.5,
                'ai_momentum_enabled': False
            }
        )
        
        # Trading configuration
        self.trading_pairs = ['BTC-USD', 'ETH-USD', 'SOL-USD', 'AVAX-USD', 'XRP-USD']
        self.timeframe = '5m'
        self.min_candles_required = 80
        self.max_consecutive_losses = 3
        
        # Track open positions and trade history
        self.open_positions = {}
        self.trade_history = []
        self.consecutive_losses = 0
        self.last_trade_time = None
        self.min_time_between_trades = 5  # seconds
        
        # Trade journal file
        self.trade_journal_file = os.path.join(os.path.dirname(__file__), '..', 'trade_journal.jsonl')
        
        logger.info("Trading strategy initialized successfully")
        logger.info(f"Trading pairs: {', '.join(self.trading_pairs)}")
        logger.info(f"Timeframe: {self.timeframe}")
    
    def fetch_candles(self, symbol: str) -> pd.DataFrame:
        """
        Fetch OHLCV candles for a symbol
        
        Args:
            symbol: Trading symbol (e.g., 'BTC-USD')
            
        Returns:
            DataFrame with OHLCV data or None if fetch fails
        """
        try:
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
                short_signal, short_score, short_reason = self.strategy.check_short_entry(df, indicators)
                if short_signal:
                    return {
                        'symbol': symbol,
                        'signal': 'SELL',
                        'direction': 'downtrend',
                        'score': short_score,
                        'price': df['close'].iloc[-1],
                        'reason': short_reason
                    }
            
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
            
            # Calculate position size (2-3% of account per trade)
            position_size_pct = 0.02
            position_size_usd = self.account_balance * position_size_pct
            
            # Skip if position already open
            if symbol in self.open_positions:
                logger.info(f"Skipping {symbol}: Position already open")
                return False
            
            logger.info(f"🔄 Executing {signal} for {symbol}")
            logger.info(f"   Price: ${analysis.get('price', 'N/A')}")
            logger.info(f"   Position size: ${position_size_usd:,.2f}")
            logger.info(f"   Reason: {analysis['reason']}")
            
            # Place market order
            try:
                if signal == 'BUY':
                    order = self.broker.place_market_order(symbol, 'buy', position_size_usd)
                else:
                    # For sell, we need quantity not USD
                    quantity = position_size_usd / analysis.get('price', 1.0)
                    order = self.broker.place_market_order(symbol, 'sell', quantity)
                
                if order.get('status') == 'filled':
                    # Log trade to journal
                    self.log_trade(symbol, signal, analysis.get('price'), position_size_usd)
                    
                    # Track position
                    self.open_positions[symbol] = {
                        'side': signal,
                        'entry_price': analysis.get('price'),
                        'size_usd': position_size_usd,
                        'timestamp': datetime.now()
                    }
                    
                    self.last_trade_time = time.time()
                    logger.info(f"✅ Trade executed: {symbol} {signal}")
                    return True
                else:
                    logger.warning(f"Trade failed for {symbol}: {order.get('error')}")
                    return False
            except Exception as e:
                logger.error(f"Error placing order for {symbol}: {e}")
                return False
            
        except Exception as e:
            logger.error(f"Error executing trade: {e}")
            return False
    
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
    
    def run_trading_cycle(self):
        """
        Execute one complete trading cycle:
        1. Scan all trading pairs for opportunities
        2. Analyze each pair with APEX strategy
        3. Execute trades based on signals
        4. Monitor open positions
        """
        try:
            logger.info("=" * 60)
            logger.info(f"🔄 Running trading cycle at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f"   Account balance: ${self.account_balance:,.2f}")
            logger.info(f"   Open positions: {len(self.open_positions)}")
            
            # Refresh account balance
            self.account_balance = self.broker.get_account_balance()
            
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
            logger.info("=" * 60)
            
        except Exception as e:
            logger.error(f"Error in trading cycle: {e}", exc_info=True)
