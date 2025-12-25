import logging
import time
from datetime import datetime
from typing import Optional, Tuple
import signal

logger = logging.getLogger(__name__)

class TimeoutError(Exception):
    """Custom timeout exception"""
    pass

def timeout_handler(signum, frame):
    raise TimeoutError("Function call timed out")

def call_with_timeout(func, args=(), kwargs={}, timeout_seconds=30):
    """
    Execute function with timeout. Returns (result, error).
    If timeout occurs, returns (None, TimeoutError).
    Increased default to 30s for production API latency.
    """
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(timeout_seconds)
    try:
        result = func(*args, **kwargs)
        signal.alarm(0)  # Cancel alarm
        return result, None
    except TimeoutError as e:
        return None, e
    except Exception as e:
        signal.alarm(0)
        return None, e

class TradingStrategy:
    def __init__(self, config):
        self.config = config
        self.position = None
        self.entry_price = None
        
    def analyze_market(self, market_data):
        """Analyze market conditions and generate trading signals"""
        try:
            # Basic trend analysis
            if not market_data or 'price' not in market_data:
                return None
                
            current_price = market_data['price']
            
            # Simple moving average strategy
            if 'sma_short' in market_data and 'sma_long' in market_data:
                sma_short = market_data['sma_short']
                sma_long = market_data['sma_long']
                
                # Buy signal: short MA crosses above long MA
                if sma_short > sma_long and self.position is None:
                    return 'BUY'
                # Sell signal: short MA crosses below long MA
                elif sma_short < sma_long and self.position is not None:
                    return 'SELL'
                    
            return None
            
        except Exception as e:
            logger.error(f"Error analyzing market: {e}")
            return None
    
    def execute_trade(self, signal, price):
        """Execute trading signal"""
        try:
            if signal == 'BUY' and self.position is None:
                self.position = 'LONG'
                self.entry_price = price
                logger.info(f"Opened LONG position at {price}")
                return True
                
            elif signal == 'SELL' and self.position is not None:
                profit = price - self.entry_price
                self.position = None
                self.entry_price = None
                logger.info(f"Closed position at {price}, profit: {profit}")
                return True
                
            return False
            
        except Exception as e:
            logger.error(f"Error executing trade: {e}")
            return False
