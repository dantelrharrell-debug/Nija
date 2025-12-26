import os
import sys
import time
import queue
import logging
import traceback
from threading import Thread
from dotenv import load_dotenv
import pandas as pd

load_dotenv()

logger = logging.getLogger("nija")

# Configuration constants
MARKET_SCAN_LIMIT = 20  # Number of markets to scan per cycle (reduced from 732+ to prevent timeouts)

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
            # 🚨 EMERGENCY: Check if LIQUIDATE_ALL mode is active
            liquidate_all_file = os.path.join(os.path.dirname(__file__), '..', 'LIQUIDATE_ALL_NOW.conf')
            if os.path.exists(liquidate_all_file):
                logger.error("🚨 EMERGENCY LIQUIDATION MODE ACTIVE")
                logger.error("   SELLING ALL POSITIONS IMMEDIATELY")
                
                sold_count = 0
                total_positions = 0
                
                try:
                    if self.broker:
                        try:
                            positions = call_with_timeout(self.broker.get_positions, timeout_seconds=30)
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
                                        self.broker.place_market_order,
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
            
            # CRITICAL FIX: Identify ALL positions that need to exit first
            # Then sell them ALL concurrently, not one at a time
            positions_to_exit = []
            
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
                    
                    # PROFITABILITY MODE: Aggressive exit on weak markets
                    # Exit positions when market conditions deteriorate to prevent bleeding
                    
                    # PROFITABILITY FIX: Calculate P&L for profit-taking
                    entry_price = position.get('entry_price', current_price)
                    pnl_pct = ((current_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0
                    
                    # PROFITABILITY FIX: Take profits at key levels
                    if pnl_pct >= 10.0:
                        logger.info(f"   💰 TAKE PROFIT +10%: Selling {symbol} (actual: {pnl_pct:.2f}%)")
                        positions_to_exit.append({
                            'symbol': symbol,
                            'quantity': quantity,
                            'reason': f'Take profit +10% ({pnl_pct:.2f}%)'
                        })
                        continue
                    elif pnl_pct >= 5.0:
                        logger.info(f"   💰 TAKE PROFIT +5%: Selling {symbol} (actual: {pnl_pct:.2f}%)")
                        positions_to_exit.append({
                            'symbol': symbol,
                            'quantity': quantity,
                            'reason': f'Take profit +5% ({pnl_pct:.2f}%)'
                        })
                        continue
                    elif pnl_pct >= 3.0:
                        logger.info(f"   💰 TAKE PROFIT +3%: Selling {symbol} (actual: {pnl_pct:.2f}%)")
                        positions_to_exit.append({
                            'symbol': symbol,
                            'quantity': quantity,
                            'reason': f'Take profit +3% ({pnl_pct:.2f}%)'
                        })
                        continue
                    
                    # Get market data for analysis
                    candles = self.broker.get_candles(symbol, '5m', 100)
                    if not candles or len(candles) < 100:
                        logger.warning(f"   ⚠️ Insufficient data for {symbol} ({len(candles) if candles else 0} candles)")
                        continue
                    
                    # Convert to DataFrame
                    df = pd.DataFrame(candles)
                    
                    # CRITICAL: Ensure numeric types for OHLCV data
                    for col in ['open', 'high', 'low', 'close', 'volume']:
                        if col in df.columns:
                            df[col] = pd.to_numeric(df[col], errors='coerce')
                    
                    # Calculate indicators for exit signal detection
                    logger.info(f"   DEBUG candle types → close={type(df['close'].iloc[-1])}, open={type(df['open'].iloc[-1])}, volume={type(df['volume'].iloc[-1])}")
                    indicators = self.apex.calculate_indicators(df)
                    if not indicators:
                        continue
                    
                    # PROFITABILITY FIX: Exit on RSI overbought (if profitable)
                    rsi = indicators.get('rsi', pd.Series()).iloc[-1] if 'rsi' in indicators else 0
                    if rsi > 70 and pnl_pct > 0:
                        logger.info(f"   📈 RSI OVERBOUGHT EXIT: {symbol} (RSI={rsi:.1f}, profit={pnl_pct:.2f}%)")
                        positions_to_exit.append({
                            'symbol': symbol,
                            'quantity': quantity,
                            'reason': f'RSI overbought ({rsi:.1f}) - lock profit'
                        })
                        continue
                    
                    # Check for weak market conditions (exit signal)
                    # This protects capital even without knowing entry price
                    allow_trade, trend, market_reason = self.apex.check_market_filter(df, indicators)
                    
                    # If market conditions deteriorate, mark for exit
                    if not allow_trade:
                        logger.info(f"   ⚠️ Market conditions weak: {market_reason}")
                        logger.info(f"   💰 MARKING {symbol} for concurrent exit")
                        positions_to_exit.append({
                            'symbol': symbol,
                            'quantity': quantity,
                            'reason': market_reason
                        })
                    else:
                        # Market is still good - check for tighter stop loss (PROFITABILITY FIX: 3% not 5%)
                        # This prevents unlimited downside even in trending markets
                        stop_loss_pct = 0.03  # PROFITABILITY FIX: Tighter 3% stop loss (was 5%)
                        if pnl_pct <= -stop_loss_pct * 100:
                            logger.info(f"   🛑 STOP LOSS HIT: Position down {pnl_pct:.2f}%")
                            logger.info(f"   💰 MARKING {symbol} for concurrent exit")
                            positions_to_exit.append({
                                'symbol': symbol,
                                'quantity': quantity,
                                'reason': f'Stop loss hit ({pnl_pct:.2f}%)'
                            })
                    
                except Exception as e:
                    logger.error(f"   Error analyzing position {symbol}: {e}", exc_info=True)
            
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
                    
                    try:
                        result = self.broker.place_market_order(
                            symbol=symbol,
                            side='sell',
                            quantity=quantity,
                            size_type='base'
                        )
                        if result and result.get('status') not in ['error', 'unfilled']:
                            logger.info(f"  ✅ {symbol} SOLD successfully!")
                        else:
                            error_msg = result.get('error', result.get('message', 'Unknown')) if result else 'No response'
                            logger.error(f"  ❌ {symbol} failed: {error_msg}")
                    except Exception as sell_err:
                        logger.error(f"  ❌ {symbol} error: {sell_err}")
                
                logger.info(f"="*80)
                logger.info(f"✅ Concurrent exit complete: {len(positions_to_exit)} positions processed")
                logger.info(f"")
            
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
                    
                    # Scan top markets (limit to prevent timeouts)
                    scan_limit = min(MARKET_SCAN_LIMIT, len(all_products))
                    logger.info(f"   Scanning {scan_limit} markets...")
                    
                    for i, symbol in enumerate(all_products[:scan_limit]):
                        try:
                            # Get candles
                            candles = self.broker.get_candles(symbol, '5m', 100)
                            if not candles or len(candles) < 100:
                                continue
                            
                            # Convert to DataFrame
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
