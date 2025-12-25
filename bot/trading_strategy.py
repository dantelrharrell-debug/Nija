import os
import sys
import time
import queue
import logging
from threading import Thread
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("nija")

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
        """Initialize production strategy with Coinbase broker and enforcer."""
        logger.info("Initializing TradingStrategy (APEX v7.1 - Production Mode)...")
        
        try:
            # Lazy imports to avoid circular deps and allow fallback
            from broker_manager import CoinbaseBroker
            from position_cap_enforcer import PositionCapEnforcer
            from nija_apex_strategy_v71 import NIJAApexStrategyV71
            
            # Initialize broker
            self.broker = CoinbaseBroker()
            if not self.broker.connect():
                logger.warning("Broker connection failed; strategy will run in monitor mode")
            
            # Initialize position cap enforcer (hard limit: 8 positions)
            self.enforcer = PositionCapEnforcer(max_positions=8, broker=self.broker)
            
            # Initialize APEX strategy
            self.apex = NIJAApexStrategyV71(broker_client=self.broker)
            
            logger.info("✅ TradingStrategy initialized (APEX v7.1 + Position Cap Enforcer)")
        
        except ImportError as e:
            logger.error(f"Failed to import strategy modules: {e}")
            logger.error("Falling back to safe monitor mode (no trades)")
            self.broker = None
            self.enforcer = None
            self.apex = None

    def run_cycle(self):
        """Execute a complete trading cycle with position cap enforcement.
        
        Steps:
        1. Enforce position cap (auto-sell excess if needed)
        2. Scan markets for opportunities
        3. Execute entry/exit logic
        4. Update trailing stops and take profits
        5. Log cycle summary
        """
        try:
            # CRITICAL: Enforce position cap first
            if self.enforcer:
                logger.info("🔍 Enforcing position cap (max 8)...")
                success, result = self.enforcer.enforce_cap()
                if result['excess'] > 0:
                    logger.warning(f"⚠️ Excess positions detected: {result['excess']} over cap")
                    logger.info(f"   Sold {result['sold']} positions")
            
            # CRITICAL: Check if new entries are blocked
            current_positions = self.broker.get_positions() if self.broker else []
            stop_entries_file = os.path.join(os.path.dirname(__file__), '..', 'STOP_ALL_ENTRIES.conf')
            entries_blocked = os.path.exists(stop_entries_file)
            
            if entries_blocked:
                logger.error("🛑 ALL NEW ENTRIES BLOCKED: STOP_ALL_ENTRIES.conf is active")
                logger.info("   Exiting positions only (no new buys)")
            elif len(current_positions) >= 8:
                logger.warning(f"🛑 ENTRY BLOCKED: Position cap reached ({len(current_positions)}/8)")
                logger.info("   Closing positions only until below cap")
            else:
                logger.info(f"✅ Position cap OK ({len(current_positions)}/8) - entries enabled")
            
            # Get account balance for position sizing
            if not self.broker or not self.apex:
                logger.info("📡 Monitor mode (strategy not loaded; no trades)")
                return
            
            balance_data = self.broker.get_account_balance()
            account_balance = balance_data.get('trading_balance', 0.0)
            logger.info(f"💰 Trading balance: ${account_balance:.2f}")
            
            # STEP 1: Manage existing positions (check for exits/profit taking)
            logger.info(f"📊 Managing {len(current_positions)} open position(s)...")
            for position in current_positions:
                try:
                    symbol = position.get('symbol')
                    if not symbol:
                        continue
                    
                    logger.info(f"   Analyzing {symbol}...")
                    
                    # Get current price
                    current_price = self.broker.get_current_price(symbol)
                    if not current_price or current_price == 0:
                        logger.warning(f"   ⚠️ Could not get price for {symbol}")
                        continue
                    
                    # Get position value
                    quantity = position.get('quantity', 0)
                    position_value = current_price * quantity
                    
                    logger.info(f"   {symbol}: {quantity:.8f} @ ${current_price:.2f} = ${position_value:.2f}")
                    
                    # Simple profit-taking logic (sell if profitable)
                    # Since we don't have entry price tracking, we'll use a conservative approach:
                    # - Hold positions for now
                    # - Let position_cap_enforcer handle excess positions
                    # - Future: Import position entry prices from trade history
                    
                    # Get market data for analysis
                    candles = self.broker.get_candles(symbol, '5m', 100)
                    if not candles or len(candles) < 100:
                        logger.warning(f"   ⚠️ Insufficient data for {symbol} ({len(candles) if candles else 0} candles)")
                        continue
                    
                    # Convert to DataFrame
                    import pandas as pd
                    df = pd.DataFrame(candles)
                    
                    # CRITICAL: Ensure numeric types for OHLCV data
                    for col in ['open', 'high', 'low', 'close', 'volume']:
                        if col in df.columns:
                            df[col] = pd.to_numeric(df[col], errors='coerce')
                    
                    # Calculate indicators for exit signal detection
                    indicators = self.apex.calculate_indicators(df)
                    if not indicators:
                        continue
                    
                    # Check for opposite signal (trend reversal)
                    # This doesn't require knowing entry price
                    allow_trade, trend, market_reason = self.apex.check_market_filter(df, indicators)
                    
                    # If market conditions deteriorate, consider selling
                    if not allow_trade:
                        logger.info(f"   ⚠️ Market conditions weak: {market_reason}")
                        logger.info(f"   💰 SELLING {symbol} due to weak market conditions")
                        
                        # Place sell order via broker
                        try:
                            result = self.broker.place_market_order(
                                symbol=symbol,
                                side='sell',
                                quantity=quantity,
                                size_type='base'
                            )
                            if result.get('status') != 'error':
                                logger.info(f"   ✅ Position closed successfully")
                            else:
                                logger.error(f"   ❌ Failed to close position: {result.get('error')}")
                        except Exception as sell_err:
                            logger.error(f"   ❌ Error closing position: {sell_err}")
                    
                except Exception as e:
                    logger.error(f"   Error managing position {symbol}: {e}", exc_info=True)
            
            # STEP 2: Look for new entry opportunities (only if entries allowed)
            if not entries_blocked and len(current_positions) < 8 and account_balance >= 25.0:
                logger.info("🔍 Scanning for new opportunities...")
                
                # Get top market candidates (limit scan to prevent timeouts)
                try:
                    # Get list of all products
                    all_products = self.broker.get_all_products()
                    if not all_products:
                        logger.warning("   No products available for scanning")
                        return
                    
                    # Scan top 20 markets (reduce from full 732+ to prevent timeout)
                    scan_limit = min(20, len(all_products))
                    logger.info(f"   Scanning {scan_limit} markets...")
                    
                    for i, symbol in enumerate(all_products[:scan_limit]):
                        try:
                            # Get candles
                            candles = self.broker.get_candles(symbol, '5m', 100)
                            if not candles or len(candles) < 100:
                                continue
                            
                            # Convert to DataFrame
                            import pandas as pd
                            df = pd.DataFrame(candles)
                            
                            # CRITICAL: Ensure numeric types
                            for col in ['open', 'high', 'low', 'close', 'volume']:
                                if col in df.columns:
                                    df[col] = pd.to_numeric(df[col], errors='coerce')
                            
                            # Analyze for entry
                            analysis = self.apex.analyze_market(df, symbol, account_balance)
                            action = analysis.get('action', 'hold')
                            
                            # Execute buy actions
                            if action in ['enter_long', 'enter_short']:
                                logger.info(f"   🎯 BUY SIGNAL: {symbol} - {analysis.get('reason', '')}")
                                success = self.apex.execute_action(analysis, symbol)
                                if success:
                                    logger.info(f"   ✅ Position opened successfully")
                                    break  # Only open one position per cycle
                                else:
                                    logger.error(f"   ❌ Failed to open position")
                        
                        except Exception as e:
                            logger.debug(f"   Error scanning {symbol}: {e}")
                            continue
                
                except Exception as e:
                    logger.error(f"Error during market scan: {e}", exc_info=True)
            else:
                logger.info("   Skipping new entries (blocked or insufficient balance)")
            
        except Exception as e:
            # Never raise to keep bot loop alive
            logger.error(f"Error in trading cycle: {e}", exc_info=True)
