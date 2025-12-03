# trading_strategy.py
import time
import pandas as pd
from datetime import datetime, timedelta
from nija_trailing_system import NIJATrailingSystem

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
        self.max_daily_trades = 15
        
        # NIJA Trailing System
        self.nija = NIJATrailingSystem()
        self.position_counter = 0
        
        # Trade Cooldown (2 minutes)
        self.last_trade_time = None
        self.trade_cooldown_seconds = 120  # 2 minutes
        
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
    
    def get_product_candles(self, product_id, granularity=300, count=100):
        """Fetch candle data for technical analysis"""
        try:
            end = int(time.time())
            start = end - (granularity * count)
            
            candles = self.client.get_candles(
                product_id=product_id,
                start=start,
                end=end,
                granularity=granularity
            )
            
            if not candles or 'candles' not in candles:
                return None
                
            df = pd.DataFrame(candles['candles'])
            df['start'] = pd.to_datetime(df['start'], unit='s')
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
            
            return df
            
        except Exception as e:
            print(f"Error fetching candles for {product_id}: {e}")
            return None
    
    def calculate_position_size(self, product_id, signal_score=3):
        """Calculate position size based on signal scoring and risk rules"""
        usd_balance = self.get_usd_balance()
        
        if usd_balance == 0:
            return 0.0
        
        # Signal-based allocation
        # Score 5/5 → 8-10%
        # Score 4/5 → 4-6%
        # Score 3/5 → 2-3%
        # Score ≤2 → No trade
        if signal_score <= 2:
            return 0.0
        elif signal_score == 3:
            allocation_pct = 2.5  # 2-3%
        elif signal_score == 4:
            allocation_pct = 5.0  # 4-6%
        elif signal_score >= 5:
            allocation_pct = 9.0  # 8-10%
        else:
            allocation_pct = 2.0  # Default minimum
        
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
        
        position_size = usd_balance * (allocation_pct / 100)
        return min(position_size, usd_balance * 0.1)  # Cap at 10% per trade
    
    def calculate_signal_score(self, product_id, indicators, df):
        """Calculate signal score 1-5 based on NIJA criteria"""
        if not indicators or indicators.get('rsi') is None:
            return None, 0
        
        rsi = indicators['rsi'].iloc[-1]
        vwap = indicators['vwap'].iloc[-1]
        current_price = df['close'].iloc[-1]
        volume = df['volume'].iloc[-1]
        avg_volume = df['volume'].rolling(20).mean().iloc[-1]
        
        score = 0
        action = None
        
        # Detect buy or sell direction first
        if indicators['buy_signal']:
            action = 'buy'
            
            # +1 point: Price above VWAP
            if current_price > vwap:
                score += 1
            
            # +1 point: RSI oversold cross (30-50 range)
            if 30 < rsi < 50:
                score += 1
            
            # +1 point: Volume confirmation
            if volume > avg_volume * 1.2:
                score += 1
            
            # +1 point: MACD bullish crossover
            if indicators['histogram'].iloc[-1] > 0:
                score += 1
            
            # +1 point: EMA alignment (9 > 21 > 50)
            ema_9 = df['close'].ewm(span=9).mean().iloc[-1]
            ema_21 = df['close'].ewm(span=21).mean().iloc[-1]
            if ema_9 > ema_21:
                score += 1
        
        elif indicators['sell_signal']:
            action = 'sell'
            
            # Similar scoring for sell signals
            if current_price < vwap:
                score += 1
            if 50 < rsi < 70:
                score += 1
            if volume > avg_volume * 1.2:
                score += 1
            if indicators['histogram'].iloc[-1] < 0:
                score += 1
            
            ema_9 = df['close'].ewm(span=9).mean().iloc[-1]
            ema_21 = df['close'].ewm(span=21).mean().iloc[-1]
            if ema_9 < ema_21:
                score += 1
        
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
            
            print(f"\n--- Analyzing {product_id} for Entry ---")
            
            # Get candle data
            df = self.get_product_candles(product_id)
            
            if df is None or len(df) < 30:
                print(f"⚠️ Insufficient data for {product_id}")
                continue
            
            # Calculate indicators
            from indicators import calculate_indicators
            indicators = calculate_indicators(df)
            
            # Check no-trade zones
            if indicators.get('no_trade_zone'):
                print(f"❌ NO-TRADE ZONE: {indicators['no_trade_reason']}")
                continue
            
            # Get signal score (1-5)
            action, signal_score = self.calculate_signal_score(product_id, indicators, df)
            
            if action == 'buy' and signal_score > 2:
                print(f"📊 Signal Score: {signal_score}/5")
                
                position_size = self.calculate_position_size(product_id, signal_score)
                
                if position_size > 10:  # Minimum $10 trade
                    self.enter_position(product_id, 'long', position_size, df)
                    self.last_trade_time = datetime.now()
                    self.daily_trades += 1
                else:
                    print(f"⚠️ Position size too small: ${position_size:.2f}")
            
            elif action == 'sell' and signal_score > 2:
                print(f"📉 Sell signal {signal_score}/5 (shorts not enabled)")
            
            else:
                print(f"⏸️ No entry signal (score: {signal_score}/5)")
            
            # Display current indicators
            if indicators and indicators.get('rsi') is not None:
                print(f"   RSI: {indicators['rsi'].iloc[-1]:.1f}")
                print(f"   VWAP: ${df['close'].iloc[-1]:.2f} vs ${indicators['vwap'].iloc[-1]:.2f}")
    
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
            
            # Open NIJA position
            self.position_counter += 1
            position_id = f"{product_id}-{self.position_counter}"
            
            position = self.nija.open_position(
                position_id=position_id,
                side=side,
                entry_price=entry_price,
                size=size,
                volatility=volatility
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
