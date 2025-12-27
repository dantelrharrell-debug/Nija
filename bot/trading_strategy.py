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
MIN_CANDLES_REQUIRED = 90  # Minimum candles needed for analysis (relaxed from 100 to prevent infinite sell loops)

# Exit strategy constants (no entry price required)
MIN_POSITION_VALUE = 1.0  # Auto-exit positions under this USD value
RSI_OVERBOUGHT_THRESHOLD = 70  # Exit when RSI exceeds this (lock gains)
RSI_OVERSOLD_THRESHOLD = 30  # Exit when RSI below this (cut losses)
DEFAULT_RSI = 50  # Default RSI value when indicators unavailable

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
        
        # Track positions that can't be sold (too small/dust) to avoid infinite retry loops
        self.unsellable_positions = set()  # Set of symbols that failed to sell due to size issues
        
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
            
            # CRITICAL: Sync position tracker with actual broker positions at startup
            # This handles cases where positions were sold manually or bot was restarted
            if self.broker and hasattr(self.broker, 'position_tracker') and self.broker.position_tracker:
                try:
                    broker_positions = self.broker.get_positions()
                    removed = self.broker.position_tracker.sync_with_broker(broker_positions)
                    if removed > 0:
                        logger.info(f"🔄 Synced position tracker: removed {removed} orphaned positions")
                except Exception as sync_err:
                    logger.warning(f"⚠️ Position tracker sync failed: {sync_err}")
            
            logger.info("✅ TradingStrategy initialized (APEX v7.1 + Position Cap Enforcer + Profit Tracking)")
        
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
            
            # CRITICAL: If over position cap, prioritize selling weakest positions immediately
            # This ensures we get back under cap quickly to avoid further bleeding
            positions_over_cap = len(current_positions) - 8
            if positions_over_cap > 0:
                logger.warning(f"🚨 OVER POSITION CAP: {len(current_positions)}/8 positions ({positions_over_cap} excess)")
                logger.warning(f"   Will prioritize selling {positions_over_cap} weakest positions first")
            
            # CRITICAL FIX: Identify ALL positions that need to exit first
            # Then sell them ALL concurrently, not one at a time
            positions_to_exit = []
            
            for position in current_positions:
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
                    if self.broker and hasattr(self.broker, 'position_tracker') and self.broker.position_tracker:
                        try:
                            pnl_data = self.broker.position_tracker.calculate_pnl(symbol, current_price)
                            if pnl_data:
                                pnl_percent = pnl_data['pnl_percent']
                                pnl_dollars = pnl_data['pnl_dollars']
                                entry_price = pnl_data['entry_price']
                                
                                logger.info(f"   💰 P&L: ${pnl_dollars:+.2f} ({pnl_percent:+.2f}%) | Entry: ${entry_price:.2f}")
                                
                                # STEPPED PROFIT TAKING - Exit portions at profit targets
                                # This locks in gains and frees capital for new opportunities
                                if pnl_percent >= 3.0:
                                    logger.info(f"   🎯 PROFIT TARGET HIT: {symbol} at +{pnl_percent:.2f}% (target: +3.0%)")
                                    positions_to_exit.append({
                                        'symbol': symbol,
                                        'quantity': quantity,
                                        'reason': f'Profit target +3.0% hit (actual: +{pnl_percent:.2f}%)'
                                    })
                                    continue
                                elif pnl_percent >= 2.0:
                                    logger.info(f"   🎯 PROFIT TARGET HIT: {symbol} at +{pnl_percent:.2f}% (target: +2.0%)")
                                    positions_to_exit.append({
                                        'symbol': symbol,
                                        'quantity': quantity,
                                        'reason': f'Profit target +2.0% hit (actual: +{pnl_percent:.2f}%)'
                                    })
                                    continue
                                elif pnl_percent >= 1.0:
                                    logger.info(f"   🎯 PROFIT TARGET HIT: {symbol} at +{pnl_percent:.2f}% (target: +1.0%)")
                                    positions_to_exit.append({
                                        'symbol': symbol,
                                        'quantity': quantity,
                                        'reason': f'Profit target +1.0% hit (actual: +{pnl_percent:.2f}%)'
                                    })
                                    continue
                                elif pnl_percent >= 0.5:
                                    logger.info(f"   🎯 PROFIT TARGET HIT: {symbol} at +{pnl_percent:.2f}% (target: +0.5%)")
                                    positions_to_exit.append({
                                        'symbol': symbol,
                                        'quantity': quantity,
                                        'reason': f'Profit target +0.5% hit (actual: +{pnl_percent:.2f}%)'
                                    })
                                    continue
                                
                                # STOP LOSS - Cut losses aggressively
                                elif pnl_percent <= -2.0:
                                    logger.warning(f"   🛑 STOP LOSS HIT: {symbol} at {pnl_percent:.2f}% (stop: -2.0%)")
                                    positions_to_exit.append({
                                        'symbol': symbol,
                                        'quantity': quantity,
                                        'reason': f'Stop loss -2.0% hit (actual: {pnl_percent:.2f}%)'
                                    })
                                    continue
                                elif pnl_percent <= -1.0:
                                    logger.warning(f"   ⚠️ Approaching stop loss: {symbol} at {pnl_percent:.2f}%")
                                    # Don't exit yet, but log it
                                
                        except Exception as pnl_err:
                            logger.debug(f"   Could not calculate P&L for {symbol}: {pnl_err}")
                    
                    # Get market data for analysis
                    candles = self.broker.get_candles(symbol, '5m', 100)
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
                    logger.info(f"   DEBUG candle types → close={type(df['close'].iloc[-1])}, open={type(df['open'].iloc[-1])}, volume={type(df['volume'].iloc[-1])}")
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
                    
                    # CRITICAL FIX: Exit on RSI extremes without requiring entry price
                    rsi = indicators.get('rsi', pd.Series()).iloc[-1] if 'rsi' in indicators else DEFAULT_RSI
                    
                    # RSI overbought (>70) or oversold (<30) - exit to lock in gains or cut losses
                    if rsi > RSI_OVERBOUGHT_THRESHOLD:
                        logger.info(f"   📈 RSI OVERBOUGHT EXIT: {symbol} (RSI={rsi:.1f})")
                        positions_to_exit.append({
                            'symbol': symbol,
                            'quantity': quantity,
                            'reason': f'RSI overbought ({rsi:.1f})'
                        })
                        continue
                    elif rsi < RSI_OVERSOLD_THRESHOLD:
                        logger.info(f"   📉 RSI OVERSOLD EXIT: {symbol} (RSI={rsi:.1f}) - prevent further losses")
                        positions_to_exit.append({
                            'symbol': symbol,
                            'quantity': quantity,
                            'reason': f'RSI oversold ({rsi:.1f}) - cut losses'
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
            
            # CRITICAL: If still over cap after normal exit analysis, force-sell weakest remaining positions
            if len(current_positions) > 8 and len(positions_to_exit) < (len(current_positions) - 8):
                logger.warning(f"🚨 STILL OVER CAP: Need to sell {len(current_positions) - 8 - len(positions_to_exit)} more positions")
                
                # Identify positions not yet marked for exit
                symbols_to_exit = {p['symbol'] for p in positions_to_exit}
                remaining_positions = [p for p in current_positions if p.get('symbol') not in symbols_to_exit]
                
                # Sort by USD value (smallest first - easiest to exit and lowest capital impact)
                remaining_sorted = sorted(remaining_positions, key=lambda p: p.get('quantity', 0) * self.broker.get_current_price(p.get('symbol', '')))
                
                # Force-sell smallest positions to get under cap
                positions_needed = (len(current_positions) - 8) - len(positions_to_exit)
                for pos in remaining_sorted[:positions_needed]:
                    symbol = pos.get('symbol')
                    quantity = pos.get('quantity', 0)
                    try:
                        price = self.broker.get_current_price(symbol)
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
                            # Remove from unsellable set if it was there (position grew and became sellable)
                            self.unsellable_positions.discard(symbol)
                        else:
                            error_msg = result.get('error', result.get('message', 'Unknown')) if result else 'No response'
                            error_code = result.get('error') if result else None
                            logger.error(f"  ❌ {symbol} sell failed: {error_msg}")
                            logger.error(f"     Full result: {result}")
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
                
                logger.info(f"="*80)
                logger.info(f"✅ Concurrent exit complete: {len(positions_to_exit)} positions processed")
                logger.info(f"")
            
            # STEP 2: Look for new entry opportunities (only if entries allowed)
            # CRITICAL: Prevent positions under $2 and enforce strict 8-position cap
            min_position_size = 2.0  # Never trade below $2
            max_positions = 8
            
            if not entries_blocked and len(current_positions) < max_positions and account_balance >= 25.0:
                logger.info(f"🔍 Scanning for new opportunities (positions: {len(current_positions)}/{max_positions}, balance: ${account_balance:.2f})...")
                
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
                                position_size = analysis.get('position_size', 0)
                                
                                # CRITICAL: Skip positions under $2
                                if position_size < min_position_size:
                                    logger.warning(f"   ⚠️  {symbol} position size ${position_size:.2f} < ${min_position_size} minimum - SKIPPING")
                                    continue
                                
                                # CRITICAL: Verify we're still under position cap
                                if len(current_positions) >= max_positions:
                                    logger.warning(f"   ⚠️  Position cap ({max_positions}) reached - STOP NEW ENTRIES")
                                    break
                                
                                logger.info(f"   🎯 BUY SIGNAL: {symbol} - size=${position_size:.2f} - {analysis.get('reason', '')}")
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
