import os
import sys
import time
import queue
from threading import Thread
from datetime import datetime, timedelta
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

load_dotenv()

# Timeout wrapper for broker API calls to prevent indefinite hangs
def call_with_timeout(func, args=(), kwargs={}, timeout_seconds=30):
    """
    Execute function with timeout. Returns (result, error).
    If timeout occurs, returns (None, TimeoutError).
    Increased default to 30s for production API latency.
    """
    result_queue = queue.Queue()
    
    def worker():
        try:
            result = func(*args, **kwargs)
            result_queue.put(('success', result))
        except Exception as e:
            result_queue.put(('error', e))
    
    thread = Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)
    
    if thread.is_alive():
        # Timeout occurred - thread is still running
        return None, TimeoutError(f"Operation timed out after {timeout_seconds}s")
    
    try:
        status, value = result_queue.get_nowait()
        if status == 'success':
            return value, None
        else:
            return None, value
    except queue.Empty:
        return None, Exception("Thread completed but no result available")

# Add bot directory to path if running from root
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from bot.market_data import get_current_price
except ImportError:
    print("[WARNING] Could not import get_current_price from bot.market_data")
    def get_current_price(symbol):
        return None

class TradingStrategy:
    def __init__(self):
        self.api_key = os.getenv('ALPACA_API_KEY')
        self.secret_key = os.getenv('ALPACA_SECRET_KEY')
        self.base_url = os.getenv('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')
        
        if not self.api_key or not self.secret_key:
            raise ValueError("Alpaca API credentials not found in environment variables")
        
        self.trading_client = TradingClient(self.api_key, self.secret_key, paper=True)
        self.data_client = StockHistoricalDataClient(self.api_key, self.secret_key)
        
        # Strategy parameters
        self.rsi_period = 14
        self.rsi_oversold = 30
        self.rsi_overbought = 70
        self.position_size = 0.1  # 10% of portfolio per trade
    
    def calculate_rsi(self, prices, period=14):
        """Calculate Relative Strength Index"""
        if len(prices) < period + 1:
            return None
        
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [-d if d < 0 else 0 for d in deltas]
        
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        
        if avg_loss == 0:
            return 100
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def get_historical_data(self, symbol, days=30):
        """Fetch historical price data"""
        try:
            end = datetime.now()
            start = end - timedelta(days=days)
            
            request_params = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame.Day,
                start=start,
                end=end
            )
            
            bars = self.data_client.get_stock_bars(request_params)
            prices = [bar.close for bar in bars[symbol]]
            return prices
        except Exception as e:
            print(f"Error fetching historical data: {e}")
            return None
    
    def should_buy(self, symbol):
        """Determine if we should buy based on RSI"""
        prices = self.get_historical_data(symbol)
        if not prices:
            return False, "Unable to fetch historical data"
        
        rsi = self.calculate_rsi(prices, self.rsi_period)
        if rsi is None:
            return False, "Insufficient data for RSI calculation"
        
        if rsi < self.rsi_oversold:
            return True, f"RSI ({rsi:.2f}) is oversold"
        
        return False, f"RSI ({rsi:.2f}) is not oversold"
    
    def should_sell(self, symbol):
        """Determine if we should sell based on RSI"""
        prices = self.get_historical_data(symbol)
        if not prices:
            return False, "Unable to fetch historical data"
        
        rsi = self.calculate_rsi(prices, self.rsi_period)
        if rsi is None:
            return False, "Insufficient data for RSI calculation"
        
        if rsi > self.rsi_overbought:
            return True, f"RSI ({rsi:.2f}) is overbought"
        
        return False, f"RSI ({rsi:.2f}) is not overbought"
    
    def execute_trade(self, symbol, side, quantity):
        """Execute a market order"""
        try:
            order_data = MarketOrderRequest(
                symbol=symbol,
                qty=quantity,
                side=side,
                time_in_force=TimeInForce.DAY
            )
            
            order = self.trading_client.submit_order(order_data)
            return True, f"Order submitted: {order.id}"
        except Exception as e:
            return False, f"Error executing trade: {e}"
    
    def get_account_value(self):
        """Get current account value"""
        try:
            account = self.trading_client.get_account()
            return float(account.equity)
        except Exception as e:
            print(f"Error getting account value: {e}")
            return None
    
    def calculate_position_size(self, symbol, price):
        """Calculate position size based on account value"""
        account_value = self.get_account_value()
        if not account_value or not price:
            return 0
        
        position_value = account_value * self.position_size
        quantity = int(position_value / price)
        return quantity
