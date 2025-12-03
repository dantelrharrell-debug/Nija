# trading_strategy.py
import time
import pandas as pd
from datetime import datetime, timedelta
import sys
import os

# Add bot directory to path if running from root
if os.path.basename(os.getcwd()) != 'bot':
    sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from nija_trailing_system import NIJATrailingSystem
from market_adapter import market_adapter, MarketType

class TradingStrategy:
    """
    NIJA Ultimate Trading Strategy with Advanced Trailing System
    
    Features:
    - VWAP, RSI, MACD indicators for entry signals
    - NIJA Trailing Stop-Loss (TSL) with EMA-21 and micro-trail
    - NIJA Trailing Take-Profit (TTP) with dynamic exits
    - Partial position management (50% → 25% → 25%)
    - Risk management and position sizing
    """
    
    def __init__(self, client, pairs=None, base_allocation=5.0, max_exposure=0.3, max_daily_loss=0.025):
        self.client = client
        self.pairs = pairs or ["BTC-USD", "ETH-USD", "SOL-USD"]
        self.base_allocation = base_allocation  # % of balance per trade
        self.max_exposure = max_exposure  # max % of account in positions
        self.max_daily_loss = max_daily_loss  # max daily loss % (default 2.5%)
        self.daily_pnl = 0.0
        self.start_balance = 0.0
        self.daily_trades = 0
        self.max_daily_trades = 200  # 12+ trades per hour
        
        # NIJA Trailing System
        self.nija = NIJATrailingSystem()
        self.position_counter = 0
        
        # Trade Cooldown (removed for high frequency)
        self.last_trade_time = None
        self.trade_cooldown_seconds = 0  # No cooldown for 12 trades/hour
        
        # Smart Burn-Down Rule
        self.consecutive_losses = 0
        self.burn_down_mode = False
        self.burn_down_trades_remaining = 0
        
        # Daily Profit Lock
        self.daily_profit_lock_threshold = 0.03  # 3% daily profit
        self.profit_lock_active = False
        
    def get_usd_balance(self):
        """Get USD balance from Coinbase"""
        try:
            accounts = self.client.get_accounts()
            for account in accounts['accounts']:
                if account['currency'] == 'USD':
                    return float(account['available_balance']['value'])
        except Exception as e:
            print(f"Error fetching USD balance: {e}")
        return 0.0
    
    def get_product_candles(self, product_id, granularity="FIVE_MINUTE", count=100):
        """Fetch candle data for technical analysis"""
        try:
            # Coinbase API granularity mapping
            granularity_seconds = {
                "ONE_MINUTE": 60,
                "FIVE_MINUTE": 300,
                "FIFTEEN_MINUTE": 900,
                "THIRTY_MINUTE": 1800,
                "ONE_HOUR": 3600,
                "TWO_HOUR": 7200,
                "SIX_HOUR": 21600,
                "ONE_DAY": 86400
            }
            
            seconds = granularity_seconds.get(granularity, 300)
            end = int(time.time())
            start = end - (seconds * count)
            
            print(f"      Calling Coinbase API: product={product_id}, start={start}, end={end}, granularity={granularity}")
            
            candles = self.client.get_candles(
                product_id=product_id,
                start=start,
                end=end,
                granularity=granularity
            )
            
            print(f"      API response received: {type(candles)}")
            
            if not candles:
                print(f"      Response is None or empty!")
                return None
                
            # Handle different response types
            if hasattr(candles, '__dict__'):
                print(f"      Response attributes: {list(candles.__dict__.keys())}")
                
            if hasattr(candles, 'candles'):
                candle_list = candles.candles
                print(f"      Found candles attribute: {len(candle_list) if candle_list else 0} candles")
            elif isinstance(candles, dict) and 'candles' in candles:
                candle_list = candles['candles']
                print(f"      Found candles in dict: {len(candle_list)} candles")
            else:
                print(f"      No candles found in response!")
                return None
            
            if not candle_list:
                print(f"      Candle list is empty!")
                return None
            
            print(f"      Processing {len(candle_list)} candles...")
            
            # Convert candle objects to dict format
            candle_dicts = []
            for candle in candle_list:
                if hasattr(candle, '__dict__'):
                    candle_dicts.append(candle.__dict__)
                elif isinstance(candle, dict):
                    candle_dicts.append(candle)
                else:
                    # Try to convert to dict
                    candle_dicts.append(dict(candle))
            
            df = pd.DataFrame(candle_dicts)
            print(f"      DataFrame columns: {list(df.columns)}")
            df['start'] = pd.to_datetime(pd.to_numeric(df['start'], errors='coerce'), unit='s')
            df = df.sort_values('start')
            
            # Rename columns for indicators
            df.rename(columns={
                'low': 'low',
                'high': 'high',
                'open': 'open',
                'close': 'close',
                'volume': 'volume'
            }, inplace=True)
            
            # Convert to float
            for col in ['low', 'high', 'open', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            print(f"      DataFrame created: {len(df)} rows")
            return df
            
        except Exception as e:
            print(f"Error fetching candles for {product_id}: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def calculate_position_size(self, product_id, signal_score=3):
        """
        NIJA Position Sizing Logic - Multi-Market Adaptive
        
        Auto-detects market type and adjusts sizing:
        - Crypto: 2-10%
        - Stocks: 1-5%
        - Futures: 0.25-0.75%
        - Options: 1-3%
        
        Allocation based on signal strength (score 1-5)
        """
        usd_balance = self.get_usd_balance()
        
        if usd_balance == 0:
            return 0.0
        
        # Get market-specific parameters
        params = market_adapter.get_parameters(product_id)
        market_type = params.market_type
        
        # Use market adapter for position sizing
        position_size = market_adapter.get_position_size(product_id, signal_score, usd_balance)
        
        if position_size == 0:
            return 0.0
        
        # Convert to percentage for logging
        allocation_pct = (position_size / usd_balance) * 100
        
        # Smart Burn-Down Rule: 3 losses in a row → 2% for next 3 trades
        if self.burn_down_mode:
            allocation_pct = 2.0
            print(f"🔥 BURN-DOWN MODE: Reduced to 2% ({self.burn_down_trades_remaining} trades remaining)")
        
        # Daily Profit Lock: If +3% daily profit → smaller size (2-3%), only A+ setups
        if self.profit_lock_active:
            if signal_score < 5:
                print(f"🔒 PROFIT LOCK: Skipping (need A+ setup, score={signal_score})")
                return 0.0
            allocation_pct = min(allocation_pct, 2.5)  # Cap at 2-3%
            print(f"🔒 PROFIT LOCK: Reduced to {allocation_pct}% (A+ only)")
        
        # Check max exposure (sum of all open NIJA positions)
        current_exposure = sum([
            pos['entry_price'] * pos['size'] * pos['remaining_size']
            for pos in self.nija.positions.values()
        ])
        
        if current_exposure / usd_balance > self.max_exposure:
            print(f"⚠️ Max exposure reached ({current_exposure/usd_balance:.1%})")
            return 0.0
        
        # Check daily loss limit (2.5%)
        if self.start_balance > 0 and self.daily_pnl / self.start_balance < -self.max_daily_loss:
            print(f"⚠️ Max daily loss reached ({self.daily_pnl:.2f})")
            return 0.0
        
        # Check max daily trades
        if self.daily_trades >= self.max_daily_trades:
            print(f"⚠️ Max daily trades reached ({self.daily_trades}/{self.max_daily_trades})")
            return 0.0
        
        print(f"   💰 Market: {market_type.value.upper()} | Allocation: {allocation_pct:.1f}%")
        
        return position_size
    
    def calculate_signal_score(self, product_id, indicators, df):
        """
        NIJA ULTIMATE TRADING LOGIC™ - Signal Strength Scoring
        
        Scores 1-5 based on how many entry conditions are met.
        All 5 conditions = Score 5/5 (A+ setup)
        """
        if not indicators or indicators.get('rsi') is None:
            return None, 0
        
        action = None
        score = 0
        
        # Check if we have a buy or sell signal
        if indicators['buy_signal']:
            action = 'buy'
            # Count how many LONG conditions are TRUE
            long_conditions = indicators['entry_conditions']['long']
            score = sum(1 for condition in long_conditions.values() if condition)
        
        elif indicators['sell_signal']:
            action = 'sell'
            # Count how many SHORT conditions are TRUE
            short_conditions = indicators['entry_conditions']['short']
            score = sum(1 for condition in short_conditions.values() if condition)
        
        return action, score
    
    def place_market_order(self, product_id, side, usd_amount):
        """Place a market order"""
        try:
            # Get current price
            ticker = self.client.get_product(product_id=product_id)
            price = float(ticker['price'])
            
            # Calculate size
            size = usd_amount / price
            
            # Place order
            order = self.client.market_order_buy(
                client_order_id=f"{product_id}-{int(time.time())}",
                product_id=product_id,
                quote_size=str(round(usd_amount, 2))
            )
            
            print(f"✅ {side.upper()} order placed: {size:.8f} {product_id} @ ${price:.2f} = ${usd_amount:.2f}")
            
            return {
                'product_id': product_id,
                'side': side,
                'size': size,
                'entry_price': price,
                'usd_amount': usd_amount,
                'timestamp': datetime.now(),
                'closed': False
            }
            
        except Exception as e:
            print(f"❌ Error placing order: {e}")
            return None
    
    def run_trading_cycle(self):
        """Run one trading cycle with NIJA Trailing System"""
        print(f"\n{'='*60}")
        print(f"🔥 NIJA Trading Cycle - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}")
        
        usd_balance = self.get_usd_balance()
        
        if self.start_balance == 0:
            self.start_balance = usd_balance
        
        print(f"💰 USD Balance: ${usd_balance:.2f}")
        print(f"📊 Daily P&L: ${self.daily_pnl:.2f} ({self.daily_pnl/self.start_balance*100:.2f}%)")
        print(f"📍 Open Positions: {len(self.nija.positions)}")
        
        # Manage existing positions first
        self.manage_open_positions()
        
        # Check daily profit lock
        if self.start_balance > 0:
            daily_profit_pct = self.daily_pnl / self.start_balance
            if daily_profit_pct >= self.daily_profit_lock_threshold and not self.profit_lock_active:
                self.profit_lock_active = True
                print(f"\n🔒 DAILY PROFIT LOCK ACTIVATED: +{daily_profit_pct*100:.2f}% (threshold: +3%)")
                print(f"   → Switching to: Smaller size (2-3%), A+ setups only")
        
        # Look for new entry signals
        for product_id in self.pairs:
            # Skip if already have position in this pair
            if any(pos['product_id'] == product_id for pos in self.nija.positions.values()):
                continue
            
            # Check trade cooldown (2 minutes)
            if self.last_trade_time:
                time_since_last = (datetime.now() - self.last_trade_time).total_seconds()
                if time_since_last < self.trade_cooldown_seconds:
                    print(f"\n⏳ Trade cooldown active: {self.trade_cooldown_seconds - time_since_last:.0f}s remaining")
                    continue
            
            market_type = market_adapter.detect_market_type(product_id)
            print(f"\n--- Analyzing {product_id} ({market_type.value.upper()}) for Entry ---")
            
            # Get candle data
            try:
                print(f"   📈 Fetching candle data...")
                df = self.get_product_candles(product_id)
                
                if df is None or len(df) < 30:
                    print(f"⚠️ Insufficient data for {product_id}")
                    continue
                    
                print(f"   ✅ Got {len(df)} candles")
            except Exception as e:
                print(f"❌ Error fetching candles for {product_id}: {e}")
                import traceback
                traceback.print_exc()
                continue
            
            # Calculate indicators
            try:
                print(f"   🧮 Calculating indicators...")
                from indicators import calculate_indicators
                indicators = calculate_indicators(df)
                print(f"   ✅ Indicators calculated")
            except Exception as e:
                print(f"❌ Error calculating indicators for {product_id}: {e}")
                import traceback
                traceback.print_exc()
                continue
            
            # Check no-trade zones
            if indicators.get('no_trade_zone'):
                print(f"❌ NO-TRADE ZONE: {indicators['no_trade_reason']}")
                continue
            
            # Get signal score (1-5)
            action, signal_score = self.calculate_signal_score(product_id, indicators, df)
            
            if action == 'buy' and signal_score >= 2:
                print(f"� LONG SIGNAL DETECTED - Score: {signal_score}/5")
                
                # Display entry conditions
                long_cond = indicators['entry_conditions']['long']
                print(f"   {'✅' if long_cond['price_above_vwap'] else '❌'} Price above VWAP: {long_cond['price_above_vwap']}")
                print(f"   {'✅' if long_cond['ema_alignment'] else '❌'} EMA 9>21>50: {long_cond['ema_alignment']}")
                print(f"   {'✅' if long_cond['rsi_favorable'] else '❌'} RSI favorable (momentum/pullback): {long_cond['rsi_favorable']}")
                print(f"   {'✅' if long_cond['volume_confirmation'] else '❌'} Volume ≥ 50% prev 2: {long_cond['volume_confirmation']}")
                print(f"   {'✅' if long_cond['candle_close_bullish'] else '❌'} Candle close bullish: {long_cond['candle_close_bullish']}")
                
                position_size = self.calculate_position_size(product_id, signal_score)
                
                if position_size > 10:  # Minimum $10 trade
                    self.enter_position(product_id, 'long', position_size, df)
                    self.last_trade_time = datetime.now()
                    self.daily_trades += 1
                else:
                    print(f"⚠️ Position size too small: ${position_size:.2f}")
            
            elif action == 'sell' and signal_score >= 2:
                print(f"📉 SHORT SIGNAL DETECTED - Score: {signal_score}/5")
                
                # Display entry conditions
                short_cond = indicators['entry_conditions']['short']
                print(f"   {'✅' if short_cond['price_below_vwap'] else '❌'} Price below VWAP: {short_cond['price_below_vwap']}")
                print(f"   {'✅' if short_cond['ema_alignment'] else '❌'} EMA 9<21<50: {short_cond['ema_alignment']}")
                print(f"   {'✅' if short_cond['rsi_favorable'] else '❌'} RSI favorable (momentum/bounce): {short_cond['rsi_favorable']}")
                print(f"   {'✅' if short_cond['volume_confirmation'] else '❌'} Volume ≥ 50% prev 2: {short_cond['volume_confirmation']}")
                print(f"   {'✅' if short_cond['candle_close_bearish'] else '❌'} Candle close bearish: {short_cond['candle_close_bearish']}")
                
                print(f"   (Shorts not enabled)")
            
            else:
                print(f"⏸️ No entry signal (score: {signal_score}/5)")
            
            # Display current indicators
            if indicators and indicators.get('rsi') is not None:
                print(f"   RSI: {indicators['rsi'].iloc[-1]:.1f} (prev: {indicators['rsi_prev']:.1f})")
                print(f"   Price: ${df['close'].iloc[-1]:.2f} | VWAP: ${indicators['vwap'].iloc[-1]:.2f}")
                print(f"   EMA: 9=${indicators['ema_9'].iloc[-1]:.2f} | 21=${indicators['ema_21'].iloc[-1]:.2f} | 50=${indicators['ema_50'].iloc[-1]:.2f}")
    
    def enter_position(self, product_id, side, usd_amount, df):
        """Enter a new position with NIJA trailing"""
        try:
            # Get current price
            ticker = self.client.get_product(product_id=product_id)
            entry_price = float(ticker['price'])
            
            # Calculate size
            size = usd_amount / entry_price
            
            # Place market order
            order = self.client.market_order_buy(
                client_order_id=f"{product_id}-{int(time.time())}",
                product_id=product_id,
                quote_size=str(round(usd_amount, 2))
            )
            
            # Calculate volatility for stop-loss
            volatility = df['close'].pct_change().std()
            
            # Get market-specific parameters
            params = market_adapter.get_parameters(product_id)
            
            # Open NIJA position with market-adjusted parameters
            self.position_counter += 1
            position_id = f"{product_id}-{self.position_counter}"
            
            position = self.nija.open_position(
                position_id=position_id,
                side=side,
                entry_price=entry_price,
                size=size,
                volatility=volatility,
                market_params=params
            )
            
            # Add product_id for tracking
            position['product_id'] = product_id
            
            print(f"✅ NIJA Position Opened: {size:.8f} {product_id} @ ${entry_price:.2f}")
            print(f"   Entry: ${entry_price:.2f} | Stop: ${position['stop_loss']:.2f}")
            print(f"   Position ID: {position_id}")
            
        except Exception as e:
            print(f"❌ Error entering position: {e}")
    
    def manage_open_positions(self):
        """Manage all open positions with NIJA Trailing System"""
        if not self.nija.positions:
            return
        
        print(f"\n{'='*60}")
        print(f"📍 Managing {len(self.nija.positions)} Open Position(s)")
        print(f"{'='*60}")
        
        for position_id, position in list(self.nija.positions.items()):
            product_id = position['product_id']
            
            # Get latest candle data
            df = self.get_product_candles(product_id)
            if df is None or len(df) < 30:
                continue
            
            # Calculate indicators
            from indicators import calculate_indicators
            indicators = calculate_indicators(df)
            
            if indicators is None or indicators.get('rsi') is None:
                continue
            
            current_price = float(df['close'].iloc[-1])
            rsi = indicators['rsi'].iloc[-1]
            vwap = indicators['vwap'].iloc[-1]
            
            # NIJA Trailing Management
            action, size_to_close, reason = self.nija.manage_position(
                position_id, current_price, df, rsi, vwap
            )
            
            print(f"\n{product_id} [{position_id}]:")
            print(f"   Price: ${current_price:.2f} | Entry: ${position['entry_price']:.2f}")
            print(f"   Profit: {position['profit_pct']:.2f}% | Remaining: {position['remaining_size']*100:.0f}%")
            print(f"   Stop: ${position['stop_loss']:.2f} | TSL: {'✅' if position.get('tsl_active') else '❌'} | TTP: {'✅' if position.get('ttp_active') else '❌'}")
            print(f"   → {reason}")
            
            # Execute action
            if action == 'partial_close':
                self.close_partial_position(product_id, size_to_close, reason)
            elif action == 'close_all':
                self.close_full_position(product_id, position_id, reason)
    
    def close_partial_position(self, product_id, size_pct, reason):
        """Close a partial position (TP1 or TP2)"""
        try:
            print(f"   🔄 Partial Close: {size_pct*100:.0f}% - {reason}")
            # Implement actual sell order here
            # For now, just log it
        except Exception as e:
            print(f"   ❌ Error closing partial: {e}")
    
    def close_full_position(self, product_id, position_id, reason):
        """Close full position with burn-down tracking"""
        try:
            position = self.nija.positions.get(position_id)
            if position:
                profit = position['profit_pct']
                profit_usd = position['entry_price'] * position['size'] * profit / 100
                
                print(f"   🎯 Full Close: {reason}")
                print(f"   Final P&L: {profit:.2f}% (${profit_usd:.2f})")
                
                # Update daily P&L
                self.daily_pnl += profit_usd
                
                # Smart Burn-Down Rule: Track consecutive losses
                if profit < 0:
                    self.consecutive_losses += 1
                    print(f"   📉 Consecutive Losses: {self.consecutive_losses}")
                    
                    # 3 losses in a row → activate burn-down mode
                    if self.consecutive_losses >= 3 and not self.burn_down_mode:
                        self.burn_down_mode = True
                        self.burn_down_trades_remaining = 3
                        print(f"\n🔥 SMART BURN-DOWN ACTIVATED")
                        print(f"   → Reducing allocation to 2% for next 3 trades")
                else:
                    # Win resets consecutive losses
                    self.consecutive_losses = 0
                    
                    # If in burn-down mode, count down wins
                    if self.burn_down_mode:
                        self.burn_down_trades_remaining -= 1
                        print(f"   ✅ Burn-down win ({self.burn_down_trades_remaining} trades remaining)")
                        
                        if self.burn_down_trades_remaining <= 0:
                            self.burn_down_mode = False
                            print(f"\n🎉 BURN-DOWN COMPLETE - Resuming normal allocation")
                
                # Remove from NIJA system
                self.nija.close_position(position_id)
                
                # Implement actual sell order here
        except Exception as e:
            print(f"   ❌ Error closing position: {e}")
