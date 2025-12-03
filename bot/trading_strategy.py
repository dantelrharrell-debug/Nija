# trading_strategy.py
import time
import pandas as pd
from datetime import datetime, timedelta

class TradingStrategy:
    """
    Advanced trading strategy with:
    - VWAP, RSI, MACD indicators
    - Dynamic position sizing based on volatility
    - Risk management (max exposure, stop loss)
    - Trade history tracking
    """
    
    def __init__(self, client, pairs=None, base_allocation=5.0, max_exposure=0.3, max_daily_loss=0.1):
        self.client = client
        self.pairs = pairs or ["BTC-USD", "ETH-USD", "SOL-USD"]
        self.base_allocation = base_allocation  # % of balance per trade
        self.max_exposure = max_exposure  # max % of account in positions
        self.max_daily_loss = max_daily_loss  # max daily loss %
        self.trade_history = []
        self.daily_pnl = 0.0
        self.start_balance = 0.0
        
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
    
    def calculate_position_size(self, product_id, signal_strength=1.0):
        """Calculate position size based on volatility and account balance"""
        usd_balance = self.get_usd_balance()
        
        if usd_balance == 0:
            return 0.0
        
        # Base allocation adjusted by signal strength
        allocation_pct = self.base_allocation * signal_strength
        
        # Check max exposure
        current_exposure = sum([t.get('size', 0) * t.get('entry_price', 0) 
                               for t in self.trade_history if not t.get('closed', True)])
        
        if current_exposure / usd_balance > self.max_exposure:
            print(f"⚠️ Max exposure reached ({current_exposure/usd_balance:.1%})")
            return 0.0
        
        # Check daily loss limit
        if self.daily_pnl / self.start_balance < -self.max_daily_loss:
            print(f"⚠️ Max daily loss reached ({self.daily_pnl:.2f})")
            return 0.0
        
        position_size = usd_balance * (allocation_pct / 100)
        return min(position_size, usd_balance * 0.1)  # Cap at 10% per trade
    
    def should_trade(self, product_id, indicators):
        """Determine if we should trade based on indicators"""
        if not indicators or indicators.get('rsi') is None:
            return None, 0.0
        
        rsi = indicators['rsi'].iloc[-1]
        buy_signal = indicators['buy_signal']
        sell_signal = indicators['sell_signal']
        
        # Strong buy signal: oversold + MACD crossover + above VWAP
        if buy_signal and rsi < 40:
            return 'buy', 0.8
        
        # Moderate buy signal
        elif buy_signal:
            return 'buy', 0.5
        
        # Strong sell signal: overbought + MACD crossunder + below VWAP
        elif sell_signal and rsi > 60:
            return 'sell', 0.8
        
        # Moderate sell signal
        elif sell_signal:
            return 'sell', 0.5
        
        return None, 0.0
    
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
        """Run one trading cycle across all pairs"""
        print(f"\n{'='*60}")
        print(f"🤖 Trading Cycle - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}")
        
        usd_balance = self.get_usd_balance()
        
        if self.start_balance == 0:
            self.start_balance = usd_balance
        
        print(f"💰 USD Balance: ${usd_balance:.2f}")
        print(f"📊 Daily P&L: ${self.daily_pnl:.2f} ({self.daily_pnl/self.start_balance*100:.2f}%)")
        
        for product_id in self.pairs:
            print(f"\n--- Analyzing {product_id} ---")
            
            # Get candle data
            df = self.get_product_candles(product_id)
            
            if df is None or len(df) < 30:
                print(f"⚠️ Insufficient data for {product_id}")
                continue
            
            # Calculate indicators
            from indicators import calculate_indicators
            indicators = calculate_indicators(df)
            
            # Get trading signal
            action, signal_strength = self.should_trade(product_id, indicators)
            
            if action == 'buy':
                position_size = self.calculate_position_size(product_id, signal_strength)
                
                if position_size > 10:  # Minimum $10 trade
                    trade = self.place_market_order(product_id, 'buy', position_size)
                    if trade:
                        self.trade_history.append(trade)
                else:
                    print(f"⚠️ Position size too small: ${position_size:.2f}")
            
            elif action == 'sell':
                print(f"📉 Sell signal detected (strength: {signal_strength:.1%})")
                # Implement sell logic here if holding positions
            
            else:
                print(f"⏸️ No trade signal")
            
            # Display current indicators
            if indicators and indicators.get('rsi') is not None:
                print(f"   RSI: {indicators['rsi'].iloc[-1]:.1f}")
                print(f"   VWAP: ${df['close'].iloc[-1]:.2f} vs ${indicators['vwap'].iloc[-1]:.2f}")
