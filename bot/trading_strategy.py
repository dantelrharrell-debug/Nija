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
from paper_trading import get_paper_account

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
    
    def __init__(self, client, pairs=None, base_allocation=8.0, max_exposure=0.7, max_daily_loss=0.025, paper_mode=False):
        self.client = client
        self.pairs = pairs or ["BTC-USD", "ETH-USD", "SOL-USD"]
        self.base_allocation = base_allocation  # % of balance per trade
        self.max_exposure = max_exposure  # max % of account in positions (70% - ultra aggressive)
        self.max_daily_loss = max_daily_loss  # max daily loss % (default 2.5%)
        self.daily_pnl = 0.0
        self.start_balance = 0.0
        self.daily_trades = 0
        self.max_daily_trades = 500  # Ultra high frequency (no limits)
        
        # Trading mode: LIVE or PAPER
        self.paper_mode = paper_mode or os.getenv("PAPER_MODE", "false").lower() == "true"
        if self.paper_mode:
            self.paper_account = get_paper_account(initial_balance=10000.0)
            print("📄 PAPER TRADING MODE ENABLED (Simulation)")
        else:
            self.paper_account = None
            print("💰 LIVE TRADING MODE ENABLED (Real Money)")
        
        # NIJA Trailing System
        self.nija = NIJATrailingSystem()
        self.position_counter = 0
        
        # Track synced positions (manual trades)
        self.synced_positions = set()  # Track which Coinbase positions we've imported
        
        # Trade Cooldown (removed for high frequency)
        self.last_trade_time = None
        self.trade_cooldown_seconds = 0  # No cooldown for 12 trades/hour
        
        # Aggressive Mode: No burn-down restrictions
        self.consecutive_losses = 0
        
        # Daily Profit Lock: Disabled for maximum opportunity
        self.profit_lock_active = False
        
    def sync_coinbase_positions(self):
        """Import ALL open positions from Coinbase (including manual trades) into NIJA management"""
        try:
            print(f"\n🔄 Syncing ALL Coinbase positions into NIJA management...")
            accounts = self.client.get_accounts()
            
            imported_count = 0
            for account in accounts['accounts']:
                currency = account['currency']
                
                # Skip USD and stablecoins - these are cash positions
                if currency in ['USD', 'USDC', 'USDT']:
                    continue
                
                # Handle both dict and object formats
                if hasattr(account, 'available_balance'):
                    balance = float(account.available_balance.get('value', 0)) if isinstance(account.available_balance, dict) else float(account.available_balance.value)
                else:
                    balance = float(account.get('available_balance', {}).get('value', 0))
                
                # If we have a balance, we have a position
                if balance > 0:
                    product_id = f"{currency}-USD"
                    position_key = f"{product_id}-manual"
                    
                    # Skip if already synced
                    if position_key in self.synced_positions:
                        continue
                    
                    # Get current price to estimate entry (we don't know actual entry)
                    try:
                        ticker = self.client.get_product(product_id=product_id)
                        current_price = float(ticker['price'])
                        
                        # Check if already managed by NIJA
                        already_managed = any(
                            pos['product_id'] == product_id 
                            for pos in self.nija.positions.values()
                        )
                        
                        if not already_managed:
                            # Import into NIJA management
                            # Estimate volatility from current market
                            df = self.get_product_candles(product_id)
                            if df is not None and len(df) > 5:
                                volatility = df['close'].pct_change().std()
                            else:
                                volatility = 0.004  # Default
                            
                            # Get market parameters
                            params = market_adapter.get_parameters(product_id)
                            
                            # Create position in NIJA system
                            self.position_counter += 1
                            position_id = f"{product_id}-manual-{self.position_counter}"
                            
                            position = self.nija.open_position(
                                position_id=position_id,
                                side='long',  # Assume long (we hold the asset)
                                entry_price=current_price,  # Use current price as proxy
                                size=balance,
                                volatility=volatility,
                                market_params=params
                            )
                            
                            position['product_id'] = product_id
                            position['imported'] = True  # Mark as imported (not NIJA-created)
                            
                            self.synced_positions.add(position_key)
                            imported_count += 1
                            
                            print(f"   ✅ Imported: {balance:.8f} {currency} (${balance * current_price:.2f}) - Now managed by NIJA")
                    
                    except Exception as e:
                        print(f"   ⚠️ Could not import {currency}: {e}")
            
            if imported_count > 0:
                print(f"\n✅ Synced {imported_count} manual position(s) into NIJA management")
            else:
                print(f"   ℹ️ No new positions to sync")
            
        except Exception as e:
            print(f"❌ Error syncing Coinbase positions: {e}")
    
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
    
    def calculate_position_size(self, product_id, signal_score=3, df=None):
        """
        NIJA Position Sizing Logic - Multi-Market Adaptive with Volatility Boost
        
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
        
        # VOLATILITY BOOST: Increase size 20% for high volatility (more profit potential)
        volatility = df['close'].pct_change().std() if df is not None and len(df) > 5 else 0.004
        if volatility > 0.008:  # High volatility
            position_size *= 1.2
            print(f"   🔥 High volatility ({volatility:.2%}) - boosting position 20%")
        
        # Convert to percentage for logging
        allocation_pct = (position_size / usd_balance) * 100
        
        # AGGRESSIVE MODE: No restrictions - full allocation always
        # Let trailing stops handle risk management
        
        # Check max exposure (sum of NIJA-created positions only, not imported manual trades)
        current_exposure = sum([
            pos['entry_price'] * pos['size'] * pos['remaining_size']
            for pos in self.nija.positions.values()
            if not pos.get('imported', False)  # Exclude imported manual positions
        ])
        
        if current_exposure / usd_balance > self.max_exposure:
            print(f"⚠️ Max exposure reached ({current_exposure/usd_balance:.1%}) - waiting for exits")
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
        
        # Sync ALL Coinbase positions (including manual trades) into NIJA management
        self.sync_coinbase_positions()
        
        usd_balance = self.get_usd_balance()
        
        if self.start_balance == 0:
            self.start_balance = usd_balance
        
        print(f"💰 USD Balance: ${usd_balance:.2f}")
        print(f"📊 Daily P&L: ${self.daily_pnl:.2f} ({self.daily_pnl/self.start_balance*100:.2f}%)")
        print(f"📍 Open Positions: {len(self.nija.positions)} (NIJA + Manual)")
        
        # Manage existing positions first (includes imported positions)
        self.manage_open_positions()
        
        # AGGRESSIVE MODE: No profit locks
        
        # Look for new entry signals
        for product_id in self.pairs:
            # PYRAMIDING: Allow adding to winning positions (if profit > 2%)
            existing_positions = [pos for pos_id, pos in self.nija.positions.items() if pos.get('product_id') == product_id]
            has_profitable_position = any(pos.get('profit_pct', 0) > 2.0 for pos in existing_positions)
            
            # Skip if already have position UNLESS it's profitable (pyramid opportunity)
            if any(pos['product_id'] == product_id for pos in self.nija.positions.values()):
                if not has_profitable_position:
                    continue
                # else: Allow pyramiding on winners
            
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
            
            # QUALITY OVER QUANTITY: Require 3/5 signals for better win rate
            min_score = 3  # Higher quality setups only
            if indicators.get('rsi') is not None:
                rsi_val = float(indicators['rsi'].iloc[-1])
                # Allow 2/5 with extreme momentum
                if action == 'buy' and 55 < rsi_val < 65:
                    min_score = 2
                elif action == 'sell' and 35 < rsi_val < 45:
                    min_score = 2
            
            if action == 'buy' and signal_score >= min_score:
                print(f"� LONG SIGNAL DETECTED - Score: {signal_score}/5")
                
                # Display entry conditions
                long_cond = indicators['entry_conditions']['long']
                print(f"   {'✅' if long_cond['price_above_vwap'] else '❌'} Price above VWAP: {long_cond['price_above_vwap']}")
                print(f"   {'✅' if long_cond['ema_alignment'] else '❌'} EMA 9>21>50: {long_cond['ema_alignment']}")
                print(f"   {'✅' if long_cond['rsi_favorable'] else '❌'} RSI favorable (momentum/pullback): {long_cond['rsi_favorable']}")
                print(f"   {'✅' if long_cond['volume_confirmation'] else '❌'} Volume ≥ 50% prev 2: {long_cond['volume_confirmation']}")
                print(f"   {'✅' if long_cond['candle_close_bullish'] else '❌'} Candle close bullish: {long_cond['candle_close_bullish']}")
                
                position_size = self.calculate_position_size(product_id, signal_score, df)
                
                if position_size > 0.005:  # Minimum $0.005 trade (AGGRESSIVE)
                    self.enter_position(product_id, 'long', position_size, df)
                    self.last_trade_time = datetime.now()
                    self.daily_trades += 1
                else:
                    print(f"⚠️ Position size too small: ${position_size:.4f} (minimum: $0.005)")
            
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
        """Enter a new position with NIJA trailing (supports LIVE and PAPER modes)"""
        try:
            # Get current price
            ticker = self.client.get_product(product_id=product_id)
            entry_price = float(ticker['price'])
            
            # Calculate size
            size = usd_amount / entry_price
            
            # Calculate volatility for stop-loss
            volatility = df['close'].pct_change().std()
            
            # Get market-specific parameters
            params = market_adapter.get_parameters(product_id)
            
            # Generate position ID
            self.position_counter += 1
            position_id = f"{product_id}-{self.position_counter}"
            
            # LIVE MODE: Execute real trade on Coinbase
            if not self.paper_mode:
                order = self.client.market_order_buy(
                    client_order_id=f"{product_id}-{int(time.time())}",
                    product_id=product_id,
                    quote_size=str(round(usd_amount, 2))
                )
            
            # PAPER MODE: Simulate trade
            else:
                # Calculate stop loss for paper account
                base_stop_pct = params['stop_loss']['base_pct']
                volatility_stop = volatility * params['stop_loss']['volatility_multiplier']
                stop_pct = max(base_stop_pct, volatility_stop)
                stop_loss = entry_price * (1 - stop_pct)
                
                # Open paper position
                self.paper_account.open_position(
                    symbol=product_id,
                    size=size,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    side=side,
                    position_id=position_id
                )
            
            # Open NIJA position tracking (both modes)
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
            
            mode_indicator = "📄 PAPER" if self.paper_mode else "✅ NIJA"
            print(f"{mode_indicator} Position Opened: {size:.8f} {product_id} @ ${entry_price:.2f}")
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
            
            # Update paper position if in paper mode
            if self.paper_mode and self.paper_account:
                self.paper_account.update_position(position_id, current_price)
            
            # NIJA Trailing Management
            action, size_to_close, reason = self.nija.manage_position(
                position_id, current_price, df, rsi, vwap
            )
            
            mode_indicator = "📄" if self.paper_mode else "💰"
            print(f"\n{mode_indicator} {product_id} [{position_id}]:")
            print(f"   Price: ${current_price:.2f} | Entry: ${position['entry_price']:.2f}")
            print(f"   Profit: {position['profit_pct']:.2f}% | Remaining: {position['remaining_size']*100:.0f}%")
            print(f"   Stop: ${position['stop_loss']:.2f} | TSL: {'✅' if position.get('tsl_active') else '❌'} | TTP: {'✅' if position.get('ttp_active') else '❌'}")
            print(f"   → {reason}")
            
            # Execute action
            if action == 'partial_close':
                self.close_partial_position(product_id, position_id, size_to_close, current_price, reason)
            elif action == 'close_all':
                self.close_full_position(product_id, position_id, current_price, reason)
    
    def close_partial_position(self, product_id, position_id, size_pct, current_price, reason):
        """Close a partial position (TP1 or TP2) - supports LIVE and PAPER modes"""
        try:
            position = self.nija.positions.get(position_id)
            if not position:
                print(f"   ⚠️ Position {position_id} not found")
                return
            
            mode_indicator = "📄 PAPER" if self.paper_mode else "💰 LIVE"
            print(f"   🔄 {mode_indicator} Partial Close: {size_pct*100:.0f}% - {reason}")
            
            # Calculate amount to sell (base crypto size)
            total_crypto_size = position['size']
            crypto_to_sell = total_crypto_size * size_pct
            
            # LIVE MODE: Execute real sell order
            if not self.paper_mode:
                try:
                    order = self.client.market_order_sell(
                        client_order_id=f"{product_id}-sell-{int(time.time())}",
                        product_id=product_id,
                        base_size=str(crypto_to_sell)
                    )
                    print(f"   ✅ Sold {crypto_to_sell:.8f} {product_id.split('-')[0]} at ${current_price:.2f}")
                except Exception as sell_error:
                    print(f"   ❌ Sell order failed: {sell_error}")
                    return
            
            # PAPER MODE: Update paper account
            else:
                if self.paper_account:
                    self.paper_account.close_position(
                        position_id=position_id,
                        exit_price=current_price,
                        close_pct=size_pct * 100,
                        reason=reason
                    )
        except Exception as e:
            print(f"   ❌ Error closing partial: {e}")
    
    def close_full_position(self, product_id, position_id, current_price, reason):
        """Close full position - supports LIVE and PAPER modes"""
        try:
            position = self.nija.positions.get(position_id)
            if position:
                profit = position['profit_pct']
                profit_usd = position['entry_price'] * position['size'] * profit / 100
                
                mode_indicator = "📄 PAPER" if self.paper_mode else "💰 LIVE"
                print(f"   🎯 {mode_indicator} Full Close: {reason}")
                print(f"   Final P&L: {profit:.2f}% (${profit_usd:.2f})")
                
                # Update daily P&L
                self.daily_pnl += profit_usd
                
                # Track consecutive losses (for stats only)
                if profit < 0:
                    self.consecutive_losses += 1
                else:
                    self.consecutive_losses = 0
                
                # LIVE MODE: Execute real sell order
                if not self.paper_mode:
                    try:
                        # Calculate remaining crypto size to sell
                        total_crypto_size = position['size']
                        remaining_size = total_crypto_size * position['remaining_size']
                        
                        order = self.client.market_order_sell(
                            client_order_id=f"{product_id}-sell-{int(time.time())}",
                            product_id=product_id,
                            base_size=str(remaining_size)
                        )
                        print(f"   ✅ Sold {remaining_size:.8f} {product_id.split('-')[0]} at ${current_price:.2f}")
                    except Exception as sell_error:
                        print(f"   ❌ Sell order failed: {sell_error}")
                        return
                
                # PAPER MODE: Close paper position
                else:
                    if self.paper_account:
                        self.paper_account.close_position(
                            position_id=position_id,
                            exit_price=current_price,
                            close_pct=100.0,
                            reason=reason
                        )
                
                # Remove from NIJA system
                self.nija.close_position(position_id)
                
        except Exception as e:
            print(f"   ❌ Error closing position: {e}")
